from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from nachtlabs.audit import record
from nachtlabs.errors import require
from nachtlabs.integrations.service import network_allowed
from nachtlabs.models import IntegrationConnection, IntegrationProbe, now
from nachtlabs.security import encrypt
from nachtlabs_api.dependencies import Actor, DB, context, rate_limit, recent
from nachtlabs_api.integration_schemas import ConnectionInput, ConnectionOutput, CredentialInput, ProbeInput, ProbeOutput, VersionInput

router = APIRouter(prefix="/integrations", tags=["Integrations"])


def connection_for(db: DB, actor: Actor, identifier: UUID, lock: bool = False) -> IntegrationConnection:
    actor.human_admin()
    statement = select(IntegrationConnection).where(IntegrationConnection.id == identifier, IntegrationConnection.org_id == actor.org_id)
    value = db.scalar(statement.with_for_update().execution_options(populate_existing=True) if lock else statement)
    require(value is not None, 404, "not_found", "Connection not found")
    assert value is not None
    return value


def probe_view(job: IntegrationProbe, include_results: bool = True) -> dict[str, Any]:
    return {"id": job.id, "connection_id": job.connection_id, "connection_version": job.connection_version,
            "page": job.page, "state": job.state, "created_at": job.created_at, "finished_at": job.finished_at,
            "error_code": job.error_code, "duration_ms": job.duration_ms, "result": job.result if include_results else {}}


def connection_view(db: DB, value: IntegrationConnection) -> dict[str, Any]:
    latest = db.scalar(select(IntegrationProbe).where(IntegrationProbe.connection_id == value.id)
                       .order_by(IntegrationProbe.created_at.desc(), IntegrationProbe.id.desc()).limit(1))
    return {"id": value.id, "name": value.name, "provider": value.provider, "base_url": value.base_url,
            "pinned_addresses": value.pinned_addresses, "allow_private": value.allow_private,
            "allow_http": value.allow_http, "timeout_seconds": value.timeout_seconds, "active": value.active,
            "version": value.version, "credential_present": value.credential is not None,
            "credential_version": value.credential_version, "network_allowed": network_allowed(value.provider),
            "latest_probe": probe_view(latest, False) if latest else None}


@router.get("", response_model=list[ConnectionOutput])
def connections(actor: Actor, db: DB) -> list[dict[str, Any]]:
    actor.human_admin()
    return [connection_view(db, value) for value in db.scalars(select(IntegrationConnection)
            .where(IntegrationConnection.org_id == actor.org_id).order_by(IntegrationConnection.name))]


@router.post("", status_code=201, response_model=ConnectionOutput)
def create_connection(body: ConnectionInput, request: Request, actor: Actor, db: DB) -> dict[str, Any]:
    actor.human_admin()
    recent(actor)
    require(body.expected_version == 0, 409, "stale_version", "New connections start at version zero")
    value = IntegrationConnection(org_id=actor.org_id, **body.model_dump(exclude={"expected_version"}))
    db.add(value)
    db.flush()
    record(db, context(request), "integration.created", str(value.id), actor=actor.actor, org_id=actor.org_id,
           details={"provider": value.provider})
    return connection_view(db, value)


@router.get("/{identifier}", response_model=ConnectionOutput)
def connection_detail(identifier: UUID, actor: Actor, db: DB) -> dict[str, Any]:
    return connection_view(db, connection_for(db, actor, identifier))


@router.put("/{identifier}", response_model=ConnectionOutput)
def update_connection(identifier: UUID, body: ConnectionInput, request: Request, actor: Actor, db: DB) -> dict[str, Any]:
    recent(actor)
    value = connection_for(db, actor, identifier, True)
    require(value.version == body.expected_version, 409, "stale_version", "Connection changed; refresh first")
    require(value.provider == body.provider, 422, "provider_immutable", "Create a separate connection for another provider")
    # Credentials cannot silently follow a new hostname/IP or weakened transport policy.
    changed_destination = any(getattr(value, key) != getattr(body, key) for key in
                              ("base_url", "pinned_addresses", "allow_private", "allow_http"))
    if changed_destination:
        value.credential = None
        value.credential_version += 1
    for key, item in body.model_dump(exclude={"expected_version"}).items():
        setattr(value, key, item)
    value.version += 1
    record(db, context(request), "integration.updated", str(value.id), actor=actor.actor, org_id=actor.org_id,
           details={"version": value.version, "destination_changed": changed_destination})
    return connection_view(db, value)


