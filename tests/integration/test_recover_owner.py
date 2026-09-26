"""Break-glass Owner recovery, including the first-account bootstrap path.

The console scripts refuse to run as non-root and read the new password from a
terminal, so both are neutralised here to exercise the database logic that
actually matters. ``client`` is requested only for its truncation, so each test
starts from the empty disposable database.
"""

import contextlib
import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from nachtlabs.database import session
from nachtlabs.models import AuditEvent, User
from nachtlabs.security import new_token, password_matches
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "recover-owner.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("recover_owner", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def patch_output(sink: list[str]):
    """Capture stdout so assertions can read what the operator is shown."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        yield
    sink.append(buffer.getvalue())


def run(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    password: str,
) -> None:
    email = argv[argv.index("--email") + 1]
    monkeypatch.setattr("os.geteuid", lambda: 0)
    monkeypatch.setattr("builtins.input", lambda _prompt: email)
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": password)
    monkeypatch.setattr(sys, "argv", ["recover-owner.py", *argv])
    module.main()


def only_user() -> User:
    with session() as db:
        db.scalar(select(User.id).limit(1))
        assert db.scalar(select(func.count()).select_from(User)) == 1
        user = db.scalar(select(User))
        assert user is not None
        db.expunge(user)
        return user


def audit_actions(action: str) -> int:
    with session() as db:
        return db.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)
        )


def test_break_glass_requires_root() -> None:
    module = load()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("os.geteuid", lambda: 1000)
        patch.setattr(sys, "argv", ["recover-owner.py", "--email", "a@b.example", "--reason", "t"])
        with pytest.raises(SystemExit, match="Root console"):
            module.main()


def test_bootstrap_creates_the_first_owner(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    password = new_token()
    run(
        load(),
        monkeypatch,
        [
            "--bootstrap",
            "--email",
            "first@example.com",
            "--reason",
            "setup token lost",
            "--name",
            "First Owner",
            "--organization",
            "Recovered",
        ],
        password,
    )
    user = only_user()
    assert user.email == "first@example.com"
    assert user.name == "First Owner"
    assert user.role == "owner"
    assert user.active is True
    assert password_matches(user.password_hash, password)
    assert audit_actions("identity.owner.bootstrapped") == 1


def test_bootstrap_refuses_when_an_account_exists(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load()
    run(
        module,
        monkeypatch,
        ["--bootstrap", "--email", "first@example.com", "--reason", "initial"],
        new_token(),
    )
    with pytest.raises(SystemExit, match="already exists"):
        run(
            module,
            monkeypatch,
            ["--bootstrap", "--email", "second@example.com", "--reason", "duplicate"],
            new_token(),
        )
    assert only_user().email == "first@example.com"


def test_recovery_resets_a_lost_owner_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load()
    run(
        module,
        monkeypatch,
        ["--bootstrap", "--email", "owner@example.com", "--reason", "initial"],
        new_token(),
    )
    replacement = new_token()
    run(
        module,
        monkeypatch,
        ["--email", "owner@example.com", "--reason", "forgotten", "--reset-password"],
        replacement,
    )
    user = only_user()
    assert password_matches(user.password_hash, replacement)
    assert audit_actions("identity.owner.recovered") == 1


def test_list_accounts_is_read_only_and_reports_the_owner(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without this, an operator who has lost the Owner email has no route in.

    --email is mandatory for recovery and the interface will not disclose account
    addresses to an anonymous visitor, so without --list the host console was the
    only remaining option.
    """
    module = load()
    run(
        module,
        monkeypatch,
        ["--bootstrap", "--email", "owner@example.com", "--reason", "initial"],
        new_token(),
    )
    with session() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1

    seen: list[str] = []

    def fake_getpass(prompt: str = "") -> str:
        raise AssertionError("--list must not prompt for a password")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("os.geteuid", lambda: 0)
        patch.setattr("getpass.getpass", fake_getpass)
        patch.setattr(
            "builtins.input",
            lambda _prompt: (_ for _ in ()).throw(AssertionError("--list must not prompt")),
        )
        patch.setattr(sys, "argv", ["recover-owner.py", "--list"])
        with patch_output(seen):
            assert module.main() == 0

    text = "".join(seen)
    assert "owner@example.com" in text
    assert "owner" in text
    assert "active" in text
    # Read-only: the account is untouched and still usable.
    with session() as db:
        user = db.scalar(select(User).where(User.email == "owner@example.com"))
        assert user is not None and user.active is True and user.role == "owner"
    assert audit_actions("identity.owner.recovered") == 0
    assert audit_actions("identity.owner.bootstrapped") == 1


def test_list_accounts_reports_an_empty_installation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load()
    seen: list[str] = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("os.geteuid", lambda: 0)
        patch.setattr(sys, "argv", ["recover-owner.py", "--list"])
        with patch_output(seen):
            assert module.main() == 0
    text = "".join(seen)
    # Must be actionable rather than merely reporting nothing.
    assert "not completed" in text
    assert "--bootstrap" in text


def test_email_is_required_unless_listing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("os.geteuid", lambda: 0)
        patch.setattr(sys, "argv", ["recover-owner.py", "--reset-password"])
        with pytest.raises(SystemExit) as caught:
            module.main()
    # argparse exits 2 on a usage error.
    assert caught.value.code == 2
    assert "--email is required" in capsys.readouterr().err


def test_list_still_requires_root() -> None:
    module = load()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("os.geteuid", lambda: 1000)
        patch.setattr(sys, "argv", ["recover-owner.py", "--list"])
        with pytest.raises(SystemExit, match="Root console"):
            module.main()
