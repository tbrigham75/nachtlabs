from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from nachtlabs.access import KEY_SCOPES
from nachtlabs.audit import record
from nachtlabs.errors import require
from nachtlabs.identity import create_identity_token, user_view
from nachtlabs.models import APIKey, Organization, Project, ServiceAccount, User, UserSession, now
from nachtlabs.security import digest, new_token
from sqlalchemy import delete, func, select

from nachtlabs_api.dependencies import DB, Actor, context, rate_limit, recent
from nachtlabs_api.output import IssuedKeyOutput, KeyOutput, UserOutput
from nachtlabs_api.schemas import (
    Invite,
    KeyInput,
    OrganizationChange,
    ServiceAccountInput,
    UserChange,
)

router = APIRouter(tags=["Administration"])


@router.get("/users", response_model=list[UserOutput])
def users(actor: Actor, db: DB) -> list[dict[str, Any]]:
    actor.human_admin()
    return [
        user_view(u)
        for u in db.scalars(select(User).where(User.org_id == actor.org_id).order_by(User.email))
    ]


@router.post("/invitations", status_code=201)
def invite(body: Invite, request: Request, actor: Actor, db: DB) -> dict[str, bool]:
    actor.human_admin()
    recent(actor)
    rate_limit(request, "invitation", 20, actor.actor)
    require(
        db.scalar(select(User.id).where(User.email == str(body.email).lower())) is None,
        409,
        "account_exists",
        "An account already exists",
    )
    org = db.get(Organization, actor.org_id)
    assert org is not None
    create_identity_token(
        db, context(request), org, str(body.email), "invitation", body.role, actor.actor
    )
    return {"queued": True}


