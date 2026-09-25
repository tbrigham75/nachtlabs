"""Durable workflow, executor, evidence and monitoring persistence."""
from datetime import datetime
from typing import Any
from uuid import UUID
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from nachtlabs.models import Base, Record, now


class ProjectPolicy(Base):
    __tablename__ = "project_policies"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class WorkflowDefinition(Record, Base):
    __tablename__ = "workflow_definitions"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("org_id", "name", "version"),)


class WorkRequest(Record, Base):
    __tablename__ = "work_requests"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    actor: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(20), default="web")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    criteria: Mapped[list[str]] = mapped_column(JSONB)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    target_ref: Mapped[str] = mapped_column(String(256))
    workflow_id: Mapped[UUID | None] = mapped_column(ForeignKey("workflow_definitions.id"))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="submitted")
    __table_args__ = (UniqueConstraint("project_id", "actor", "idempotency_key"),)


class Run(Record, Base):
    __tablename__ = "runs"
    request_id: Mapped[UUID] = mapped_column(ForeignKey("work_requests.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="implementation")
    state: Mapped[str] = mapped_column(String(40), default="queued")
    stage: Mapped[str] = mapped_column(String(40), default="planning")
    version: Mapped[int] = mapped_column(Integer, default=1)
    event_seq: Mapped[int] = mapped_column(Integer, default=0)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    plan_digest: Mapped[str | None] = mapped_column(String(64))
    base_commit: Mapped[str | None] = mapped_column(String(64))
    candidate: Mapped[str | None] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    delivery: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class RunEvent(Record, Base):
    __tablename__ = "run_events"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20), default="info")
    stage: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)


class RunApproval(Record, Base):
    __tablename__ = "run_approvals"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    digest: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(30))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Evidence(Record, Base):
    __tablename__ = "run_evidence"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    candidate: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    protected: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(80))


class ExecutorJob(Record, Base):
    __tablename__ = "executor_jobs"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    attempt: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(30), default="pending")
    specification: Mapped[dict[str, Any]] = mapped_column(JSONB)
    spec_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[str | None] = mapped_column(Text)
    lease_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unit_name: Mapped[str | None] = mapped_column(String(100))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("run_id", "stage", "attempt"),
                      Index("one_active_factory_execution", text("(1)"), unique=True,
                            postgresql_where=text("state IN ('claimed','running')")),
                      )


class WebhookBinding(Record, Base):
    __tablename__ = "webhook_bindings"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), unique=True)
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("integration_connections.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    actors: Mapped[list[str]] = mapped_column(JSONB, default=list)
    labels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    commands: Mapped[list[str]] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)


class WebhookReceipt(Record, Base):
    __tablename__ = "webhook_receipts"
    binding_id: Mapped[UUID] = mapped_column(ForeignKey("webhook_bindings.id"), index=True)
    delivery_key: Mapped[str] = mapped_column(String(64), unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30))
    request_id: Mapped[UUID | None] = mapped_column(ForeignKey("work_requests.id"))


class FactoryControl(Base):
    __tablename__ = "factory_controls"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Incident(Record, Base):
    __tablename__ = "incidents"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    status: Mapped[str] = mapped_column(String(20), default="open")
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    assigned_to: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, default=list)
    __table_args__ = (UniqueConstraint("org_id", "fingerprint"),)


class IncidentEvent(Record, Base):
    __tablename__ = "incident_events"
    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id"), index=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text)


class Recommendation(Record, Base):
    __tablename__ = "recommendations"
    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="new")
    proposal: Mapped[dict[str, Any]] = mapped_column(JSONB)
    proposal_hash: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_version: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Notification(Record, Base):
    __tablename__ = "notifications"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("user_id", "incident_id"),)


class SavedSearch(Record, Base):
    __tablename__ = "saved_searches"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    log_days: Mapped[int] = mapped_column(Integer, default=30)
    artifact_days: Mapped[int] = mapped_column(Integer, default=90)
    version: Mapped[int] = mapped_column(Integer, default=1)

class OperationalEvent(Record, Base):
    __tablename__ = "operational_events"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(160), unique=True)
    service: Mapped[str] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20), default="info")
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
