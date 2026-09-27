"""Permitted origins over HTTP: both checks, both error codes, and the cookie.

The same refusal is reported as "origin" before authentication and "csrf" after
it, and the pre-authentication route and the authenticated one are separate code
paths. Pinning both keeps a future refactor from quietly narrowing the check to
one of them.
"""

import os

import pytest
from fastapi.testclient import TestClient
from nachtlabs.settings import get_settings
from nachtlabs_api.main import create_app

pytestmark = pytest.mark.integration

ACCEPTED = "http://testserver"


def widen(monkeypatch: pytest.MonkeyPatch, origins: str, hosts: str) -> None:
    """Set the permitted origins and rebuild Settings from the environment.

    Clearing the cache makes the next request construct Settings afresh, so the
    required credential paths have to be present in the environment at that
    moment; the fixture set them, and this carries them across the clear.
    """
    monkeypatch.setenv("NACHTLABS_DATABASE_URL_FILE", os.environ["NACHTLABS_DATABASE_URL_FILE"])
    monkeypatch.setenv("NACHTLABS_MASTER_KEY_FILE", os.environ["NACHTLABS_MASTER_KEY_FILE"])
    monkeypatch.setenv("NACHTLABS_ALLOWED_ORIGINS", origins)
    monkeypatch.setenv("NACHTLABS_ALLOWED_HOSTS", hosts)
    get_settings.cache_clear()


def test_setup_refuses_an_unpermitted_origin(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/setup",
        headers={"Origin": "https://not-permitted.invalid"},
        json={"email": "a@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin"
    assert "origin is not permitted" in response.json()["error"]["message"]


def test_authenticated_mutation_refuses_an_unpermitted_origin(
    owner: TestClient,
) -> None:
    # The same refusal on an authenticated route, which is reported as "csrf"
    # because the CSRF guard and the origin guard share that path. A caller
    # matching on "origin" alone would miss this entirely.
    owner.headers["Origin"] = "https://not-permitted.invalid"
    response = owner.post(
        "/api/v1/integrations",
        json={
            "name": "Blocked",
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "pinned_addresses": ["127.0.0.1"],
            "allow_private": True,
            "allow_http": True,
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf"
    assert "origin is not permitted" in response.json()["error"]["message"]


def test_preflight_reports_the_whole_permitted_set(client: TestClient) -> None:
    body = client.get("/api/v1/auth/preflight", headers={"Origin": ACCEPTED}).json()
    assert body["origin_accepted"] is True
    assert body["allowed"] == [ACCEPTED]
    assert body["expected"] == ACCEPTED
    # The fixture runs plain HTTP, so the cookie cannot be Secure.
    assert body["secure_cookies"] is False


def test_preflight_names_the_fix_when_refused(client: TestClient) -> None:
    body = client.get(
        "/api/v1/auth/preflight",
        headers={"Origin": "https://wrong.invalid"},
    ).json()
    assert body["origin_accepted"] is False
    # "must match exactly" was only ever true while there was one origin.
    assert "ALLOWED_ORIGINS" in body["hint"]
    assert ACCEPTED in body["hint"]


def test_a_request_with_no_origin_header_is_never_permitted(
    client: TestClient,
) -> None:
    # Every browser sends Origin on a cross-origin or non-GET request, so a
    # mutating call arriving without one is not something to serve. The shared
    # client fixture always sets one, so absence needs a client of its own. The
    # fixture is still requested for the credential environment it installs.
    with TestClient(create_app()) as bare:
        body = bare.get("/api/v1/auth/preflight").json()
        assert body["origin"] is None
        assert body["origin_accepted"] is False
        response = bare.post(
            "/api/v1/auth/setup",
            json={"email": "b@example.com", "password": "correct-horse-battery"},
        )
        assert response.status_code == 403


def test_a_second_permitted_origin_is_accepted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    widen(
        monkeypatch,
        "https://nacht.lan,https://lab.lan",
        "nacht.lan,lab.lan",
    )
    monkeypatch.setenv("NACHTLABS_PUBLIC_URL", "https://nacht.lan")
    get_settings.cache_clear()
    try:
        for origin in ("https://nacht.lan", "https://lab.lan"):
            accepted = client.get("/api/v1/auth/preflight", headers={"Origin": origin}).json()
            assert accepted["origin_accepted"] is True, origin
            assert origin in accepted["allowed"]
        # An unlisted origin is still refused: the list widens, it does not open.
        refused = client.get(
            "/api/v1/auth/preflight", headers={"Origin": "https://evil.invalid"}
        ).json()
        assert refused["origin_accepted"] is False
        # Every origin is HTTPS now, so the cookie keeps the Secure attribute.
        assert client.get("/api/v1/auth/preflight").json()["secure_cookies"] is True
    finally:
        monkeypatch.undo()


def test_the_session_cookie_is_secure_only_when_every_origin_is(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    widen(
        monkeypatch,
        "https://nacht.lan,http://lab.lan:3000",
        "testserver,nacht.lan,lab.lan",
    )
    try:
        response = client.post(
            "/api/v1/auth/setup",
            headers={"Origin": ACCEPTED},
            json={
                "email": "owner@example.com",
                "name": "Owner",
                "organization": "Origin Test",
                "password": "correct-horse-battery",
            },
        )
        assert response.status_code == 201, response.text
        assert "nachtlabs_session=" in response.headers.get("set-cookie", "")
        # One permitted origin is plain HTTP, so Secure would lock that origin out.
        assert "Secure" not in response.headers.get("set-cookie", "")
        assert get_settings().secure_cookies is False
    finally:
        monkeypatch.undo()


def test_the_session_cookie_is_secure_when_all_origins_are_https(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fixture's public_url is plain HTTP, so it moves too; otherwise one
    # plain-HTTP entry is always present and the assertion is meaningless.
    widen(monkeypatch, "https://lab.lan", "nacht.lan,lab.lan")
    monkeypatch.setenv("NACHTLABS_PUBLIC_URL", "https://nacht.lan")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/v1/auth/setup",
            headers={"Origin": "https://nacht.lan"},
            json={
                "email": "owner@example.com",
                "name": "Owner",
                "organization": "Secure Test",
                "password": "correct-horse-battery",
            },
        )
        assert response.status_code == 201, response.text
        assert "Secure" in response.headers.get("set-cookie", "")
        assert get_settings().secure_cookies is True
    finally:
        monkeypatch.undo()


def test_a_refused_setup_creates_nothing(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/setup",
        headers={"Origin": "https://not-permitted.invalid"},
        json={"email": "c@example.com", "password": "correct-horse-battery"},
    )
    # Still uninitialized, so the refusal happened before any write.
    assert client.get("/api/v1/auth/setup-status").json() == {"initialized": False}
