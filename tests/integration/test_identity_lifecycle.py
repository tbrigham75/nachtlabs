"""Identity lifecycle checks for the operator's isolated PostgreSQL environment."""

from urllib.parse import parse_qs, urlsplit

import pyotp
import pytest
from fastapi.testclient import TestClient
from nachtlabs.database import session
from nachtlabs.models import MailJob, User
from nachtlabs.security import decrypt, hasher, new_token
from sqlalchemy import select

pytestmark = pytest.mark.integration


def test_mfa_recovery_code_is_single_use(owner: TestClient) -> None:
    password = new_token()
    with session() as db:
        user = db.scalar(select(User))
        assert user is not None
        user.password_hash = hasher.hash(password)
        email = user.email
        db.commit()
    enrollment = owner.post("/api/v1/auth/mfa/enroll")
    assert enrollment.status_code == 200
    code = pyotp.TOTP(enrollment.json()["secret"]).now()
    confirmation = owner.post("/api/v1/auth/mfa/confirm", json={"code": code})
    assert confirmation.status_code == 200
    recovery = confirmation.json()["recovery_codes"][0]
    assert recovery not in owner.get("/api/v1/auth/me").text
    assert recovery not in owner.get("/api/v1/audit-log").text
    assert owner.post("/api/v1/auth/logout").status_code == 200
    login = owner.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200 and login.json()["mfa_required"]
    verification = owner.post(
        "/api/v1/auth/mfa/verify",
        json={
            "challenge": login.json()["challenge"],
            "code": recovery,
        },
    )
    assert verification.status_code == 200
    owner.headers["X-CSRF-Token"] = owner.cookies["nachtlabs_csrf"]
    assert owner.post("/api/v1/auth/logout").status_code == 200
    repeated = owner.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert repeated.status_code == 200
    assert (
        owner.post(
            "/api/v1/auth/mfa/verify",
            json={
                "challenge": repeated.json()["challenge"],
                "code": recovery,
            },
        ).status_code
        == 401
    )


def test_password_reset_revokes_session_and_link(owner: TestClient) -> None:
    email = owner.get("/api/v1/auth/me").json()["email"]
    requested = owner.post("/api/v1/auth/forgot-password", json={"email": email})
    assert requested.status_code == 200
    with session() as db:
        job = db.scalar(select(MailJob))
        assert job is not None and job.payload is not None
        payload = decrypt(job.payload, f"mail:{job.id}")
        link = str(payload["body"]).splitlines()[1]
        raw = parse_qs(urlsplit(link).fragment)["token"][0]
    password = new_token()
    response = owner.post("/api/v1/auth/reset-password", json={"token": raw, "password": password})
    assert response.status_code == 200
    assert owner.get("/api/v1/auth/me").status_code == 401
    assert (
        owner.post(
            "/api/v1/auth/reset-password", json={"token": raw, "password": new_token()}
        ).status_code
        == 400
    )
    assert (
        owner.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code
        == 200
    )
