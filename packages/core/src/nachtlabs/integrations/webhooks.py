"""Raw-body verification primitives. No public webhook intake or workflow dispatch in M4."""
import hashlib
import hmac
import re

from nachtlabs.integrations.contracts import ProviderError


def verify_signature(provider: str, body: bytes, signature: str, secret: str) -> None:
    if not secret or len(body) > 131072:
        raise ProviderError("webhook_rejected")
    if provider == "github":
        if not signature.startswith("sha256="):
            raise ProviderError("webhook_rejected")
        signature = signature[7:]
    elif provider != "gitea":
        raise ProviderError("unsupported_provider")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", signature):
        raise ProviderError("webhook_rejected")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.lower(), expected):
        raise ProviderError("webhook_rejected")


def delivery_fingerprint(connection_id: str, delivery_id: str, body: bytes) -> tuple[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", delivery_id):
        raise ProviderError("webhook_rejected")
    # Future intake must UNIQUE the first key and reject same-ID/different-body reuse.
    return hashlib.sha256(f"{connection_id}:{delivery_id}".encode()).hexdigest(), hashlib.sha256(body).hexdigest()
