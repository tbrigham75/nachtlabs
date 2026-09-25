from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from nachtlabs.access import Principal, project_access
from nachtlabs.audit import AuditContext, record
from nachtlabs.errors import require
from nachtlabs.factory_models import Evidence, FactoryControl, ProjectPolicy, Run, RunApproval, RunEvent, WorkRequest, WorkflowDefinition
from nachtlabs.models import GovernanceDocument, GovernanceVersion, ProjectIntegration, now
from nachtlabs.security import encrypt, decrypt
from nachtlabs.workflows.policy import ProjectExecutionPolicy, WorkInput, fingerprint

TERMINAL = {"completed", "cancelled", "rejected", "dry_run_complete"}
WAITING = {"awaiting_approval", "awaiting_manual", "blocked", "human_review", "delivery_uncertain"}


def event(db: Session, run: Run, category: str, details: dict[str, Any] | None = None, severity: str = "info") -> None:
    run.event_seq += 1
    run.version += 1
    run.updated_at = now()
    db.add(RunEvent(run_id=run.id, sequence=run.event_seq, category=category, stage=run.stage, severity=severity, details=details or {}))
    work = db.get(WorkRequest, run.request_id)
    if work is not None:
        work.status = run.state
        record(db, AuditContext(str(uuid4()), "workflow"), category, str(run.id), actor=(details or {}).get("actor", "workflow"),
               org_id=work.org_id, project_id=run.project_id, details={"stage": run.stage, "state": run.state, "sequence": run.event_seq})


def locked_run(db: Session, run_id: UUID) -> Run:
    value = db.scalar(select(Run).where(Run.id == run_id).with_for_update().execution_options(populate_existing=True))
    require(value is not None, 404, "not_found", "Run not found")
    assert value is not None
    return value


def can_operate(actor: Principal) -> None:
    require(actor.user is not None and actor.user.role in {"owner", "admin", "operator"}, 403, "operator_required", "A human Operator, Admin or Owner is required")


def capture_snapshot(db: Session, actor: Principal, project_id: UUID) -> dict[str, Any]:
    project = project_access(db, actor, project_id, lock=True)
    require(not project.archived, 409, "project_archived", "Restore this project before submitting work")
    policy = db.get(ProjectPolicy, project_id)
    configuration = ProjectExecutionPolicy.model_validate(policy.configuration if policy else {}).model_dump(mode="json")
    mission = db.scalar(select(GovernanceDocument).where(GovernanceDocument.project_id == project_id, GovernanceDocument.kind == "mission"))
    require(mission is not None and not mission.archived and mission.approved_version is not None, 409, "mission_required", "Approve a Mission first")
    assert mission is not None
    version = db.scalar(select(GovernanceVersion).where(GovernanceVersion.document_id == mission.id, GovernanceVersion.number == mission.approved_version))
    assert version is not None
    baseline = version.content.get("required_journey_ids", [])
    require(bool(baseline), 409, "baseline_required", "An approved validation baseline is required")
    journeys = []
    for identifier in baseline:
        document = db.get(GovernanceDocument, UUID(identifier))
        require(document is not None and document.project_id == project_id and document.approved_version is not None and not document.archived, 409, "baseline_required", "The baseline must remain approved and active")
        assert document is not None
        item = db.scalar(select(GovernanceVersion).where(GovernanceVersion.document_id == document.id, GovernanceVersion.number == document.approved_version))
        assert item is not None
        require(item.content.get("enabled") is True, 409, "baseline_disabled", "Required Journey is disabled")
        journeys.append({"id": str(document.id), "version_id": str(item.id), "content": item.content})
    holdouts = []
    if configuration["include_holdouts"]:
        for doc in db.scalars(select(GovernanceDocument).where(GovernanceDocument.project_id == project_id, GovernanceDocument.kind == "holdout", GovernanceDocument.archived.is_(False))):
            require(doc.approved_version is not None, 409, "holdout_unapproved", "Approve configured holdouts before execution")
            item = db.scalar(select(GovernanceVersion).where(GovernanceVersion.document_id == doc.id, GovernanceVersion.number == doc.approved_version))
            assert item is not None
            holdouts.append(str(item.id))
    require(not configuration["include_holdouts"] or bool(holdouts), 409, "holdout_required", "Configure at least one approved holdout")
    binding = db.get(ProjectIntegration, project_id)
    return {"policy": configuration, "policy_version": policy.version if policy else 0,
            "mission_id": str(version.id), "mission": version.content, "journeys": journeys,
            "holdout_ids": holdouts, "binding_version": binding.version if binding else 0,
            "implementation_agent_id": configuration["implementation_agent_id"] or (str(binding.implementation_agent_id) if binding and binding.implementation_agent_id else None),
            "verifier_agent_id": configuration["verifier_agent_id"] or (str(binding.verifier_agent_id) if binding and binding.verifier_agent_id else None),
            "require_distinct_models": binding.require_distinct_models if binding else True}


