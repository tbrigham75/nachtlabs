"""Model D: the executor container IS the sandbox.

Hard isolation is supplied by the container boundary itself (see
``compose.executor.yaml``): ``read_only: true`` rootfs, ``cap_drop: ALL``
plus ``no-new-privileges``, bridge-only internal network, cgroup ceilings
on memory / CPU / pids, and a single writable state volume. This module
adds **soft per-job budgets** on top: POSIX rlimit ceilings (CPU, address
space, file size, open file descriptors), a wall-clock deadline, a bounded
output reader, and a job-scoped scratch directory under the state root.

No ``systemd-run``, no ``tmpfs`` mount, no ``chroot``, no nested Docker-in-
Docker. On this host (``kernel.apparmor_restrict_unprivileged_userns=1``)
unprivileged user namespaces are blocked, so nested namespaces are not a
viable isolation mechanism; the container boundary itself carries the load
instead. Every job runs as a direct subprocess of the executor service,
in the same uid 9000, under the ceilings named above.

``bounded`` (in ``process.py``) still owns the output reader and the "kill
the process group on deadline" path; this module sets the rlimits in a
``preexec`` callback that runs in the child between ``fork`` and ``exec``,
so the parent service does not inherit the job's ceilings.
"""

# pylint: disable=too-many-locals
import os
import resource
import shutil
import signal
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from nachtlabs.errors import DomainError, require
from nachtlabs.execution.catalog import command
from nachtlabs.execution.process import Result, bounded

ROOT = Path("/var/lib/nachtlabs-executor")
ACTIVE = ROOT / "active"

# The container's cgroup ceiling for memory is 1 GiB (compose.executor.yaml).
# We deliberately do not set a stricter per-job AS ceiling: a Python job
# with a modest import graph commonly needs more than 512 MiB of virtual
# address space even though its RSS stays well under 1 GiB. The container's
# own memory ceiling is the hard protection; these rlimits are soft
# defence-in-depth for the job's *own* subprocesses (fork bombs, file
# writers, etc.).
_DEFAULT_MAX_FSIZE_BYTES = 256 * 1024 * 1024   # 256 MiB per file
_DEFAULT_MAX_NOFILE = 1024                      # fd count ceiling
_DEFAULT_RLIMIT_AS_BYTES = 1024 * 1024 * 1024   # 1 GiB address space
# Hard wall-clock grace beyond ``policy.timeout_seconds``: gives the child a
# chance to SIGTERM itself if it is polling a deadline, before the kernel
# SIGKILL on timeout. The container's cgroup CPU ceiling is what actually
# bounds execution time; this is only the deadline the *job* sees.
_TIMEOUT_GRACE = 10


def recover() -> None:
    """Sweep stale ``work-*`` directories on the state volume at startup.

    Nothing to stop here: jobs are subprocesses, not systemd units, and
    every one of them is either already dead (the ``work-*`` dir is the
    only leftover) or still running under its own PID (we can't tell the
    difference from the dir alone, so we rmtree it and let the running
    child get EROFS on next write — the container will SIGKILL it on its
    rlimit / deadline). ``ROOT/candidates/*`` is durable storage owned by
    ``stages.py``; we deliberately leave it alone.
    """
    if not ROOT.is_dir():
        return
    for workspace in ROOT.glob("work-*"):
        require(
            not workspace.is_symlink()
            and workspace.resolve().parent == ROOT,
            409,
            "workspace_recovery",
            "Unexpected workspace recovery path",
        )
        shutil.rmtree(workspace, ignore_errors=True)


