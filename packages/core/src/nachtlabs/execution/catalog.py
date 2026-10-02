"""Executable catalog + operator qualification, verified by HMAC-SHA256.

Model D trust model:

* The **catalog** is the operator's choice of which executables may run at
  all. It lives at ``/etc/nachtlabs/execution-catalog.json`` — a fixed
  absolute path inside the read-only-mounted config volume — and is small
  (≤ 1 MiB).
* The **qualification receipt** is the operator's one-time attestation
  that *this exact catalog* was reviewed and approved at *this exact
  release*. The operator runs ``scripts/qualify-executor.py`` as root,
  which writes ``/etc/nachtlabs/executor-qualification.json`` containing
  the catalog's SHA-256 digest and an **HMAC-SHA256** over the raw catalog
  bytes, computed with a qualification key file (``/etc/nachtlabs/
  credentials/executor-qualification-key``, 32 base64-
  encoded bytes, 0640 root:9000 so uid 9000 can read it).
* The **executor service** (uid 9000) reads both files, recomputes the
  HMAC, and compares. It never needs to be root, never needs
  ``os.geteuid() == 0``, and never needs the receipt file to be
  root-owned. The key file is the trust anchor: it is the one secret the
  executor must be allowed to read, and it is the same secret the
  operator's qualification script uses to sign.

The chain of trust therefore moves from "the executor is running as root,
so the file on disk is trusted" (Model A) to "the operator signed the
catalog with a key the executor is allowed to read, and the signed bytes
match the file on disk" (Model D). The euid / root-ownership checks are
gone. ``os.name == "posix"`` is retained: the executor is assumed to run
on Linux (the kernel rlimits in ``sandbox.py`` and the container's own
cgroup policy both depend on it).
"""

import base64
import hashlib
import hmac
import json
import os
import stat
from ipaddress import ip_address
from pathlib import Path
from typing import Any, cast

from nachtlabs.errors import DomainError, require

CATALOG = Path("/etc/nachtlabs/execution-catalog.json")
QUALIFICATION = Path("/etc/nachtlabs/executor-qualification.json")
QUALIFICATION_KEY = Path("/etc/nachtlabs/credentials/executor-qualification-key")
RELEASE = "0.1.0"


def _read_trusted_bytes(path: Path) -> bytes:
    """Read a config-volume file under the constraints we can still
    enforce without an euid check:

    * the path is a real file (no symlinks on any component of the path —
      the config volume is ``ro`` in the container, so a symlink could not
      be used to escape into a writable path, but we still reject symlinks
      as a general rule);
    * the file is at most 1 MiB (catalog + receipt are both tiny by
      design; a 1 MiB ceiling keeps the read-and-hash cost bounded and
      the disk-usage attack bounded);
    * the file is not group- or world-writable (a writable catalog file
      would be a self-modification vector even in ``ro`` mode, since the
      volume is mounted from a host path the operator controls).

    Ownership by uid 0 is no longer required: in Model D, the receipt's
    HMAC is the trust boundary, not the file's owner.
    """
    resolved = path.resolve(strict=True)
    require(resolved == path, 409, "catalog_symlink", "Trusted paths cannot contain symlinks")
    for item in [path, *path.parents]:
        info = item.stat()
        require(
            not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH),
            409,
            "catalog_permissions",
            "Execution configuration must not be group- or world-writable",
        )
    require(
        path.is_file() and path.stat().st_size <= 1048576,
        409,
        "catalog_size",
        "Invalid catalog size",
    )
    return path.read_bytes()


def trusted_file(path: Path) -> bytes:
    """Public trusted-read API for config-volume files (pinned by
    ``tests/native/test_executor_boundary.py``: ``json.loads(trusted_file(CATALOG))``).

    Returns the raw bytes of a file located under ``/etc/nachtlabs`` with
    the size and permission constraints of ``_read_trusted_bytes``. The
    file's content is *not* parsed here — callers decide (catalog JSON,
    receipt JSON, opaque keys). Trust in Model D derives from the
    qualification HMAC over these exact bytes, not from the file's owner.
    """
    resolved = path
    require(
        resolved.parent == Path("/etc/nachtlabs") or resolved.parent == Path("/etc/nachtlabs/credentials"),
        409,
        "trusted_file_location",
        "Trusted files must live in /etc/nachtlabs",
    )
    return _read_trusted_bytes(resolved)


def _qualification_key() -> bytes:
    """Read the 32-byte qualification key the operator's ``qualify-executor.py``
    used to sign the receipt. The key is a base64-encoded 32-byte value in
    a file readable by the executor (uid 9000); the executor needs only
    *read* access — it never writes, so the key is not a secret of the
    runtime in the usual sense, it is a shared secret between the
    operator's qualification action and the executor's verification."""
    try:
        raw = QUALIFICATION_KEY.read_bytes().strip()
    except OSError as exc:
        raise PermissionError(
            f"Qualification key unreadable ({exc}); operator must run "
            "scripts/qualify-executor.py to create it"
        ) from exc
    key = base64.b64decode(raw, validate=True)
    require(len(key) == 32, 409, "qualification_key", "Qualification key must be 32 bytes")
    return key


