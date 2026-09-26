from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from nachtlabs.access import project_access
from nachtlabs.audit import record
from nachtlabs.errors import require
from nachtlabs.integrations.agents import capabilities
from nachtlabs.models import (
    AgentConfiguration,
    IntegrationConnection,
    ModelProfile,
    ProjectIntegration,
)
from sqlalchemy import select

from nachtlabs_api.dependencies import DB, Actor, context, recent
from nachtlabs_api.integration_routes import connection_for, current_probe
from nachtlabs_api.integration_schemas import (
    AgentInput,
    AgentOutput,
    BindingInput,
    BindingOutput,
    ProfileInput,
    ProfileOutput,
)

router = APIRouter(tags=["Agents and models"])


def profile_for(db: DB, actor: Actor, identifier: UUID) -> ModelProfile:
    value = db.get(ModelProfile, identifier)
    require(
        value is not None and value.org_id == actor.org_id,
        404,
        "not_found",
        "Model profile not found",
    )
    assert value is not None
    return value


def profile_view(value: ModelProfile) -> dict[str, Any]:
    return {
        "id": value.id,
        "name": value.name,
        "connection_id": value.connection_id,
        "model": value.model,
        "temperature": value.temperature,
        "role": value.role,
        "active": value.active,
        "version": value.version,
        "concurrency_limit": 1,
        "execution_available": None,
    }


def agent_view(value: AgentConfiguration) -> dict[str, Any]:
    return {
        "id": value.id,
        "name": value.name,
        "provider": value.provider,
        "executable": value.executable,
        "expected_agent_version": value.expected_version,
        "model_profile_id": value.model_profile_id,
        "timeout_seconds": value.timeout_seconds,
        "active": value.active,
        "version": value.version,
        "capabilities": capabilities(value.provider),
        "tested_version": None,
        "execution_available": None,
    }


@router.get("/model-profiles", response_model=list[ProfileOutput])
def profiles(actor: Actor, db: DB) -> list[dict[str, Any]]:
    actor.human_admin()
    return [
        profile_view(p)
        for p in db.scalars(
            select(ModelProfile)
            .where(ModelProfile.org_id == actor.org_id)
            .order_by(ModelProfile.name)
        )
    ]


