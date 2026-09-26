"""One transient systemd cgroup per command, fresh writable home and bounded tmpfs."""

import ipaddress
import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from nachtlabs.errors import require
from nachtlabs.execution.catalog import command
from nachtlabs.execution.process import Result, bounded

ROOT = Path("/var/lib/nachtlabs-executor")
ACTIVE = ROOT / "active.json"


def stop_unit(unit: str) -> None:
    require(
        unit.startswith("nachtlabs-job-")
        and unit.endswith(".service")
        and all(c.isalnum() or c in "-." for c in unit),
        409,
        "unit_name",
        "Invalid execution unit",
    )
    bounded(["/usr/bin/systemctl", "stop", unit], 30, 65536)
    status = bounded(["/usr/bin/systemctl", "is-active", unit], 10, 4096)
    require(
        status.output.decode().strip() in {"inactive", "failed", "unknown"},
        409,
        "unit_stop_uncertain",
        "Cannot confirm that the execution cgroup stopped",
    )


def recover() -> None:
    # On restart, stop any recorded cgroup before releasing the durable lease.
    if ACTIVE.exists():
        data = json.loads(ACTIVE.read_text())
        stop_unit(data["unit"])
        ACTIVE.unlink()
    for workspace in ROOT.glob("work-*"):
        require(
            not workspace.is_symlink() and workspace.resolve().parent == ROOT,
            409,
            "workspace_recovery",
            "Unexpected workspace recovery path",
        )
        if workspace.is_mount():
            result = bounded(["/usr/bin/umount", str(workspace)], 20, 4096)
            require(result.code == 0, 409, "workspace_recovery", "Orphan workspace remains mounted")
        workspace.rmdir()


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
    command(argv)
    runtime = Path(configuration["runtime_root"])
    require(
        runtime.is_absolute()
        and runtime.is_dir()
        and runtime.resolve() == runtime
        and runtime.stat().st_uid == 0
        and not runtime.stat().st_mode & 0o022,
        409,
        "runtime_root",
        "A protected curated runtime root is required",
    )
    unit = "nachtlabs-job-" + uuid4().hex + ".service"
    ACTIVE.write_text(json.dumps({"unit": unit}))
    ACTIVE.chmod(0o600)
    properties = {
        "Type": "exec",
        "DynamicUser": "yes",
        "RootDirectory": str(runtime),
        "WorkingDirectory": "/work",
        "ProtectSystem": "strict",
        "ProtectHome": "yes",
        "PrivateTmp": "yes",
        "PrivateDevices": "yes",
        "NoNewPrivileges": "yes",
        "ProtectKernelTunables": "yes",
        "ProtectKernelModules": "yes",
        "ProtectKernelLogs": "yes",
        "ProtectControlGroups": "yes",
        "ProtectProc": "invisible",
        "ProcSubset": "pid",
        "RestrictSUIDSGID": "yes",
        "LockPersonality": "yes",
        "RestrictNamespaces": "yes",
        "CapabilityBoundingSet": "",
        "AmbientCapabilities": "",
        "RestrictAddressFamilies": "AF_UNIX AF_INET AF_INET6" if network else "AF_UNIX",
        "IPAddressDeny": "any",
        "PrivateNetwork": "no" if network else "yes",
        "KillMode": "control-group",
        "SendSIGKILL": "yes",
        "TimeoutStopSec": "5s",
        "RuntimeMaxSec": str(policy["timeout_seconds"]),
        "MemoryMax": "1G",
        "MemorySwapMax": "0",
        "TasksMax": "128",
        "CPUQuota": "100%",
        "LimitNOFILE": "1024",
        "LimitCORE": "0",
        "BindPaths": str(workspace) + ":/work",
        "BindReadOnlyPaths": str(inputs) + ":/run/nachtlabs/input",
        "TemporaryFileSystem": "/home:rw,size=64M /tmp:rw,size=128M",
        "Environment": "HOME=/tmp/home PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8",
        "UMask": "0077",
    }
    if network:
        addresses = configuration.get("allowed_addresses", [])
        require(bool(addresses), 409, "network_policy", "Pinned egress policy required")
        properties["IPAddressAllow"] = " ".join(str(ipaddress.ip_address(v)) for v in addresses)
    args = ["/usr/bin/systemd-run", "--quiet", "--wait", "--pipe", "--collect", "--unit", unit]
    for key, value in properties.items():
        args.extend(["--property", key + "=" + value])
    try:
        return bounded(
            args + ["--"] + argv,
            policy["timeout_seconds"] + 10,
            policy["max_output_bytes"],
            cancelled,
            stdin,
        )
    finally:
        stop_unit(unit)
        ACTIVE.unlink(missing_ok=True)


class Workspace:
    def __init__(self, budget: int):
        ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix="work-", dir=ROOT))
        self.budget = budget

    def __enter__(self) -> Path:
        result = bounded(
            [
                "/usr/bin/mount",
                "-t",
                "tmpfs",
                "-o",
                f"size={self.budget},nr_inodes=24000,nosuid,nodev,mode=0777",
                "tmpfs",
                str(self.path),
            ],
            20,
            4096,
        )
        require(result.code == 0, 409, "workspace_mount", "Bounded workspace mount unavailable")
        return self.path

    def __exit__(self, *args: object) -> None:
        result = bounded(["/usr/bin/umount", str(self.path)], 20, 4096)
        require(
            result.code == 0,
            409,
            "workspace_unmount",
            "Workspace cleanup requires operator attention",
        )
        self.path.rmdir()


def writable_copy(source: Path, target: Path) -> None:
    shutil.copytree(source, target, dirs_exist_ok=True, symlinks=False)
    for path in target.rglob("*"):
        path.chmod(0o777 if path.is_dir() or path.stat().st_mode & 0o111 else 0o666)
