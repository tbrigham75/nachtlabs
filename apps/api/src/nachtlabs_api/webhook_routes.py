"""Signed, allowlisted intake only. A webhook never approves or executes a plan."""

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from nachtlabs.access import Principal, project_access
from nachtlabs.audit import record
from nachtlabs.errors import DomainError, require
from nachtlabs.factory_models import WebhookBinding, WebhookReceipt
from nachtlabs.integrations.contracts import ProviderError
from nachtlabs.integrations.webhooks import delivery_fingerprint, verify_signature
from nachtlabs.models import APIKey, IntegrationConnection, Project, ProjectIntegration
from nachtlabs.security import decrypt
from nachtlabs.workflows.policy import Strict, WorkInput
from nachtlabs.workflows.state import submit
from pydantic import Field
from sqlalchemy import select

from nachtlabs_api.dependencies import DB, Actor, context, rate_limit, recent

router = APIRouter(tags=["webhook intake"])


class BindingInput(Strict):
    version: int
    enabled: bool
    actors: list[str] = Field(min_length=1, max_length=100)
    labels: list[str] = Field(min_length=1, max_length=30)
    commands: list[str] = Field(
        default_factory=lambda: ["/nachtlabs implement"], min_length=1, max_length=1
    )


@router.get("/projects/{project_id}/webhook")
def binding(project_id: UUID, db: DB, actor: Actor) -> dict[str, Any]:
    actor.human_admin()
    project_access(db, actor, project_id)
    value = db.scalar(select(WebhookBinding).where(WebhookBinding.project_id == project_id))
    return {
        "version": value.version if value else 0,
        "enabled": value.enabled if value else False,
        "actors": value.actors if value else [],
        "labels": value.labels if value else [],
        "commands": value.commands if value else ["/nachtlabs implement"],
        "path": "/api/v1/hooks/" + str(value.id) if value else None,
    }


@router.put("/projects/{project_id}/webhook")
def configure(
    project_id: UUID, body: BindingInput, request: Request, db: DB, actor: Actor
) -> dict[str, Any]:
    actor.human_admin()
    recent(actor)
    project_access(db, actor, project_id, lock=True)
    integration = db.get(ProjectIntegration, project_id)
    require(
        integration is not None, 409, "repository_required", "Bind an approved repository first"
    )
    assert integration is not None
    require(
        body.commands == ["/nachtlabs implement"]
        and all(0 < len(v) <= 100 for v in [*body.actors, *body.labels]),
        422,
        "webhook_policy",
        "Use bounded actors, labels and the supported intake command",
    )
    value = db.scalar(
        select(WebhookBinding).where(WebhookBinding.project_id == project_id).with_for_update()
    )
    require(
        body.version == (value.version if value else 0),
        409,
        "stale_version",
        "Refresh webhook settings",
    )
    if value is None:
        value = WebhookBinding(
            project_id=project_id, connection_id=integration.connection_id, version=0
        )
        db.add(value)
    value.connection_id, value.enabled = integration.connection_id, body.enabled
    value.actors, value.labels, value.commands, value.version = (
        body.actors,
        body.labels,
        body.commands,
        body.version + 1,
    )
    db.flush()
    record(
        db,
        context(request),
        "webhook.configured",
        str(value.id),
        actor=actor.actor,
        org_id=actor.org_id,
        project_id=project_id,
    )
    return {"version": value.version, "path": "/api/v1/hooks/" + str(value.id)}


@router.post("/hooks/{identifier}")
async def intake(identifier: UUID, request: Request, db: DB) -> dict[str, Any]:
    rate_limit(request, "webhook", 120, str(identifier))
    binding = db.scalar(
        select(WebhookBinding).where(WebhookBinding.id == identifier).with_for_update()
    )
    require(binding is not None and binding.enabled, 404, "not_found", "Webhook unavailable")
    assert binding is not None
    connection = db.get(IntegrationConnection, binding.connection_id)
    integration = db.get(ProjectIntegration, binding.project_id)
    require(
        connection is not None
        and connection.active
        and integration is not None
        and integration.connection_id == connection.id,
        404,
        "not_found",
        "Webhook unavailable",
    )
    assert connection is not None and integration is not None
    raw = await request.body()
    credentials = (
        decrypt(connection.credential, f"integration:{connection.id}")
        if connection.credential
        else {}
    )
    github = connection.provider == "github"
    signature = request.headers.get("x-hub-signature-256" if github else "x-gitea-signature", "")
    delivery = request.headers.get("x-github-delivery" if github else "x-gitea-delivery", "")
    try:
        verify_signature(connection.provider, raw, signature, credentials.get("webhook_secret", ""))
        key, payload_hash = delivery_fingerprint(str(binding.id), delivery, raw)
    except ProviderError:
        raise DomainError(401, "webhook_rejected", "Webhook authentication failed") from None
    prior = db.scalar(select(WebhookReceipt).where(WebhookReceipt.delivery_key == key))
    if prior:
        require(
            prior.payload_hash == payload_hash,
            409,
            "webhook_replay",
            "Delivery identifier has conflicting content",
        )
        return {
            "status": prior.status,
            "request_id": str(prior.request_id) if prior.request_id else None,
        }
    receipt = WebhookReceipt(
        binding_id=binding.id, delivery_key=key, payload_hash=payload_hash, status="ignored"
    )
    db.add(receipt)
    try:
        payload = json.loads(raw)
        require(isinstance(payload, dict), 422, "webhook_payload", "Object payload required")
        issue, comment = payload.get("issue", {}), payload.get("comment", {})
        sender = payload.get("sender", {}).get("login")
        repository = payload.get("repository", {})
        labels = {
            str(v["name"])
            for v in issue.get("labels", [])
            if isinstance(v, dict) and isinstance(v.get("name"), str)
        }
        event = request.headers.get("x-github-event" if github else "x-gitea-event", "")
        text = comment.get("body", "")
        allowed = (
            event == "issue_comment"
            and payload.get("action") == "created"
            and sender in binding.actors
            and repository.get("full_name") == integration.full_name
            and str(repository.get("id")) == integration.repository_id
            and set(binding.labels) <= labels
            and isinstance(text, str)
            and text.splitlines()
            and text.splitlines()[0].strip() in binding.commands
            and "pull_request" not in issue
        )
        if not allowed:
            return {"status": "ignored", "request_id": None}
        description = issue.get("body") or ""
        # Intake command must carry explicit criteria; issue text is untrusted plan input.
        criteria = [line[2:].strip() for line in text.splitlines()[1:] if line.startswith("- ")]
        body = WorkInput(
            project_id=binding.project_id,
            title=issue.get("title", ""),
            description=description,
            acceptance_criteria=criteria,
            target_ref=integration.default_branch,
            labels=sorted(labels),
        )
        project = db.get(Project, binding.project_id)
        # Ephemeral scoped identity is constructed only after signature and binding checks.
        require(project is not None, 404, "not_found", "Webhook unavailable")
        assert project is not None
        principal = Principal(
            project.org_id,
            "webhook:" + str(binding.id),
            key=APIKey(scopes=["work_requests:create"], project_ids=[str(project.id)]),
        )
        work, _ = submit(db, principal, body, key, context(request), source="webhook")
        receipt.status, receipt.request_id = "accepted", work.id
        return {"status": "accepted", "request_id": str(work.id)}
    except (ValueError, TypeError, AttributeError):
        receipt.status = "rejected"
        return {"status": "rejected", "request_id": None}