@router.patch("/users/{user_id}", response_model=UserOutput)
def update_user(
    user_id: UUID, body: UserChange, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    acting_user = actor.human_admin()
    recent(actor)
    # Serialize all ownership/security mutations through the organization row.
    db.scalar(
        select(Organization)
        .where(Organization.id == actor.org_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    user = db.scalar(
        select(User)
        .where(User.id == user_id, User.org_id == actor.org_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    require(user is not None, 404, "not_found", "User not found")
    assert user is not None
    require(user.version == body.version, 409, "stale_version", "User changed; refresh and retry")
    if user.role == "owner" or body.role == "owner":
        require(
            acting_user.role == "owner", 403, "owner_required", "Only an Owner can change ownership"
        )
    if user.role == "owner" and user.active and (body.role != "owner" or not body.active):
        owners = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.org_id == actor.org_id, User.role == "owner", User.active.is_(True))
        )
        require(
            bool(owners and owners > 1),
            409,
            "last_owner",
            "The last active Owner cannot be removed",
        )
    user.role, user.active, user.version = body.role, body.active, user.version + 1
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    record(
        db,
        context(request),
        "user.updated",
        str(user.id),
        actor=actor.actor,
        org_id=actor.org_id,
        details={"role": body.role, "active": body.active},
    )
    return user_view(user)


@router.get("/organization")
def organization(actor: Actor, db: DB) -> dict[str, Any]:
    actor.human_admin()
    org = db.get(Organization, actor.org_id)
    assert org is not None
    return {"name": org.name, "require_admin_mfa": org.require_admin_mfa, "version": org.version}


@router.put("/organization")
def update_organization(
    body: OrganizationChange, request: Request, actor: Actor, db: DB
) -> dict[str, bool]:
    user = actor.human_admin()
    recent(actor)
    org = db.scalar(
        select(Organization)
        .where(Organization.id == actor.org_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert org is not None
    require(
        org.version == body.version, 409, "stale_version", "Settings changed; refresh and retry"
    )
    if org.require_admin_mfa != body.require_admin_mfa:
        require(
            user.role == "owner", 403, "owner_required", "Only an Owner can change the MFA policy"
        )
        if body.require_admin_mfa:
            require(
                bool(user.mfa_secret and actor.session and actor.session.mfa_verified),
                409,
                "enroll_first",
                "Enroll and verify your MFA before enforcing it",
            )
    org.name, org.require_admin_mfa, org.version = (
        body.name,
        body.require_admin_mfa,
        org.version + 1,
    )
    record(
        db,
        context(request),
        "organization.updated",
        str(org.id),
        actor=actor.actor,
        org_id=actor.org_id,
        details={"require_admin_mfa": org.require_admin_mfa},
    )
    return {"ok": True}


@router.get("/service-accounts")
def accounts(actor: Actor, db: DB) -> list[dict[str, Any]]:
    actor.human_admin()
    return [
        {"id": a.id, "name": a.name, "active": a.active}
        for a in db.scalars(select(ServiceAccount).where(ServiceAccount.org_id == actor.org_id))
    ]


@router.post("/service-accounts", status_code=201)
def create_account(
    body: ServiceAccountInput, request: Request, actor: Actor, db: DB
) -> dict[str, Any]:
    actor.human_admin()
    recent(actor)
    account = ServiceAccount(org_id=actor.org_id, name=body.name)
    db.add(account)
    db.flush()
    record(
        db,
        context(request),
        "service_account.created",
        str(account.id),
        actor=actor.actor,
        org_id=actor.org_id,
    )
    return {"id": account.id, "name": account.name, "active": account.active}


def key_view(key: APIKey) -> dict[str, Any]:
    return {
        "id": key.id,
        "service_account_id": key.service_account_id,
        "name": key.name,
        "prefix": key.prefix,
        "scopes": key.scopes,
        "project_ids": key.project_ids,
        "expires_at": key.expires_at,
        "revoked_at": key.revoked_at,
        "last_used_at": key.last_used_at,
        "last_source": key.last_source,
    }


@router.get("/api-keys", response_model=list[KeyOutput])
def keys(actor: Actor, db: DB) -> list[dict[str, Any]]:
    actor.human_admin()
    query = (
        select(APIKey)
        .join(ServiceAccount)
        .where(ServiceAccount.org_id == actor.org_id)
        .order_by(APIKey.created_at.desc())
    )
    return [key_view(k) for k in db.scalars(query)]


@router.post("/api-keys", status_code=201, response_model=IssuedKeyOutput)
def create_key(body: KeyInput, request: Request, actor: Actor, db: DB) -> dict[str, Any]:
    actor.human_admin()
    recent(actor)
    rate_limit(request, "key-create", 10, actor.actor)
    require(set(body.scopes) <= KEY_SCOPES, 422, "invalid_scope", "Unsupported scope")
    account = db.get(ServiceAccount, body.service_account_id)
    require(
        account is not None and account.org_id == actor.org_id and account.active,
        404,
        "not_found",
        "Service account not found",
    )
    project_ids = list(set(body.project_ids))
    found = list(
        db.scalars(
            select(Project.id).where(
                Project.id.in_(project_ids),
                Project.org_id == actor.org_id,
                Project.archived.is_(False),
            )
        )
    )
    require(
        set(found) == set(project_ids),
        422,
        "invalid_projects",
        "Choose active projects from this organization",
    )
    if body.expires_at:
        require(
            body.expires_at.tzinfo is not None and body.expires_at > now(),
            422,
            "invalid_expiry",
            "Expiry must be a future UTC timestamp",
        )
    raw = "nl_" + new_token()
    key = APIKey(
        service_account_id=body.service_account_id,
        name=body.name,
        prefix=raw[:12],
        token_hash=digest(raw),
        scopes=sorted(set(body.scopes)),
        project_ids=[str(p) for p in project_ids],
        expires_at=body.expires_at,
    )
    db.add(key)
    db.flush()
    record(
        db,
        context(request),
        "api_key.created",
        str(key.id),
        actor=actor.actor,
        org_id=actor.org_id,
        details={"scopes": key.scopes},
    )
    return {**key_view(key), "raw_key": raw}


def owned_key(db: DB, actor: Actor, key_id: UUID) -> APIKey:
    key = db.scalar(
        select(APIKey)
        .join(ServiceAccount)
        .where(APIKey.id == key_id, ServiceAccount.org_id == actor.org_id)
        .with_for_update(of=APIKey)
    )
    require(key is not None, 404, "not_found", "API key not found")
    assert key is not None
    return key


@router.post("/api-keys/{key_id}/revoke")
def revoke_key(key_id: UUID, request: Request, actor: Actor, db: DB) -> dict[str, bool]:
    actor.human_admin()
    recent(actor)
    key = owned_key(db, actor, key_id)
    key.revoked_at = now()
    record(
        db, context(request), "api_key.revoked", str(key.id), actor=actor.actor, org_id=actor.org_id
    )
    return {"ok": True}


@router.post("/api-keys/{key_id}/rotate", status_code=201, response_model=IssuedKeyOutput)
def rotate_key(key_id: UUID, request: Request, actor: Actor, db: DB) -> dict[str, Any]:
    actor.human_admin()
    recent(actor)
    old = owned_key(db, actor, key_id)
    require(
        old.revoked_at is None and (old.expires_at is None or old.expires_at > now()),
        409,
        "inactive_key",
        "Only an active key can be rotated",
    )
    original_expiry = old.expires_at
    result = create_key(
        KeyInput(
            service_account_id=old.service_account_id,
            name=old.name,
            scopes=old.scopes,
            project_ids=[UUID(p) for p in old.project_ids],
            expires_at=original_expiry,
        ),
        request,
        actor,
        db,
    )
    old.expires_at = (
        min(original_expiry, now() + timedelta(hours=24))
        if original_expiry
        else now() + timedelta(hours=24)
    )
    record(
        db, context(request), "api_key.rotated", str(old.id), actor=actor.actor, org_id=actor.org_id
    )
    return {**result, "previous_key_expires_at": old.expires_at}
