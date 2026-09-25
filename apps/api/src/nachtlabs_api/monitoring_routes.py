from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import func, or_, select

from nachtlabs.access import project_access
from nachtlabs.audit import record
from nachtlabs.errors import require
from nachtlabs.factory_models import Incident, IncidentEvent, Notification, ProjectPolicy, Recommendation, RetentionPolicy, Run, RunEvent, SavedSearch
from nachtlabs.models import Project, ProjectMember, User, now
from nachtlabs.workflows.policy import ProjectExecutionPolicy, Strict, fingerprint
from nachtlabs_api.dependencies import Actor, DB, context, recent

router = APIRouter(tags=["monitoring"])


def projects(db: DB, actor: Actor):
    actor.scope("runs:read")
    query = select(Project.id).where(Project.org_id == actor.org_id)
    if actor.key:
        query = query.where(Project.id.in_([UUID(v) for v in actor.key.project_ids]))
    elif not actor.admin:
        query = query.join(ProjectMember).where(ProjectMember.user_id == actor.user.id)
    return query


def incident_view(value: Incident) -> dict[str, Any]:
    return {"id": str(value.id), "project_id": str(value.project_id) if value.project_id else None,
            "category": value.category, "severity": value.severity, "status": value.status,
            "occurrences": value.occurrences, "last_seen": value.last_seen, "version": value.version,
            "assigned_to": str(value.assigned_to) if value.assigned_to else None,
            "snoozed_until": value.snoozed_until, "evidence_refs": value.evidence_refs}


def incident_access(db: DB, actor: Actor, identifier: UUID, lock: bool = False) -> Incident:
    actor.scope("runs:read")
    query = select(Incident).where(Incident.id == identifier, Incident.org_id == actor.org_id)
    value = db.scalar(query.with_for_update() if lock else query)
    require(value is not None, 404, "not_found", "Incident not found")
    if value.project_id:
        project_access(db, actor, value.project_id)
    else:
        actor.human_admin()
    return value


class IncidentAction(Strict):
    version: int
    action: Literal["acknowledge", "resolve", "reopen", "assign", "snooze", "note"]
    note: str = Field(min_length=3, max_length=2000)
    assigned_to: UUID | None = None
    snooze_hours: int = Field(default=1, ge=1, le=168)


class RecommendationAction(Strict):
    version: int
    digest: str
    action: Literal["approve", "reject", "apply", "rollback"]
    reason: str = Field(min_length=3, max_length=2000)


class SearchInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    project_id: UUID | None = None
    severity: Literal["info", "warning", "error"] | None = None
    stage: str = Field(default="", max_length=40)
    shared: bool = False


class RetentionInput(Strict):
    version: int
    log_days: int = Field(ge=7, le=365)
    artifact_days: int = Field(ge=30, le=3650)


@router.get("/monitoring")
def dashboard(db: DB, actor: Actor):
    rows = db.execute(select(Run.state, func.count()).where(Run.project_id.in_(projects(db, actor))).group_by(Run.state)).all()
    failures = list(db.scalars(select(Incident).where(Incident.project_id.in_(projects(db, actor)), Incident.status != "resolved").order_by(Incident.last_seen.desc()).limit(20)))
    return {"states": dict(rows), "incidents": [incident_view(v) for v in failures],
            "schedules_enabled": False, "metrics_source": "durable_run_states", "token_cost": None}


@router.get("/logs")
def logs(db: DB, actor: Actor, project_id: UUID | None = None, severity: str | None = None,
         stage: str | None = None, before: datetime | None = None):
    retention = db.get(RetentionPolicy, actor.org_id)
    cutoff = now() - timedelta(days=retention.log_days if retention else 30)
    query = select(RunEvent).join(Run).where(Run.project_id.in_(projects(db, actor)), RunEvent.created_at >= cutoff)
    if project_id:
        project_access(db, actor, project_id)
        query = query.where(Run.project_id == project_id)
    if severity:
        query = query.where(RunEvent.severity == severity)
    if stage:
        query = query.where(RunEvent.stage == stage)
    if before:
        query = query.where(RunEvent.created_at < before)
    rows = db.scalars(query.order_by(RunEvent.created_at.desc(), RunEvent.id.desc()).limit(100))
    return [{"id": str(v.id), "run_id": str(v.run_id), "time": v.created_at, "category": v.category,
             "stage": v.stage, "severity": v.severity, "details": v.details} for v in rows]


