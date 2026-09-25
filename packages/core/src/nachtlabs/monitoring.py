"""Deterministic incident detection and narrowly scoped, human-approved recommendations."""
from uuid import uuid4

from sqlalchemy import select, text

from nachtlabs.database import session
from nachtlabs.factory_models import Incident, IncidentEvent, Notification, ProjectPolicy, Recommendation, Run
from nachtlabs.models import MailJob, Project, User, now
from nachtlabs.security import encrypt
from nachtlabs.workflows.policy import fingerprint


def monitoring_tick() -> None:
    with session() as db:
        if not db.scalar(text("SELECT pg_try_advisory_xact_lock(9182711)")):
            return
        runs = db.scalars(select(Run).where(Run.state.in_(["blocked", "human_review", "delivery_uncertain"]))
                          .order_by(Run.updated_at.desc()).limit(200))
        for run in runs:
            project = db.get(Project, run.project_id)
            category = run.error_code or "human_review"
            key = fingerprint({"run": str(run.id), "category": category})
            reference = str(run.id) + ":" + str(run.version)
            incident = db.scalar(select(Incident).where(Incident.org_id == project.org_id, Incident.fingerprint == key).with_for_update())
            if incident and reference in incident.evidence_refs:
                continue
            if incident is None:
                incident = Incident(org_id=project.org_id, project_id=project.id, fingerprint=key,
                                    category=category, evidence_refs=[reference])
                db.add(incident)
                db.flush()
                db.add(IncidentEvent(incident_id=incident.id, actor="monitor", action="opened", note="Run needs human review"))
                # Only admins receive org operational mail; project data is excluded.
                for user in db.scalars(select(User).where(User.org_id == project.org_id, User.active.is_(True), User.role.in_(["owner", "admin"]))):
                    db.add(Notification(user_id=user.id, incident_id=incident.id))
                    identifier = uuid4()
                    db.add(MailJob(id=identifier, payload=encrypt({"recipient": user.email,
                           "subject": "NachtLabs incident needs review",
                           "body": "An operational incident needs review. Sign in to NachtLabs and open Monitoring. Incident: " + str(incident.id)},
                           f"mail:{identifier}")))
                if category == "execution_timeout":
                    policy = db.get(ProjectPolicy, project.id)
                    if policy:
                        before = policy.configuration.get("timeout_seconds", 600)
                        after = min(3600, before + 300)
                        if before != after:
                            proposal = {"project_id": str(project.id), "policy_version": policy.version,
                                        "field": "timeout_seconds", "before": before, "after": after,
                                        "reason": "A recorded timeout may justify a bounded increase after resource review."}
                            db.add(Recommendation(incident_id=incident.id, proposal=proposal, proposal_hash=fingerprint(proposal)))
            else:
                incident.evidence_refs = [*incident.evidence_refs[-99:], reference]
                incident.occurrences += 1
                incident.last_seen = now()
                incident.version += 1
                if incident.status == "resolved":
                    incident.status = "open"
                db.add(IncidentEvent(incident_id=incident.id, actor="monitor", action="recurred", note="A new run transition repeated this condition"))
        db.commit()
