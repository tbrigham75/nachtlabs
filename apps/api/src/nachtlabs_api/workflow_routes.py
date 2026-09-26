import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from nachtlabs.access import project_access
from nachtlabs.audit import record
from nachtlabs.database import session
from nachtlabs.errors import DomainError, require
from nachtlabs.factory_models import (
    Evidence,
    FactoryControl,
    ProjectPolicy,
    Run,
    RunEvent,
    WorkflowDefinition,
    WorkRequest,
)
from nachtlabs.workflows.policy import ProjectExecutionPolicy, Strict, WorkInput
from nachtlabs.workflows.state import (
    TERMINAL,
    approve,
    can_operate,
    current_snapshot,
    event,
    evidence_payload,
    locked_run,
    store_evidence,
    submit,
)
from pydantic import Field
from sqlalchemy import func, select

from nachtlabs_api.dependencies import DB, Actor, context, principal, rate_limit, recent

router = APIRouter(tags=["Workflows and runs"])


class PolicyInput(Strict):
    expected_version: int = Field(ge=0)
    configuration: ProjectExecutionPolicy


class DecisionInput(Strict):
    expected_version: int = Field(ge=1)
    digest: str = Field(min_length=64, max_length=64)
    decision: Literal["approve", "reject", "request_changes"]
    reason: str = Field(min_length=1, max_length=2000)


class ActionInput(Strict):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class AttestationInput(Strict):
    expected_version: int = Field(ge=1)
    candidate: str = Field(pattern=r"^[a-f0-9]{40,64}$")
    journey_id: UUID
    outcome: Literal["passed", "failed", "blocked"]
    evidence: str = Field(min_length=10, max_length=8000)


class WorkflowInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=0)
    description: str = Field(min_length=1, max_length=4000)
    max_repairs: int = Field(default=1, ge=0, le=2)


def request_view(value: WorkRequest) -> dict[str, Any]:
    return {
        "id": value.id,
        "project_id": value.project_id,
        "title": value.title,
        "description": value.description,
        "acceptance_criteria": value.criteria,
        "target_ref": value.target_ref,
        "status": value.status,
        "source": value.source,
        "actor": value.actor,
        "created_at": value.created_at,
        "metadata": value.metadata_json,
    }


def run_view(value: Run) -> dict[str, Any]:
    return {
        "id": value.id,
        "request_id": value.request_id,
        "project_id": value.project_id,
        "kind": value.kind,
        "state": value.state,
        "stage": value.stage,
        "version": value.version,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
        "plan": value.plan,
        "plan_digest": value.plan_digest,
        "base_commit": value.base_commit,
        "candidate": value.candidate,
        "attempt": value.attempt,
        "error_code": value.error_code,
        "cancel_requested": value.cancel_requested,
        "delivery": value.delivery,
        "holdout_required": bool(value.snapshot.get("holdout_ids")),
        "policy_version": value.snapshot.get("policy_version"),
    }


def accessible_run(db: DB, actor: Actor, identifier: UUID, lock: bool = False) -> Run:
    actor.scope("runs:read")
    value = locked_run(db, identifier) if lock else db.get(Run, identifier)
    require(value is not None, 404, "not_found", "Run not found")
    assert value is not None
    project_access(db, actor, value.project_id)
    return value


@router.get("/projects/{project_id}/execution-policy")
def get_policy(project_id: UUID, actor: Actor, db: DB) -> dict[str, Any]:
    actor.human_admin()
    project_access(db, actor, project_id)
    value = db.get(ProjectPolicy, project_id)
    return {
        "version": value.version if value else 0,
        "configuration": value.configuration
        if value
        else ProjectExecutionPolicy().model_dump(mode="json"),
    }


