import base64
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from nachtlabs.audit import record
from nachtlabs.errors import require
from nachtlabs.models import AuditEvent, ProjectMember, WorkerHeartbeat, now
from sqlalchemy import func, literal, select, text, tuple_
from sqlalchemy.exc import SQLAlchemyError

from nachtlabs_api.dependencies import DB, Actor, context

router = APIRouter(tags=["Health and audit"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "alive", "version": "0.1.0"}


@router.get("/health/ready")
def ready(db: DB, response: Response) -> dict[str, str]:
    try:
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        require(revision == "0003", 503, "schema_mismatch", "Database schema requires migration")
        db.execute(select(WorkerHeartbeat.name).limit(1))
    except SQLAlchemyError:
        db.rollback()
        response.status_code = 503
        return {"status": "unavailable"}
    return {"status": "ready", "schema": "0003"}


@router.get("/overview")
def overview(actor: Actor, db: DB) -> dict[str, Any]:
    actor.scope("projects:read")
    heartbeat = db.scalar(select(func.max(WorkerHeartbeat.seen_at)))
    return {
        "worker": "online"
        if heartbeat and heartbeat > now() - timedelta(seconds=120)
        else "unavailable",
        "worker_last_seen": heartbeat,
        "checkpoint": "M10-source",
        "execution_enabled": None,
        "message": "Execution requires an independently qualified Linux executor. The API does not infer qualification from configuration.",
    }


def audit_query(actor: Actor) -> Any:
    actor.scope("audit:read")
    query = select(AuditEvent).where(AuditEvent.org_id == actor.org_id)
    if actor.key:
        query = query.where(AuditEvent.project_id.in_([UUID(p) for p in actor.key.project_ids]))
    elif not actor.admin:
        assert actor.user is not None
        query = query.where(
            AuditEvent.project_id.in_(
                select(ProjectMember.project_id).where(ProjectMember.user_id == actor.user.id)
            )
        )
    return query


def event_view(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "created_at": event.created_at.isoformat(),
        "actor": event.actor_id,
        "action": event.action,
        "target": event.target,
        "outcome": event.outcome,
        "project_id": str(event.project_id) if event.project_id else None,
        "request_id": event.request_id,
        "source": event.source,
        "details": event.details,
    }


@router.get("/audit-log")
def audit_log(
    actor: Actor,
    db: DB,
    action: str = "",
    project_id: UUID | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    query = audit_query(actor)
    if action:
        query = query.where(AuditEvent.action == action[:100])
    if project_id:
        query = query.where(AuditEvent.project_id == project_id)
    if cursor:
        try:
            timestamp, identifier = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
            stamp = datetime.fromisoformat(timestamp)
            require(stamp.tzinfo is not None, 422, "invalid_cursor", "Invalid cursor")
            query = query.where(
                tuple_(AuditEvent.created_at, AuditEvent.id)
                < tuple_(literal(stamp), literal(UUID(identifier)))
            )
        except (ValueError, UnicodeError):
            require(False, 422, "invalid_cursor", "Invalid cursor")
    rows = list(
        db.scalars(
            query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit + 1)
        )
    )
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = base64.urlsafe_b64encode(
            f"{last.created_at.isoformat()}|{last.id}".encode()
        ).decode()
    return {"items": [event_view(e) for e in rows[:limit]], "next_cursor": next_cursor}


@router.get("/audit-log/export")
def export(request: Request, actor: Actor, db: DB) -> Response:
    rows = list(
        db.scalars(
            audit_query(actor)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(1001)
        )
    )
    require(
        len(rows) <= 1000,
        409,
        "export_limit",
        "Use the paginated API for exports exceeding 1,000 records",
    )
    record(
        db,
        context(request),
        "audit.exported",
        "audit",
        actor=actor.actor,
        org_id=actor.org_id,
        details={"count": len(rows)},
    )
    return Response(
        json.dumps([event_view(e) for e in rows]),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="nachtlabs-audit.json"'},
    )
