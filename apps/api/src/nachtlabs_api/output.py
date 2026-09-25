"""Explicit public projections; persistence entities never serialize themselves."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from nachtlabs_api.schemas import JourneyContent, MissionContent, Role, Theme


class UserOutput(BaseModel):
    id: UUID
    email: str
    name: str
    role: Role
    active: bool
    theme: Theme
    mfa_enabled: bool
    version: int


class MeOutput(UserOutput):
    organization: str
    mfa_required: bool


class LoginOutput(BaseModel):
    mfa_required: bool
    challenge: str | None = None
    user: UserOutput | None = None


class ProjectOutput(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str
    archived: bool
    version: int
    plan_approval_required: bool = True
    delivery_mode: str
    execution_enabled: bool
    readiness: dict[str, bool] | None = None


class KeyOutput(BaseModel):
    id: UUID
    service_account_id: UUID
    name: str
    prefix: str
    scopes: list[str]
    project_ids: list[UUID]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    last_source: str | None


class IssuedKeyOutput(KeyOutput):
    raw_key: str
    previous_key_expires_at: datetime | None = None


class GovernanceOutput(BaseModel):
    id: UUID
    name: str
    kind: str
    version: int
    latest_version: int
    approved_version: int | None
    content: MissionContent | JourneyContent
    author_id: UUID
    created_at: datetime
    approved_at: datetime | None
    approver_id: UUID | None
    last_run: None = None
    execution_available: bool
