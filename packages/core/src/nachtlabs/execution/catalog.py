"""Root-controlled executable catalog and explicit qualification gate."""
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from nachtlabs.errors import require

CATALOG = Path("/etc/nachtlabs/execution-catalog.json")
QUALIFICATION = Path("/etc/nachtlabs/executor-qualification.json")


def trusted_file(path: Path) -> bytes:
    resolved = path.resolve(strict=True)
    require(resolved == path, 409, "catalog_symlink", "Trusted paths cannot contain symlinks")
    for item in [path, *path.parents]:
        info = item.stat()
        require(info.st_uid == 0 and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH),
                409, "catalog_permissions", "Execution configuration must be root owned and protected")
    require(path.is_file() and path.stat().st_size <= 1048576, 409, "catalog_size", "Invalid catalog size")
    return path.read_bytes()


def catalog() -> dict[str, Any]:
    require(os.name == "posix" and os.geteuid() == 0, 409, "linux_executor_required", "Native privileged Linux executor required")
    raw = trusted_file(CATALOG)
    receipt = json.loads(trusted_file(QUALIFICATION))
    require(receipt.get("qualified") is True and receipt.get("catalog_sha256") == hashlib.sha256(raw).hexdigest()
            and receipt.get("release") == "0.1.0",
            409, "executor_unqualified", "Operator qualification is required for this exact catalog and release")
    value = json.loads(raw)
    require(value.get("schema") == 1, 409, "catalog_schema", "Unsupported execution catalog")
    from ipaddress import ip_address
    from nachtlabs.integrations.transport import METADATA
    for address in value.get("allowed_addresses", []):
        ip = ip_address(address)
        require(ip not in METADATA and not ip.is_loopback and not ip.is_link_local and not ip.is_reserved
                and not ip.is_multicast and not ip.is_unspecified
                and (ip.is_global or value.get("allow_private_network") is True),
                409, "executor_network_policy", "Use an explicitly approved, dedicated model endpoint address")
    runtime = Path(value["runtime_root"])
    pins = value.get("runtime_files", {})
    require(bool(pins), 409, "runtime_unpinned", "Pin runtime executable and check script digests")
    for name, expected in pins.items():
        relative = Path(name)
        require(relative.is_absolute() and ".." not in relative.parts, 409, "runtime_pin", "Invalid runtime pin")
        target = runtime / name.lstrip("/")
        require(target.resolve() == target and target.is_file() and target.stat().st_uid == 0
                and not target.stat().st_mode & 0o022, 409, "runtime_permissions", "Runtime pin is not protected")
        for parent in target.parents:
            require(parent.stat().st_uid == 0 and not parent.stat().st_mode & 0o022,
                    409, "runtime_permissions", "Runtime ancestors must be root controlled")
            if parent == runtime:
                break
        digest = hashlib.sha256()
        with target.open("rb") as source:
            while block := source.read(65536):
                digest.update(block)
        require(digest.hexdigest() == expected, 409, "runtime_changed", "Qualified runtime file changed")
    executables = [v["argv"][0] for v in value["commands"].values()] + [v["executable"] for v in value["agents"].values()]
    require(all(name in pins for name in executables), 409, "runtime_unpinned", "Every executable needs a runtime pin")
    return value


def command(value: Any) -> list[str]:
    require(isinstance(value, list) and 0 < len(value) <= 64
            and all(isinstance(v, str) and "\x00" not in v for v in value)
            and value[0].startswith("/"), 409, "command_catalog", "Invalid catalog command")
    return value