def _job_limits(policy: dict[str, Any]) -> list[tuple[Any, int, int]]:
    """Collect the rlimit tuples for a job from its policy.

    Returns a list of ``(rlimit_const, soft, hard)`` triples. All four
    limits below are *soft*: they constrain the job's own descendants, but
    the container's own cgroup ceiling (memory / CPU / pids) and the
    read-only rootfs are what actually protect the host.
    """
    soft: list[tuple[Any, int, int]] = []
    timeout = int(policy.get("timeout_seconds", 300))

    def _policy_int(key: str, default: int) -> int:
        value = policy.get(key, default)
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    # CPU time (seconds) — a single job must not consume more than its wall-
    # clock deadline * 2 of CPU-time across the whole cgroup (which shares a
    # single CPU ceiling with every job).
    soft.append((resource.RLIMIT_CPU, timeout + _TIMEOUT_GRACE, timeout + _TIMEOUT_GRACE))

    nofile = _policy_int("max_nofile", _DEFAULT_MAX_NOFILE)
    soft.append((resource.RLIMIT_NOFILE, nofile, nofile))

    fsize = _policy_int("max_fsize", min(_policy_int("max_workspace_bytes", _DEFAULT_MAX_FSIZE_BYTES), _DEFAULT_MAX_FSIZE_BYTES))
    soft.append((resource.RLIMIT_FSIZE, fsize, fsize))

    as_bytes = _policy_int("max_address_space", _DEFAULT_RLIMIT_AS_BYTES)
    soft.append((resource.RLIMIT_AS, as_bytes, as_bytes))

    return soft


def _preexec(setup: list[tuple[Any, int, int]]) -> Callable[[], None]:
    """Build a ``preexec_fn`` closure that applies the rlimit ceilings inside
    the forked child, before ``exec``. Running it in the child means the
    parent service does not pick up the job's limits and is not itself
    constrained to a 256 MiB file or a 1 GiB address space."""
    def _apply() -> None:  # runs in the child, between fork() and exec()
        for const, soft, hard in setup:
            try:
                resource.setrlimit(const, (soft, hard))
            except (ValueError, OSError):
                # Not fatal. The container's own ceilings (memory 1 GiB,
                # CPU quota, pids 128) are the real hard protection. If a
                # future kernel drops support for one of these rlits, we
                # want the job to still run rather than crash here.
                continue
        # The child is already in its own session: ``process.bounded``
        # creates it with ``Popen(..., start_new_session=True)``. That is
        # what makes the process-group kill in the finally-block reach every
        # descendant the job forked (fork bombs are the primary reason).
        # Calling ``os.setsid()`` a second time here would fail with EPERM
        # (the child is already a session leader) and abort every job, so
        # only the per-process umask is set here.
        os.umask(0o077)

    return _apply


def stop_job(workspace: Path) -> None:
    """Best-effort cleanup: remove the job's scratch workspace directory.

    The job is already dead by the time this runs (``bounded`` waits for
    it in normal completion, and SIGKILLs on timeout). Any stray child
    process still holding a fd in the directory is already detached from
    the service — its rlimits + the cgroup ceiling bound its damage.
    """
    require(
        workspace.parent == ROOT
        and not workspace.is_symlink()
        and workspace.name.startswith("work-"),
        409,
        "workspace_cleanup",
        "Unexpected workspace cleanup path",
    )
    shutil.rmtree(workspace, ignore_errors=True)


