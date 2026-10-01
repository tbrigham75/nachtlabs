import base64
import hashlib
import hmac
import json
import secrets
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from nachtlabs.settings import get_settings

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def password_matches(encoded: str, password: str) -> bool:
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def token_matches(raw: str, encoded: str) -> bool:
    return hmac.compare_digest(digest(raw), encoded)


def decode_key(encoded: str) -> bytes:
    key = base64.b64decode(encoded.strip(), validate=True)
    if len(key) != 32:
        raise ValueError("Master key must contain 32 base64-encoded bytes")
    return key


def encryption_keys() -> dict[str, bytes]:
    settings = get_settings()
    previous = (
        json.loads(settings.previous_master_keys_file.read_text())
        if settings.previous_master_keys_file
        else {}
    )
    keys = {key_id: decode_key(value) for key_id, value in previous.items()}
    keys[settings.master_key_id] = decode_key(settings.master_key_file.read_text())
    return keys


def encrypt_with_key(value: dict[str, Any], context: str, key_id: str, key: bytes) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, json.dumps(value).encode(), context.encode())
    return key_id + ":" + base64.b64encode(nonce + ciphertext).decode()


def encrypt(value: dict[str, Any], context: str) -> str:
    settings = get_settings()
    return encrypt_with_key(
        value, context, settings.master_key_id, encryption_keys()[settings.master_key_id]
    )


def decrypt(value: str, context: str) -> dict[str, Any]:
    key_id, encoded = value.split(":", 1)
    key = encryption_keys().get(key_id)
    if key is None:
        raise ValueError("Unknown encryption key version")
    payload = base64.b64decode(encoded, validate=True)
    result: dict[str, Any] = json.loads(
        AESGCM(key).decrypt(payload[:12], payload[12:], context.encode())
    )
    return result


def redact(value: Any) -> Any:
    """Defense in depth; callers must use explicit safe metadata, never request bodies."""
    if isinstance(value, dict):
        return {
            str(k): "[redacted]"
            if any(
                word in str(k).lower()
                for word in ("password", "secret", "token", "cookie", "authorization", "holdout")
            )
            else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return value.replace("\n", " ").replace("\r", " ")[:1000]
    return value


# --- Executor channel signature (worker -> executor over the shared Postgres
# queue). The signature proves the job row was enqueued by the trusted worker
# and not forged / replayed. Key is derived from NACHTLABS_EXECUTOR_CHANNEL_KEY
# (base64 32 bytes) or the pre-baked key in the shared keyring. Disabled when
# the setting is absent -- tests can assert both the active and the disabled
# path without changing production behaviour.


def executor_sign(specification: dict[str, Any], key: bytes) -> str:
    """Signed payload over the stable serialization of a job specification.

    Deterministic: dict keys are sorted, JSON separators are fixed. Any change
    to the spec (including nested policy objects, candidate digest, attempt,
    stage, or run_id) changes the signature. The ``channel_signature`` field
    itself is excluded from the signed body (a signature cannot sign its own
    field), so signing the spec and signing spec-minus-signature are identical.
    """
    body: dict[str, Any] = {k: v for k, v in specification.items() if k != "channel_signature"}
    message = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def executor_verify(specification: dict[str, Any], signature: str, key: bytes) -> bool:
    """Constant-time compare of the stored signature against a fresh one."""
    expected = executor_sign(specification, key)
    return hmac.compare_digest(expected.encode(), signature.encode())


def _executor_channel_key() -> bytes | None:
    settings = get_settings()
    path = settings.executor_channel_key_file
    if path is None:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    raw = p.read_bytes().strip()
    return base64.b64decode(raw, validate=True) if raw else None


def executor_sign_spec(specification: dict[str, Any]) -> str | None:
    """Sign a job specification with the channel key, or None if no key is set."""
    key = _executor_channel_key()
    return executor_sign(specification, key) if key else None


def executor_verify_spec(specification: dict[str, Any], signature: str | None) -> bool:
    """Verify a job-row signature. When the channel key is unset the check is
    skipped (return True) so the disabled path is observable and testable."""
    if signature is None:
        return True
    key = _executor_channel_key()
    if key is None:
        return False
    return executor_verify(specification, signature, key)