def save_profile(
    body: ProfileInput, request: Request, actor: Actor, db: DB, identifier: UUID | None = None
) -> dict[str, Any]:
    actor.human_admin()
    recent(actor)
    connection = connection_for(db, actor, body.connection_id, True)
    require(
        connection.provider == "ollama" and connection.active,
        422,
        "invalid_connection",
        "Select an active Ollama connection",
    )
    value = (
        db.scalar(
            select(ModelProfile)
            .where(ModelProfile.id == identifier, ModelProfile.org_id == actor.org_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if identifier
        else None
    )
    if identifier:
        require(value is not None, 404, "not_found", "Model profile not found")
    require(
        (value.version if value else 0) == body.expected_version,
        409,
        "stale_version",
        "Profile changed; refresh first",
    )
    if value is None:
        value = ModelProfile(org_id=actor.org_id)
        db.add(value)
    else:
        value.version += 1
    for key, item in body.model_dump(exclude={"expected_version"}).items():
        setattr(value, key, item)
    db.flush()
    record(
        db,
        context(request),
        "model_profile.saved",
        str(value.id),
        actor=actor.actor,
        org_id=actor.org_id,
        details={"version": value.version},
    )
    return profile_view(value)


@router.post("/model-profiles", status_code=201, response_model=ProfileOutput)
def create_profile(body: ProfileInput, request: Request, actor: Actor, db: DB) -> dict[str, Any]:
    return save_profile(body, request, actor, db)


@router.put("/model-profiles/{identifier}", response_model=ProfileOutput)
def update_profile(
    identifier: UUID, body: ProfileInput, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    return save_profile(body, request, actor, db, identifier)


@router.get("/agents", response_model=list[AgentOutput])
def agents(actor: Actor, db: DB) -> list[dict[str, Any]]:
    actor.human_admin()
    return [
        agent_view(a)
        for a in db.scalars(
            select(AgentConfiguration)
            .where(AgentConfiguration.org_id == actor.org_id)
            .order_by(AgentConfiguration.name)
        )
    ]


def save_agent(
    body: AgentInput, request: Request, actor: Actor, db: DB, identifier: UUID | None = None
) -> dict[str, Any]:
    actor.human_admin()
    recent(actor)
    profile = profile_for(db, actor, body.model_profile_id)
    require(profile.active, 422, "inactive_profile", "Select an active model profile")
    value = (
        db.scalar(
            select(AgentConfiguration)
            .where(AgentConfiguration.id == identifier, AgentConfiguration.org_id == actor.org_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if identifier
        else None
    )
    if identifier:
        require(value is not None, 404, "not_found", "Agent configuration not found")
    require(
        (value.version if value else 0) == body.expected_version,
        409,
        "stale_version",
        "Agent configuration changed; refresh first",
    )
    if value is None:
        value = AgentConfiguration(org_id=actor.org_id)
        db.add(value)
    else:
        value.version += 1
    for key, item in body.model_dump(
        exclude={"expected_version", "expected_agent_version"}
    ).items():
        setattr(value, key, item)
    value.expected_version = body.expected_agent_version
    db.flush()
    record(
        db,
        context(request),
        "agent_configuration.saved",
        str(value.id),
        actor=actor.actor,
        org_id=actor.org_id,
        details={"version": value.version, "provider": value.provider},
    )
    return agent_view(value)


@router.post("/agents", status_code=201, response_model=AgentOutput)
def create_agent(body: AgentInput, request: Request, actor: Actor, db: DB) -> dict[str, Any]:
    return save_agent(body, request, actor, db)


@router.put("/agents/{identifier}", response_model=AgentOutput)
def update_agent(
    identifier: UUID, body: AgentInput, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    return save_agent(body, request, actor, db, identifier)


def binding_view(value: ProjectIntegration) -> dict[str, Any]:
    return {
        key: getattr(value, key)
        for key in (
            "project_id",
            "connection_id",
            "repository_id",
            "full_name",
            "default_branch",
            "probe_id",
            "implementation_agent_id",
            "verifier_agent_id",
            "require_distinct_models",
            "version",
        )
    }


@router.get("/projects/{project_id}/integration", response_model=BindingOutput | None)
def project_binding(project_id: UUID, actor: Actor, db: DB) -> dict[str, Any] | None:
    actor.human_admin()
    project_access(db, actor, project_id)
    value = db.get(ProjectIntegration, project_id)
    return binding_view(value) if value else None


@router.put("/projects/{project_id}/integration", response_model=BindingOutput)
def bind_project(
    project_id: UUID, body: BindingInput, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    actor.human_admin()
    recent(actor)
    project = project_access(db, actor, project_id, lock=True)
    require(
        not project.archived,
        409,
        "project_archived",
        "Restore this project before changing its integration",
    )
    # Lock the connection to serialize against credential/destination changes.
    connection = connection_for(db, actor, body.connection_id, True)
    require(
        connection.active and connection.provider in {"github", "gitea"},
        422,
        "invalid_connection",
        "Select an active Git connection",
    )
    probe = current_probe(db, connection, body.probe_id)
    repositories = probe.result.get("repositories", [])
    chosen = next((r for r in repositories if r.get("provider_id") == body.repository_id), None)
    require(
        chosen is not None,
        422,
        "repository_not_discovered",
        "Select a repository from this discovery page",
    )
    profiles: list[ModelProfile] = []
    for identifier, role in (
        (body.implementation_agent_id, "implementation"),
        (body.verifier_agent_id, "verifier"),
    ):
        if identifier:
            agent = db.get(AgentConfiguration, identifier)
            require(
                agent is not None and agent.org_id == actor.org_id and agent.active,
                422,
                "invalid_agent",
                "Select active agents from this organization",
            )
            assert agent is not None
            profile = profile_for(db, actor, agent.model_profile_id)
            endpoint = db.get(IntegrationConnection, profile.connection_id)
            require(
                profile.active
                and profile.role == role
                and endpoint is not None
                and endpoint.active,
                422,
                "invalid_routing",
                "Use an active model profile with the matching implementation/verifier role",
            )
            profiles.append(profile)
    if body.require_distinct_models and len(profiles) == 2:
        require(
            profiles[0].model != profiles[1].model,
            422,
            "model_independence",
            "Choose different model identifiers for implementation and verification",
        )
    value = db.scalar(
        select(ProjectIntegration)
        .where(ProjectIntegration.project_id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    require(
        (value.version if value else 0) == body.expected_version,
        409,
        "stale_version",
        "Project integration changed; refresh first",
    )
    if value is None:
        value = ProjectIntegration(project_id=project_id)
        db.add(value)
    else:
        value.version += 1
    for key, item in body.model_dump(exclude={"expected_version"}).items():
        setattr(value, key, item)
    assert chosen is not None
    value.full_name, value.default_branch = chosen["full_name"], chosen["default_branch"]
    db.flush()
    record(
        db,
        context(request),
        "project.integration.saved",
        str(project_id),
        actor=actor.actor,
        org_id=actor.org_id,
        project_id=project_id,
        details={"version": value.version, "connection_id": str(connection.id)},
    )
    return binding_view(value)