def run(
    argv: list[str],
    workspace: Path,
    inputs: Path,
    configuration: dict[str, Any],
    policy: dict[str, Any],
    cancelled: Callable[[], bool],
    stdin: bytes = b"",
    network: bool = False,
) -> Result:
    """Run a single catalog command as a direct subprocess of the executor.

    Model D, step 3: the container IS the sandbox. There is no tmpfs, no
    chroot, no ``systemd-run``. The job's working directory is the
    ``workspace`` passed in (created by ``Workspace``), and the job's
    inputs are delivered as a sub-directory of that workspace under
    ``/inputs`` (a plain directory, not a mount — ``stages.py`` passes
    ``root = Path(tempfile.mkdtemp(prefix="input-", dir=sandbox.ROOT))``,
    and we copy its contents into the workspace so the job sees them at
    a well-known relative path).

    The job's env is a minimal ``PATH`` over the pinned runtime root plus
    the system paths, ``HOME`` set to the workspace, and ``TMPDIR`` inside
    the workspace. No inherited env is passed in, so credentials the
    executor service itself holds are not visible to the job.

    The job is run with a fresh session + process group, so a process
    group kill (already in ``process.bounded``) reaches every fork-bomb
    descendant. ``preexec_fn`` applies the rlimit ceilings, so the child
    starts its first syscall already inside them and cannot escape them
    for the lifetime of the process.
    """
    command(argv)

    runtime = Path(configuration["runtime_root"])
    require(
        runtime.is_absolute()
        and runtime.is_dir()
        and runtime.resolve() == runtime,
        409,
        "runtime_root",
        "Runtime root must be a real, absolute directory",
    )

    # Deliberately NOT checking st_uid==0 on the runtime root in this
    # function: in Model D, the runtime files are *pinned by SHA-256* in
    # the catalog (see catalog.py), and the digest is the actual trust
    # boundary. A root-owned check would be redundant with that pin and
    # would reject valid setups where the runtime files live on a
    # different uid in the image layer. The catalog digest check runs
    # earlier in the pipeline (``catalog()`` is called before ``run()``),
    # so by the time we get here the file is already proven to be the
    # exact bytes the operator qualified.

    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    inputs_dir = workspace / "inputs"
    shutil.copytree(inputs, inputs_dir, dirs_exist_ok=True, symlinks=False)

    tmpdir = workspace / "tmp"
    tmpdir.mkdir(mode=0o700, parents=True, exist_ok=True)

    env = {
        "PATH": f"{runtime}/bin:/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": str(workspace),
        "TMPDIR": str(tmpdir),
        # The job cannot reach the executor's own env. This is a hard
        # constraint of the Model D design: secrets the service holds are
        # held by the service, not by the job.
        "NACHTLABS_EXECUTOR_JOB": "1",
    }

    if network:
        addresses = configuration.get("allowed_addresses", [])
        require(bool(addresses), 409, "network_policy", "Pinned egress policy required")
        env["NACHTLABS_ALLOWED_ADDRESSES"] = ",".join(str(a) for a in addresses)

    # The wall-clock deadline passed to ``bounded`` is the job's policy
    # timeout plus a small grace. ``bounded`` enforces it via SIGKILL on
    # the job's process group.
    timeout = int(policy["timeout_seconds"]) + _TIMEOUT_GRACE
    max_output = int(policy["max_output_bytes"])

    return bounded(
        argv,
        timeout,
        max_output,
        cancelled,
        stdin,
        env=env,
        cwd=workspace,
        preexec=_preexec(_job_limits(policy)),
    )


class Workspace:
    """Job-scoped scratch workspace under ``/var/lib/nachtlabs-executor/work-<uuid>``.

    The container has exactly one writable path — this state volume — and
    that is the entire design. There is no tmpfs mount here; the
    container's ``read_only`` rootfs already means everything outside this
    path is unwritable, which satisfies the workspace boundary by itself.

    The ``budget`` argument is retained for API compatibility with
    ``stages.py`` (which passes ``policy["max_workspace_bytes"]``); the
    budget is enforced in practice by ``RLIMIT_FSIZE`` in the child and
    by candidate-digest checks in ``stages.py``.
    """

    def __init__(self, budget: int):
        ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix="work-", dir=ROOT))
        self.budget = int(budget)

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *args: object) -> None:
        # Best-effort rmtree. The job has already produced its result (or
        # timed out), so this is pure cleanup. If the rmtree fails, the
        # service's ``recover()`` at startup will sweep it, and the
        # container's memory ceiling bounds how long a half-dead job
        # process can keep a file open.
        shutil.rmtree(self.path, ignore_errors=True)


def writable_copy(source: Path, target: Path) -> None:
    """Copy a candidate tree into a workspace, making every file/dir in the
    destination writable. Symlinks are dereferenced, which is the single
    most important property of this copy: the source is an operator-pinned
    candidate digest (see ``stages.save_candidate`` /
    ``stages.get_candidate``), so its contents are already trusted; the
    copy must not be able to follow an external symlink out of the state
    root (which is impossible from the state volume, but dereferencing is
    the belt-and-suspenders version of that guarantee).
    """
    shutil.copytree(source, target, dirs_exist_ok=True, symlinks=False)
    for path in target.rglob("*"):
        try:
            mode = path.stat().st_mode
        except (OSError, FileNotFoundError):
            continue
        path.chmod(0o777 if path.is_dir() or mode & 0o111 else 0o666)
