"""Offline break-glass identity recovery; root console and migration credentials required.

Without --bootstrap this recovers an existing Owner. With --bootstrap it creates
the very first Owner on an installation that has none, which is the one state
that is otherwise unreachable: the setup token may be lost, and this script is
the only supported way back in.
"""

import argparse
import getpass
import os
from uuid import uuid4

from nachtlabs.audit import AuditContext, record
from nachtlabs.database import session
from nachtlabs.models import LoginChallenge, Organization, User, UserSession
from nachtlabs.security import hasher
from sqlalchemy import delete, select, text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--reset-password", action="store_true")
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Create the first Owner when no account exists on this installation",
    )
    parser.add_argument("--name", default="Owner")
    parser.add_argument("--organization", default="NachtLabs")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Root console access is required")
    if input(f"Type {args.email} to confirm offline Owner recovery: ") != args.email:
        raise SystemExit("Recovery cancelled")
    password = None
    if args.reset_password or args.bootstrap:
        password = getpass.getpass("New password (12-128 characters): ")
        if not 12 <= len(password) <= 128 or password != getpass.getpass("Confirm new password: "):
            raise SystemExit("Password confirmation failed")
    with session() as db:
        if args.bootstrap:
            # Take the same advisory lock as the setup route so an operator at
            # the browser cannot create the first account concurrently.
            db.execute(text("SELECT pg_advisory_xact_lock(9182701)"))
            existing = db.scalar(select(User.id).limit(1))
            if existing is not None:
                raise SystemExit(
                    "An account already exists; refusing to bootstrap. Use --reset-password instead."
                )
            org = Organization(name=args.organization)
            db.add(org)
            db.flush()
            user = User(
                org_id=org.id,
                email=args.email.lower(),
                name=args.name,
                role="owner",
                password_hash=hasher.hash(password),
            )
            db.add(user)
            db.flush()
            record(
                db,
                AuditContext(str(uuid4()), "local-console"),
                "identity.owner.bootstrapped",
                str(user.id),
                actor="operator:root-console",
                org_id=org.id,
                details={"reason": args.reason[:500], "organization": org.name},
            )
            db.commit()
            print(
                f"First Owner bootstrapped for {user.email} in organization {org.name!r}. "
                "Sign in and configure the installation; setup is now closed."
            )
            return
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