@router.put("/projects/{project_id}/execution-policy")
def set_policy(
    project_id: UUID, body: PolicyInput, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    actor.human_admin()
    recent(actor)
    project = project_access(db, actor, project_id, lock=True)
    require(not project.archived, 409, "archived", "Project is archived")
    value = db.get(ProjectPolicy, project_id)
    require(
        (value.version if value else 0) == body.expected_version,
        409,
        "stale_version",
        "Policy changed",
    )
    if value is None:
        value = ProjectPolicy(project_id=project_id, version=1)
        db.add(value)
    else:
        value.version += 1
    value.configuration = body.configuration.model_dump(mode="json")
    record(
        db,
        context(request),
        "project.execution_policy.updated",
        str(project_id),
        actor=actor.actor,
        org_id=actor.org_id,
        project_id=project_id,
        details={"version": value.version},
    )
    return {"version": value.version, "configuration": value.configuration}


@router.post("/work-requests", status_code=201)
def create_work(
    body: WorkInput,
    request: Request,
    actor: Actor,
    db: DB,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict[str, Any]:
    rate_limit(request, "work-intake", 30, actor.actor)
    work, run = submit(
        db, actor, body, idempotency_key, context(request), "api" if actor.key else "web"
    )
    return {"work_request": request_view(work), "run": run_view(run)}


@router.get("/work-requests")
def list_work(
    actor: Actor, db: DB, project_id: UUID, limit: int = Query(50, ge=1, le=100)
) -> list[dict[str, Any]]:
    actor.scope("work_requests:read")
    project_access(db, actor, project_id)
    return [
        request_view(w)
        for w in db.scalars(
            select(WorkRequest)
            .where(WorkRequest.project_id == project_id)
            .order_by(WorkRequest.created_at.desc())
            .limit(limit)
        )
    ]


@router.get("/work-requests/{identifier}")
def work_detail(identifier: UUID, actor: Actor, db: DB) -> dict[str, Any]:
    actor.scope("work_requests:read")
    work = db.get(WorkRequest, identifier)
    require(work is not None, 404, "not_found", "Work request not found")
    assert work is not None
    project_access(db, actor, work.project_id)
    return {
        **request_view(work),
        "runs": [run_view(r) for r in db.scalars(select(Run).where(Run.request_id == identifier))],
    }


@router.get("/runs")
def runs(
    actor: Actor, db: DB, project_id: UUID, limit: int = Query(50, ge=1, le=100)
) -> list[dict[str, Any]]:
    actor.scope("runs:read")
    project_access(db, actor, project_id)
    return [
        run_view(r)
        for r in db.scalars(
            select(Run)
            .where(Run.project_id == project_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
        )
    ]


@router.get("/runs/{identifier}")
def run_detail(identifier: UUID, actor: Actor, db: DB) -> dict[str, Any]:
    value = accessible_run(db, actor, identifier)
    work = db.get(WorkRequest, value.request_id)
    assert work is not None
    evidence = list(
        db.scalars(
            select(Evidence).where(Evidence.run_id == identifier).order_by(Evidence.created_at)
        )
    )
    return {
        **run_view(value),
        "work_request": request_view(work),
        "journeys": [j for j in value.snapshot.get("journeys", [])],
        "evidence": [
            {
                "id": e.id,
                "name": "Protected validation" if e.protected else e.name,
                "kind": "protected" if e.protected else e.kind,
                "status": e.status,
                "candidate": e.candidate,
                "created_at": e.created_at,
                "protected": e.protected,
                "content_hash": None if e.protected else e.content_hash,
            }
            for e in evidence
        ],
    }


@router.post("/runs/{identifier}/approval")
def decide(
    identifier: UUID, body: DecisionInput, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    recent(actor)
    value = accessible_run(db, actor, identifier, True)
    require(value.version == body.expected_version, 409, "stale_version", "Run changed")
    approve(db, actor, value, body.decision, body.digest, body.reason, context(request))
    return run_view(value)


@router.post("/runs/{identifier}/cancel")
def cancel(
    identifier: UUID, body: ActionInput, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    can_operate(actor)
    value = accessible_run(db, actor, identifier, True)
    require(
        value.version == body.expected_version and value.state not in TERMINAL,
        409,
        "stale_version",
        "Run changed or finished",
    )
    value.cancel_requested = True
    if value.state != "executor_wait":
        value.state = "cancelled"
    event(db, value, "cancellation.requested", {"actor": actor.actor})
    record(
        db,
        context(request),
        "run.cancel.requested",
        str(value.id),
        actor=actor.actor,
        org_id=actor.org_id,
        project_id=value.project_id,
    )
    return run_view(value)


@router.post("/runs/{identifier}/replan")
def replan(
    identifier: UUID, body: ActionInput, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    can_operate(actor)
    recent(actor)
    value = accessible_run(db, actor, identifier, True)
    require(
        value.version == body.expected_version and value.state in {"blocked", "human_review"},
        409,
        "stale_version",
        "Run cannot be replanned",
    )
    require(
        value.error_code != "executor_uncertain",
        409,
        "reconcile_first",
        "Reconcile orphan execution locally before retrying",
    )
    maximum = (
        value.snapshot.get("workflow_repair_limit", value.snapshot["policy"]["max_repairs"])
        + value.snapshot["policy"]["max_verifier_reworks"]
    )
    require(
        value.attempt < maximum,
        409,
        "retry_budget",
        "Repair/rework budget exhausted; create a new reviewed request",
    )
    current_snapshot(db, actor, value)
    value.attempt += 1
    value.state, value.stage, value.error_code, value.plan_digest = "queued", "planning", None, None
    event(db, value, "replan.requested", {"actor": actor.actor, "attempt": value.attempt})
    return run_view(value)


@router.post("/runs/{identifier}/attestations")
def attest(
    identifier: UUID, body: AttestationInput, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    can_operate(actor)
    recent(actor)
    value = accessible_run(db, actor, identifier, True)
    require(
        value.version == body.expected_version
        and value.state == "awaiting_manual"
        and body.candidate == value.candidate,
        409,
        "stale_evidence",
        "Attest against the current candidate in the manual review stage",
    )
    journey = next((j for j in value.snapshot["journeys"] if j["id"] == str(body.journey_id)), None)
    require(
        journey is not None and journey["content"]["execution_type"] == "manual",
        422,
        "manual_journey",
        "Choose a required manual Journey",
    )
    rank = {"operator": 1, "admin": 2, "owner": 3}
    assert actor.user is not None and journey is not None
    require(
        rank.get(actor.user.role, 0) >= rank[journey["content"]["approval_role"]],
        403,
        "attestation_role",
        "This Journey requires a more privileged human",
    )
    require(
        db.scalar(
            select(Evidence.id).where(
                Evidence.run_id == value.id,
                Evidence.candidate == value.candidate,
                Evidence.name == str(body.journey_id),
            )
        )
        is None,
        409,
        "already_attested",
        "This candidate already has an attestation for the Journey",
    )
    store_evidence(
        db,
        value,
        str(body.journey_id),
        "human_attestation",
        body.outcome,
        {"observation": body.evidence, "journey_version": journey["version_id"]},
        actor.actor,
    )
    if body.outcome != "passed":
        value.state, value.error_code = "human_review", "manual_validation_failed"
    else:
        required = {
            j["id"]
            for j in value.snapshot["journeys"]
            if j["content"]["execution_type"] == "manual"
        }
        completed = set(
            db.scalars(
                select(Evidence.name).where(
                    Evidence.run_id == value.id,
                    Evidence.candidate == value.candidate,
                    Evidence.kind == "human_attestation",
                    Evidence.status == "passed",
                )
            )
        )
        if required <= completed:
            from nachtlabs.workflows.engine import delivery_gate

            delivery_gate(db, value, require_verifier=False)
            value.state, value.stage = (
                ("completed", "complete")
                if value.kind == "regression"
                else ("queued", "verification")
            )
    event(db, value, "manual_review.result", {"actor": actor.actor, "outcome": body.outcome})
    record(
        db,
        context(request),
        "run.manual_attestation",
        str(value.id),
        actor=actor.actor,
        org_id=actor.org_id,
        project_id=value.project_id,
        details={"outcome": body.outcome},
    )
    return run_view(value)


@router.get("/runs/{identifier}/evidence/{evidence_id}")
def evidence_detail(
    identifier: UUID, evidence_id: UUID, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    accessible_run(db, actor, identifier)
    value = db.get(Evidence, evidence_id)
    require(
        value is not None and value.run_id == identifier, 404, "not_found", "Evidence not found"
    )
    assert value is not None
    if value.protected:
        actor.human_admin()
        record(
            db,
            context(request),
            "protected_evidence.read",
            str(evidence_id),
            actor=actor.actor,
            org_id=actor.org_id,
        )
    return {
        "id": value.id,
        "candidate": value.candidate,
        "payload": evidence_payload(value),
        "content_hash": value.content_hash,
    }


@router.get("/runs/{identifier}/events")
def events(identifier: UUID, actor: Actor, db: DB, after: int = Query(0, ge=0)) -> dict[str, Any]:
    value = accessible_run(db, actor, identifier)
    rows = list(
        db.scalars(
            select(RunEvent)
            .where(RunEvent.run_id == identifier, RunEvent.sequence > after)
            .order_by(RunEvent.sequence)
            .limit(100)
        )
    )
    return {
        "items": [
            {
                "id": e.sequence,
                "category": e.category,
                "stage": e.stage,
                "severity": e.severity,
                "details": e.details,
                "created_at": e.created_at,
            }
            for e in rows
        ],
        "latest": value.event_seq,
    }


@router.get("/runs/{identifier}/stream")
def stream(
    identifier: UUID,
    request: Request,
    actor: Actor,
    db: DB,
    last_event_id: str = Header(default="0"),
) -> StreamingResponse:
    value = accessible_run(db, actor, identifier)
    rate_limit(request, "run-stream", 60, actor.actor)
    require(actor.user is not None, 403, "human_required", "Browser session required for streaming")
    try:
        cursor = max(0, int(last_event_id))
    except ValueError:
        require(False, 422, "invalid_cursor", "Invalid Last-Event-ID")
        cursor = 0
    require(
        cursor <= value.event_seq, 422, "invalid_cursor", "Cursor exceeds recorded event history"
    )

    def batch(after: int) -> list[dict[str, Any]]:
        with session() as stream_db:
            fresh = principal(request, stream_db)
            value = accessible_run(stream_db, fresh, identifier)
            rows = list(
                stream_db.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == value.id, RunEvent.sequence > after)
                    .order_by(RunEvent.sequence)
                    .limit(100)
                )
            )
            stream_db.commit()
            return [
                {
                    "id": e.sequence,
                    "category": e.category,
                    "stage": e.stage,
                    "severity": e.severity,
                    "details": e.details,
                }
                for e in rows
            ]

    async def generate() -> AsyncIterator[str]:
        position, deadline = cursor, time.monotonic() + 300
        while time.monotonic() < deadline and not await request.is_disconnected():
            try:
                rows = await asyncio.to_thread(batch, position)
            except DomainError:
                yield "event: revoked\ndata: {}\n\n"
                return
            for row in rows:
                position = row["id"]
                yield f"id: {position}\nevent: run\ndata: {json.dumps(row)}\n\n"
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/workflows")
def workflows(actor: Actor, db: DB) -> list[dict[str, Any]]:
    actor.human_admin()
    return [
        {"id": w.id, "name": w.name, "version": w.version, "configuration": w.configuration}
        for w in db.scalars(
            select(WorkflowDefinition)
            .where(WorkflowDefinition.org_id == actor.org_id)
            .order_by(WorkflowDefinition.name, WorkflowDefinition.version.desc())
        )
    ]


@router.post("/workflows", status_code=201)
def save_workflow(body: WorkflowInput, request: Request, actor: Actor, db: DB) -> dict[str, Any]:
    actor.human_admin()
    recent(actor)
    latest = (
        db.scalar(
            select(func.max(WorkflowDefinition.version)).where(
                WorkflowDefinition.org_id == actor.org_id, WorkflowDefinition.name == body.name
            )
        )
        or 0
    )
    require(latest == body.expected_version, 409, "stale_version", "Workflow changed")
    value = WorkflowDefinition(
        org_id=actor.org_id,
        name=body.name,
        version=latest + 1,
        configuration={
            "description": body.description,
            "max_repairs": body.max_repairs,
            "stages": [
                "planning",
                "approval",
                "implementation",
                "validation",
                "verification",
                "delivery",
            ],
            "approval_required": True,
            "delivery_mode": "pr_only",
        },
    )
    db.add(value)
    db.flush()
    record(
        db,
        context(request),
        "workflow.version_created",
        str(value.id),
        actor=actor.actor,
        org_id=actor.org_id,
    )
    return {"id": value.id, "version": value.version}


@router.get("/factory-control")
def factory_control(actor: Actor, db: DB) -> dict[str, Any]:
    actor.human_admin()
    value = db.get(FactoryControl, actor.org_id)
    return {
        "emergency_stop": bool(value and value.emergency_stop),
        "version": value.version if value else 0,
    }


class StopInput(Strict):
    expected_version: int = Field(ge=0)
    emergency_stop: bool


@router.put("/factory-control")
def stop_factory(body: StopInput, request: Request, actor: Actor, db: DB) -> dict[str, Any]:
    actor.human_admin()
    recent(actor)
    value = db.scalar(
        select(FactoryControl).where(FactoryControl.org_id == actor.org_id).with_for_update()
    )
    require(
        (value.version if value else 0) == body.expected_version,
        409,
        "stale_version",
        "Factory control changed",
    )
    if value is None:
        value = FactoryControl(org_id=actor.org_id, version=1)
        db.add(value)
    else:
        value.version += 1
    value.emergency_stop = body.emergency_stop
    record(
        db,
        context(request),
        "factory.emergency_stop",
        str(actor.org_id),
        actor=actor.actor,
        org_id=actor.org_id,
        details={"enabled": body.emergency_stop},
    )
    return {"version": value.version, "emergency_stop": value.emergency_stop}


@router.post("/regressions", status_code=201)
def regression(
    body: WorkInput,
    request: Request,
    actor: Actor,
    db: DB,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict[str, Any]:
    can_operate(actor)
    work, run = submit(
        db, actor, body, idempotency_key, context(request), "manual_regression", "regression"
    )
    return {"work_request": request_view(work), "run": run_view(run)}


@router.post("/runs/{identifier}/accept-verifier-warnings")
def accept_verifier_warnings(
    identifier: UUID, body: ActionInput, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    recent(actor)
    value = accessible_run(db, actor, identifier, True)
    require(value.version == body.expected_version, 409, "stale_version", "Review the current run")
    from nachtlabs.workflows.exceptions import accept_warning

    accept_warning(db, actor, value, body.reason)
    return run_view(value)
