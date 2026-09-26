"""Single-host executor broker. Never started by the API or ordinary worker."""

import json
import logging
import signal
import threading
import time
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from nachtlabs.access import Principal
from nachtlabs.database import session
from nachtlabs.errors import DomainError, require
from nachtlabs.execution import sandbox
from nachtlabs.execution.catalog import catalog
from nachtlabs.execution.stages import execute
from nachtlabs.factory_models import (
    Evidence,
    ExecutorJob,
    FactoryControl,
    ProjectPolicy,
    Run,
    RunApproval,
    WorkRequest,
)
from nachtlabs.models import AgentConfiguration, HoldoutContent, ModelProfile, Project, User, now
from nachtlabs.security import decrypt, encrypt
from nachtlabs.workflows.engine import delivery_gate, enforce_approval
from nachtlabs.workflows.policy import fingerprint
from nachtlabs.workflows.state import current_snapshot, event

stop = threading.Event()


def agent(db: Session, identifier: str | None, org_id: UUID) -> dict[str, Any]:
    value = db.get(AgentConfiguration, UUID(identifier)) if identifier else None
    require(
        value is not None and value.active and value.org_id == org_id,
        409,
        "agent_required",
        "Active agent configuration required",
    )
    assert value is not None
    profile = db.get(ModelProfile, value.model_profile_id)
    require(
        profile is not None and profile.active and profile.org_id == value.org_id,
        409,
        "model_required",
        "Active model profile required",
    )
    assert profile is not None
    return {
        "id": str(value.id),
        "provider": value.provider,
        "executable": value.executable,
        "version": value.version,
        "expected_version": value.expected_version,
        "profile_version": profile.version,
        "model": profile.model,
        "role": profile.role,
    }


def context_for(
    db: Session, job: ExecutorJob, run: Run, configuration: dict[str, Any]
) -> dict[str, Any]:
    project = db.get(Project, run.project_id)
    policy = db.get(ProjectPolicy, run.project_id)
    require(
        project is not None
        and not project.archived
        and policy is not None
        and policy.version == run.snapshot["policy_version"],
        409,
        "stale_project",
        "Project or policy changed",
    )
    assert project is not None and policy is not None
    require(
        job.spec_hash == fingerprint(job.specification)
        and job.specification["policy"] == run.snapshot["policy"]
        and job.specification["candidate"] == run.candidate
        and job.specification["base_commit"] == run.base_commit
        and job.specification["plan_digest"] == run.plan_digest,
        409,
        "job_changed",
        "Execution specification is stale",
    )
    control = db.get(FactoryControl, project.org_id)
    require(
        not run.cancel_requested and not (control and control.emergency_stop),
        409,
        "cancelled",
        "Execution stopped",
    )
    work = db.get(WorkRequest, run.request_id)
    assert work is not None
    agentless = run.kind == "regression" or work.metadata_json.get("dry_run") is True
    implementation = (
        {} if agentless else agent(db, run.snapshot["implementation_agent_id"], project.org_id)
    )
    verifier = {} if agentless else agent(db, run.snapshot["verifier_agent_id"], project.org_id)
    require(
        agentless
        or (implementation["role"] == "implementation" and verifier["role"] == "verifier"),
        409,
        "agent_role",
        "Agent profile roles must match their stages",
    )
    versions = {
        "implementation": implementation,
        "verifier": verifier,
        "catalog": fingerprint(configuration),
    }
    if job.stage != "discovery":
        enforce_approval(db, run)
        approval = db.scalar(
            select(RunApproval)
            .where(
                RunApproval.run_id == run.id,
                RunApproval.digest == run.plan_digest,
                RunApproval.decision == "approve",
            )
            .order_by(RunApproval.created_at.desc())
            .limit(1)
        )
        require(
            approval is not None, 409, "approval_missing", "Approved plan is no longer recorded"
        )
        assert approval is not None
        user = db.get(User, approval.user_id)
        require(
            user is not None and user.active and user.role in {"owner", "admin", "operator"},
            409,
            "approval_identity",
            "Approval identity is no longer authorized",
        )
        assert user is not None
        current_snapshot(db, Principal(user.org_id, str(user.id), user=user), run)
        require(
            versions == run.snapshot["agent_versions"],
            409,
            "agent_changed",
            "Agent or model changed since planning",
        )
    if job.stage == "delivery":
        delivery_gate(db, run)
    evidence = [
        {
            "name": "protected" if e.protected else e.name,
            "kind": "protected" if e.protected else e.kind,
            "status": e.status,
            "candidate": e.candidate,
        }
        for e in db.scalars(
            select(Evidence).where(Evidence.run_id == run.id, Evidence.candidate == run.candidate)
        )
    ]
    holdouts: dict[str, dict[str, Any]] = {}
    if job.stage == "validation":
        for identifier in run.snapshot["holdout_ids"]:
            value = db.get(HoldoutContent, UUID(identifier))
            require(
                value is not None,
                409,
                "holdout_missing",
                "Protected validation content unavailable",
            )
            assert value is not None
            holdouts[identifier] = decrypt(value.ciphertext, "holdout:" + identifier)
    return {
        "project_id": str(run.project_id),
        "request": {
            "title": work.title,
            "description": work.description,
            "criteria": {str(i + 1): v for i, v in enumerate(work.criteria)},
        },
        "plan": run.plan,
        "mission": run.snapshot["mission"],
        "journeys": run.snapshot["journeys"],
        "holdouts": holdouts,
        "implementation": implementation,
        "verifier": verifier,
        "agent_versions": versions,
        "require_distinct_models": run.snapshot["require_distinct_models"],
        "evidence": evidence,
        "base_candidate": run.snapshot.get("discovery", {}).get("base_candidate"),
        "org_id": str(work.org_id),
    }


