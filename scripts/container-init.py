#!/usr/bin/env python3
"""Generate container credentials and derive the browser origin at first start.

This is the container counterpart of scripts/configure.py. The native installer
asks the operator for four database passwords on a console; a container has no
console and no operator at that moment, so this generates them instead and
prints where the one-time values are.

The rules that carry over from configure.py are kept deliberately:

  * Nothing is ever overwritten. An existing file wins, so restarting the stack
    is a no-op and a rotation stays an explicit operator action.
  * Secrets are written 0600, or 0640 for the two the API reads, because the
    service account has to be able to read them and must not be able to rewrite
    them.
  * The origin is written into configuration rather than inferred per request,
    because origin_permitted() is a CSRF control and must stay an exact
    membership test.

What it does not do is decide the deployment's identity. NACHTLABS_LAN_ORIGIN is
the operator's single input, because the app cannot know the address a browser
will use to reach it; see docs/adr/0006. Without it the origin is loopback, which
is correct for a laptop and wrong for a server, so the printed URL is the thing
the operator actually needs to read.
"""

from __future__ import annotations

import base64
import os
import secrets
import shlex
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(os.environ.get("NACHTLABS_CONFIG_DIR", "/etc/nachtlabs"))
CREDENTIALS = ROOT / "credentials"
WEB_PORT = os.environ.get("NACHTLABS_WEB_PORT", "3035")
DB_HOST = os.environ.get("NACHTLABS_DB_HOST", "postgres")
DB_PORT = os.environ.get("NACHTLABS_DB_PORT", "5432")
DB_NAME = os.environ.get("NACHTLABS_DB_NAME", "nachtlabs")
TEST_DB_NAME = os.environ.get("NACHTLABS_TEST_DB_NAME", "nachtlabs_test")
# Next's rewrite proxy forwards the *upstream* hostname in the Host header, so
# the API receives "api:8000" rather than the address the browser used.
# TrustedHostMiddleware rejects that unless the service name is permitted, which
# is a 400 with no route matched and nothing in the log to explain it. Permitting
# it is not a relaxation of the origin check, which is a separate exact-membership
# test on the Origin header and remains the CSRF control.
API_HOST = os.environ.get("NACHTLABS_API_HOST", "api")
# The service account in the image. The generated files have to be readable by
# it, and a named volume is created root-owned, so ownership is set explicitly
# rather than inherited: a file left root:root at 0640 is unreadable by the
# non-root service and fails with a bare "Permission denied".
SERVICE_UID = int(os.environ.get("NACHTLABS_SERVICE_UID", "9000"))
SERVICE_GID = int(os.environ.get("NACHTLABS_SERVICE_GID", "9000"))


def fail(message: str) -> None:
    print(f"container-init: {message}", file=sys.stderr)
    raise SystemExit(1)


def _own(path: Path) -> None:
    """Make a generated file readable by the service account without letting it
    be rewritten. Group ownership plus 0640 is the same arrangement the systemd
    units use through the nachtlabs-secrets group."""
    try:
        os.chown(path, 0, SERVICE_GID)
    except (PermissionError, OSError):
        # Running unprivileged outside a container; the modes still apply and the
        # caller is the owner, so the file is readable either way.
        pass


def _own_dir(path: Path, mode: int) -> None:
    """Group-own and open a directory for traversal by the service account.

    A directory left root:root at 0750 is not even listable by the service, so
    every read fails with a bare Permission denied and no indication of which
    path is at fault. 0750 with the service group is what makes the files inside
    reachable at all.
    """
    path.chmod(mode)
    try:
        os.chown(path, 0, SERVICE_GID)
    except (PermissionError, OSError):
        pass


def secret(name: str, value: str, mode: int = 0o600) -> Path:
    """Write once. An existing file is never replaced."""
    path = CREDENTIALS / name
    if path.exists():
        _own(path)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(mode)
    _own(path)
    return path


def token() -> str:
    return secrets.token_urlsafe(32)


# One password per role, held for the life of the process so that every
# credential file mentioning a role carries the same value. PostgreSQL
# authenticates a role by password and not per database, so a second generated
# password for the same role would simply fail to authenticate.
ROLE_PASSWORDS: dict[str, str] = {}


def role_password(role: str) -> str:
    if role not in ROLE_PASSWORDS:
        ROLE_PASSWORDS[role] = secrets.token_urlsafe(24)
    return ROLE_PASSWORDS[role]


