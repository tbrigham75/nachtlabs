"""Offline, root-controlled mirrors; candidate identity includes every byte and mode."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from nachtlabs.errors import require
from nachtlabs.execution.files import manifest
from nachtlabs.execution.process import bounded
from nachtlabs.workflows.policy import safe_ref, safe_relative

GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_NO_REPLACE_OBJECTS": "1",
}


def git(repository: Path, *args: str, limit: int = 1048576) -> bytes:
    require(
        repository.is_absolute()
        and repository.resolve() == repository
        and repository.stat().st_uid == 0
        and not repository.stat().st_mode & 0o022,
        409,
        "mirror_permissions",
        "Mirror must be root owned and protected",
    )
    result = bounded(
        [
            "/usr/bin/git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "protocol.file.allow=never",
            "-c",
            "core.fsmonitor=false",
            "--git-dir=" + str(repository),
            *args,
        ],
        30,
        limit,
        env=GIT_ENV,
    )
    require(result.code == 0, 409, "repository_read_failed", "Unable to read approved local mirror")
    return result.output


def export(
    repository: Path,
    ref: str,
    target: Path,
    budget: int,
    cancelled: Callable[[], bool] = lambda: False,
) -> tuple[str, dict[str, Any]]:
    safe_ref(ref)
    commit = (
        git(repository, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
        .decode()
        .strip()
    )
    require(
        len(commit) in {40, 64} and all(c in "0123456789abcdef" for c in commit),
        409,
        "repository_commit",
        "Invalid repository commit",
    )
    entries = git(repository, "ls-tree", "-rz", "--full-tree", commit, limit=4194304).split(b"\x00")
    total = 0
    for row in entries:
        require(not cancelled(), 409, "cancelled", "Discovery cancelled or timed out")
        if not row:
            continue
        header, raw_path = row.split(b"\t", 1)
        mode, kind, oid = header.decode().split()
        relative = raw_path.decode("utf-8", errors="strict")
        safe_relative(relative)
        require(
            kind == "blob" and mode in {"100644", "100755"} and ".git" not in Path(relative).parts,
            409,
            "repository_file_type",
            "Symlinks and submodules require operator review",
        )
        size = int(git(repository, "cat-file", "-s", oid))
        total += size
        require(total <= budget, 409, "workspace_budget", "Repository exceeds workspace budget")
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(git(repository, "cat-file", "blob", oid, limit=max(1, size + 1)))
        path.chmod(0o755 if mode == "100755" else 0o644)
    return commit, manifest(target, budget)
