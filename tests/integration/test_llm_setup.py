"""LLM setup readiness: the derived state the setup wizard renders.

The wizard must never imply more than is true, so these checks pin the four
states apart: a saved connection is not a working one, a discovery is not a
compatibility proof, and execution is never available from configuration.
"""

import pytest
from fastapi.testclient import TestClient
from nachtlabs.settings import get_settings
from nachtlabs_api.main import create_app

pytestmark = pytest.mark.integration


def connection(client: TestClient, name: str = "Local Ollama") -> dict:
    response = client.post(
        "/api/v1/integrations",
        json={
            "name": name,
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "pinned_addresses": ["127.0.0.1"],
            "allow_private": True,
            "allow_http": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def profile(client: TestClient, connection_id: str, role: str, model: str) -> dict:
    response = client.post(
        "/api/v1/model-profiles",
        json={
            "name": role.capitalize(),
            "connection_id": connection_id,
            "model": model,
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_readiness_starts_empty_and_never_claims_execution(owner: TestClient) -> None:
    body = owner.get("/api/v1/llm-readiness").json()
    assert body["connection"] is None
    assert body["connection_count"] == 0
    assert body["discovery"]["state"] == "not_run"
    assert body["discovery"]["models"] == []
    assert body["implementation_profile"] is None
    assert body["verifier_profile"] is None
    assert body["agent"] is None
    assert body["distinct_models"] is False
    assert body["complete"] is False
    # The API cannot observe a root-owned qualification, so it must never imply
    # execution is possible.
    assert body["execution_available"] is False
    # The fixture disables provider egress, and the wizard relies on this being
    # reported rather than guessed.
    assert body["provider_network_enabled"] is False


def test_readiness_requires_a_session(owner: TestClient) -> None:
    assert owner.get("/api/v1/llm-readiness").status_code == 200
    # The owner fixture hands back the same client, so a genuinely anonymous
    # request needs its own app instance with no session cookie.
    with TestClient(create_app(), headers={"Origin": "http://testserver"}) as anonymous:
        assert anonymous.get("/api/v1/llm-readiness").status_code == 401


def test_connection_then_profiles_report_distinctness(owner: TestClient) -> None:
    item = connection(owner)
    body = owner.get("/api/v1/llm-readiness").json()
    assert body["connection"] is not None
    assert body["connection"]["id"] == item["id"]
    # Loopback is detected so the wizard can warn that it cannot serve agents.
    assert body["connection"]["loopback_pinned"] is True
    assert body["connection_count"] == 1
    # A saved endpoint is emphatically not a working one.
    assert body["discovery"]["state"] == "not_run"
    assert body["complete"] is False

    profile(owner, item["id"], "implementation", "qwen3-coder:30b")
    body = owner.get("/api/v1/llm-readiness").json()
    assert body["implementation_profile"]["model"] == "qwen3-coder:30b"
    assert body["verifier_profile"] is None
    # The same model on both sides is not independence.
    assert body["distinct_models"] is False
    assert body["complete"] is False

    # Several profiles per role are legitimate, so a differing verifier anywhere
    # in the set satisfies the rule even though the first one still matches.
    profile(owner, item["id"], "verifier", "qwen3-coder:30b")
    assert owner.get("/api/v1/llm-readiness").json()["distinct_models"] is False
    profile(owner, item["id"], "verifier", "qwen3:8b")
    body = owner.get("/api/v1/llm-readiness").json()
    assert body["distinct_models"] is True
    # Still not complete: no agent, and no current discovery.
    assert body["agent"] is None
    assert body["complete"] is False


def test_agent_binding_completes_the_chain(owner: TestClient) -> None:
    item = connection(owner)
    implementation = profile(owner, item["id"], "implementation", "qwen3-coder:30b")
    profile(owner, item["id"], "verifier", "qwen3:8b")
    agent = owner.post(
        "/api/v1/agents",
        json={
            "name": "Hermes",
            "provider": "hermes",
            "executable": "/usr/local/bin/hermes",
            "expected_agent_version": "1.2.3",
            "model_profile_id": implementation["id"],
            "timeout_seconds": 300,
        },
    )
    assert agent.status_code == 201, agent.text
    body = owner.get("/api/v1/llm-readiness").json()
    assert body["agent"]["provider"] == "hermes"
    assert body["agent"]["executable"] == "/usr/local/bin/hermes"
    # A probe needs the worker and the installation switch, neither of which a
    # test can honestly fake, so completeness must still be refused.
    assert body["discovery"]["state"] != "succeeded"
    assert body["complete"] is False
    assert body["execution_available"] is False


def test_network_switch_is_reported_not_assumed(
    owner: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection(owner)
    monkeypatch.setenv("NACHTLABS_INTEGRATION_NETWORK_ENABLED", "true")
    get_settings.cache_clear()
    try:
        assert get_settings().integration_network_enabled is True
        body = owner.get("/api/v1/llm-readiness").json()
        assert body["provider_network_enabled"] is True
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_readiness_is_scoped_to_the_organization(owner: TestClient) -> None:
    # A second organization must not see the first one's model configuration.
    connection(owner)
    with TestClient(create_app(), headers={"Origin": "http://testserver"}) as other:
        assert other.get("/api/v1/llm-readiness").status_code == 401
