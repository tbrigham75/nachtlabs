from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID

from nachtlabs.integrations.contracts import ProviderError
from nachtlabs.integrations.transport import Endpoint
from pydantic import BaseModel, Field, SecretStr, model_validator

from nachtlabs_api.schemas import Input

Provider = Literal["github", "gitea", "ollama"]


class ConnectionInput(Input):
    name: str = Field(min_length=1, max_length=120)
    provider: Provider
    base_url: str = Field(max_length=512)
    pinned_addresses: list[str] = Field(min_length=1, max_length=1)
    allow_private: bool = False
    allow_http: bool = False
    timeout_seconds: int = Field(default=15, ge=1, le=30)
    active: bool = True
    expected_version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def endpoint(self) -> "ConnectionInput":
        self.base_url = self.base_url.rstrip("/")
        try:
            Endpoint(
                self.base_url,
                tuple(self.pinned_addresses),
                self.allow_private,
                self.allow_http,
                self.timeout_seconds,
            ).validate()
        except ProviderError:
            raise ValueError("Provide an approved origin and a permitted pinned IP") from None
        if self.provider == "github" and self.base_url != "https://api.github.com":
            raise ValueError(
                "Initial GitHub adapter supports api.github.com; use Gitea for self-hosted Git"
            )
        return self


class CredentialInput(Input):
    token: SecretStr | None = Field(default=None, max_length=8192)
    webhook_secret: SecretStr | None = Field(default=None, max_length=512)
    expected_version: int = Field(ge=1)


class VersionInput(Input):
    expected_version: int = Field(ge=1)


class ProbeInput(VersionInput):
    page: int = Field(default=1, ge=1, le=100)


class ProfileInput(Input):
    name: str = Field(min_length=1, max_length=120)
    connection_id: UUID
    model: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_./:@+-]*$")
    role: Literal["implementation", "verifier", "planning"]
    temperature: float = Field(default=0.2, ge=0, le=2, allow_inf_nan=False)
    active: bool = True
    expected_version: int = Field(default=0, ge=0)


class AgentInput(Input):
    name: str = Field(min_length=1, max_length=120)
    provider: Literal["hermes", "opencode"]
    executable: str = Field(min_length=1, max_length=512, pattern=r"^/[A-Za-z0-9_./-]+$")
    expected_agent_version: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._+-]+$")
    model_profile_id: UUID
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    active: bool = True
    expected_version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def executable_path(self) -> "AgentInput":
        if ".." in PurePosixPath(self.executable).parts:
            raise ValueError("Executable must be an absolute Linux path without parent traversal")
        return self


class BindingInput(Input):
    connection_id: UUID
    probe_id: UUID
    repository_id: str = Field(min_length=1, max_length=256)
    implementation_agent_id: UUID | None = None
    verifier_agent_id: UUID | None = None
    require_distinct_models: bool = True
    expected_version: int = Field(default=0, ge=0)


class ConnectionOutput(BaseModel):
    id: UUID
    name: str
    provider: Provider
    base_url: str
    pinned_addresses: list[str]
    allow_private: bool
    allow_http: bool
    timeout_seconds: int
    active: bool
    version: int
    credential_present: bool
    credential_version: int
    network_allowed: bool
    latest_probe: dict[str, Any] | None
    compatibility: str = "unverified"
    execution_available: bool | None = False


class ProbeOutput(BaseModel):
    id: UUID
    connection_id: UUID
    connection_version: int
    page: int
    state: str
    created_at: datetime
    finished_at: datetime | None
    error_code: str | None
    duration_ms: int | None
    result: dict[str, Any]


class ProfileOutput(BaseModel):
    id: UUID
    name: str
    connection_id: UUID
    model: str
    temperature: float
    role: Literal["implementation", "verifier", "planning"]
    active: bool
    version: int
    concurrency_limit: int
    execution_available: bool | None


class AgentOutput(BaseModel):
    id: UUID
    name: str
    provider: Literal["hermes", "opencode"]
    executable: str
    expected_agent_version: str
    model_profile_id: UUID
    timeout_seconds: int
    active: bool
    version: int
    capabilities: dict[str, Any]
    tested_version: str | None
    execution_available: bool | None


class BindingOutput(BaseModel):
    project_id: UUID
    connection_id: UUID
    repository_id: str
    full_name: str
    default_branch: str
    probe_id: UUID
    implementation_agent_id: UUID | None
    verifier_agent_id: UUID | None
    require_distinct_models: bool
    version: int
