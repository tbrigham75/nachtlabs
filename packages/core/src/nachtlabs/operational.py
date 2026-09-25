"""Safe durable system events; no journald scraping or raw exception persistence."""
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, select, text

from nachtlabs.database import session
from nachtlabs.factory_models import Incident, IncidentEvent, Notification, OperationalEvent, RetentionPolicy
from nachtlabs.models import IntegrationConnection, IntegrationProbe, MailJob, Organization, User, now
from nachtlabs.security import encrypt
from nachtlabs.workflows.policy import fingerprint


def operational_tick() -> None:
    with session() as db:
        if not db.scalar(text("SELECT pg_try_advisory_xact_lock(9182712)")):
            return
        for org in db.scalars(select(Organization)):
            retention = db.get(RetentionPolicy, org.id)
            cutoff = now() - timedelta(days=retention.log_days if retention else 30)
            db.execute(delete(OperationalEvent).where(OperationalEvent.org_id == org.id, OperationalEvent.created_at < cutoff))
            key = "worker:" + str(org.id) + ":" + str(int(now().timestamp()) // 300)
            if db.scalar(select(OperationalEvent.id).where(OperationalEvent.event_key == key)) is None:
                db.add(OperationalEvent(org_id=org.id, event_key=key, service="worker", category="worker.heartbeat", details={}))
            probes = db.execute(select(IntegrationProbe, IntegrationConnection).join(IntegrationConnection)
                                .where(IntegrationConnection.org_id == org.id, IntegrationProbe.state.in_(["succeeded", "failed"]),
                                       IntegrationProbe.finished_at >= cutoff)
                                .order_by(IntegrationProbe.finished_at.desc()).limit(100)).all()
            for probe, connection in probes:
                key = "probe:" + str(probe.id)
                if db.scalar(select(OperationalEvent.id).where(OperationalEvent.event_key == key)):
                    continue
                db.add(OperationalEvent(org_id=org.id, event_key=key, service="integration",
                       category="probe." + probe.state, severity="warning" if probe.state == "failed" else "info",
                       details={"probe_id": str(probe.id), "connection_id": str(connection.id),
                                "code": probe.error_code, "duration_ms": probe.duration_ms}))
                if probe.state != "failed":
                    continue
                fingerprint_value = fingerprint({"connection": str(connection.id), "code": probe.error_code})
                value = db.scalar(select(Incident).where(Incident.org_id == org.id, Incident.fingerprint == fingerprint_value).with_for_update())
                if value:
                    value.occurrences += 1
                    value.last_seen = now()
                    value.version += 1
                    value.evidence_refs = [*value.evidence_refs[-99:], key]
                    if value.status == "resolved":
                        value.status = "open"
                    db.add(IncidentEvent(incident_id=value.id, actor="monitor", action="recurred", note="Another signed-in operator probe failed"))
                    continue
                value = Incident(org_id=org.id, fingerprint=fingerprint_value, category=("integration_" + (probe.error_code or "unavailable"))[:80],
                                 evidence_refs=[key])
                db.add(value)
                db.flush()
                db.add(IncidentEvent(incident_id=value.id, actor="monitor", action="opened", note="Provider probe failed; inspect the integration configuration"))
                for user in db.scalars(select(User).where(User.org_id == org.id, User.active.is_(True), User.role.in_(["owner", "admin"]))):
                    db.add(Notification(user_id=user.id, incident_id=value.id))
                    identifier = uuid4()
                    db.add(MailJob(id=identifier, payload=encrypt({"recipient": user.email, "subject": "NachtLabs integration needs review",
                           "body": "A provider probe failed. Review incident " + str(value.id) + " in NachtLabs."}, f"mail:{identifier}")))
        db.commit()
