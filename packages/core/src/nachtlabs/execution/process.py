"""Bounded subprocess collection; sandbox lifecycle owns the complete cgroup."""

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from nachtlabs.errors import DomainError


@dataclass(frozen=True)
class Result:
    code: int
    output: bytes


def bounded(
    argv: list[str],
    timeout: int,
    limit: int,
    cancelled: Callable[[], bool] = lambda: False,
    stdin: bytes = b"",
    env: dict[str, str] | None = None,
) -> Result:
    # Input is delivered via a temporary regular file: pipe writes must not deadlock.
    import tempfile

    with tempfile.TemporaryFile() as source:
        source.write(stdin)
        source.seek(0)
        process = subprocess.Popen(
            argv,
            stdin=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env or {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
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
                if cancelled():
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
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            process.stdout.close()
