"""Record an operator's completed qualification; never runs acceptance on their behalf."""
import argparse
import hashlib
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--evidence", type=Path, required=True)
parser.add_argument("--confirm-linux-isolation-passed", action="store_true")
args = parser.parse_args()
if os.geteuid() != 0 or not args.confirm_linux_isolation_passed:
    raise SystemExit("Requires root and explicit acknowledgement of completed Linux isolation acceptance")
catalog = Path("/etc/nachtlabs/execution-catalog.json")
evidence = args.evidence.resolve(strict=True)
if not evidence.is_file() or evidence.stat().st_size < 100:
    raise SystemExit("Provide the completed qualification report, not the unfilled template")
# This is an operator attestation, not automated proof of the content of the report.
receipt = {"qualified": True, "release": "0.1.0",
           "catalog_sha256": hashlib.sha256(catalog.read_bytes()).hexdigest(),
           "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
           "evidence_reference": str(evidence)}
path = Path("/etc/nachtlabs/executor-qualification.json")
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as handle:
    json.dump(receipt, handle, indent=2)
print("Operator qualification recorded. Executor was not started. Changes to the catalog require requalification.")
