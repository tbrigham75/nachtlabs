from datetime import timedelta
from ipaddress import ip_address
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from nachtlabs.access import project_access
from nachtlabs.audit import record
from nachtlabs.errors import require
from nachtlabs.integrations.agents import capabilities
from nachtlabs.integrations.service import network_allowed
from nachtlabs.models import (
    AgentConfiguration,
    IntegrationConnection,
    IntegrationProbe,
    ModelProfile,
    ProjectIntegration,
    now,
)
from sqlalchemy import select

from nachtlabs_api.dependencies import DB, Actor, context, recent
from nachtlabs_api.integration_routes import connection_for, current_probe
from nachtlabs_api.integration_schemas import (
    AgentInput,
    AgentOutput,
    BindingInput,
    BindingOutput,
    LlmReadinessOutput,
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


@router.get("/llm-readiness", response_model=LlmReadinessOutput)
def llm_readiness(actor: Actor, db: DB) -> dict[str, Any]:
    """Report how far the model/agent chain is configured, for the setup wizard.

    Everything here is read from the tables the operator already writes; nothing
    is inferred or assumed. The four states the architecture keeps separate stay
    separate here: a saved connection is not a working one, a successful
    discovery is not a compatibility proof, and neither is execution, which
    always reports unavailable because it depends on a root-owned qualification
    the API cannot see.
    """
    actor.human_admin()
    connections = list(
        db.scalars(
            select(IntegrationConnection)
            .where(
                IntegrationConnection.org_id == actor.org_id,
                IntegrationConnection.provider == "ollama",
            )
            .order_by(IntegrationConnection.created_at)
        )
    )
    profiles = list(
        db.scalars(
            select(ModelProfile)
            .where(ModelProfile.org_id == actor.org_id)
            .order_by(ModelProfile.created_at)
        )
    )
    agents = list(
        db.scalars(
            select(AgentConfiguration)
            .where(AgentConfiguration.org_id == actor.org_id)
            .order_by(AgentConfiguration.created_at)
        )
    )

    def freshest(value: IntegrationConnection) -> IntegrationProbe | None:
        return db.scalar(
            select(IntegrationProbe)
            .where(IntegrationProbe.connection_id == value.id)
            .order_by(IntegrationProbe.created_at.desc())
            .limit(1)
        )

    def discovery_state(value: IntegrationConnection) -> str:
        # Mirrors current_probe exactly, so the wizard and project binding can
        # never disagree about whether a discovery still counts.
        job = freshest(value)
        if job is None:
            return "not_run"
        if job.connection_version != value.version:
            return "stale"
        if job.state != "succeeded":
            return job.state
        if job.finished_at is None or job.finished_at <= now() - timedelta(hours=24):
            return "expired"
        return "succeeded"

    active = [c for c in connections if c.active]
    # Prefer a connection that already has a current discovery, so an operator
    # with several is not pushed back to the start.
    chosen = next(
        (c for c in active if discovery_state(c) == "succeeded"),
        active[0] if active else (connections[0] if connections else None),
    )
    state = discovery_state(chosen) if chosen is not None else "not_run"
    models: list[dict[str, Any]] = []
    checked_at: str | None = None
    if chosen is not None:
        job = freshest(chosen)
        if job is not None:
            checked_at = job.created_at.isoformat()
        if state == "succeeded" and job is not None:
            rows = (job.result or {}).get("models") or []
            models = [
                {"name": str(row["name"]), "digest": row.get("digest")}
                for row in rows
                if isinstance(row, dict) and isinstance(row.get("name"), str)
            ]

    def by_role(role: str) -> dict[str, Any] | None:
        found = next(
            (
                p
                for p in profiles
                if p.role == role and p.active and (chosen is None or p.connection_id == chosen.id)
            ),
            None,
        )
        return None if found is None else {"id": str(found.id), "model": found.model}

    implementation = by_role("implementation")
    verifier = by_role("verifier")
    planning = by_role("planning")
    # The binding rule compares the two profiles actually selected, so readiness
    # asks whether such a pair exists rather than comparing one arbitrary pick.
    # An operator may legitimately hold several profiles per role.
    role_models = {
        role: [
            p.model
            for p in profiles
            if p.role == role and p.active and (chosen is None or p.connection_id == chosen.id)
        ]
        for role in ("implementation", "verifier")
    }
    distinct = any(i != v for i in role_models["implementation"] for v in role_models["verifier"])
    bound = {p["id"] for p in (implementation, verifier) if p is not None}
    agent = next(
        (a for a in agents if a.active and str(a.model_profile_id) in bound),
        None,
    )

    # Agent egress is refused for loopback by the root execution catalog, so a
    # loopback pin configures discovery and planning but can never run an agent.
    loopback = False
    # A cleartext endpoint to anything other than loopback: permitted only when
    # the operator enabled it, and worth saying so wherever the endpoint is listed
    # rather than only at the moment it was created.
    cleartext = False
    if chosen is not None:
        for address in chosen.pinned_addresses:
            try:
                value = ip_address(str(address))
            except ValueError:
                loopback = False
                continue
            if value.is_loopback:
                loopback = True
            if chosen.base_url.startswith("http://") and not value.is_loopback:
                cleartext = True

    return {
        "provider_network_enabled": network_allowed("ollama"),
        "connection": None
        if chosen is None
        else {
            "id": str(chosen.id),
            "name": chosen.name,
            "active": chosen.active,
            "version": chosen.version,
            "loopback_pinned": loopback,
            "cleartext_endpoint": cleartext,
        },
        "connection_count": len(connections),
        "discovery": {"state": state, "models": models, "checked_at": checked_at},
        "implementation_profile": implementation,
        "verifier_profile": verifier,
        "planning_profile": planning,
        "agent": None
        if agent is None
        else {
            "id": str(agent.id),
            "name": agent.name,
            "provider": agent.provider,
            "executable": agent.executable,
        },
        "distinct_models": distinct,
        # The API never infers executor qualification from configuration.
        "execution_available": False,
        "complete": bool(
            chosen is not None
            and chosen.active
            and state == "succeeded"
            and implementation is not None
            and verifier is not None
            and distinct
            and agent is not None
        ),
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
