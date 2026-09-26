"""Durable workflow boundaries. No agent, network or target Git execution."""

from uuid import UUID

import pytest
from nachtlabs.database import session
from nachtlabs.factory_models import Run, RunApproval, WorkRequest
from nachtlabs.models import User
from nachtlabs.workflows.state import approval_digest
from sqlalchemy import select

pytestmark = pytest.mark.integration


def governed(owner):
    project = owner.post("/api/v1/projects", json={"name": "Factory", "slug": "factory"}).json()
    base = "/api/v1/projects/" + project["id"] + "/governance"
    content = {
        "description": "Observe the greeting",
        "steps": "Read the document",
        "expected_outcomes": "Correct greeting",
        "evidence_requirements": "Record the exact candidate",
        "execution_type": "manual",
        "owner": "Fixture",
    }
    journey = owner.post(base + "/journey", json={"name": "Greeting", "content": content}).json()
    assert (
        owner.post(
            base + "/journey/" + journey["id"] + "/approve", json={"expected_version": 1}
        ).status_code
        == 200
    )
    mission = {
        key: "Synthetic fixture only"
        for key in [
            "purpose",
            "intended_users",
            "outcomes",
            "scope",
            "non_goals",
            "technical_constraints",
            "security_constraints",
            "escalation",
            "unacceptable_changes",
        ]
    }
    mission["required_journey_ids"] = [journey["id"]]
    document = owner.post(
        base + "/mission", json={"name": "Fixture Mission", "content": mission}
    ).json()
    assert (
        owner.post(
            base + "/mission/" + document["id"] + "/approve", json={"expected_version": 1}
        ).status_code
        == 200
    )
    return project


def intake(owner, project, key="fixture-idempotency", **changes):
    body = {
        "project_id": project["id"],
        "title": "Write greeting",
        "description": "Write the synthetic greeting document.",
        "acceptance_criteria": ["Greeting matches"],
        **changes,
    }
    return owner.post("/api/v1/work-requests", json=body, headers={"Idempotency-Key": key})


def test_intake_replay_and_conflict(owner):
    project = governed(owner)
    first = intake(owner, project)
    assert first.status_code == 201, first.text
    second = intake(owner, project)
    assert second.json()["run"]["id"] == first.json()["run"]["id"]
    assert intake(owner, project, title="Different work").status_code == 409
    with session() as db:
        assert len(list(db.scalars(select(WorkRequest)))) == 1


def test_missing_mission_never_queues_run(owner):
    project = owner.post("/api/v1/projects", json={"name": "No baseline", "slug": "missing"}).json()
    assert intake(owner, project).status_code == 409
    with session() as db:
        assert db.scalar(select(Run)) is None


def test_changed_policy_invalidates_approval(owner):
    project = governed(owner)
    value = intake(owner, project).json()["run"]
    with session() as db:
        run = db.get(Run, UUID(value["id"]))
        run.plan = {"origin": "test-fixture", "summary": "A reviewed fixture"}
        run.plan_digest = approval_digest(run)
        run.state = "awaiting_approval"
        digest = run.plan_digest
        db.commit()
    response = owner.put(
        "/api/v1/projects/" + project["id"] + "/execution-policy",
        json={"expected_version": 0, "configuration": {"allowed_paths": ["docs/"]}},
    )
    assert response.status_code == 200
    response = owner.post(
        "/api/v1/runs/" + value["id"] + "/approval",
        json={
            "expected_version": value["version"],
            "digest": digest,
            "decision": "approve",
            "reason": "Reviewed",
        },
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "stale_governance"
    with session() as db:
        assert db.scalar(select(RunApproval)) is None


def test_viewer_cannot_intake_or_stop_factory(owner):
    project = governed(owner)
    with session() as db:
        user = db.scalar(select(User))
        user.role = "viewer"
        db.commit()
    assert intake(owner, project).status_code in {403, 404}
    assert (
        owner.put(
            "/api/v1/factory-control", json={"expected_version": 0, "emergency_stop": True}
        ).status_code
        == 403
    )


def test_cancel_is_version_fenced(owner):
    project = governed(owner)
    run = intake(owner, project).json()["run"]
    path = "/api/v1/runs/" + run["id"] + "/cancel"
    assert (
        owner.post(
            path, json={"expected_version": run["version"] + 1, "reason": "stale"}
        ).status_code
        == 409
    )
    result = owner.post(
        path, json={"expected_version": run["version"], "reason": "Operator cancelled"}
    )
    assert result.status_code == 200 and result.json()["state"] == "cancelled"
