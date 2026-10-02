#!/usr/bin/env python3
"""Generate container credentials and derive the browser origin at first start.

This is the container counterpart of scripts/configure.py. The native installer
asks the operator for four database passwords on a console; a container has no
console and no operator at that moment, so this generates them instead and
prints where the one-time values are.

The rules that carry over from configure.py are kept deliberately:

  * Nothing is ever overwritten. An existing file wins, so restarting the stack
    is a no-op and a rotation stays an explicit operator action. The one
    exception is an explicit NACHTLABS_REWRITE_CONFIG=true, which updates the
    operator-tunable switches in OPERATOR_KEYS and nothing else.
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

# The keys an operator may change on a live install, and the only ones the
# rewrite path below is allowed to touch. Deliberately a list and not a pattern:
# this rewrites a live install's configuration, so a key not named here cannot be
# reached by it no matter what it looks like.
#
# The first of these is the one that made the rewrite necessary at all. It is
# written into the generated files, and with-env.sh sources those files after
# compose has set the container's environment, so a compose-level value for it was
# silently discarded and the advertised way to enable it did nothing. They are
# recorded from the environment when a file is first written instead, which makes
# the documented command work and leaves the generated file as the single source.
#
# The CA bundle is here for the same reason and was the clearest case of it: the
# wizard told an operator to point this at a bundle in api.env and worker.env, but
# it was in neither the generated files nor compose, so there was no supported way
# to set it at all. It is a path, not a secret.
#
# The three origin keys are the other such case. They are only ever written from a
# NACHTLABS_LAN_ORIGIN the operator supplied, and are recomputed rather than
# accepted verbatim, so the allowlist permits a change of address without permitting
# an inconsistent one.
OPERATOR_KEYS = (
    "NACHTLABS_INTEGRATION_NETWORK_ENABLED",
    "NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE",
    "NACHTLABS_GIT_PROVIDER_NETWORK_ENABLED",
    "NACHTLABS_INTEGRATION_CA_FILE",
    "NACHTLABS_PUBLIC_URL",
    "NACHTLABS_ALLOWED_HOSTS",
    "NACHTLABS_ALLOWED_ORIGINS",
    "NACHTLABS_ENV",
)


def fail(message: str) -> None:
    print(f"container-init: {message}", file=sys.stderr)
    raise SystemExit(1)


def switch(key: str, default: str = "false") -> str:
    """Read a boolean switch, refusing anything that is not true or false.

    pydantic would reject a typo eventually, but the message names a setting
    several layers from this file and arrives after the stack is already up. A
    switch that decides whether this installation may send traffic off the box is
    worth refusing early and naming clearly.
    """
    raw = os.environ.get(key, default).strip().lower()
    if raw not in {"true", "false"}:
        fail(f"{key} must be true or false, not {raw!r}")
    return raw


def switch_if_set(key: str) -> str | None:
    """The value for a rewrite, or None when the environment did not mention it.

    A rewrite applies only what the operator actually named. Falling back to the
    default for a switch nobody mentioned would quietly undo a deliberate setting,
    because rebinding the origin without restating the egress switches would turn
    provider traffic back off on an install that had turned it on. The same is true
    of a CA bundle, where an empty default would silently drop a configured one.
    """
    if key not in os.environ:
        return None
    return switch(key)


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
        # A pre-existing file is never rewritten (the install contract above),
        # but its mode and ownership are re-applied so a restart can self-heal a
        # mode that was set wrong at first install (e.g. 0600 instead of 0640).
        path.chmod(mode)
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
    # 0640, like every peer: 0600 leaves the group read bit unset, so the
    # worker/executor service (gid 9000) cannot open its own DB URL.
    executor = secret("executor-db", connection("nachtlabs_executor", DB_NAME), 0o640)
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


def rewrite_env(name: str, values: dict[str, str]) -> bool:
    """Update named keys in an existing generated file, leaving the rest alone.

    Editing a value by hand means editing a file inside a named volume that the
    host cannot see, so this exists to make the documented change followable. It is
    deliberately narrow:

      * only keys in OPERATOR_KEYS are written; anything else is a no-op, so a
        caller cannot reach a credential, a token or a database URL by passing a
        wider dict,
      * every other line is preserved exactly, including order, quoting and
        comments, so an operator's own notes survive,
      * a key that is absent is appended rather than invented elsewhere, and the
        file's mode and group ownership are put back after writing.

    Returns whether anything changed, so a no-op run stays quiet.
    """
    path = ROOT / name
    if not path.exists():
        return False
    updates = {k: v for k, v in values.items() if k in OPERATOR_KEYS}
    if not updates:
        return False
    stat = path.stat()
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        # Only an unquoted assignment is a key. Quoting is how a value containing
        # '=' is stored, so splitting on the first '=' identifies the key and
        # leaves the value's own '=' alone.
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in updates:
            out.append(f"{key}={shlex.quote(updates[key])}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={shlex.quote(value)}")
    body = "\n".join(out) + "\n"
    if body == path.read_text(encoding="utf-8"):
        return False
    # Replace rather than rewrite in place: the service account must never observe
    # a partially written configuration file. The temporary is created with the
    # final mode rather than chmod-ed to it, so it is never briefly readable at
    # whatever the umask happened to be.
    tmp = path.with_name(path.name + ".rewrite")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.st_mode & 0o7777)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _own(tmp)
    tmp.replace(path)
    return True


def main() -> int:
    public_url, host, hosts = origin()
    files = build_credentials()
    env = "production" if public_url.startswith("https://") else "development"

    # Recorded, never decided. Both default false and an unset environment stays
    # false, so this step cannot widen the installation on its own; it only records
    # an opt-in the operator already made in the environment. The value is written
    # into the generated files rather than passed through compose, because
    # with-env.sh sources those files after compose has set the container's
    # environment and would otherwise discard it.
    #
    # NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE was not written here before, which
    # is why its compose override worked while this one did not. It is recorded the
    # same way now so the two switches behave identically.
    operator = {
        "NACHTLABS_INTEGRATION_NETWORK_ENABLED": switch("NACHTLABS_INTEGRATION_NETWORK_ENABLED"),
        "NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE": switch(
            "NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE"
        ),
        "NACHTLABS_GIT_PROVIDER_NETWORK_ENABLED": switch("NACHTLABS_GIT_PROVIDER_NETWORK_ENABLED"),
        # Not a switch: a path, so no strict boolean parsing. Empty means trust
        # only the system roots, which is the correct default.
        "NACHTLABS_INTEGRATION_CA_FILE": os.environ.get("NACHTLABS_INTEGRATION_CA_FILE", ""),
    }

    # The origin an install answers on is derived, not typed, and an install that
    # has already started could not change it at all: PUBLIC_URL and
    # ALLOWED_HOSTS were outside the rewrite allowlist, and a file is never
    # overwritten. Moving off loopback therefore meant discarding the volume and
    # with it the Owner account, which is an absurd price for a Host header.
    #
    # These are recomputed from NACHTLABS_LAN_ORIGIN through origin() rather than
    # accepted verbatim, so the allowed hosts can never disagree with the origin
    # they are meant to permit, and NACHTLABS_ENV still follows the scheme.
    #
    # Only when a new origin is actually supplied. A rewrite that is merely about
    # provider egress must leave the origin alone, or an unset NACHTLABS_LAN_ORIGIN
    # would quietly rebind a working LAN install back to loopback and lock the
    # operator out of their own server.
    rebind = {}
    if os.environ.get("NACHTLABS_LAN_ORIGIN", "").strip():
        rebind = {
            "NACHTLABS_PUBLIC_URL": public_url,
            "NACHTLABS_ALLOWED_HOSTS": hosts,
            "NACHTLABS_ENV": env,
        }
        # Extra browser origins, because an install usually has more than one way
        # to be reached: the LAN address for a machine on another box, and
        # loopback for whoever is sitting at the server. Without this a rebind
        # silently revokes whichever of the two it replaced, and the symptom is a
        # 403 on login that looks like a credentials problem.
        extra = os.environ.get("NACHTLABS_EXTRA_ORIGINS", "").strip()
        if extra:
            for candidate in extra.split(","):
                candidate = candidate.strip()
                if not candidate:
                    continue
                parsed = urlparse(candidate)
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.path not in {"", "/"}
                    or parsed.query
                    or parsed.fragment
                    or parsed.username
                    or parsed.password
                ):
                    fail(
                        "NACHTLABS_EXTRA_ORIGINS entries must be a bare scheme, host "
                        f"and optional port, not {candidate!r}"
                    )
                # A permitted origin whose host TrustedHostMiddleware would reject
                # is refused at startup by settings.py, so catching it here names
                # the actual mistake rather than an unexplained 400 much later.
                if parsed.hostname not in hosts.split(","):
                    fail(
                        f"NACHTLABS_EXTRA_ORIGINS host {parsed.hostname!r} is not in "
                        f"the allowed hosts derived from the origin ({hosts})"
                    )
            rebind["NACHTLABS_ALLOWED_ORIGINS"] = extra

    # Signed worker→executor job channel (ADR 0007, control 4). The HMAC key
    # is generated here at install time and is never baked into an image:
    # worker.env signs job rows, executor.env verifies them, so both files
    # must point at the same credential. Regenerating the key invalidates
    # every unsigned job row -- expected, and the operator's decision to make.
    channel_key = CREDENTIALS / "executor-channel-key"
    channel_key.parent.mkdir(mode=0o750, exist_ok=True)
    if not channel_key.exists():
        # ADR 0007 (control 4): the worker signs and the executor verifies with
        # this key. Write once, like secret() -- rotating it on every restart
        # would invalidate every signed job row, which is an operator action,
        # never a side effect of a restart.
        channel_key.write_bytes(base64.b64encode(os.urandom(32)))
    # 0640 root:<service gid>, group-owned, so BOTH the worker (signer) and the
    # executor (verifier), running under that gid, can read it. 0600 root:root,
    # readable by neither, was what disabled the HMAC channel end to end.
    channel_key.chmod(0o640)
    _own(channel_key)

    common = {
        "NACHTLABS_ENV": env,
        "NACHTLABS_PUBLIC_URL": public_url,
        "NACHTLABS_ALLOWED_HOSTS": hosts,
        "NACHTLABS_ALLOWED_ORIGINS": "",
        "NACHTLABS_MASTER_KEY_FILE": str(CREDENTIALS / "master-key"),
        "NACHTLABS_MASTER_KEY_ID": "v1",
        **operator,
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
    channel_env = {"NACHTLABS_EXECUTOR_CHANNEL_KEY_FILE": str(channel_key)}
    write_env(
        "worker.env",
        {**common, "NACHTLABS_DATABASE_URL_FILE": str(files["worker"]), **channel_env},
        0o640,
    )
    write_env(
        "executor.env",
        {**common, "NACHTLABS_DATABASE_URL_FILE": str(files["executor"]), **channel_env},
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

    # The switches are recorded when a file is first written, and a file is never
    # rewritten, so an install created before this existed keeps its original
    # values forever. NACHTLABS_REWRITE_CONFIG=true applies the environment to an
    # existing install instead. It is a separate step rather than automatic
    # because a restart must stay a no-op, and because changing whether this
    # installation may send traffic off the box is not something to do by
    # accident while chasing an unrelated failure.
    # Bound unconditionally so the summary below can report what the install will
    # actually do, not what this invocation happened to pass. On a rewrite the
    # switches may have been left alone, and a hint derived from the creation
    # default would tell an operator provider traffic is off when they turned it on
    # last week.
    applied: dict[str, str] = {}
    if switch("NACHTLABS_REWRITE_CONFIG") == "true":
        # Only what the operator named, plus a rebind if they gave an origin. A key
        # the environment does not mention keeps the value already in the file.
        applied = dict(rebind)
        for key in (
            "NACHTLABS_INTEGRATION_NETWORK_ENABLED",
            "NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE",
            "NACHTLABS_GIT_PROVIDER_NETWORK_ENABLED",
        ):
            given = switch_if_set(key)
            if given is not None:
                applied[key] = given
        if "NACHTLABS_INTEGRATION_CA_FILE" in os.environ:
            applied["NACHTLABS_INTEGRATION_CA_FILE"] = os.environ["NACHTLABS_INTEGRATION_CA_FILE"]

        # Every generated file that carries the keys, not just api.env and
        # worker.env: they share one dict, and leaving any of them behind would
        # give a value that depends on which file a service happened to read.
        # A rebind is applied to the same set, because the host policy has to be
        # identical everywhere or a service accepts a Host the others reject.
        for name in (
            "api.env",
            "worker.env",
            "executor.env",
            "migration.env",
            "test-migration.env",
        ):
            rewrite_env(name, applied)
        print("")
        if applied:
            print(f"    Applied {', '.join(sorted(applied))} to the existing configuration.")
        else:
            print("    Nothing to apply: name a value to change, or pass an origin.")
        if rebind:
            print(f"    This installation now answers on {public_url}.")
            print("    Allowed hosts are recomputed from that origin, not typed.")
        print("    Restart the services that read it: docker compose restart api worker")
        print("")

    print("")
    print("  NachtLabs is ready to start.")
    print("")
    print(f"    Open this in a browser:   {public_url}")
    if rebind:
        # Say what the rewrite did and what it did not: the egress switches still
        # hold whatever was already recorded, because an unset switch keeps its
        # previous value rather than reverting to the default.
        print("")
        print("    The origin was recorded. It takes effect after a restart:")
        print("      docker compose restart api worker")
        print("    Only the address changed. The egress switches kept their values.")
    elif not os.environ.get("NACHTLABS_LAN_ORIGIN", "").strip():
        print("")
        print("    This is loopback. To serve your network:")
        print(f"      NACHTLABS_LAN_ORIGIN=http://<your-server-ip>:{WEB_PORT} \\")
        print("        NACHTLABS_REWRITE_CONFIG=true docker compose run --rm init")
        print("        docker compose restart api worker")
        print("    On a first start, omitting NACHTLABS_REWRITE_CONFIG is enough.")
    print("")
    print("    First run creates the Owner. This installation does not require the")
    print("    one-time setup token, so the first account is whoever reaches the URL")
    print("    first. Set NACHTLABS_SETUP_TOKEN_REQUIRED=true and restart the API if")
    print("    this address is reachable by anyone you do not trust.")
    print("")
    # Report what the install will actually do, not what this invocation happened to
    # pass. On a rewrite the switches may have been left alone, and a hint derived
    # from the creation default would tell an operator provider traffic is off when
    # they turned it on last week.
    effective = {**operator, **applied}
    if effective["NACHTLABS_INTEGRATION_NETWORK_ENABLED"] == "false":
        print("    Provider traffic is off. The endpoint step will not check or call a")
        print("    model until an operator turns it on, which needs the value recorded")
        print("    in the generated files and a restart of the api and worker:")
        print("      NACHTLABS_INTEGRATION_NETWORK_ENABLED=true \\")
        print("        NACHTLABS_REWRITE_CONFIG=true docker compose run --rm init")
        print("        docker compose restart api worker")
        print("")
    print(f"    Generated credentials are in {CREDENTIALS} (mode 0600/0640).")
    print("    They are never written to the repository or baked into an image.")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
