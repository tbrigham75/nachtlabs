from collections.abc import Generator
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from nachtlabs.access import Principal
from nachtlabs.audit import AuditContext
from nachtlabs.database import limiter_engine, session
from nachtlabs.errors import require
from nachtlabs.models import (
    APIKey,
    Organization,
    RateBucket,
    ServiceAccount,
    User,
    UserSession,
    now,
)
from nachtlabs.security import digest, token_matches
from nachtlabs.settings import get_settings
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


def get_db() -> Generator[Session, None, None]:
    with session() as db:
        yield db
        db.commit()


DB = Annotated[Session, Depends(get_db, scope="function")]


def origin_permitted(request: Request) -> bool:
    """Whether this request's Origin is one the operator configured.

    Exact membership in settings.permitted_origins, never a wildcard or prefix
    match, so every accepted origin is a decision someone wrote down. Shared by
    the pre-authentication guard and the CSRF check so the two cannot drift, and
    a request with no Origin header is never permitted: every browser sends one on
    a cross-origin or non-GET request, and a mutating call without it is not one
    this installation should serve.
    """
    seen = request.headers.get("origin")
    return seen is not None and seen in get_settings().permitted_origins


def context(request: Request) -> AuditContext:
    return AuditContext(
        request.state.request_id, request.client.host if request.client else "unknown"
    )


def rate_limit(request: Request, category: str, limit: int = 20, identity: str = "") -> None:
    source = request.client.host if request.client else "unknown"
    key = digest(f"{category}:{identity or source}")
    window = int(now().timestamp()) // 300
    # Separate committed transaction: failed authentication cannot roll back the limit.
    with Session(limiter_engine()) as db:
        from sqlalchemy import case

        statement = insert(RateBucket).values(key=key, window=window, count=1)
        upserted = statement.on_conflict_do_update(
            index_elements=[RateBucket.key],
            set_={
                "window": window,
                "count": case((RateBucket.window == window, RateBucket.count + 1), else_=1),
            },
        ).returning(RateBucket.count)
        count = db.scalar(upserted)
        db.commit()
    require(
        count is not None and count <= limit,
        429,
        "rate_limited",
        "Too many attempts; wait five minutes",
    )


def principal(request: Request, db: DB) -> Principal:
    authorization = request.headers.get("authorization", "")
    if authorization:
        require(
            authorization.startswith("Bearer "),
            401,
            "unauthenticated",
            "Bearer credential required",
        )
        rate_limit(request, "bearer-source", 600)
        raw = authorization[7:]
        key = db.scalar(select(APIKey).where(APIKey.token_hash == digest(raw)))
        require(
            key is not None
            and key.revoked_at is None
            and (key.expires_at is None or key.expires_at > now()),
            401,
            "unauthenticated",
            "Invalid API key",
        )
        assert key is not None
        account = db.get(ServiceAccount, key.service_account_id)
        require(
            account is not None and account.active, 401, "unauthenticated", "Invalid API identity"
        )
        assert account is not None
        rate_limit(request, "api", 300, str(key.id))
        key.last_used_at = now()
        key.last_source = context(request).source
        return Principal(account.org_id, f"service:{account.id}", key=key)
    raw = request.cookies.get("nachtlabs_session", "")
    auth = db.scalar(select(UserSession).where(UserSession.token_hash == digest(raw)))
    require(
        auth is not None and auth.expires_at > now() and auth.idle_expires_at > now(),
        401,
        "unauthenticated",
        "Sign in to continue",
    )
    assert auth is not None
    user = db.get(User, auth.user_id)
    require(user is not None and user.active, 401, "unauthenticated", "Sign in to continue")
    assert user is not None
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require(
            origin_permitted(request),
            403,
            "csrf",
            "Request origin is not permitted",
        )
        require(
            token_matches(request.headers.get("x-csrf-token", ""), auth.csrf_hash),
            403,
            "csrf",
            "Refresh this page before retrying",
        )
    org = db.get(Organization, user.org_id)
    assert org is not None
    enrollment_paths = {
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
        "/api/v1/auth/reauthenticate",
        "/api/v1/auth/mfa/enroll",
        "/api/v1/auth/mfa/confirm",
    }
    if (
        org.require_admin_mfa
        and user.role in {"owner", "admin"}
        and not (auth.mfa_verified and user.mfa_secret)
    ):
        require(
            request.url.path in enrollment_paths,
            403,
            "mfa_required",
            "Enroll and verify MFA to continue",
        )
    auth.idle_expires_at = min(
        auth.expires_at, now() + timedelta(seconds=get_settings().session_idle_seconds)
    )
    return Principal(user.org_id, str(user.id), user=user, session=auth)


Actor = Annotated[Principal, Depends(principal)]


def recent(actor: Principal) -> None:
    require(
        actor.session is not None
        and actor.session.authenticated_at > now() - timedelta(minutes=10),
        403,
        "reauth_required",
        "Confirm your password in Security settings and retry",
    )


def browser_origin(request: Request) -> None:
    require(
        origin_permitted(request),
        403,
        "origin",
        "Request origin is not permitted",
    )
