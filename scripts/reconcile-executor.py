"""Local-only recovery of an uncertain job after operator inspection."""
import argparse
import json
import os
from uuid import UUID
from sqlalchemy import select
from nachtlabs.database import session
from nachtlabs.execution import sandbox
from nachtlabs.factory_models import ExecutorJob, Run
from nachtlabs.security import encrypt
from nachtlabs.workflows.state import event

parser = argparse.ArgumentParser()
parser.add_argument("job_id", type=UUID)
parser.add_argument("--reason", required=True)
parser.add_argument("--confirm-executor-stopped", action="store_true")
args = parser.parse_args()
if os.geteuid() != 0 or not args.confirm_executor_stopped or len(args.reason) < 10:
    raise SystemExit("Stop executor and inspect cgroups, filesystem, and delivery intent; then provide an explanation")
import fcntl
lock = (sandbox.ROOT / "broker.lock").open("a")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
sandbox.recover()
with session() as db:
    job = db.scalar(select(ExecutorJob).where(ExecutorJob.id == args.job_id).with_for_update())
    if job is None or job.state != "uncertain":
        raise SystemExit("Only uncertain jobs can be reconciled")
    run = db.scalar(select(Run).where(Run.id == job.run_id).with_for_update())
    if job.stage == "delivery":
        # Never blindly retry push/PR creation. Only a durable completed local journal is accepted.
        path = sandbox.ROOT / "delivery" / (str(run.id) + "-" + str(job.attempt) + ".json")
        journal = json.loads(path.read_text()) if path.exists() else {}
        if journal.get("state") != "complete" or journal.get("candidate") != run.candidate:
            raise SystemExit("Delivery is unresolved. Inspect the remote using an authorized environment; preserve this job until reviewed recovery is possible.")
        job.result = encrypt(journal["result"], f"executor:{job.id}")
        job.state = "succeeded"
        run.state = "executor_wait"
    else:
        job.result = encrypt({"error_code": "operator_reconciled_failure"}, f"executor:{job.id}")
        job.state = "failed"
        run.state = "executor_wait"
    event(db, run, "executor.reconciled", {"actor": "local-administrator", "job_id": str(job.id)})
    db.commit()
print("Reconciliation recorded. A failed run still needs a new plan and human approval.")
