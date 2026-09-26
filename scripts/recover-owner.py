"""Offline break-glass identity recovery; root console and migration credentials required."""

import argparse
import getpass
import os
from uuid import uuid4

from nachtlabs.audit import AuditContext, record
from nachtlabs.database import session
from nachtlabs.models import LoginChallenge, Organization, User, UserSession
from nachtlabs.security import hasher
from sqlalchemy import delete, select


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--reset-password", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Root console access is required")
    if input(f"Type {args.email} to confirm offline Owner recovery: ") != args.email:
        raise SystemExit("Recovery cancelled")
    password = None
    if args.reset_password:
        password = getpass.getpass("New password (12-128 characters): ")
        if not 12 <= len(password) <= 128 or password != getpass.getpass("Confirm new password: "):
            raise SystemExit("Password confirmation failed")
    with session() as db:
        db.scalar(select(Organization).with_for_update())
        user = db.scalar(
            select(User)
            .where(User.email == args.email.lower(), User.role == "owner", User.active.is_(True))
            .with_for_update()
        )
        if user is None:
            raise SystemExit("Active Owner not found; no identity was modified")
        user.mfa_secret = None
        user.mfa_pending = None
        user.mfa_last_step = 0
        user.recovery_hashes = []
        if password:
            user.password_hash = hasher.hash(password)
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        db.execute(delete(LoginChallenge).where(LoginChallenge.user_id == user.id))
        record(
            db,
            AuditContext(str(uuid4()), "local-console"),
            "identity.owner.recovered",
            str(user.id),
            actor="operator:root-console",
            org_id=user.org_id,
            details={"reason": args.reason[:500], "password_reset": password is not None},
        )
        db.commit()
    print(
        "Owner recovery recorded. Existing sessions revoked. Organization MFA policy remains in force; enroll again on next sign-in."
    )


if __name__ == "__main__":
    main()
