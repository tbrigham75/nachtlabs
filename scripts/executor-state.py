"""Encrypted companion archive for stopped executor state. Never restores qualification."""

import argparse
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["backup", "restore"])
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--recipient")
parser.add_argument("--identity", type=Path)
parser.add_argument("--destination", type=Path)
parser.add_argument("--services-stopped", action="store_true")
args = parser.parse_args()
if os.geteuid() != 0 or not args.services_stopped:
    raise SystemExit("Requires root and stopped API, worker and executor services")
for unit in ("nachtlabs-api", "nachtlabs-worker", "nachtlabs-executor"):
    state = subprocess.run(
        ["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10
    )
    if state.stdout.strip() not in {"inactive", "failed", "unknown"}:
        raise SystemExit("Stop NachtLabs services before taking or restoring the paired snapshot")
os.umask(0o077)
with tempfile.TemporaryDirectory(prefix="nachtlabs-state-") as name:
    temporary = Path(name)
    bundle_path = temporary / "executor.tar"
    if args.mode == "backup":
        if not args.recipient or args.archive.exists():
            raise SystemExit("Provide an age recipient and a new archive path")
        root = Path("/var/lib/nachtlabs-executor")
        with tarfile.open(bundle_path, "w") as bundle:
            for directory in ("candidates", "delivery", "mirrors"):
                source = root / directory
                if not source.exists():
                    continue
                for item in [source, *source.rglob("*")]:
                    if item.is_symlink() or not (item.is_file() or item.is_dir()):
                        raise SystemExit(
                            "Unsafe file type in executor state; inspect before backup"
                        )
                # dereference avoids preserving local-mirror hardlinks as extraction links.
                bundle.dereference = True
                bundle.add(source, arcname=directory)
            catalog = Path("/etc/nachtlabs/execution-catalog.json")
            if catalog.exists():
                bundle.add(catalog, arcname="execution-catalog.json")
        partial = args.archive.with_suffix(args.archive.suffix + ".partial")
        try:
            with partial.open("xb") as output:
                subprocess.run(
                    ["age", "--encrypt", "--recipient", args.recipient, str(bundle_path)],
                    stdout=output,
                    check=True,
                )
                output.flush()
                os.fsync(output.fileno())
            os.link(partial, args.archive)
        finally:
            partial.unlink(missing_ok=True)
        print(
            "Executor state encrypted. Keep with the database/key snapshot from this same stopped-service window."
        )
    else:
        if (
            not args.identity
            or not args.destination
            or args.destination.exists()
            or not args.destination.is_absolute()
        ):
            raise SystemExit(
                "Restore requires an age identity and a new absolute destination directory"
            )
        destination = args.destination.resolve()
        if destination in {
            Path("/"),
            Path("/etc"),
            Path("/var"),
            Path("/var/lib/nachtlabs-executor"),
        }:
            raise SystemExit("Restore only to a separate staging directory")
        with bundle_path.open("xb") as output:
            subprocess.run(
                ["age", "--decrypt", "--identity", str(args.identity), str(args.archive)],
                stdout=output,
                check=True,
            )
        with tarfile.open(bundle_path) as bundle:
            members = bundle.getmembers()
            if len(members) > 200000 or sum(v.size for v in members) > 68719476736:
                raise SystemExit("Archive exceeds restore budget")
            names = set()
            for member in members:
                path = PurePosixPath(member.name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or not path.parts
                    or member.name in names
                    or path.parts[0]
                    not in {"candidates", "delivery", "mirrors", "execution-catalog.json"}
                    or not (member.isfile() or member.isdir())
                ):
                    raise SystemExit("Archive contains unsafe or duplicate entries")
                names.add(member.name)
            destination.mkdir(mode=0o700)
            bundle.extractall(destination, filter="data")
        print(
            "Staged executor state. Verify candidates against database evidence before installation. Requalify the runtime; no qualification receipt was restored."
        )
