from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from nachtlabs.models import AuditEvent
from nachtlabs.security import redact


@dataclass(frozen=True)
class AuditContext:
    request_id: str
    source: str


def record(
    db: Session,
    context: AuditContext,
    action: str,
    target: str,
    *,
    actor: str = "anonymous",
    org_id: UUID | None = None,
    project_id: UUID | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            org_id=org_id,
            project_id=project_id,
            actor_id=actor,
            action=action,
            target=target,
            outcome=outcome,
            request_id=context.request_id,
            source=context.source[:64],
            details=redact(details or {}),
        )
    )
