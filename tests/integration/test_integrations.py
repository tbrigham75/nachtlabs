import pytest
from fastapi.testclient import TestClient
from nachtlabs.database import session
from nachtlabs.models import IntegrationConnection, IntegrationProbe, User
from nachtlabs.security import decrypt, new_token
from sqlalchemy import select

pytestmark = pytest.mark.integration


def connection(owner: TestClient) -> dict:
    response = owner.post(
        "/api/v1/integrations",
        json={
            "name": "Isolated Ollama",
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "pinned_addresses": ["127.0.0.1"],
            "allow_private": True,
            "allow_http": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_credentials_never_read_back_and_destination_change_clears(owner: TestClient) -> None:
    item = connection(owner)
    canary = new_token()
    response = owner.put(
        f"/api/v1/integrations/{item['id']}/credential",
        json={"token": canary, "expected_version": item["version"]},
    )
    assert response.status_code == 200 and canary not in response.text
    updated = response.json()
    assert canary not in owner.get("/api/v1/integrations").text
    assert canary not in owner.get("/api/v1/audit-log").text
    with session() as db:
        value = db.scalar(select(IntegrationConnection))
        assert value is not None and value.credential is not None
        assert canary not in value.credential
        assert decrypt(value.credential, f"integration:{value.id}")["token"] == canary
    changed = owner.put(
        f"/api/v1/integrations/{item['id']}",
        json={
            "name": item["name"],
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11435",
            "pinned_addresses": ["127.0.0.1"],
            "allow_private": True,
            "allow_http": True,
            "expected_version": updated["version"],
        },
    )
    assert changed.status_code == 200 and changed.json()["credential_present"] is False


def test_disabled_network_cannot_queue_probe(owner: TestClient) -> None:
    item = connection(owner)
    response = owner.post(
        f"/api/v1/integrations/{item['id']}/probes", json={"expected_version": item["version"]}
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "network_disabled"
    with session() as db:
        assert db.scalar(select(IntegrationProbe)) is None


def test_non_admin_cannot_read_connection_configuration(owner: TestClient) -> None:
    connection(owner)
    with session() as db:
        user = db.scalar(select(User))
        assert user is not None
        user.role = "viewer"
        db.commit()
    assert owner.get("/api/v1/integrations").status_code == 403
    assert owner.get("/api/v1/agents").status_code == 403
    assert owner.get("/api/v1/model-profiles").status_code == 403


def test_stale_credential_rotation_rejected(owner: TestClient) -> None:
    item = connection(owner)
    path = f"/api/v1/integrations/{item['id']}/credential"
    assert owner.put(path, json={"token": new_token(), "expected_version": 1}).status_code == 200
    assert owner.put(path, json={"token": new_token(), "expected_version": 1}).status_code == 409


def test_archived_project_cannot_approve_governance(owner: TestClient) -> None:
    def journey() -> dict:
        return {
            "description": "Synthetic",
            "steps": "Observe",
            "expected_outcomes": "Visible",
            "evidence_requirements": "Observation",
            "execution_type": "manual",
            "owner": "Fixture",
        }

    project = owner.post(
        "/api/v1/projects", json={"name": "Archive fixture", "slug": "archive-fixture"}
    ).json()
    path = f"/api/v1/projects/{project['id']}"
    document = owner.post(
        path + "/governance/journey", json={"name": "Fixture", "content": journey()}
    ).json()
    assert (
        owner.patch(
            path,
            json={
                "name": project["name"],
                "description": "",
                "archived": True,
                "version": project["version"],
            },
        ).status_code
        == 200
    )
    assert (
        owner.post(
            path + f"/governance/journey/{document['id']}/approve", json={"expected_version": 1}
        ).status_code
        == 409
    )


def test_discovery_queue_uses_injected_transport_and_rejects_duplicate(
    owner: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nachtlabs.integrations.contracts import Discovery, Model
    from nachtlabs.integrations.providers import OllamaAdapter
    from nachtlabs.integrations.service import probe_tick
    from nachtlabs.settings import get_settings

    item = connection(owner)
    get_settings().integration_network_enabled = True
    path = f"/api/v1/integrations/{item['id']}/probes"
    assert owner.post(path, json={"expected_version": item["version"]}).status_code == 202
    assert owner.post(path, json={"expected_version": item["version"]}).status_code == 409
    monkeypatch.setattr(
        OllamaAdapter,
        "discover",
        lambda self, page=1: Discovery(
            "ollama", models=[Model("fixture-model")], provider_version="fixture"
        ),
    )
    probe_tick()
    result = owner.get(path).json()[0]
    assert result["state"] == "succeeded"
    assert result["result"]["models"][0]["name"] == "fixture-model"


def test_configuration_change_discards_running_probe(
    owner: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nachtlabs.integrations.contracts import Discovery
    from nachtlabs.integrations.providers import OllamaAdapter
    from nachtlabs.integrations.service import probe_tick
    from nachtlabs.settings import get_settings

    item = connection(owner)
    get_settings().integration_network_enabled = True
    path = f"/api/v1/integrations/{item['id']}/probes"
    assert owner.post(path, json={"expected_version": item["version"]}).status_code == 202

    def change_during_discovery(self, page=1):
        with session() as db:
            value = db.scalar(select(IntegrationConnection))
            assert value is not None
            value.version += 1
            db.commit()
        return Discovery("must-not-persist")

    monkeypatch.setattr(OllamaAdapter, "discover", change_during_discovery)
    probe_tick()
    result = owner.get(path).json()[0]
    assert result["state"] == "stale" and result["result"] == {}