def tick() -> None:
    configuration = catalog()
    with session() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(9182710)"))
        active = db.scalar(select(ExecutorJob).where(ExecutorJob.state.in_(["claimed", "running"])))
        if active:
            # A running job without a live lease can never be renewed; recover it rather than block forever.
            if active.lease_until is None or active.lease_until < now():
                sandbox.recover()
                active.state = "uncertain"
                active.finished_at = now()
                db.commit()
            return
        job = db.scalar(
            select(ExecutorJob)
            .where(ExecutorJob.state == "pending")
            .order_by(ExecutorJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return
        run = db.scalar(select(Run).where(Run.id == job.run_id).with_for_update())
        require(run is not None, 409, "run_missing", "Executor job has no run")
        assert run is not None
        try:
            require(
                run.state == "executor_wait" and job.attempt == run.attempt,
                409,
                "job_stale",
                "Run no longer awaits this job",
            )
            context = context_for(db, job, run, configuration)
        except DomainError as exc:
            job.state = "failed"
            job.result = encrypt({"error_code": exc.code}, f"executor:{job.id}")
            job.finished_at = now()
            db.commit()
            return
        lease = uuid4()
        job.state, job.lease_id, job.lease_until = "running", lease, now() + timedelta(seconds=60)
        identifier, specification = job.id, job.specification
        event(db, run, "executor.started", {"job_id": str(job.id), "stage": job.stage})
        db.commit()
    last_check = 0.0
    execution_deadline = time.monotonic() + specification["policy"]["timeout_seconds"]

    def cancelled() -> bool:
        nonlocal last_check
        if stop.is_set() or time.monotonic() >= execution_deadline:
            return True
        if time.monotonic() - last_check < 2:
            return False
        last_check = time.monotonic()
        with session() as db:
            job = db.scalar(
                select(ExecutorJob).where(ExecutorJob.id == identifier).with_for_update()
            )
            assert job is not None
            if job.lease_id != lease or job.state != "running":
                return True
            run = db.get(Run, job.run_id)
            control = db.get(FactoryControl, UUID(context["org_id"]))
            job.lease_until = now() + timedelta(seconds=60)
            assert run is not None
            policy = db.get(ProjectPolicy, run.project_id)
            project = db.get(Project, run.project_id)
            result = (
                run.cancel_requested
                or bool(control and control.emergency_stop)
                or policy is None
                or policy.version != run.snapshot["policy_version"]
                or project is None
                or project.archived
            )
            db.commit()
            return result

    try:
        result = execute(specification, context, configuration, cancelled)
        require(not cancelled(), 409, "cancelled", "Run stopped before result publication")
        state = "succeeded"
    except DomainError as exc:
        uncertain = False
        if specification["stage"] == "delivery":
            journal = (
                sandbox.ROOT
                / "delivery"
                / (specification["run_id"] + "-" + str(specification["attempt"]) + ".json")
            )
            try:
                uncertain = journal.exists() and json.loads(journal.read_text()).get("state") in {
                    "push_intent",
                    "pr_intent",
                    "complete",
                }
            except Exception:
                uncertain = True
        result, state = (
            {
                "error_code": "execution_timeout"
                if time.monotonic() >= execution_deadline
                else exc.code
            },
            "uncertain" if uncertain else "failed",
        )
    except Exception:
        result, state = {"error_code": "execution_internal"}, "uncertain"
    with session() as db:
        job = db.scalar(select(ExecutorJob).where(ExecutorJob.id == identifier).with_for_update())
        if job is not None and job.lease_id == lease and job.state == "running":
            job.state, job.finished_at = state, now()
            job.result = encrypt(result, f"executor:{identifier}")
            db.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    sandbox.ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    import fcntl

    lock = (sandbox.ROOT / "broker.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sandbox.recover()
    maintenance_at = 0.0
    while not stop.is_set():
        try:
            tick()
            if time.monotonic() - maintenance_at > 3600:
                from nachtlabs.execution.retention import retention_tick

                retention_tick()
                maintenance_at = time.monotonic()
        except Exception as exc:
            logging.error(
                json.dumps({"event": "executor.blocked", "error_type": type(exc).__name__})
            )
        stop.wait(5)


if __name__ == "__main__":
    main()