def connection(role: str, database: str) -> str:
    return (
        f"postgresql+psycopg://{role}:{quote(role_password(role), safe='')}"
        f"@{DB_HOST}:{DB_PORT}/{database}"
    )


def build_credentials() -> dict[str, Path]:
    CREDENTIALS.mkdir(parents=True, exist_ok=True)
    _own_dir(ROOT, 0o750)
    _own_dir(CREDENTIALS, 0o750)
    # Seed every role's password before writing anything, so all the files for a
    # role share one value and a rerun cannot leave two different ones on disk.
    for role in ("nachtlabs_api", "nachtlabs_worker", "nachtlabs_migrator", "nachtlabs_executor"):
        role_password(role)
    # api-db and worker-db are the two the service accounts read, so they are
    # group-readable exactly as configure.py sets them. Everything else, including
    # the master key, stays owner-only.
    api = secret("api-db", connection("nachtlabs_api", DB_NAME), 0o640)
    worker = secret("worker-db", connection("nachtlabs_worker", DB_NAME), 0o640)
    migrator = secret("migration-db", connection("nachtlabs_migrator", DB_NAME), 0o640)
    executor = secret("executor-db", connection("nachtlabs_executor", DB_NAME))
    # The API decrypts stored secrets with this at request time, so it has to be
    # readable by the service account: 0640, group-owned, not writable. The
    # executor and migrator roles do not need it, but the mode is uniform because
    # a per-file mode that silently makes the API unusable is not worth the
    # tidiness.
    secret("master-key", base64.b64encode(secrets.token_bytes(32)).decode(), 0o640)
    bootstrap = secret("bootstrap-token", token(), 0o640)
    # The postgres image's entrypoint takes the superuser password from a file,
    # and that file must hold the password alone rather than a connection URL.
    # This is the migrator's own password, so there is no second identity here.
    migrator_url = urlparse(migrator.read_text(encoding="utf-8").strip())
    secret("postgres-superuser", migrator_url.password or fail("migration-db is malformed"), 0o600)
    # The integration suite refuses any database whose name does not end in
    # _test (tests/conftest.py), so the test database and its credentials are
    # provisioned here rather than being pointed at the application database.
    # The migrator owns this schema: applying the migrations needs DDL, and the
    # runtime roles are deliberately not given it.
    test = secret("test-migration-db", connection("nachtlabs_migrator", TEST_DB_NAME), 0o640)
    # The credential the test suite actually opens sessions with, which is the
    # least-privilege API role and not the migrator.
    secret("test-db", connection("nachtlabs_api", TEST_DB_NAME), 0o640)
    return {
        "api": api,
        "worker": worker,
        "migrator": migrator,
        "executor": executor,
        "bootstrap": bootstrap,
        "test": test,
    }


def origin() -> tuple[str, str, str]:
    """The public URL, its host, and the matching allowed-hosts value.

    ALLOWED_HOSTS must name the origin's host or the app refuses to start
    (packages/core/src/nachtlabs/settings.py), and TrustedHostMiddleware is built
    from it once at startup, so it cannot be widened later from a request. A
    wildcard is deliberately not used: the validator tests exact membership, and
    "*" would fail that check rather than widen it.
    """
    raw = os.environ.get("NACHTLABS_LAN_ORIGIN", "").strip().rstrip("/")
    if not raw:
        # Loopback is the right default for a laptop and an obviously wrong one
        # for a server, so the banner below makes the difference explicit rather
        # than letting a server start and refuse every browser.
        return (
            f"http://localhost:{WEB_PORT}",
            "localhost",
            f"localhost,127.0.0.1,{DB_HOST},{API_HOST}",
        )
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        fail(f"NACHTLABS_LAN_ORIGIN must be an absolute http(s) origin, not {raw!r}")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        fail("NACHTLABS_LAN_ORIGIN must be scheme, host and port only")
    if parsed.username or parsed.password:
        fail("NACHTLABS_LAN_ORIGIN must not contain credentials")
    host = parsed.hostname
    # A LAN install is plain HTTP by choice, and production mode refuses that
    # (settings.py), so the caller derives the environment from the scheme. The
    # runbook states what that costs: the session cookie loses Secure, and the
    # DevelopmentAdapter fixture becomes reachable.
    hosts = ",".join(dict.fromkeys([host, "localhost", "127.0.0.1", DB_HOST, API_HOST]))
    return raw, host, hosts


