import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def safe_ref(value: str) -> str:
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,199}", value) or ".." in value
            or "//" in value or value.endswith(("/", ".", ".lock"))):
        raise ValueError("Invalid branch/ref")
    return value


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or value in {".", "./"} or path.is_absolute() or ".." in path.parts or "\\" in value or any(ord(c) < 32 for c in value):
        raise ValueError("Use a repository-relative path without parent traversal")
    return value


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectExecutionPolicy(Strict):
    repository_key: str = Field(default="", pattern=r"^[A-Za-z0-9_-]{0,80}$")
    planning_profile_id: UUID | None = None
    implementation_agent_id: UUID | None = None
    verifier_agent_id: UUID | None = None
    validation_commands: list[str] = Field(default_factory=list, max_length=30)
    journey_commands: dict[str, str] = Field(default_factory=dict)
    allowed_paths: list[str] = Field(default_factory=lambda: ["docs/"], min_length=1, max_length=50)
    include_holdouts: bool = False
    allow_verifier_warning_exception: bool = False
    max_repairs: int = Field(default=1, ge=0, le=2)
    max_verifier_reworks: int = Field(default=1, ge=0, le=2)
    timeout_seconds: int = Field(default=600, ge=30, le=3600)
    max_output_bytes: int = Field(default=1048576, ge=4096, le=2097152)
    max_workspace_bytes: int = Field(default=104857600, ge=1048576, le=1073741824)
    max_changed_files: int = Field(default=20, ge=1, le=100)
    require_plan_approval: Literal[True] = True
    delivery_mode: Literal["pr_only"] = "pr_only"
    schedules_enabled: Literal[False] = False
    regression_enabled: bool = False

    @model_validator(mode="after")
    def paths(self) -> "ProjectExecutionPolicy":
        for value in self.allowed_paths:
            safe_relative(value)
        for command in [*self.validation_commands, *self.journey_commands.values()]:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", command):
                raise ValueError("Commands reference an administrator-owned execution catalog")
        return self


class WorkInput(Strict):
    project_id: UUID
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=12000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=30)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    target_ref: str = "main"
    links: list[str] = Field(default_factory=list, max_length=20)
    labels: list[str] = Field(default_factory=list, max_length=20)
    workflow_id: UUID | None = None
    target_date: str | None = None
    dry_run: bool = False

    @model_validator(mode="after")
    def bounded(self) -> "WorkInput":
        safe_ref(self.target_ref)
        if any(not c.strip() or len(c) > 2000 for c in self.acceptance_criteria):
            raise ValueError("Supply bounded nonempty acceptance criteria")
        if any(not v.startswith("https://") or len(v) > 2000 for v in self.links):
            raise ValueError("Links must be HTTPS references; they are not fetched automatically")
        if any(len(v) > 80 for v in self.labels):
            raise ValueError("Labels are limited to 80 characters")
        return self


class Plan(Strict):
    summary: str = Field(min_length=1, max_length=4000)
    steps: list[str] = Field(min_length=1, max_length=30)
    affected_files: list[str] = Field(min_length=1, max_length=100)
    risks: list[str] = Field(default_factory=list, max_length=30)
    dependencies: list[str] = Field(default_factory=list, max_length=30)
    test_strategy: list[str] = Field(min_length=1, max_length=30)
    criteria_mapping: dict[str, list[str]]
    mission_alignment: Literal["aligned", "partially_aligned", "unclear", "out_of_scope", "conflicts"]
    mission_reason: str = Field(min_length=1, max_length=4000)
    journey_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def bounded(self) -> "Plan":
        for value in self.affected_files:
            safe_relative(value)
        if any(len(v) > 2000 for v in [*self.steps, *self.risks, *self.dependencies, *self.test_strategy]):
            raise ValueError("Plan entries exceed limits")
        return self


class VerifierFinding(Strict):
    verdict: Literal["pass", "pass_with_warnings", "needs_rework", "failed", "human_review_required"]
    summary: str = Field(min_length=1, max_length=4000)
    criteria: dict[str, bool]
    concerns: list[str] = Field(default_factory=list, max_length=30)
    confidence: float = Field(ge=0, le=1)
    candidate: str = Field(pattern=r"^[a-f0-9]{40,64}$")
