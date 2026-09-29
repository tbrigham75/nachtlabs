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
from nachtlabs.operator_env import require_operator_env
from nachtlabs.security import hasher
from sqlalchemy import delete, select, text


def list_owners() -> int:
    """Report the organization and its accounts. Reads nothing, writes nothing.

    Without this, an operator who has lost the Owner email has no supported way
    in: --email is mandatory for recovery, and the interface deliberately will
    not disclose account addresses to an anonymous visitor. That combination
    left the host console as the only option. This is root-gated and mutates
    nothing, so it removes the need for hand-written SQL.
    """
    with session() as db:
        orgs = list(db.execute(select(Organization.id, Organization.name)))
        if not orgs:
            print("No organization exists. This installation has not completed")
            print("first-time setup, so an Owner can be created without a reset:")
            print(
                '  sudo python3 scripts/recover-owner.py --bootstrap --email you@example.com --reason "first owner"'
            )
            return 0
        for org_id, name in orgs:
            print(f"organization: {name}")
            users = list(
                db.execute(
                    select(User.email, User.role, User.active, User.mfa_secret.is_not(None))
                    .where(User.org_id == org_id)
                    .order_by(User.created_at)
                )
            )
            if not users:
                print("  (no accounts)")
            for email, role, active, has_mfa in users:
                state = "active" if active else "INACTIVE"
                mfa = ", mfa enrolled" if has_mfa else ""
                print(f"  {role:11} {email}  [{state}{mfa}]")
    print("")
    print("To regain access as the operator, reset that account's password:")
    print(
        '  sudo python3 scripts/recover-owner.py --email <address> --reason "why" --reset-password'
    )
    print("To discard everything and start from zero instead:")
    print("  sudo make reset-first-run")
    return 0


def main() -> int:
    # Root is checked before anything else: a non-root caller cannot read
    # /etc/nachtlabs, so reporting missing configuration first would be wrong.
    if os.geteuid() != 0:
        raise SystemExit("Root console access is required")
    # An installed deployment keeps its configuration in /etc/nachtlabs, and a
    # bare `sudo python3 scripts/recover-owner.py` inherits nothing.
    require_operator_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--email")
    parser.add_argument("--reason")
    parser.add_argument("--reset-password", action="store_true")
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_accounts",
        help="Show the organization and its accounts, then exit. Changes nothing.",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Create the first Owner when no account exists on this installation",
    )
    parser.add_argument("--name", default="Owner")
    parser.add_argument("--organization", default="NachtLabs")
    args = parser.parse_args()
    if args.list_accounts:
        return list_owners()
    if not args.email:
        parser.error("--email is required (or use --list to see the accounts)")
    if not args.reason:
        parser.error("--reason is required for any change to an account")
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
            return 0
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
