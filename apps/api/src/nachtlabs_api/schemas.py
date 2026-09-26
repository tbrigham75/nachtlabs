from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, model_validator

Role = Literal["owner", "admin", "operator", "contributor", "viewer"]
Theme = Literal["midnight", "graphite", "canvas", "forest", "nordic", "solarized", "system"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)


class Setup(Login):
    password: SecretStr = Field(min_length=12, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    organization: str = Field(min_length=1, max_length=120)
    # Only consulted when NACHTLABS_SETUP_TOKEN_REQUIRED is enabled.
    bootstrap_token: SecretStr | None = None


class EmailInput(Input):
    email: EmailStr


class Invite(EmailInput):
    role: Literal["admin", "operator", "contributor", "viewer"] = "viewer"


class PasswordToken(Input):
    token: SecretStr
    password: SecretStr = Field(min_length=12, max_length=128)
    name: str = Field(default="", max_length=120)


class MFAChallenge(Input):
    challenge: SecretStr
    code: SecretStr = Field(min_length=6, max_length=64)


class MFACode(Input):
    code: SecretStr = Field(min_length=6, max_length=64)


class Preference(Input):
    theme: Theme


class Reauthenticate(Input):
    password: SecretStr
    code: SecretStr | None = None


class UserChange(Input):
    role: Role
    active: bool
    version: int = Field(ge=1)


class OrganizationChange(Input):
    name: str = Field(min_length=1, max_length=120)
    require_admin_mfa: bool
    version: int = Field(ge=1)


class ProjectInput(Input):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    description: str = Field(default="", max_length=4000)


class ProjectChange(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    archived: bool = False
    version: int = Field(ge=1)


class MemberInput(Input):
    user_id: UUID


class MissionContent(Input):
    purpose: str = Field(min_length=1, max_length=4000)
    intended_users: str = Field(min_length=1, max_length=2000)
    outcomes: str = Field(min_length=1, max_length=4000)
    scope: str = Field(min_length=1, max_length=4000)
    non_goals: str = Field(min_length=1, max_length=4000)
    technical_constraints: str = Field(min_length=1, max_length=4000)
    security_constraints: str = Field(min_length=1, max_length=4000)
    reliability_requirements: str = Field(default="", max_length=4000)
    escalation: str = Field(min_length=1, max_length=1000)
    unacceptable_changes: str = Field(min_length=1, max_length=4000)
    risk_tolerance: Literal["low", "moderate", "high"] = "low"
    required_journey_ids: list[UUID] = Field(default_factory=list, max_length=100)


class JourneyContent(Input):
    description: str = Field(min_length=1, max_length=4000)
    category: Literal[
        "critical_path", "regression", "security", "usability", "api", "integration"
    ] = "critical_path"
    preconditions: str = Field(default="", max_length=4000)
    test_data: str = Field(default="", max_length=4000)
    steps: str = Field(min_length=1, max_length=8000)
    expected_outcomes: str = Field(min_length=1, max_length=4000)
    evidence_requirements: str = Field(min_length=1, max_length=4000)
    execution_type: Literal["manual", "script", "api", "browser", "integration", "external"] = (
        "manual"
    )
    command_reference: str | None = Field(default=None, max_length=200)
    approval_role: Literal["owner", "admin", "operator"] = "operator"
    required_on: list[str] = Field(default_factory=lambda: ["standard"], max_length=20)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    enabled: bool = True
    owner: str = Field(min_length=1, max_length=120)
    source_reference: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def needs_command(self) -> "JourneyContent":
        if self.execution_type != "manual" and not self.command_reference:
            raise ValueError("Automated journeys need an approved command/adapter reference")
        return self


class DocumentInput(Input):
    name: str = Field(min_length=1, max_length=120)
    content: MissionContent | JourneyContent
    expected_version: int = Field(default=0, ge=0)


class ApprovalInput(Input):
    expected_version: int = Field(ge=1)


class ServiceAccountInput(Input):
    name: str = Field(min_length=1, max_length=120)


class KeyInput(Input):
    service_account_id: UUID
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=10)
    project_ids: list[UUID] = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None
