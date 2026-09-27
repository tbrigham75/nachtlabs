from datetime import timedelta
from typing import Any

import pyotp
from fastapi import APIRouter, Request, Response
from nachtlabs.audit import record
from nachtlabs.errors import require
from nachtlabs.identity import (
    authenticate,
    bootstrap,
    consume_identity_token,
    create_identity_token,
    issue_session,
    user_view,
    verify_mfa,
)
from nachtlabs.models import LoginChallenge, Organization, User, UserSession, now
from nachtlabs.security import decrypt, digest, encrypt, new_token, password_matches
from nachtlabs.settings import get_settings
from sqlalchemy import delete, select

from nachtlabs_api.dependencies import DB, Actor, browser_origin, context, rate_limit, recent
from nachtlabs_api.output import LoginOutput, MeOutput, UserOutput
from nachtlabs_api.schemas import (
    EmailInput,
    Login,
    MFAChallenge,
    MFACode,
    PasswordToken,
    Preference,
    Reauthenticate,
    Setup,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def set_session(response: Response, pair: tuple[str, str]) -> None:
    settings = get_settings()
    # Decided by the whole permitted set, not by the canonical origin alone: a
    # Secure cookie is never sent over plain HTTP, so marking it while any
    # permitted origin is HTTP would lock the operator out of that one.
    secure = settings.secure_cookies
    response.set_cookie(
        "nachtlabs_session",
        pair[0],
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=settings.session_absolute_seconds,
        path="/",
    )
    response.set_cookie(
        "nachtlabs_csrf",
        pair[1],
        httponly=False,
        secure=secure,
        samesite="strict",
        max_age=settings.session_absolute_seconds,
        path="/",
    )


@router.get("/setup-status")
def setup_status(db: DB) -> dict[str, bool]:
    return {"initialized": db.scalar(select(Organization.id)) is not None}


@router.get("/preflight")
def preflight(request: Request, db: DB) -> dict[str, Any]:
    """Report whether a mutating request from this origin would be accepted.

    A GET never reaches browser_origin, and any mutating endpoint rejects an
    invalid body during validation before that check runs, so a probe cannot
    distinguish "origin refused" from "bad input" without creating an account.
    This answers it directly and mutates nothing.

    It reports the configured public URL and the full set of permitted origins so
    an operator can see the exact mismatch rather than infer it. That is
    operator-facing configuration on a single-tenant self-hosted console,
    comparable to what setup-status already discloses, and it is not reachable to
    learn anything about accounts.

    origin_accepted is only meaningful when a request actually carries an Origin
    header. A same-origin GET does not, so a browser reading this from its own
    page always sees null here even on a healthy installation; callers must
    compare the origin they know they are using against `allowed` instead.
    """
    settings = get_settings()
    seen = request.headers.get("origin")
    permitted = list(settings.permitted_origins)
    accepted = seen is not None and seen in permitted
    return {
        "origin": seen,
        "expected": settings.public_url,
        # The full membership set, so a caller can tell a wrong address from a
        # wrong configuration without a second request.
        "allowed": permitted,
        "origin_accepted": accepted,
        # False only when a permitted origin is plain HTTP, which means the
        # session cookie cannot be marked Secure.
        "secure_cookies": settings.secure_cookies,
        "setup_token_required": settings.setup_token_required,
        # Whether cleartext to a private provider is permitted at all. Reported so
        # the interface can explain the rule instead of refusing a shape the
        # operator has already enabled.
        "allow_http_private": settings.integration_allow_http_private,
        "initialized": db.scalar(select(Organization.id)) is not None,
        "hint": None
        if accepted or seen is None
        else (
            f"Add {seen} to NACHTLABS_ALLOWED_ORIGINS, or browse one of: " + ", ".join(permitted)
        ),
    }


@router.post("/setup", status_code=201, response_model=UserOutput)
def setup(body: Setup, request: Request, response: Response, db: DB) -> dict[str, Any]:
    browser_origin(request)
    rate_limit(request, "setup", 5)
    user = bootstrap(
        db,
        context(request),
        body.bootstrap_token.get_secret_value() if body.bootstrap_token else None,
        str(body.email),
        body.name,
        body.password.get_secret_value(),
        body.organization,
    )
    set_session(response, issue_session(db, user, False))
    return user_view(user)


@router.post("/login", response_model=LoginOutput, response_model_exclude_none=True)
def login(body: Login, request: Request, response: Response, db: DB) -> dict[str, Any]:
    browser_origin(request)
    rate_limit(request, "login-source", 30)
    rate_limit(request, "login-identity", 10, str(body.email).lower())
    user = authenticate(db, context(request), str(body.email), body.password.get_secret_value())
    if user.mfa_secret:
        raw = new_token()
        db.add(
            LoginChallenge(
                user_id=user.id, token_hash=digest(raw), expires_at=now() + timedelta(minutes=5)
            )
        )
        return {"mfa_required": True, "challenge": raw}
    set_session(response, issue_session(db, user, False))
    record(db, context(request), "auth.login", str(user.id), actor=str(user.id), org_id=user.org_id)
    return {"mfa_required": False, "user": user_view(user)}


@router.post("/mfa/verify", response_model=UserOutput)
def mfa_verify(body: MFAChallenge, request: Request, response: Response, db: DB) -> dict[str, Any]:
    browser_origin(request)
    rate_limit(request, "mfa-source", 20)
    rate_limit(request, "mfa-challenge", 5, digest(body.challenge.get_secret_value()))
    challenge = db.scalar(
        select(LoginChallenge)
        .where(LoginChallenge.token_hash == digest(body.challenge.get_secret_value()))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    require(
        challenge is not None and challenge.expires_at > now(),
        401,
        "invalid_mfa",
        "Challenge expired; sign in again",
    )
    assert challenge is not None
    user = db.scalar(
        select(User)
        .where(User.id == challenge.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    require(user is not None and user.active, 401, "invalid_mfa", "Invalid challenge")
    assert user is not None
    if not verify_mfa(user, body.code.get_secret_value()):
        record(db, context(request), "auth.mfa", str(user.id), org_id=user.org_id, outcome="denied")
        db.commit()
        require(False, 401, "invalid_mfa", "Invalid or already used code")
    db.delete(challenge)
    set_session(response, issue_session(db, user, True))
    record(db, context(request), "auth.login", str(user.id), actor=str(user.id), org_id=user.org_id)
    return user_view(user)


@router.get("/me", response_model=MeOutput)
def me(actor: Actor, db: DB) -> dict[str, Any]:
    require(actor.user is not None, 403, "human_required", "This endpoint requires a user session")
    assert actor.user is not None
    org = db.get(Organization, actor.org_id)
    assert org is not None
    return {
        **user_view(actor.user),
        "organization": org.name,
        "mfa_required": org.require_admin_mfa
        and actor.admin
        and not bool(actor.user.mfa_secret and actor.session and actor.session.mfa_verified),
    }


@router.post("/logout")
def logout(request: Request, response: Response, actor: Actor, db: DB) -> dict[str, bool]:
    if actor.session:
        db.delete(actor.session)
    response.delete_cookie("nachtlabs_session", path="/")
    response.delete_cookie("nachtlabs_csrf", path="/")
    record(db, context(request), "auth.logout", actor.actor, actor=actor.actor, org_id=actor.org_id)
    return {"ok": True}


@router.post("/reauthenticate")
def reauthenticate(body: Reauthenticate, request: Request, actor: Actor, db: DB) -> dict[str, bool]:
    require(
        actor.user is not None and actor.session is not None,
        403,
        "human_required",
        "User session required",
    )
    assert actor.user is not None and actor.session is not None
    rate_limit(request, "reauth", 5, actor.actor)
    user = db.scalar(
        select(User)
        .where(User.id == actor.user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert user is not None
    require(
        password_matches(user.password_hash, body.password.get_secret_value()),
        401,
        "invalid_credentials",
        "Invalid credentials",
    )
    if user.mfa_secret:
        require(
            body.code is not None and verify_mfa(user, body.code.get_secret_value()),
            401,
            "invalid_mfa",
            "A fresh MFA or recovery code is required",
        )
        actor.session.mfa_verified = True
    actor.session.authenticated_at = now()
    record(
        db,
        context(request),
        "auth.reauthenticated",
        actor.actor,
        actor=actor.actor,
        org_id=actor.org_id,
    )
    return {"ok": True}


@router.post("/mfa/enroll")
def mfa_enroll(request: Request, actor: Actor, db: DB) -> dict[str, str]:
    recent(actor)
    assert actor.user is not None
    require(actor.user.mfa_secret is None, 409, "mfa_exists", "MFA is already enabled")
    secret = pyotp.random_base32()
    actor.user.mfa_pending = encrypt(
        {"secret": secret, "expires": (now() + timedelta(minutes=10)).isoformat()},
        f"mfa-pending:{actor.user.id}",
    )
    record(
        db,
        context(request),
        "auth.mfa.enrollment_started",
        actor.actor,
        actor=actor.actor,
        org_id=actor.org_id,
    )
    return {
        "secret": secret,
        "uri": pyotp.TOTP(secret).provisioning_uri(actor.user.email, issuer_name="NachtLabs"),
    }


@router.post("/mfa/confirm")
def mfa_confirm(body: MFACode, request: Request, actor: Actor, db: DB) -> dict[str, list[str]]:
    from datetime import datetime

    recent(actor)
    rate_limit(request, "mfa-enroll", 5, actor.actor)
    assert actor.user is not None and actor.session is not None
    user = db.scalar(
        select(User)
        .where(User.id == actor.user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert user is not None
    require(
        user.mfa_pending is not None and user.mfa_secret is None,
        409,
        "no_enrollment",
        "Start MFA enrollment first",
    )
    assert user.mfa_pending is not None
    pending = decrypt(user.mfa_pending, f"mfa-pending:{user.id}")
    require(
        datetime.fromisoformat(str(pending["expires"])) > now(),
        400,
        "enrollment_expired",
        "Restart MFA enrollment",
    )
    secret = str(pending["secret"])
    require(
        pyotp.TOTP(secret).verify(body.code.get_secret_value()),
        400,
        "invalid_mfa",
        "Invalid authenticator code",
    )
    codes = [new_token()[:20].lower() for _ in range(10)]
    user.mfa_secret = encrypt({"secret": secret}, f"mfa:{user.id}")
    user.mfa_pending = None
    user.recovery_hashes = [digest(code) for code in codes]
    user.mfa_last_step = int(now().timestamp()) // 30
    actor.session.mfa_verified = True
    db.execute(
        delete(UserSession).where(
            UserSession.user_id == user.id, UserSession.id != actor.session.id
        )
    )
    record(
        db,
        context(request),
        "auth.mfa.enabled",
        actor.actor,
        actor=actor.actor,
        org_id=actor.org_id,
    )
    return {"recovery_codes": codes}


@router.post("/mfa/disable")
def mfa_disable(request: Request, actor: Actor, db: DB) -> dict[str, bool]:
    recent(actor)
    assert actor.user is not None
    org = db.get(Organization, actor.org_id)
    require(
        not (org and org.require_admin_mfa and actor.admin),
        403,
        "mfa_policy",
        "Organization policy requires MFA",
    )
    require(
        actor.session is not None and actor.session.mfa_verified,
        403,
        "mfa_required",
        "Verify MFA before disabling it",
    )
    assert actor.session is not None
    actor.user.mfa_secret = None
    actor.user.mfa_pending = None
    actor.user.recovery_hashes = []
    actor.session.mfa_verified = False
    db.execute(
        delete(UserSession).where(
            UserSession.user_id == actor.user.id, UserSession.id != actor.session.id
        )
    )
    record(
        db,
        context(request),
        "auth.mfa.disabled",
        actor.actor,
        actor=actor.actor,
        org_id=actor.org_id,
    )
    return {"ok": True}


@router.post("/forgot-password")
def forgot(body: EmailInput, request: Request, db: DB) -> dict[str, str]:
    browser_origin(request)
    rate_limit(request, "reset-source", 10)
    rate_limit(request, "reset-identity", 3, str(body.email).lower())
    require(
        bool(get_settings().smtp_host),
        503,
        "email_unconfigured",
        "Email delivery is not configured; recover the Owner with "
        "scripts/recover-owner.py --reset-password on the host console",
    )
    user = db.scalar(
        select(User).where(User.email == str(body.email).lower(), User.active.is_(True))
    )
    if user:
        org = db.get(Organization, user.org_id)
        assert org is not None
        create_identity_token(db, context(request), org, user.email, "reset")
    return {"message": "If an active account matches, a reset email will be sent."}


@router.post("/reset-password")
def reset(body: PasswordToken, request: Request, db: DB) -> dict[str, bool]:
    browser_origin(request)
    rate_limit(request, "reset-consume", 10)
    consume_identity_token(
        db,
        context(request),
        body.token.get_secret_value(),
        "reset",
        body.password.get_secret_value(),
    )
    return {"ok": True}


@router.post("/accept-invitation")
def accept(body: PasswordToken, request: Request, db: DB) -> dict[str, bool]:
    browser_origin(request)
    rate_limit(request, "invitation-consume", 10)
    require(bool(body.name), 422, "name_required", "Your name is required")
    consume_identity_token(
        db,
        context(request),
        body.token.get_secret_value(),
        "invitation",
        body.password.get_secret_value(),
        body.name,
    )
    return {"ok": True}


@router.put("/preferences")
def preferences(body: Preference, actor: Actor) -> dict[str, str]:
    require(actor.user is not None, 403, "human_required", "User session required")
    assert actor.user is not None
    actor.user.theme = body.theme
    return {"theme": body.theme}
