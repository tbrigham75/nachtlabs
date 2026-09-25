"""Version fences and organization boundaries for operational controls."""
import pytest
from sqlalchemy import select

from nachtlabs.database import session
from nachtlabs.factory_models import Incident, ProjectPolicy, Recommendation
from nachtlabs.models import Project, User
from nachtlabs.workflows.policy import ProjectExecutionPolicy, fingerprint

pytestmark = pytest.mark.integration


def proposal(owner):
    project = owner.post("/api/v1/projects", json={"name": "Recommendation fixture", "slug": "recommendation"}).json()
    from uuid import UUID
    with session() as db:
        value = db.get(Project, UUID(project["id"]))
        db.add(ProjectPolicy(project_id=value.id, version=1, configuration=ProjectExecutionPolicy().model_dump(mode="json")))
        incident = Incident(org_id=value.org_id, project_id=value.id, fingerprint=fingerprint("fixture"), category="execution_timeout")
        db.add(incident)
        db.flush()
        body = {"project_id": str(value.id), "policy_version": 1, "field": "timeout_seconds", "before": 600, "after": 900, "reason": "Recorded fixture timeout"}
        item = Recommendation(incident_id=incident.id, proposal=body, proposal_hash=fingerprint(body))
        db.add(item)
        db.flush()
        identifier = str(item.id)
        db.commit()
    return project["id"], identifier


def test_recommendation_needs_approval_then_refuses_stale_policy(owner):
    project, identifier = proposal(owner)
    recommendation = owner.get("/api/v1/recommendations").json()[0]
    path = "/api/v1/recommendations/" + identifier + "/actions"
    body = {"version": recommendation["version"], "digest": recommendation["digest"], "reason": "Operator reviewed the fixture"}
    assert owner.post(path, json={**body, "action": "apply"}).status_code == 409
    assert owner.post(path, json={**body, "action": "approve"}).status_code == 200
    changed = owner.put("/api/v1/projects/" + project + "/execution-policy", json={"expected_version": 1, "configuration": {"timeout_seconds": 700}})
    assert changed.status_code == 200
    assert owner.post(path, json={**body, "version": 2, "action": "apply"}).status_code == 409
    assert owner.get("/api/v1/projects/" + project + "/execution-policy").json()["configuration"]["timeout_seconds"] == 700


def test_recommendation_rollback_preserves_concurrent_changes(owner):
    project, identifier = proposal(owner)
    item = owner.get("/api/v1/recommendations").json()[0]
    path = "/api/v1/recommendations/" + identifier + "/actions"
    base = {"digest": item["digest"], "reason": "Reviewed fixture"}
    assert owner.post(path, json={**base, "version": 1, "action": "approve"}).status_code == 200
    assert owner.post(path, json={**base, "version": 2, "action": "apply"}).status_code == 200
    assert owner.put("/api/v1/projects/" + project + "/execution-policy", json={"expected_version": 2, "configuration": {"timeout_seconds": 1000}}).status_code == 200
    assert owner.post(path, json={**base, "version": 3, "action": "rollback"}).status_code == 409


def test_viewer_cannot_read_system_logs_or_recommendations(owner):
    with session() as db:
        user = db.scalar(select(User))
        user.role = "viewer"
        db.commit()
    assert owner.get("/api/v1/system-logs").status_code == 403
    assert owner.get("/api/v1/recommendations").status_code == 403
    assert owner.get("/api/v1/retention").status_code == 403
