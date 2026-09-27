import json
import time
from dataclasses import asdict
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, update

from nachtlabs.audit import AuditContext, record
from nachtlabs.database import session
from nachtlabs.integrations.contracts import ProviderError
from nachtlabs.integrations.providers import GitAdapter, OllamaAdapter
from nachtlabs.integrations.transport import Endpoint, PinnedJSON
from nachtlabs.models import IntegrationConnection, IntegrationProbe, now
from nachtlabs.security import decrypt
from nachtlabs.settings import get_settings


def network_allowed(provider: str) -> bool:
    settings = get_settings()
    return settings.integration_network_enabled and (
        provider == "ollama" or settings.git_provider_network_enabled
    )


def probe_tick() -> None:
    """One explicitly requested read-only discovery. No automatic connection checks or Git writes."""
    timestamp = now()
    with session() as db:
        # A crashed process is not silently replayed; operator can explicitly request another probe.
        db.execute(
            update(IntegrationProbe)
            .where(IntegrationProbe.state == "running", IntegrationProbe.lease_until < timestamp)
            .values(state="failed", error_code="worker_interrupted", finished_at=timestamp)
        )
        job = db.scalar(
            select(IntegrationProbe)
            .where(IntegrationProbe.state == "pending")
            .order_by(IntegrationProbe.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            db.commit()
            return
        connection = db.get(IntegrationConnection, job.connection_id)
        assert connection is not None
        if (
            not connection.active
            or connection.version != job.connection_version
            or not network_allowed(connection.provider)
        ):
            job.state, job.error_code, job.finished_at = (
                "stale",
                "configuration_or_network_policy",
                timestamp,
            )
            db.commit()
            return
        job.state, job.lease_id, job.lease_until = (
            "running",
            uuid4(),
            timestamp + timedelta(minutes=3),
        )
        job_id, lease_id, version = job.id, job.lease_id, connection.version
        connection_id, org_id, provider, page = (
            connection.id,
            connection.org_id,
            connection.provider,
            job.page,
        )
        endpoint = Endpoint(
            connection.base_url,
            tuple(connection.pinned_addresses),
            connection.allow_private,
            connection.allow_http,
            connection.timeout_seconds,
            get_settings().integration_allow_http_private,
        )
        encrypted = connection.credential
        record(
            db,
            AuditContext(str(job_id), "worker"),
            "integration.probe.started",
            str(connection.id),
            actor="worker",
            org_id=org_id,
            details={"configuration_version": version},
        )
        if encrypted:
            record(
                db,
                AuditContext(str(job_id), "worker"),
                "integration.credential.used",
                str(connection.id),
                actor="worker",
                org_id=org_id,
            )
        db.commit()
    started = time.monotonic()
    result, error = {}, None
    try:
        credentials = decrypt(encrypted, f"integration:{connection_id}") if encrypted else {}
        token = str(credentials.get("token", ""))
        if provider in {"github", "gitea"} and not token:
            raise ProviderError("credential_required")
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = ("token " if provider == "gitea" else "Bearer ") + token
        if provider == "github":
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        transport = PinnedJSON(endpoint, headers, get_settings().integration_ca_file)
        adapter = (
            OllamaAdapter(transport) if provider == "ollama" else GitAdapter(transport, provider)
        )
        result = asdict(adapter.discover(page))
        if any(
            value and json.dumps(str(value))[1:-1] in json.dumps(result)
            for value in credentials.values()
        ):
            result = {}
            raise ProviderError("credential_reflection")
    except ProviderError as exc:
        error = exc.code
    except Exception:
        # Decryption/provider/parser exception strings may contain credentials or response content.
        error = "integration_internal"
    with session() as db:
        job = db.scalar(
            select(IntegrationProbe).where(IntegrationProbe.id == job_id).with_for_update()
        )
        if job is None or job.state != "running" or job.lease_id != lease_id:
            return
        connection = db.scalar(
            select(IntegrationConnection)
            .where(IntegrationConnection.id == connection_id)
            .with_for_update()
        )
        if (
            connection is None
            or connection.version != version
            or not connection.active
            or not network_allowed(provider)
        ):
            job.state, job.error_code, job.result = "stale", "configuration_changed", {}
        else:
            job.state, job.error_code, job.result = (
                ("failed" if error else "succeeded"),
                error,
                result,
            )
        job.finished_at, job.lease_until = now(), None
        job.duration_ms = round((time.monotonic() - started) * 1000)
        record(
            db,
            AuditContext(str(job_id), "worker"),
            "integration.probe.finished",
            str(connection_id),
            actor="worker",
            org_id=org_id,
            outcome=job.state,
            details={"error_code": job.error_code, "duration_ms": job.duration_ms},
        )
        db.commit()
