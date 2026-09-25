"""Foundation, governance and integrations; factory mappings are registered below."""
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Organization(Record, Base):
    __tablename__ = "organizations"
    # v1 has exactly one installation organization; later migrations can relax this.
    singleton: Mapped[int] = mapped_column(Integer, default=1, unique=True)
    name: Mapped[str] = mapped_column(String(120))
    require_admin_mfa: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (CheckConstraint("singleton = 1"),)


class User(Record, Base):
    __tablename__ = "users"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    theme: Mapped[str] = mapped_column(String(30), default="midnight")
    mfa_secret: Mapped[str | None] = mapped_column(Text)
    mfa_pending: Mapped[str | None] = mapped_column(Text)
    mfa_last_step: Mapped[int] = mapped_column(Integer, default=0)
    recovery_hashes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (CheckConstraint("role IN ('owner','admin','operator','contributor','viewer')"),)


class UserSession(Record, Base):
    __tablename__ = "user_sessions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (Index("sessions_expiry", "expires_at"),)


class LoginChallenge(Record, Base):
    __tablename__ = "login_challenges"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdentityToken(Record, Base):
    __tablename__ = "identity_tokens"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    email: Mapped[str] = mapped_column(String(254), index=True)
    purpose: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("purpose IN ('reset','invitation')"),)


class Project(Record, Base):
    __tablename__ = "projects"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Policies cannot enable execution in Checkpoint A.
    plan_approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    delivery_mode: Mapped[str] = mapped_column(String(20), default="pr_only")
    __table_args__ = (
        UniqueConstraint("org_id", "slug"),
        CheckConstraint("plan_approval_required AND delivery_mode = 'pr_only'"),
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)


class GovernanceDocument(Record, Base):
    __tablename__ = "governance_documents"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=0)
    approved_version: Mapped[int | None] = mapped_column(Integer)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        CheckConstraint("kind IN ('mission','journey','holdout')"),
        CheckConstraint("approved_version IS NULL OR (approved_version > 0 AND approved_version <= version)"),
        Index("one_mission_per_project", "project_id", unique=True, postgresql_where=text("kind = 'mission'")),
    )


class GovernanceVersion(Record, Base):
    __tablename__ = "governance_versions"
    document_id: Mapped[UUID] = mapped_column(ForeignKey("governance_documents.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    # Holdouts never enter this JSON column, even encrypted.
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("document_id", "number"), CheckConstraint("number > 0"))


class HoldoutContent(Base):
    __tablename__ = "holdout_contents"
    version_id: Mapped[UUID] = mapped_column(ForeignKey("governance_versions.id"), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)


class GovernanceApproval(Record, Base):
    __tablename__ = "governance_approvals"
    version_id: Mapped[UUID] = mapped_column(ForeignKey("governance_versions.id"), unique=True)
    approver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


class ServiceAccount(Record, Base):
    __tablename__ = "service_accounts"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class APIKey(Record, Base):
    __tablename__ = "api_keys"
    service_account_id: Mapped[UUID] = mapped_column(ForeignKey("service_accounts.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    project_ids: Mapped[list[str]] = mapped_column(JSONB)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_source: Mapped[str | None] = mapped_column(String(64))


class AuditEvent(Record, Base):
    __tablename__ = "audit_events"
    org_id: Mapped[UUID | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(100), index=True)
    target: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(20), default="success")
    request_id: Mapped[str] = mapped_column(String(36))
    source: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index("audit_cursor", "created_at", "id"),)


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer)


class MailJob(Record, Base):
    __tablename__ = "mail_jobs"
    payload: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (CheckConstraint("state IN ('pending','sending','sent','failed')"),)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[str] = mapped_column(String(20), default="0.1.0")


class IntegrationConnection(Record, Base):
    __tablename__ = "integration_connections"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(20))
    base_url: Mapped[str] = mapped_column(String(512))
    pinned_addresses: Mapped[list[str]] = mapped_column(JSONB)
    allow_private: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_http: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=15)
    credential: Mapped[str | None] = mapped_column(Text)
    credential_version: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (CheckConstraint("provider IN ('github','gitea','ollama')"),
                      CheckConstraint("timeout_seconds BETWEEN 1 AND 30"),)


class IntegrationProbe(Record, Base):
    __tablename__ = "integration_probes"
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("integration_connections.id"), index=True)
    connection_version: Mapped[int] = mapped_column(Integer)
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    page: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    lease_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        CheckConstraint("state IN ('pending','running','succeeded','failed','stale')"),
        CheckConstraint("page BETWEEN 1 AND 100"),
        Index("one_active_probe", "connection_id", unique=True,
              postgresql_where=text("state IN ('pending','running')")),
    )


class ModelProfile(Record, Base):
    __tablename__ = "model_profiles"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("integration_connections.id"))
    name: Mapped[str] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(256))
    temperature: Mapped[float] = mapped_column(default=0.2)
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (CheckConstraint("role IN ('implementation','verifier','planning')"),
                      CheckConstraint("temperature BETWEEN 0 AND 2"),)


class AgentConfiguration(Record, Base):
    __tablename__ = "agent_configurations"
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(20))
    executable: Mapped[str] = mapped_column(String(512))
    expected_version: Mapped[str] = mapped_column(String(80))
    model_profile_id: Mapped[UUID] = mapped_column(ForeignKey("model_profiles.id"))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (CheckConstraint("provider IN ('hermes','opencode')"),
                      CheckConstraint("timeout_seconds BETWEEN 10 AND 3600"),)


class ProjectIntegration(Base):
    __tablename__ = "project_integrations"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("integration_connections.id"))
    repository_id: Mapped[str] = mapped_column(String(256))
    full_name: Mapped[str] = mapped_column(String(256))
    default_branch: Mapped[str] = mapped_column(String(256))
    probe_id: Mapped[UUID] = mapped_column(ForeignKey("integration_probes.id"))
    implementation_agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_configurations.id"))
    verifier_agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_configurations.id"))
    require_distinct_models: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

# Register modular factory mappings for migration metadata.
from nachtlabs import factory_models as factory_models  # noqa: E402,F401
