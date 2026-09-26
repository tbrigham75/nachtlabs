"""Load operator environment for host-console scripts.

An installed deployment keeps its configuration in /etc/nachtlabs, not in the
repository, and a bare ``sudo python3 scripts/something.py`` inherits nothing.
Without this, every host-console script that reaches the database fails with a
validation error about ``database_url_file`` before it can do anything useful.

Nothing is overridden: variables already present in the environment win, so an
operator can always point a script somewhere specific. These scripts need write
access to identity rows, which is why /etc/nachtlabs/migration.env is preferred
over the API's read-mostly credential.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

# Ordered by suitability: the migrator role is what these scripts need.
CANDIDATES: tuple[str, ...] = (
    "/etc/nachtlabs/migration.env",
    "/etc/nachtlabs/api.env",
)
OVERRIDE = "NACHTLABS_OPERATOR_ENV_FILE"


def _apply(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        key = key.strip()
        if not key:
            continue
        # Values are written shlex-quoted by configure.py, so unquote them.
        try:
            value = shlex.split(raw)[0] if raw.strip() else ""
        except ValueError:
            value = raw.strip().strip("'\"")
        os.environ.setdefault(key, value)


def load_operator_env() -> str | None:
    """Populate the environment from an operator env file. Returns its path.

    Returns None when the environment is already configured or when no file
    could be found; the caller decides whether that is fatal, because a script
    may legitimately be running with the environment already exported.
    """
    if os.environ.get("NACHTLABS_DATABASE_URL_FILE"):
        return None
    candidates = list(CANDIDATES)
    override = os.environ.get(OVERRIDE)
    if override:
        candidates.insert(0, override)
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            _apply(path)
            return str(path)
    return None


def require_operator_env() -> str:
    """Like load_operator_env, but explains the failure instead of raising a
    pydantic error the operator has to decode."""
    from_path = load_operator_env()
    if from_path is not None:
        return from_path
    if os.environ.get("NACHTLABS_DATABASE_URL_FILE"):
        return "environment"
    raise SystemExit(
        "No operator configuration found. Looked for:\n"
        + "".join(f"  {path}\n" for path in CANDIDATES)
        + f"Set {OVERRIDE} to the env file to use, for example:\n"
        f"  {OVERRIDE}=/etc/nachtlabs/migration.env\n"
        "If this installation has never been configured, run configure.py first:\n"
        "  sudo python3 scripts/configure.py --origin https://your-host"
    )
