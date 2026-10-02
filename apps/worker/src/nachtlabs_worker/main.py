import json
import logging
import os
import signal
import smtplib
import ssl
import threading
from datetime import timedelta
from email.message import EmailMessage

from nachtlabs.database import session
from nachtlabs.integrations.service import probe_tick
from nachtlabs.models import (
    IdentityToken,
    LoginChallenge,
    MailJob,
    RateBucket,
    UserSession,
    WorkerHeartbeat,
    now,
)
from nachtlabs.monitoring import monitoring_tick
from nachtlabs.operational import operational_tick
from nachtlabs.security import decrypt
from nachtlabs.settings import get_settings
from nachtlabs.workflows.engine import factory_tick
from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert

stop = threading.Event()
logger = logging.getLogger("nachtlabs.worker")


def send(payload: dict[str, str]) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        raise RuntimeError("SMTPNotConfigured")
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = payload["recipient"]
    message["Subject"] = payload["subject"]
    message.set_content(payload["body"])
    context = ssl.create_default_context()
    connection: smtplib.SMTP
    if settings.smtp_tls_mode == "tls":
        connection = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=15, context=context
        )
    else:
        connection = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
    with connection:
        if settings.smtp_tls_mode == "starttls":
            connection.starttls(context=context)
        if settings.smtp_username:
            password = (
                settings.smtp_password_file.read_text().strip()
                if settings.smtp_password_file
                else ""
            )
            connection.login(settings.smtp_username, password)
        connection.send_message(message)


def tick() -> None:
    settings = get_settings()
    timestamp = now()
    with session() as db:
        heartbeat = insert(WorkerHeartbeat).values(
            name=settings.worker_name, seen_at=timestamp, version="0.1.0"
        )
        db.execute(
            heartbeat.on_conflict_do_update(
                index_elements=[WorkerHeartbeat.name],
                set_={"seen_at": timestamp, "version": "0.1.0"},
            )
        )
        # Bounded identity housekeeping, never governance/audit deletion.
        db.execute(
            delete(UserSession).where(
                or_(UserSession.expires_at < timestamp, UserSession.idle_expires_at < timestamp)
            )
        )
        db.execute(delete(LoginChallenge).where(LoginChallenge.expires_at < timestamp))
        db.execute(
            delete(IdentityToken).where(IdentityToken.expires_at < timestamp - timedelta(days=1))
        )
        db.execute(
            delete(RateBucket).where(RateBucket.window < int(timestamp.timestamp()) // 300 - 12)
        )
        db.execute(
            update(MailJob)
            .where(MailJob.created_at < timestamp - timedelta(days=3), MailJob.payload.is_not(None))
            .values(payload=None, state="failed", last_error="Expired")
        )
        db.execute(
            update(MailJob)
            .where(
                MailJob.state == "sending", MailJob.lease_until < timestamp, MailJob.attempts >= 5
            )
            .values(state="failed", lease_until=None, last_error="RetryExhausted")
        )
        job = db.scalar(
            select(MailJob)
            .where(
                or_(
                    MailJob.state == "pending",
                    (MailJob.state == "sending") & (MailJob.lease_until < timestamp),
                ),
                MailJob.next_attempt_at <= timestamp,
                MailJob.attempts < 5,
                MailJob.payload.is_not(None),
            )
            .order_by(MailJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job:
            job.state = "sending"
            job.attempts += 1
            job.lease_until = timestamp + timedelta(minutes=2)
            job_id, ciphertext, lease, attempts = job.id, job.payload, job.lease_until, job.attempts
        db.commit()
    if not job:
        return
    error = None
    try:
        assert ciphertext is not None
        send(decrypt(ciphertext, f"mail:{job_id}"))
    except Exception as exc:
        error = type(exc).__name__[:80]  # Exception text can contain recipient/credential data.
    with session() as db:
        values = (
            {"state": "sent", "payload": None, "lease_until": None, "last_error": None}
            if error is None
            else {
                "state": "failed" if attempts >= 5 else "pending",
                "last_error": error,
                "next_attempt_at": now() + timedelta(seconds=min(3600, 30 * 2**attempts)),
                "lease_until": None,
            }
        )
        db.execute(
            update(MailJob)
            .where(MailJob.id == job_id, MailJob.lease_until == lease)
            .values(**values)
        )
        db.commit()
    logger.info(
        json.dumps(
            {
                "service": "worker",
                "event": "mail.sent" if error is None else "mail.retry",
                "job_id": str(job_id),
                "error_type": error,
            }
        )
    )


def main() -> None:
    logging.basicConfig(level=get_settings().log_level, format="%(message)s")
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    agent_execution = os.environ.get("NACHTLABS_AGENT_EXECUTION", "0") == "1"
    logger.info(json.dumps({"service": "worker", "event": "started", "agent_execution": agent_execution}))
    while not stop.is_set():
        try:
            tick()
            probe_tick()
            factory_tick()
            monitoring_tick()
            operational_tick()
        except Exception as exc:
            logger.error(
                json.dumps(
                    {"service": "worker", "event": "tick.failed", "error_type": type(exc).__name__}
                )
            )
        stop.wait(5)


if __name__ == "__main__":
    main()
