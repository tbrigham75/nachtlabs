"""Bounded subprocess collection.

The service owns the policy; this module owns the plumbing:

* ``bounded`` runs a single subprocess, pipes stdout+stderr together,
  enforces the output budget (``max_output_bytes``), enforces a wall-
  clock deadline (``timeout``), enforces a cancellation callback
  (``cancelled``), and — critically for Model D — applies
  ``preexec_fn`` in the child between ``fork`` and ``exec`` so the
  parent service does not inherit the child's resource ceilings.
* On exit (normal, timeout, or cancelled), ``bounded`` SIGKILLs the
  child's entire process group (``os.killpg``), so fork-bomb
  descendants in the child tree are all reaped.

The "kill on deadline" path is the real timeout enforcement for Model D.
The wall-clock ``timeout`` here is the outer bound; the child's own
``RLIMIT_CPU`` (set by ``sandbox._preexec``) is the inner bound, so a
child that spins in a tight loop without doing I/O will be killed by the
CPU rlimit long before the wall-clock deadline.
"""

# pylint: disable=too-many-locals
import os
import selectors
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nachtlabs.errors import DomainError


@dataclass(frozen=True)
class Result:
    code: int
    output: bytes


def bounded(
    argv: list[str],
    timeout: int,
    limit: int,
    cancelled: Callable[[], bool] | None = None,
    stdin: bytes = b"",
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    preexec: Callable[[], None] | None = None,
) -> Result:
    """Run ``argv`` and return ``Result(code, output)``.

    The output is combined stdout+stderr, truncated (the process is
    killed) if it ever exceeds ``limit`` bytes. The wall-clock deadline
    is ``timeout`` seconds; the process is SIGKILLed on expiry (whole
    process group, so forks don't survive). ``cancelled``, when it returns
    True between ``fread``s, aborts with a 409 domain error rather than
    waiting for the deadline.

    ``preexec`` runs in the child between ``fork()`` and ``exec()`` —
    this is where ``resource.setrlimit`` is applied by the callers in
    ``sandbox.py``. Session creation is this function's
    ``start_new_session=True``.

    ``cwd``, when given, is the child's working directory (the job's
    scratch workspace in Model D).
    """
    cancel = cancelled or (lambda: False)
    # Input is delivered via a temporary regular file: pipe writes must not
    # deadlock. The file is unlinked on close by the TemporaryFile
    # context manager, and the child has already inherited an fd to it.
    with tempfile.TemporaryFile() as source:
        source.write(stdin)
        source.seek(0)
        process = subprocess.Popen(
            argv,
            stdin=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env or {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            cwd=str(cwd) if cwd is not None else None,
            preexec_fn=preexec,
            start_new_session=True,
            close_fds=True,
        )
        assert process.stdout is not None
        output = bytearray()
        deadline = time.monotonic() + timeout
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while selector.get_map():
                if cancel():
                    raise DomainError(409, "cancelled", "Execution cancelled")
                if time.monotonic() > deadline:
                    raise DomainError(409, "execution_timeout", "Execution deadline exceeded")
                for key, _ in selector.select(0.25):
                    fileobj = key.fileobj
                    if not hasattr(fileobj, "fileno"):
                        continue
                    chunk = os.read(fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > limit:
                            raise DomainError(
                                409, "output_budget", "Execution output budget exceeded"
                            )
            return Result(process.wait(timeout=max(1, deadline - time.monotonic())), bytes(output))
        finally:
            selector.close()
            if process.poll() is None:
                # Kill the *process group*, not just the direct child. The
                # child started its own session (start_new_session=True),
                # so its pgid == its pid, and every descendant it forked
                # stays in the same group. This is what makes fork bombs
                # stop being possible in Model D: a bomb's children can't
                # escape the group, so they all die together.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    # The child already exited between killpg and the
                    # check — not a real error.
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            process.stdout.close()
