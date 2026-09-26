import base64
import os
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag
from nachtlabs.security import (
    decrypt,
    digest,
    encrypt,
    hasher,
    new_token,
    password_matches,
    redact,
    token_matches,
)
from nachtlabs.settings import get_settings


def test_password_and_high_entropy_token_verifiers() -> None:
    raw = new_token()
    encoded = hasher.hash(raw)
    assert raw not in encoded
    assert password_matches(encoded, raw)
    assert not password_matches(encoded, new_token())
    assert token_matches(raw, digest(raw))
    assert not token_matches(new_token(), digest(raw))


def test_encryption_is_bound_to_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = tmp_path / "master"
    key.write_text(base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("NACHTLABS_ENV", "test")
    monkeypatch.setenv("NACHTLABS_PUBLIC_URL", "http://localhost")
    monkeypatch.setenv("NACHTLABS_MASTER_KEY_FILE", str(key))
    monkeypatch.setenv("NACHTLABS_DATABASE_URL_FILE", str(tmp_path / "unused"))
    get_settings.cache_clear()
    try:
        raw = new_token()
        payload = encrypt({"value": raw}, "project-one")
        assert raw not in payload
        assert decrypt(payload, "project-one")["value"] == raw
        with pytest.raises(InvalidTag):
            decrypt(payload, "project-two")
    finally:
        get_settings.cache_clear()


def test_structured_redaction_does_not_leak_credentials() -> None:
    canary = new_token()
    result = redact(
        {"nested": [{"authorization": canary}], "password": canary, "message": "line\nbreak"}
    )
    assert canary not in str(result)
    assert result["message"] == "line break"


def test_retained_key_decrypts_old_ciphertext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from nachtlabs.security import encrypt_with_key

    old, active = os.urandom(32), os.urandom(32)
    key = tmp_path / "active"
    key.write_text(base64.b64encode(active).decode())
    retained = tmp_path / "retained"
    retained.write_text(json.dumps({"v1": base64.b64encode(old).decode()}))
    monkeypatch.setenv("NACHTLABS_ENV", "test")
    monkeypatch.setenv("NACHTLABS_PUBLIC_URL", "http://localhost")
    monkeypatch.setenv("NACHTLABS_DATABASE_URL_FILE", str(tmp_path / "unused"))
    monkeypatch.setenv("NACHTLABS_MASTER_KEY_FILE", str(key))
    monkeypatch.setenv("NACHTLABS_MASTER_KEY_ID", "v2")
    monkeypatch.setenv("NACHTLABS_PREVIOUS_MASTER_KEYS_FILE", str(retained))
    get_settings.cache_clear()
    try:
        value = {"value": new_token()}
        previous = encrypt_with_key(value, "record-one", "v1", old)
        assert decrypt(previous, "record-one") == value
        rewritten = encrypt(decrypt(previous, "record-one"), "record-one")
        assert rewritten.startswith("v2:") and decrypt(rewritten, "record-one") == value
    finally:
        get_settings.cache_clear()
