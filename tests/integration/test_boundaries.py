from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from nachtlabs.database import session
from nachtlabs.models import GovernanceVersion, Organization, User
from nachtlabs.security import new_token
from nachtlabs.settings import get_settings
from nachtlabs_api.main import create_app
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


def test_owner_setup_race(client: TestClient) -> None:
    payload = {
        "bootstrap_token": get_settings().bootstrap_token_file.read_text(),
        "name": "Owner",
        "organization": "Race Test",
        "password": new_token(),
    }

    def create(number: int) -> int:
        with TestClient(create_app(), headers={"Origin": "http://testserver"}) as browser:
            return browser.post(
                "/api/v1/auth/setup", json={**payload, "email": f"owner{number}@example.com"}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, [1, 2]))
    assert sorted(results) == [201, 409]


def test_csrf_and_last_owner(owner: TestClient) -> None:
    user = owner.get("/api/v1/auth/me").json()
    owner.headers["X-CSRF-Token"] = "incorrect"
    assert (
        owner.post("/api/v1/projects", json={"name": "Denied", "slug": "denied"}).status_code == 403
    )
    owner.headers["X-CSRF-Token"] = owner.cookies["nachtlabs_csrf"]
    response = owner.patch(
        f"/api/v1/users/{user['id']}",
        json={"role": "viewer", "active": True, "version": user["version"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_owner"


def test_api_key_scope_revocation_and_no_plaintext(owner: TestClient) -> None:
    first = owner.post("/api/v1/projects", json={"name": "First", "slug": "first"}).json()
    second = owner.post("/api/v1/projects", json={"name": "Second", "slug": "second"}).json()
    account = owner.post("/api/v1/service-accounts", json={"name": "Read-only bot"}).json()
    response = owner.post(
        "/api/v1/api-keys",
        json={
            "service_account_id": account["id"],
            "name": "One project",
            "scopes": ["projects:read"],
            "project_ids": [first["id"]],
        },
    )
    assert response.status_code == 201
    key = response.json()
    headers = {"Authorization": "Bearer " + key["raw_key"]}
    assert owner.get(f"/api/v1/projects/{first['id']}", headers=headers).status_code == 200
    assert owner.get(f"/api/v1/projects/{second['id']}", headers=headers).status_code == 404
    assert owner.get("/api/v1/users", headers=headers).status_code == 403
    assert key["raw_key"] not in owner.get("/api/v1/api-keys").text
    assert key["raw_key"] not in owner.get("/api/v1/audit-log").text
    assert owner.post(f"/api/v1/api-keys/{key['id']}/revoke").status_code == 200
    assert owner.get("/api/v1/projects", headers=headers).status_code == 401


def _key_for(owner: TestClient, project: dict) -> tuple[dict, dict]:
    account = owner.post("/api/v1/service-accounts", json={"name": f"bot-{uuid4().hex[:8]}"}).json()
    key = owner.post(
        "/api/v1/api-keys",
        json={
            "service_account_id": account["id"],
            "name": "Reader",
            "scopes": ["projects:read"],
            "project_ids": [project["id"]],
        },
    ).json()
    return key, {"Authorization": "Bearer " + key["raw_key"]}


def test_authenticated_key_traffic_does_not_consume_the_source_bucket(
    owner: TestClient,
) -> None:
    """A valid key must not be throttled by a bucket keyed on the caller's address.

    In the container deployment every request reaches the API through the web
    service's rewrite, and Next.js does not forward the client's address, so the
    source is the same value for every caller. Counting authenticated requests
    against that made one shared bucket: an agent polling in a loop exhausted the
    installation's allowance and the operator's own browser then got 429.

    Three keys are used deliberately. 220 each is past the 600 per-source
    allowance in total, but under the 300 per-key allowance individually, so this
    distinguishes the two limits: if authenticated traffic still counted against
    the source, requests past 600 would fail; with the per-key bucket doing the
    bounding, all 660 succeed.
    """
    project = owner.post("/api/v1/projects", json={"name": "Shared", "slug": "shared"}).json()
    keys = [_key_for(owner, project) for _ in range(3)]

    for _, headers in keys:
        for _ in range(220):
            assert owner.get("/api/v1/projects", headers=headers).status_code == 200

    # And a fourth key minted afterwards is unaffected, which is the property that
    # was actually lost: the allowance had been global rather than per credential.
    _, fresh = _key_for(owner, project)
    assert owner.get("/api/v1/projects", headers=fresh).status_code == 200


def test_a_single_key_is_still_bounded_by_its_own_allowance(owner: TestClient) -> None:
    """Moving the limit must not remove throttling, only relocate it.

    The per-key bucket is what now bounds an authenticated caller. Without this,
    the fix could be read as "authenticated traffic is unlimited".
    """
    project = owner.post("/api/v1/projects", json={"name": "Bounded", "slug": "bounded"}).json()
    _, headers = _key_for(owner, project)

    statuses = {owner.get("/api/v1/projects", headers=headers).status_code for _ in range(400)}
    assert 429 in statuses, "one key must still hit its own ceiling"


def test_invalid_keys_are_still_throttled_per_source(owner: TestClient) -> None:
    """The limit the fix moved has to still protect the lookup it guards.

    An unauthenticated caller can repeat the key lookup freely, so the failure path
    is where the per-source limit belongs. Dropping it entirely would leave that
    lookup unmetered.
    """
    project = owner.post("/api/v1/projects", json={"name": "Metered", "slug": "metered"}).json()
    _, headers = _key_for(owner, project)
    headers["Authorization"] = "Bearer nl_not-a-real-key"

    with session() as db:
        db.execute(text("delete from rate_buckets"))
        db.commit()

    statuses = {owner.get("/api/v1/projects", headers=headers).status_code for _ in range(700)}
    assert 429 in statuses, "repeated invalid keys must eventually be rate limited"


def journey() -> dict:
    return {
        "description": "A user can sign in",
        "steps": "Sign in with an authorized test identity",
        "expected_outcomes": "The overview is visible",
        "evidence_requirements": "Record a sanitized screenshot",
        "execution_type": "manual",
        "owner": "Test Owner",
    }


def test_governance_versions_and_protected_payload(owner: TestClient) -> None:
    project = owner.post("/api/v1/projects", json={"name": "Governed", "slug": "governed"}).json()
    base = f"/api/v1/projects/{project['id']}/governance"
    j = owner.post(base + "/journey", json={"name": "Sign in", "content": journey()}).json()
    assert (
        owner.post(f"{base}/journey/{j['id']}/approve", json={"expected_version": 1}).status_code
        == 200
    )
    assert (
        owner.put(
            f"{base}/journey/{j['id']}",
            json={"name": "Sign in v2", "content": journey(), "expected_version": 0},
        ).status_code
        == 409
    )
    updated = owner.put(
        f"{base}/journey/{j['id']}",
        json={"name": "Sign in v2", "content": journey(), "expected_version": 1},
    ).json()
    assert updated["version"] == 2 and updated["approved_version"] == 1
    canary = new_token()
    protected = owner.post(
        base + "/holdout",
        json={"name": "Private scenario", "content": {**journey(), "steps": canary}},
    )
    assert protected.status_code == 201
    assert canary not in owner.get("/api/v1/audit-log").text
    with session() as db:
        rows = db.scalars(select(GovernanceVersion)).all()
        assert all(canary not in str(row.content) for row in rows)
        user = db.scalar(select(User))
        user.role = "viewer"
        db.commit()
    assert owner.get(base + "/holdout").status_code in (403, 404)


def test_audit_is_append_only(owner: TestClient) -> None:
    with session() as db:
        with pytest.raises(DBAPIError):
            db.execute(text("UPDATE audit_events SET outcome='changed'"))
        db.rollback()


def test_request_errors_do_not_echo_password(owner: TestClient) -> None:
    canary = new_token()
    response = owner.post("/api/v1/auth/login", json={"email": "invalid", "password": canary})
    assert response.status_code == 422
    assert canary not in response.text


def test_unknown_project_is_not_visible(owner: TestClient) -> None:
    assert owner.get(f"/api/v1/projects/{uuid4()}").status_code == 404


def test_first_account_needs_no_token(client: TestClient) -> None:
    """A fresh installation must be usable without a secret nobody has been told about."""
    payload = {
        "name": "Owner",
        "organization": "Tokenless",
        "email": "owner@example.com",
        "password": new_token(),
    }
    created = client.post("/api/v1/auth/setup", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "owner"
    # Setup must still close permanently behind the first account.
    assert (
        client.post(
            "/api/v1/auth/setup", json={**payload, "email": "second@example.com"}
        ).status_code
        == 409
    )


def test_setup_token_is_enforced_when_required(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NACHTLABS_SETUP_TOKEN_REQUIRED", "true")
    get_settings.cache_clear()
    payload = {
        "name": "Owner",
        "organization": "Guarded",
        "email": "owner@example.com",
        "password": new_token(),
    }
    try:
        missing = client.post("/api/v1/auth/setup", json=payload)
        assert missing.status_code == 403
        assert missing.json()["error"]["code"] == "invalid_setup_token"
        wrong = client.post(
            "/api/v1/auth/setup", json={**payload, "bootstrap_token": "not-the-token"}
        )
        assert wrong.status_code == 403
        accepted = client.post(
            "/api/v1/auth/setup",
            json={
                **payload,
                "bootstrap_token": get_settings().bootstrap_token_file.read_text(),
            },
        )
        assert accepted.status_code == 201, accepted.text
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_setup_closes_permanently_and_defaults_descriptive_fields(
    client: TestClient,
) -> None:
    """A first run must need only an email and a password, and only once."""
    created = client.post(
        "/api/v1/auth/setup",
        json={"email": "owner@example.com", "password": new_token()},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "owner"
    # Descriptive fields are optional and default server-side.
    with session() as db:
        org = db.scalar(select(Organization).where(Organization.name == "NachtLabs"))
        assert org is not None
    # A second account can never be created this way, whatever the payload.
    for body in (
        {"email": "second@example.com", "password": new_token()},
        {"email": "third@example.com", "password": new_token(), "organization": "Other"},
    ):
        assert client.post("/api/v1/auth/setup", json=body).status_code == 409
    # An unknown field is still rejected: the confirmation must never be sent.
    rejected = client.post(
        "/api/v1/auth/setup",
        json={"email": "fourth@example.com", "password": new_token(), "password_confirm": "x"},
    )
    assert rejected.status_code == 422


def test_preflight_reports_origin_mismatch(client: TestClient) -> None:
    """The diagnostic an operator runs when a form looks dead must be honest.

    A GET never reaches browser_origin, so this is the only way to learn whether
    a mutating request from the browser would be accepted, without creating an
    account to find out.
    """
    expected = get_settings().public_url
    accepted = client.get("/api/v1/auth/preflight", headers={"Origin": expected}).json()
    assert accepted["origin_accepted"] is True
    assert accepted["expected"] == expected
    assert accepted["origin"] == expected
    assert accepted["hint"] is None
    assert "initialized" in accepted
    assert "setup_token_required" in accepted

    refused = client.get(
        "/api/v1/auth/preflight", headers={"Origin": "https://not-this-host.invalid"}
    ).json()
    assert refused["origin_accepted"] is False
    assert refused["origin"] == "https://not-this-host.invalid"
    assert refused["expected"] == expected
    assert refused["hint"]

    # A same-origin POST with an empty body is rejected by validation, which is
    # why an empty-body probe cannot detect an origin problem.
    assert client.post("/api/v1/auth/setup", json={}).status_code == 422