def _verify_receipt(raw_catalog: bytes, receipt: dict[str, Any]) -> None:
    """Check the receipt's HMAC against the raw catalog bytes, and that the
    receipt is for this release.

    The HMAC is computed over the **raw catalog bytes** (not the digest),
    which means any single bit change to the catalog invalidates the
    receipt. This is strictly stronger than "SHA-256 matches"
    (rehash-collision-resistant), and it is the exact check the
    operator's qualification script produces, so they round-trip.
    """
    require(receipt.get("qualified") is True, 409, "executor_unqualified", "Operator qualification is required")
    require(receipt.get("release") == RELEASE, 409, "executor_unqualified", "Operator qualification is required for this exact catalog and release")

    expected_sha = receipt.get("catalog_sha256")
    require(
        isinstance(expected_sha, str)
        and hashlib.sha256(raw_catalog).hexdigest() == expected_sha,
        409,
        "executor_unqualified",
        "Operator qualification is required for this exact catalog and release",
    )

    expected_sig: str | None = receipt.get("qualification_hmac")
    require(
        isinstance(expected_sig, str) and len(expected_sig) == 64,
        409,
        "executor_unqualified",
        "Operator qualification receipt is malformed",
    )
    key = _qualification_key()
    actual_sig = hmac.new(key, raw_catalog, hashlib.sha256).hexdigest()
    require(
        # `actual_sig` and the narrowed `expected_sig` are both plain str;
        # compare_digest wants two str of equal type, which this is.
        hmac.compare_digest(actual_sig, str(expected_sig)),
        409,
        "executor_unqualified",
        "Operator qualification HMAC does not match the catalog",
    )


def catalog() -> dict[str, Any]:
    """Load the execution catalog and verify the operator's qualification
    receipt against it, using an HMAC-SHA256 comparison rather than an
    euid check.

    Returns the parsed catalog, or raises a DomainError (409,
    ``executor_unqualified``) on any verification failure.
    """
    require(
        os.name == "posix",
        409,
        "linux_executor_required",
        "Native Linux executor required",
    )
    raw = _read_trusted_bytes(CATALOG)
    receipt_raw = _read_trusted_bytes(QUALIFICATION)
    try:
        receipt = json.loads(receipt_raw)
    except json.JSONDecodeError as exc:
        raise DomainError(409, "executor_unqualified", "Operator qualification receipt is not valid JSON") from exc
    _verify_receipt(raw, receipt)

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DomainError(409, "catalog_schema", "Catalog is not valid JSON") from exc
    require(value.get("schema") == 1, 409, "catalog_schema", "Unsupported execution catalog")

    for address in value.get("allowed_addresses", []):
        ip = ip_address(address)
        require(
            not ip.is_loopback
            and not ip.is_link_local
            and not ip.is_reserved
            and not ip.is_multicast
            and not ip.is_unspecified
            and (ip.is_global or value.get("allow_private_network") is True),
            409,
            "executor_network_policy",
            "Use an explicitly approved, dedicated model endpoint address",
        )

    runtime = Path(value["runtime_root"])
    pins = value.get("runtime_files", {})
    require(bool(pins), 409, "runtime_unpinned", "Pin runtime executable and check script digests")
    for name, expected in pins.items():
        relative = Path(name)
        require(
            relative.is_absolute() and ".." not in relative.parts,
            409,
            "runtime_pin",
            "Invalid runtime pin",
        )
        target = runtime / name.lstrip("/")
        require(
            target.resolve() == target
            and target.is_file(),
            409,
            "runtime_pin",
            "Runtime pin target unreachable",
        )
        digest = hashlib.sha256()
        with target.open("rb") as source:
            while block := source.read(65536):
                digest.update(block)
        require(
            digest.hexdigest() == expected,
            409,
            "runtime_changed",
            "Qualified runtime file changed",
        )
    executables = [v["argv"][0] for v in value["commands"].values()] + [
        v["executable"] for v in value["agents"].values()
    ]
    require(
        all(name in pins for name in executables),
        409,
        "runtime_unpinned",
        "Every executable needs a runtime pin",
    )
    return cast("dict[str, Any]", value)


def command(value: Any) -> list[str]:
    require(
        isinstance(value, list)
        and 0 < len(value) <= 64
        and all(isinstance(v, str) and "\x00" not in v for v in value)
        and value[0].startswith("/"),
        409,
        "command_catalog",
        "Invalid catalog command",
    )
    return cast("list[str]", value)