def submit(db: Session, actor: Principal, body: WorkInput, key: str, context: AuditContext, source: str = "web", kind: str = "implementation") -> tuple[WorkRequest, Run]:
    actor.scope("work_requests:create")
    project_access(db, actor, body.project_id, lock=True)
    require(actor.key is not None or (actor.user is not None and actor.user.role != "viewer"), 403, "forbidden", "Viewer cannot submit work")
    require(8 <= len(key) <= 200, 422, "idempotency_required", "Supply an Idempotency-Key of 8–200 characters")
    key_hash, content_hash = fingerprint(key), fingerprint({"body": body.model_dump(mode="json"), "kind": kind})
    old = db.scalar(select(WorkRequest).where(WorkRequest.project_id == body.project_id, WorkRequest.actor == actor.actor, WorkRequest.idempotency_key == key_hash))
    if old:
        require(old.request_hash == content_hash, 409, "idempotency_conflict", "This idempotency key has a different request body")
        run = db.scalar(select(Run).where(Run.request_id == old.id))
        assert run is not None
        return old, run
    control = db.get(FactoryControl, actor.org_id)
    require(not control or not control.emergency_stop, 409, "emergency_stop", "Factory emergency stop is active")
    snapshot = capture_snapshot(db, actor, body.project_id)
    if body.workflow_id:
        workflow = db.get(WorkflowDefinition, body.workflow_id)
        require(workflow is not None and workflow.org_id == actor.org_id, 404, "not_found", "Workflow not found")
        assert workflow is not None
        snapshot["workflow"] = workflow.configuration
        snapshot["workflow_version"] = workflow.version
        snapshot["workflow_repair_limit"] = min(snapshot["policy"]["max_repairs"], workflow.configuration["max_repairs"])
    if kind == "regression":
        require(snapshot["policy"]["regression_enabled"], 409, "regression_disabled", "Enable manual regression in project policy")
    request = WorkRequest(org_id=actor.org_id, project_id=body.project_id, actor=actor.actor, source=source,
                          title=body.title, description=body.description, criteria=body.acceptance_criteria,
                          target_ref=body.target_ref, workflow_id=body.workflow_id, request_hash=content_hash, idempotency_key=key_hash,
                          metadata_json=body.model_dump(mode="json", exclude={"title","description","acceptance_criteria"}))
    db.add(request)
    db.flush()
    run = Run(request_id=request.id, project_id=body.project_id, kind=kind, snapshot=snapshot)
    db.add(run)
    db.flush()
    event(db, run, "request.accepted", {"source": source, "kind": kind})
    record(db, context, "work_request.created", str(request.id), actor=actor.actor, org_id=actor.org_id, project_id=body.project_id)
    return request, run


def current_snapshot(db: Session, actor: Principal, run: Run) -> None:
    current = capture_snapshot(db, actor, run.project_id)
    require(fingerprint(current) == fingerprint({k: v for k, v in run.snapshot.items() if k not in {"workflow", "workflow_version", "agent_versions", "discovery", "workflow_repair_limit"}}),
            409, "stale_governance", "Governance or execution policy changed; create a fresh run")


def approval_digest(run: Run) -> str:
    return fingerprint({"plan": run.plan, "snapshot": run.snapshot, "base_commit": run.base_commit, "attempt": run.attempt})


def approve(db: Session, actor: Principal, run: Run, decision: str, digest: str, reason: str, context: AuditContext) -> None:
    can_operate(actor)
    require(run.state == "awaiting_approval" and digest == run.plan_digest == approval_digest(run), 409, "stale_approval", "Review the current plan before deciding")
    current_snapshot(db, actor, run)
    require(decision in {"approve", "reject", "request_changes"}, 422, "decision", "Invalid decision")
    assert actor.user is not None
    db.add(RunApproval(run_id=run.id, digest=digest, decision=decision, user_id=actor.user.id, reason=reason, expires_at=now() + timedelta(hours=24)))
    run.state = {"approve":"queued", "reject":"rejected", "request_changes":"human_review"}[decision]
    run.stage = "implementation" if decision == "approve" and run.kind != "regression" else "validation" if decision == "approve" else "planning"
    event(db, run, "plan." + decision, {"actor": actor.actor})
    record(db, context, "run.approval", str(run.id), actor=actor.actor, org_id=actor.org_id, project_id=run.project_id, details={"decision":decision,"digest":digest})


def store_evidence(db: Session, run: Run, name: str, kind: str, status: str, payload: dict[str, Any], actor: str, protected: bool = False) -> Evidence:
    require(run.candidate is not None, 409, "candidate_required", "No immutable candidate exists")
    identifier = uuid4()
    value = Evidence(id=identifier, run_id=run.id, candidate=run.candidate, name=name, kind=kind, status=status,
                     protected=protected, payload=encrypt(payload, f"evidence:{identifier}"), content_hash=fingerprint(payload), actor=actor)
    db.add(value)
    db.flush()
    event(db, run, "evidence.recorded", {"id":str(value.id), "kind":"protected" if protected else kind, "status":status})
    return value


def evidence_payload(value: Evidence) -> dict[str, Any]:
    return decrypt(value.payload, f"evidence:{value.id}")
