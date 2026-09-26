"""Operator environment loading for host-console scripts."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from nachtlabs import operator_env


def write_env(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_override_file_populates_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = write_env(
        tmp_path / "migration.env",
        "NACHTLABS_DATABASE_URL_FILE=/srv/creds/api-db\n"
        "NACHTLABS_MASTER_KEY_FILE=/srv/creds/master-key\n"
        "NACHTLABS_MASTER_KEY_ID=v1\n",
    )
    for name in ("NACHTLABS_DATABASE_URL_FILE", "NACHTLABS_MASTER_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(operator_env.OVERRIDE, str(target))
    assert operator_env.require_operator_env() == str(target)
    import os

    assert os.environ["NACHTLABS_DATABASE_URL_FILE"] == "/srv/creds/api-db"
    assert os.environ["NACHTLABS_MASTER_KEY_ID"] == "v1"


def test_values_are_unquoted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # configure.py writes shlex-quoted values, so 'two words' must survive.
    target = write_env(
        tmp_path / "migration.env",
        "NACHTLABS_DATABASE_URL_FILE='/srv/creds/a b/db'\n"
        'NACHTLABS_PUBLIC_URL="https://host.example"\n'
        "NACHTLABS_EMPTY=\n"
        "# a comment\n"
        "MALFORMED\n"
        "=novalue\n",
    )
    # The loader never overrides an existing variable, so clear each one this
    # test asserts on; otherwise a value inherited from the developer shell wins.
    for name in (
        "NACHTLABS_DATABASE_URL_FILE",
        "NACHTLABS_PUBLIC_URL",
        "NACHTLABS_EMPTY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(operator_env.OVERRIDE, str(target))
    operator_env.require_operator_env()

    assert os.environ["NACHTLABS_DATABASE_URL_FILE"] == "/srv/creds/a b/db"
    assert os.environ["NACHTLABS_PUBLIC_URL"] == "https://host.example"
    assert os.environ["NACHTLABS_EMPTY"] == ""
    assert "MALFORMED" not in os.environ


def test_existing_environment_is_never_overridden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = write_env(tmp_path / "migration.env", "NACHTLABS_DATABASE_URL_FILE=/from/file\n")
    monkeypatch.setenv("NACHTLABS_DATABASE_URL_FILE", "/from/environment")
    monkeypatch.setenv(operator_env.OVERRIDE, str(target))
    assert operator_env.require_operator_env() == "environment"

    assert os.environ["NACHTLABS_DATABASE_URL_FILE"] == "/from/environment"


def test_missing_configuration_explains_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NACHTLABS_DATABASE_URL_FILE", raising=False)
    monkeypatch.setenv(operator_env.OVERRIDE, str(tmp_path / "absent.env"))
    # No candidate exists, so the message must name the real paths and the way out
    # rather than surfacing a pydantic error about database_url_file.
    monkeypatch.setattr(operator_env, "CANDIDATES", (str(tmp_path / "nope.env"),))
    with pytest.raises(SystemExit) as caught:
        operator_env.require_operator_env()
    message = str(caught.value)
    assert "No operator configuration found" in message
    assert operator_env.OVERRIDE in message
    assert "configure.py" in message


def test_load_returns_none_when_already_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NACHTLABS_DATABASE_URL_FILE", "/already/set")
    assert operator_env.load_operator_env() is None
