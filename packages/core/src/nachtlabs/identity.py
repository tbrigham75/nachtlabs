"""Identity mutations are transactional; routes supply authorization and CSRF guards."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pyotp
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from nachtlabs.audit import AuditContext, record
from nachtlabs.errors import DomainError, require
from nachtlabs.models import (
    IdentityToken,
    LoginChallenge,
    MailJob,
    Organization,
    User,
    UserSession,
    now,
)
from nachtlabs.security import decrypt, digest, encrypt, hasher, new_token, password_matches
from nachtlabs.settings import get_settings


def user_view(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "active": user.active,
        "theme": user.theme,
        "mfa_enabled": user.mfa_secret is not None,
        "version": user.version,
    }


def bootstrap(
    db: Session,
    context: AuditContext,
    token: str | None,
    email: str,
    name: str,
    password: str,
    organization: str,
) -> User:
    """Create the organization and its first Owner.

    The advisory lock is what makes "the first account wins" race-free, so it
    guards this before anything is read. A setup token is only demanded when the
    operator opted in, which keeps an internet-facing installation from being
    claimed by whoever finds the port first.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(9182701)"))
    require(
        db.scalar(select(Organization.id)) is None, 409, "setup_closed", "Setup is already complete"
    )
    if get_settings().setup_token_required:
        path = get_settings().bootstrap_token_file
        require(
            path is not None and path.is_file(),
            503,
            "setup_unavailable",
            "Setup token is not configured",
        )
        assert path is not None
        import hmac

        require(
            token is not None and hmac.compare_digest(token, path.read_text().strip()),
            403,
            "invalid_setup_token",
            "Invalid setup token",
        )
    org = Organization(name=organization)
    db.add(org)
    db.flush()
    user = User(
        org_id=org.id,
        email=email.lower(),
        name=name,
        role="owner",
        password_hash=hasher.hash(password),
    )
    db.add(user)
    db.flush()
    record(db, context, "setup.completed", str(org.id), actor=str(user.id), org_id=org.id)
    return user


def issue_session(db: Session, user: User, mfa_verified: bool) -> tuple[str, str]:
    settings = get_settings()
    token, csrf = new_token(), new_token()
    timestamp = now()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=digest(token),
            csrf_hash=digest(csrf),
            expires_at=timestamp + timedelta(seconds=settings.session_absolute_seconds),
            idle_expires_at=timestamp + timedelta(seconds=settings.session_idle_seconds),
            mfa_verified=mfa_verified,
        )
    )
    return token, csrf


def authenticate(db: Session, context: AuditContext, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    # Use a real expensive hash even for unknown identities to reduce timing differences.
    valid = (
        password_matches(user.password_hash, password)
        if user
        else password_matches(hasher.hash(new_token()), password)
    )
    if not user or not user.active or not valid:
        record(
            db,
            context,
            "auth.login",
            "identity",
            outcome="denied",
            org_id=user.org_id if user else db.scalar(select(Organization.id)),
        )
        db.commit()
        raise DomainError(401, "invalid_credentials", "Invalid email or password")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(password)
    return user


def verify_mfa(user: User, code: str) -> bool:
    if not user.mfa_secret:
        return False
    secret = str(decrypt(user.mfa_secret, f"mfa:{user.id}")["secret"])
    totp = pyotp.TOTP(secret)
    step = int(now().timestamp()) // 30
    for candidate in (step - 1, step, step + 1):
        if candidate > user.mfa_last_step and totp.verify(
            code, for_time=datetime.fromtimestamp(candidate * 30, tz=UTC)
        ):
            user.mfa_last_step = candidate
            return True
    hashed = digest(code.replace(" ", "").lower())
    if hashed in user.recovery_hashes:
        user.recovery_hashes = [item for item in user.recovery_hashes if item != hashed]
        return True
    return False


def queue_identity_mail(db: Session, email: str, purpose: str, raw: str) -> None:
    settings = get_settings()
    require(bool(settings.smtp_host), 503, "email_unconfigured", "Email delivery is not configured")
    route = "reset-password" if purpose == "reset" else "accept-invitation"
    # Fragment is not sent to the web server or proxy access logs.
    link = f"{settings.public_url}/{route}#token={raw}"
    job_id = uuid4()
    payload = {
        "recipient": email,
        "subject": f"NachtLabs {purpose}",
        "body": f"Open this single-use link to continue:\n{link}\nIf you did not expect this email, ignore it.",
    }
    db.add(MailJob(id=job_id, payload=encrypt(payload, f"mail:{job_id}")))


def create_identity_token(
    db: Session,
    context: AuditContext,
    org: Organization,
    email: str,
    purpose: str,
    role: str = "viewer",
    actor: str = "anonymous",
) -> None:
    raw = new_token()
    db.execute(
        delete(IdentityToken).where(
            IdentityToken.email == email.lower(), IdentityToken.purpose == purpose
        )
    )
    db.add(
        IdentityToken(
            org_id=org.id,
            email=email.lower(),
            purpose=purpose,
            role=role,
            token_hash=digest(raw),
            expires_at=now() + timedelta(hours=1 if purpose == "reset" else 48),
        )
    )
    queue_identity_mail(db, email.lower(), purpose, raw)
    record(db, context, f"identity.{purpose}.requested", "identity", actor=actor, org_id=org.id)


def consume_identity_token(
    db: Session, context: AuditContext, raw: str, purpose: str, password: str, name: str = ""
) -> None:
    token = db.scalar(
        select(IdentityToken)
        .where(
            IdentityToken.token_hash == digest(raw),
            IdentityToken.purpose == purpose,
        )
        .with_for_update()
    )
    require(
        token is not None and token.consumed_at is None and token.expires_at > now(),
        400,
        "invalid_token",
        "This link is invalid or expired",
    )
    assert token is not None
    user = db.scalar(select(User).where(User.email == token.email).with_for_update())
    if purpose == "invitation":
        require(user is None, 409, "account_exists", "An account already exists")
        user = User(
            org_id=token.org_id,
            email=token.email,
            name=name,
            password_hash=hasher.hash(password),
            role=token.role,
        )
        db.add(user)
        db.flush()
    else:
        require(
            user is not None and user.active,
            400,
            "invalid_token",
            "This link is invalid or expired",
        )
        assert user is not None
        user.password_hash = hasher.hash(password)
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        db.execute(delete(LoginChallenge).where(LoginChallenge.user_id == user.id))
    token.consumed_at = now()
    record(
        db,
        context,
        f"identity.{purpose}.completed",
        str(user.id),
        actor=str(user.id),
        org_id=user.org_id,
    )