@router.put("/{identifier}/credential", response_model=ConnectionOutput)
def replace_credential(identifier: UUID, body: CredentialInput, request: Request, actor: Actor, db: DB) -> dict[str, Any]:
    recent(actor)
    value = connection_for(db, actor, identifier, True)
    require(value.version == body.expected_version, 409, "stale_version", "Connection changed; refresh first")
    secret = {key: field.get_secret_value() for key, field in
              (("token", body.token), ("webhook_secret", body.webhook_secret)) if field is not None}
    require(bool(secret) and all(v and "\r" not in v and "\n" not in v for v in secret.values()),
            422, "credential_format", "Enter non-empty credentials without line breaks")
    # Complete replacement; omitted fields are revoked rather than implicitly retained.
    value.credential = encrypt(secret, f"integration:{value.id}")
    value.credential_version += 1
    value.version += 1
    record(db, context(request), "integration.credential.replaced", str(value.id), actor=actor.actor, org_id=actor.org_id,
           details={"version": value.credential_version})
    return connection_view(db, value)


@router.post("/{identifier}/credential/revoke", response_model=ConnectionOutput)
def revoke_credential(identifier: UUID, body: VersionInput, request: Request, actor: Actor, db: DB) -> dict[str, Any]:
    recent(actor)
    value = connection_for(db, actor, identifier, True)
    require(value.version == body.expected_version, 409, "stale_version", "Connection changed; refresh first")
    value.credential = None
    value.version += 1
    value.credential_version += 1
    record(db, context(request), "integration.credential.revoked", str(value.id), actor=actor.actor, org_id=actor.org_id)
    return connection_view(db, value)


@router.post("/{identifier}/probes", status_code=202, response_model=ProbeOutput)
def request_probe(identifier: UUID, body: ProbeInput, request: Request, actor: Actor, db: DB) -> dict[str, Any]:
    user = actor.human_admin()
    recent(actor)
    rate_limit(request, "integration-probe", 20, actor.actor)
    value = connection_for(db, actor, identifier, True)
    require(value.version == body.expected_version, 409, "stale_version", "Connection changed; refresh first")
    require(value.active and network_allowed(value.provider), 409, "network_disabled",
            "Provider checks are disabled by the installation policy")
    require(value.provider != "ollama" or body.page == 1, 422, "page_limit", "Ollama uses one discovery page")
    require(value.provider == "ollama" or value.credential is not None, 409, "credential_required", "Store a provider token first")
    pending = db.scalar(select(IntegrationProbe).where(IntegrationProbe.connection_id == value.id,
                       IntegrationProbe.state.in_(["pending", "running"])))
    require(pending is None, 409, "probe_pending", "A connection check is already queued or running")
    job = IntegrationProbe(connection_id=value.id, connection_version=value.version, requested_by=user.id, page=body.page)
    db.add(job)
    db.flush()
    record(db, context(request), "integration.probe.requested", str(value.id), actor=actor.actor, org_id=actor.org_id)
    return probe_view(job)


@router.get("/{identifier}/probes", response_model=list[ProbeOutput])
def probes(identifier: UUID, actor: Actor, db: DB) -> list[dict[str, Any]]:
    connection_for(db, actor, identifier)
    return [probe_view(job) for job in db.scalars(select(IntegrationProbe).where(IntegrationProbe.connection_id == identifier)
            .order_by(IntegrationProbe.created_at.desc(), IntegrationProbe.id.desc()).limit(20))]


def current_probe(db: DB, connection: IntegrationConnection, identifier: UUID) -> IntegrationProbe:
    job = db.get(IntegrationProbe, identifier)
    require(job is not None and job.connection_id == connection.id and job.connection_version == connection.version
            and job.state == "succeeded" and job.finished_at is not None and job.finished_at > now() - timedelta(hours=24),
            409, "discovery_required", "Choose a successful discovery from the current configuration within 24 hours")
    assert job is not None
    return job
