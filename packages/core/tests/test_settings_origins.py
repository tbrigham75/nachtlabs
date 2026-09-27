"""Permitted browser origins: parsing, validation and the cookie decision.

The origin check is a CSRF control, so these pin the properties that keep it one:
exact membership only, every entry an operator decision, and an installation
that is permitted but unreachable, or reachable on two schemes of one host,
refused at startup rather than discovered later as a puzzling failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from nachtlabs.settings import Settings
from pydantic import ValidationError


def build(tmp_path: Path, **overrides: object) -> Settings:
    """Settings without a database, which no origin test needs."""
    base: dict[str, object] = {
        "env": "development",
        "public_url": "http://localhost:3000",
        "allowed_hosts": "localhost,127.0.0.1",
        "database_url_file": tmp_path / "db",
        "master_key_file": tmp_path / "key",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_an_empty_list_behaves_exactly_as_before(tmp_path: Path) -> None:
    settings = build(tmp_path)
    assert settings.permitted_origins == ("http://localhost:3000",)
    assert settings.secure_cookies is False


def test_extra_origins_are_ordered_deduped_and_normalised(tmp_path: Path) -> None:
    settings = build(
        tmp_path,
        allowed_hosts="localhost,nacht.lan,192.168.1.10",
        allowed_origins=" https://nacht.lan/ , https://nacht.lan ,http://192.168.1.10:3000 ",
    )
    # public_url stays first because it is the canonical origin, still used for
    # the identity and delivery links in email.
    assert settings.permitted_origins == (
        "http://localhost:3000",
        "https://nacht.lan",
        "http://192.168.1.10:3000",
    )
    # A trailing slash on one entry must not create a second, unreachable one.
    assert len(set(settings.permitted_origins)) == 3


def test_every_https_origin_keeps_the_cookie_secure(tmp_path: Path) -> None:
    settings = build(
        tmp_path,
        env="production",
        public_url="https://nacht.lan",
        allowed_hosts="nacht.lan,lab.lan",
        allowed_origins="https://lab.lan",
    )
    assert settings.secure_cookies is True


def test_one_plain_http_origin_costs_the_secure_attribute(tmp_path: Path) -> None:
    # A Secure cookie is never sent over HTTP, so marking it while any
    # permitted origin is HTTP would lock the operator out of that origin.
    settings = build(
        tmp_path,
        allowed_hosts="localhost,nacht.lan",
        allowed_origins="https://nacht.lan",
    )
    assert settings.secure_cookies is False


@pytest.mark.parametrize(
    "bad",
    [
        "nacht.lan",  # not absolute
        "ftp://nacht.lan",  # not http(s)
        "https://user:pw@nacht.lan",  # credentials
        "https://nacht.lan/console",  # path
        "https://nacht.lan/?a=1",  # query
        "https://nacht.lan/#x",  # fragment
    ],
)
def test_malformed_entries_are_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValidationError):
        build(tmp_path, allowed_hosts="localhost,nacht.lan", allowed_origins=bad)


def test_production_refuses_any_plain_http_origin(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        build(
            tmp_path,
            env="production",
            public_url="https://nacht.lan",
            allowed_hosts="nacht.lan,lab.lan",
            allowed_origins="http://lab.lan",
        )


def test_production_still_refuses_the_placeholder_host(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        build(tmp_path, env="production", allowed_hosts="nachtlabs.example.invalid")


def test_a_permitted_origin_must_be_a_permitted_host(tmp_path: Path) -> None:
    # Otherwise the origin passes the Origin check and then TrustedHost
    # middleware rejects the request, which is a baffling 400 much later.
    with pytest.raises(ValidationError):
        build(tmp_path, allowed_origins="https://nacht.lan")


def test_one_host_may_not_be_permitted_on_two_schemes(tmp_path: Path) -> None:
    # Cookie shadowing: a Secure cookie set on 443 is never sent on 80, while a
    # non-Secure one is sent on both, so the pair behaves unpredictably.
    with pytest.raises(ValidationError):
        build(
            tmp_path,
            allowed_hosts="localhost,nacht.lan",
            allowed_origins="https://nacht.lan,http://nacht.lan",
        )


def test_the_same_host_on_two_ports_is_allowed(tmp_path: Path) -> None:
    # Different ports are the case the Origin check exists for, and they do not
    # collide in the cookie jar, which is scoped by host and not by port.
    settings = build(
        tmp_path,
        allowed_hosts="localhost,127.0.0.1",
        allowed_origins="http://127.0.0.1:3000",
    )
    assert settings.permitted_origins == (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )
