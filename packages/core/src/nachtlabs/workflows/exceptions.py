"""One narrow exception: human acceptance of verifier warnings after every hard gate passes."""
from datetime import datetime, timedelta

from sqlalchemy import select

from nachtlabs.access import Principal
from nachtlabs.errors import require
from nachtlabs.factory_models import Evidence, Run
from nachtlabs.models import now
from nachtlabs.workflows.policy import VerifierFinding
from nachtlabs.workflows.state import evidence_payload, event, store_evidence


def warning_finding(db, run: Run) -> Evidence:
    value = db.scalar(select(Evidence).where(Evidence.run_id == run.id, Evidence.candidate == run.candidate,
                      Evidence.kind == "verifier").order_by(Evidence.created_at.desc()).limit(1))
    require(value is not None, 409, "verifier_required", "Independent verifier evidence required")
    finding = VerifierFinding.model_validate(evidence_payload(value)["finding"])
    from nachtlabs.factory_models import WorkRequest
    work = db.get(WorkRequest, run.request_id)
    require(finding.verdict == "pass_with_warnings" and finding.candidate == run.candidate
            and set(finding.criteria) == {str(i + 1) for i in range(len(work.criteria))}
            and all(finding.criteria.values()), 409, "exception_ineligible", "Only warnings with every acceptance criterion satisfied can be accepted")
    return value


def accept_warning(db, actor: Principal, run: Run, reason: str) -> None:
    require(actor.user is not None and actor.user.role == "owner", 403, "owner_required", "Only the Owner can accept verifier warnings")
    require(run.state == "human_review" and run.stage == "verification"
            and run.snapshot["policy"].get("allow_verifier_warning_exception") is True,
            409, "exception_disabled", "This policy does not permit a verifier-warning exception")
    from nachtlabs.workflows.engine import delivery_gate, enforce_approval
    from nachtlabs.workflows.state import current_snapshot
    current_snapshot(db, actor, run)
    enforce_approval(db, run)
    delivery_gate(db, run, require_verifier=False)
    finding = warning_finding(db, run)
    store_evidence(db, run, "verifier-warning-exception", "policy_exception", "approved",
                   {"finding_id": str(finding.id), "reason": reason, "expires_at": (now() + timedelta(hours=1)).isoformat()},
                   actor.actor)
    run.state, run.stage = "queued", "delivery"
    event(db, run, "exception.approved", {"actor": actor.actor, "scope": "verifier_warning"})


def valid_warning_exception(db, run: Run) -> bool:
    if not run.snapshot["policy"].get("allow_verifier_warning_exception"):
        return False
    value = db.scalar(select(Evidence).where(Evidence.run_id == run.id, Evidence.candidate == run.candidate,
                      Evidence.kind == "policy_exception", Evidence.status == "approved").order_by(Evidence.created_at.desc()).limit(1))
    if value is None:
        return False
    finding = warning_finding(db, run)
    payload = evidence_payload(value)
    return payload["finding_id"] == str(finding.id) and datetime.fromisoformat(payload["expires_at"]) > now()
