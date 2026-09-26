"""Regular-file-only candidate snapshots. No checkout hooks, filters or symlinks."""

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from nachtlabs.errors import require
from nachtlabs.workflows.policy import fingerprint, safe_relative

FORBIDDEN = {".git", ".nachtlabs"}
PROTECTED = (
    ".github/",
    ".gitea/",
    ".gitlab/",
    ".codex/",
    ".agents/",
    ".nachtlabs/",
    ".opencode/",
    ".hermes/",
)


def manifest(root: Path, byte_limit: int, file_limit: int = 20000) -> dict[str, Any]:
    entries: dict[str, Any] = {}
    total = 0
    for base, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            child = Path(base) / name
            require(
                not child.is_symlink() and name not in FORBIDDEN,
                409,
                "unsafe_workspace",
                "Reserved or symbolic directory",
            )
        for name in names:
            path = Path(base) / name
            relative = path.relative_to(root).as_posix()
            safe_relative(relative)
            info = path.lstat()
            require(
                stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and name not in FORBIDDEN,
                409,
                "unsafe_workspace",
                "Only regular, unlinked files are accepted",
            )
            total += info.st_size
            require(
                total <= byte_limit and len(entries) < file_limit,
                409,
                "workspace_budget",
                "Workspace budget exceeded",
            )
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                while block := handle.read(65536):
                    digest.update(block)
            entries[relative] = {
                "sha256": digest.hexdigest(),
                "bytes": info.st_size,
                "executable": bool(info.st_mode & 0o111),
            }
    return entries


def candidate(root: Path, budget: int) -> str:
    return fingerprint(manifest(root, budget))


def scope_gate(before: dict[str, Any], after: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    require(
        len(changed) <= policy["max_changed_files"],
        409,
        "change_budget",
        "Changed-file budget exceeded",
    )
    for path in changed:
        require(
            not path.startswith(PROTECTED)
            and Path(path).name not in {"AGENTS.md", ".gitmodules", ".gitattributes"},
            409,
            "protected_path",
            "Change touches execution or delivery controls",
        )
        require(
            any(
                path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
                for prefix in policy["allowed_paths"]
            ),
            409,
            "scope_violation",
            "Change exceeds approved scope",
        )
    return changed
