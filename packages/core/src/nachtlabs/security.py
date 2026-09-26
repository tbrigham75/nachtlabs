import base64
import hashlib
import hmac
import json
import secrets
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