def write_env(name: str, values: dict[str, str], mode: int = 0o600) -> None:
    path = ROOT / name
    if path.exists():
        return
    if any("\n" in v or "\r" in v for v in values.values()):
        fail(f"{name}: configuration values must not contain newlines")
    body = "\n".join(f"{key}={shlex.quote(value)}" for key, value in values.items())
    path.write_text(body + "\n", encoding="utf-8")
    path.chmod(mode)
    _own(path)


def main() -> int:
    public_url, host, hosts = origin()
    files = build_credentials()
    env = "production" if public_url.startswith("https://") else "development"

    common = {
        "NACHTLABS_ENV": env,
        "NACHTLABS_PUBLIC_URL": public_url,
        "NACHTLABS_ALLOWED_HOSTS": hosts,
        "NACHTLABS_ALLOWED_ORIGINS": "",
        "NACHTLABS_MASTER_KEY_FILE": str(CREDENTIALS / "master-key"),
        "NACHTLABS_MASTER_KEY_ID": "v1",
        # Both default false and stay false. A public install must opt in
        # explicitly, and this step must never widen either on its own.
        "NACHTLABS_INTEGRATION_NETWORK_ENABLED": "false",
        "NACHTLABS_GIT_PROVIDER_NETWORK_ENABLED": "false",
        "NACHTLABS_SMTP_HOST": "",
        "NACHTLABS_SMTP_PORT": "587",
        "NACHTLABS_SMTP_TLS_MODE": "starttls",
        "NACHTLABS_SMTP_FROM": "nachtlabs@example.invalid",
        "NACHTLABS_SMTP_USERNAME": "",
    }
    write_env(
        "api.env",
        {
            **common,
            "NACHTLABS_DATABASE_URL_FILE": str(files["api"]),
            "NACHTLABS_BOOTSTRAP_TOKEN_FILE": str(files["bootstrap"]),
        },
        0o640,
    )
    write_env(
        "worker.env",
        {**common, "NACHTLABS_DATABASE_URL_FILE": str(files["worker"])},
        0o640,
    )
    write_env(
        "executor.env",
        {**common, "NACHTLABS_DATABASE_URL_FILE": str(files["executor"])},
        0o640,
    )
    write_env(
        "migration.env",
        {
            **common,
            "NACHTLABS_DATABASE_URL_FILE": str(files["migrator"]),
            "NACHTLABS_MIGRATION_DATABASE_URL_FILE": str(files["migrator"]),
        },
        0o640,
    )
    # A separate file for the integration schema, rather than an override in
    # compose: with-env.sh sources this file and would otherwise reassign
    # NACHTLABS_MIGRATION_DATABASE_URL_FILE back to the application database, so
    # the second migration would silently apply to the wrong one and exit 0.
    write_env(
        "test-migration.env",
        {
            **common,
            "NACHTLABS_DATABASE_URL_FILE": str(files["migrator"]),
            "NACHTLABS_MIGRATION_DATABASE_URL_FILE": str(files["test"]),
        },
        0o640,
    )
    write_env(
        "web.env",
        {
            "NODE_ENV": "production",
            "HOSTNAME": "0.0.0.0",
            "PORT": WEB_PORT,
            "NACHTLABS_INTERNAL_API_URL": "http://api:8000",
        },
        0o640,
    )

    print("")
    print("  NachtLabs is ready to start.")
    print("")
    print(f"    Open this in a browser:   {public_url}")
    if not os.environ.get("NACHTLABS_LAN_ORIGIN", "").strip():
        print("")
        print("    This is loopback. To serve your network, stop the stack and run:")
        print(f"      NACHTLABS_LAN_ORIGIN=http://<your-server-ip>:{WEB_PORT} \\")
        print("        docker compose up -d")
    print("")
    print("    First run creates the Owner. This installation does not require the")
    print("    one-time setup token, so the first account is whoever reaches the URL")
    print("    first. Set NACHTLABS_SETUP_TOKEN_REQUIRED=true and restart the API if")
    print("    this address is reachable by anyone you do not trust.")
    print("")
    print(f"    Generated credentials are in {CREDENTIALS} (mode 0600/0640).")
    print("    They are never written to the repository or baked into an image.")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