@router.get("/incidents")
def incidents(db: DB, actor: Actor):
    query = select(Incident).where(Incident.org_id == actor.org_id)
    if not actor.admin:
        query = query.where(Incident.project_id.in_(projects(db, actor)))
    return [incident_view(v) for v in db.scalars(query.order_by(Incident.last_seen.desc()).limit(100))]


@router.get("/incidents/{identifier}")
def incident(identifier: UUID, db: DB, actor: Actor):
    value = incident_access(db, actor, identifier)
    timeline = db.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == value.id).order_by(IncidentEvent.created_at).limit(200))
    return {**incident_view(value), "timeline": [{"actor": v.actor, "action": v.action, "note": v.note, "time": v.created_at} for v in timeline]}


@router.post("/incidents/{identifier}/actions")
def incident_action(identifier: UUID, body: IncidentAction, request: Request, db: DB, actor: Actor):
    actor.human_admin()
    recent(actor)
    value = incident_access(db, actor, identifier, True)
    require(value.version == body.version, 409, "stale_version", "Refresh the incident")
    if body.action in {"acknowledge", "resolve", "reopen"}:
        value.status = {"acknowledge": "acknowledged", "resolve": "resolved", "reopen": "open"}[body.action]
    elif body.action == "assign":
        user = db.get(User, body.assigned_to) if body.assigned_to else None
        require(body.assigned_to is None or (user is not None and user.active and user.org_id == actor.org_id and user.role in {"owner", "admin"}),
                422, "assignee", "Choose an active organization administrator")
        value.assigned_to = body.assigned_to
    elif body.action == "snooze":
        value.snoozed_until = now() + timedelta(hours=body.snooze_hours)
    value.version += 1
    db.add(IncidentEvent(incident_id=value.id, actor=actor.actor, action=body.action, note=body.note))
    record(db, context(request), "incident." + body.action, str(value.id), actor=actor.actor, org_id=actor.org_id)
    return incident_view(value)


@router.get("/recommendations")
def recommendations(db: DB, actor: Actor):
    actor.human_admin()
    rows = db.scalars(select(Recommendation).join(Incident).where(Incident.org_id == actor.org_id).order_by(Recommendation.created_at.desc()).limit(100))
    return [{"id": str(v.id), "incident_id": str(v.incident_id), "status": v.status, "version": v.version,
             "proposal": v.proposal, "digest": v.proposal_hash, "expires_at": v.expires_at} for v in rows]


@router.post("/recommendations/{identifier}/actions")
def recommendation_action(identifier: UUID, body: RecommendationAction, request: Request, db: DB, actor: Actor):
    actor.human_admin()
    recent(actor)
    value = db.scalar(select(Recommendation).where(Recommendation.id == identifier).with_for_update())
    require(value is not None, 404, "not_found", "Recommendation not found")
    incident = incident_access(db, actor, value.incident_id, True)
    require(value.version == body.version and value.proposal_hash == body.digest == fingerprint(value.proposal),
            409, "stale_recommendation", "Review the current recommendation")
    proposal = value.proposal
    require(proposal.get("field") == "timeout_seconds", 409, "recommendation_type", "Unsupported recommendation")
    project_access(db, actor, UUID(proposal["project_id"]), lock=True)
    policy = db.get(ProjectPolicy, UUID(proposal["project_id"]))
    require(policy is not None, 409, "policy_missing", "Project policy unavailable")
    if body.action == "approve":
        require(value.status == "new" and policy.version == proposal["policy_version"], 409, "stale_recommendation", "Proposal no longer matches policy")
        value.status, value.approved_by, value.expires_at = "approved", actor.user.id, now() + timedelta(hours=24)
    elif body.action == "reject":
        require(value.status in {"new", "approved"}, 409, "recommendation_state", "Recommendation cannot be rejected")
        value.status = "rejected"
    else:
        rollback = body.action == "rollback"
        require(value.status == ("applied" if rollback else "approved"), 409, "recommendation_state", "Invalid recommendation transition")
        if not rollback:
            require(value.expires_at is not None and value.expires_at > now(), 409, "approval_expired", "Recommendation approval expired")
        expected = value.applied_version if rollback else proposal["policy_version"]
        require(policy.version == expected and policy.configuration.get("timeout_seconds", 600) == proposal["after" if rollback else "before"],
                409, "policy_changed", "Policy changed after recommendation; automatic overwrite refused")
        updated = {**policy.configuration, "timeout_seconds": proposal["before" if rollback else "after"]}
        policy.configuration = ProjectExecutionPolicy.model_validate(updated).model_dump(mode="json")
        policy.version += 1
        value.applied_version = policy.version
        value.status = "rolled_back" if rollback else "applied"
    value.version += 1
    db.add(IncidentEvent(incident_id=incident.id, actor=actor.actor, action="recommendation." + body.action, note=body.reason))
    record(db, context(request), "recommendation." + body.action, str(value.id), actor=actor.actor, org_id=actor.org_id, project_id=incident.project_id)
    return {"status": value.status, "version": value.version}


@router.get("/notifications")
def notifications(db: DB, actor: Actor):
    require(actor.user is not None, 403, "human_required", "Human account required")
    rows = db.scalars(select(Notification).join(Incident).where(Notification.user_id == actor.user.id,
                      Incident.org_id == actor.org_id).order_by(Notification.created_at.desc()).limit(100))
    result = []
    for value in rows:
        incident = db.get(Incident, value.incident_id)
        # A downgraded administrator loses access to organization notifications.
        if not actor.admin:
            continue
        result.append({"id": str(value.id), "incident_id": str(value.incident_id), "read": value.read_at is not None,
                       "category": incident.category, "created_at": value.created_at})
    return result


@router.post("/notifications/{identifier}/read")
def notification_read(identifier: UUID, db: DB, actor: Actor):
    require(actor.user is not None, 403, "human_required", "Human account required")
    value = db.get(Notification, identifier)
    require(value is not None and value.user_id == actor.user.id, 404, "not_found", "Notification not found")
    value.read_at = now()
    return {"read": True}


@router.get("/saved-searches")
def saved_searches(db: DB, actor: Actor):
    require(actor.user is not None, 403, "human_required", "Human account required")
    return [{"id": str(v.id), "name": v.name, "filters": v.filters, "shared": v.shared} for v in db.scalars(
        select(SavedSearch).where(SavedSearch.org_id == actor.org_id,
        or_(SavedSearch.user_id == actor.user.id, SavedSearch.shared.is_(True))).limit(100))]


@router.post("/saved-searches")
def save_search(body: SearchInput, db: DB, actor: Actor):
    require(actor.user is not None, 403, "human_required", "Human account required")
    if body.shared:
        actor.human_admin()
    if body.project_id:
        project_access(db, actor, body.project_id)
    value = SavedSearch(org_id=actor.org_id, user_id=actor.user.id, name=body.name, shared=body.shared,
                        filters=body.model_dump(mode="json", exclude={"name", "shared"}))
    db.add(value)
    db.flush()
    return {"id": str(value.id)}


@router.get("/retention")
def retention(db: DB, actor: Actor):
    actor.human_admin()
    value = db.get(RetentionPolicy, actor.org_id)
    return {"version": value.version if value else 0, "log_days": value.log_days if value else 30,
            "artifact_days": value.artifact_days if value else 90,
            "protected_history": "Audit, approvals, governance, incident timeline and evidence are never automatically deleted."}


@router.put("/retention")
def update_retention(body: RetentionInput, request: Request, db: DB, actor: Actor):
    actor.human_admin()
    recent(actor)
    from nachtlabs.models import Organization
    db.scalar(select(Organization).where(Organization.id == actor.org_id).with_for_update())
    value = db.get(RetentionPolicy, actor.org_id)
    require(body.version == (value.version if value else 0), 409, "stale_version", "Refresh retention settings")
    if value is None:
        value = RetentionPolicy(org_id=actor.org_id, version=0)
        db.add(value)
    value.log_days, value.artifact_days, value.version = body.log_days, body.artifact_days, body.version + 1
    record(db, context(request), "retention.updated", str(actor.org_id), actor=actor.actor, org_id=actor.org_id)
    return {"version": value.version}

@router.get("/system-logs")
def system_logs(db: DB, actor: Actor, severity: str | None = None, before: datetime | None = None):
    actor.human_admin()
    from nachtlabs.factory_models import OperationalEvent
    query = select(OperationalEvent).where(OperationalEvent.org_id == actor.org_id)
    if severity:
        query = query.where(OperationalEvent.severity == severity)
    if before:
        query = query.where(OperationalEvent.created_at < before)
    return [{"id": str(v.id), "run_id": None, "time": v.created_at, "category": v.category,
             "stage": v.service, "severity": v.severity, "details": v.details} for v in db.scalars(
                 query.order_by(OperationalEvent.created_at.desc()).limit(100))]
