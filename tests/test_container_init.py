"""The generated configuration: how the egress switches are recorded and changed.

These are the settings that decide whether an installation may reach a model
provider, and they are read from files the host operator cannot see. Two defects
lived here and neither had a test:

  * the switch was hard-coded false while the runbook documented a compose
    variable as the way to set it. compose's `environment:` block is applied
    before with-env.sh sources the generated file, so that variable was silently
    discarded and the documented procedure could not work;
  * compose named no build target, so the last stage in Dockerfile.api was built
    and tagged as the service image. That stage carries no postgresql-client, so
    only the roles step failed, and it failed as "psql: command not found".

The compose assertions below are deliberately structural. They read the file
rather than the running container, because the second defect produced an image
that started cleanly and only failed on one step, which is exactly the kind of
breakage a smoke test passes straight through.
"""

import runpy
import stat as statmod
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

# The module reads NACHTLABS_CONFIG_DIR at import time, so it is loaded once per
# test with the directory already pointed at a tmp_path. Reloading the module per
# test rather than patching ROOT is what makes these tests independent.
CONFIG_FILES = ("api.env", "worker.env", "executor.env", "migration.env", "test-migration.env")


@pytest.fixture
def init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("NACHTLABS_CONFIG_DIR", str(tmp_path))
    for key in (
        "NACHTLABS_INTEGRATION_NETWORK_ENABLED",
        "NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE",
        "NACHTLABS_GIT_PROVIDER_NETWORK_ENABLED",
        "NACHTLABS_INTEGRATION_CA_FILE",
        "NACHTLABS_REWRITE_CONFIG",
        "NACHTLABS_LAN_ORIGIN",
        "NACHTLABS_EXTRA_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)
    return runpy.run_path(str(ROOT / "scripts/container-init.py"))


def values(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


def test_switches_default_to_false(init: dict, tmp_path: Path) -> None:
    """An unset environment must not widen what the installation can reach."""
    init["main"]()
    for name in CONFIG_FILES:
        got = values(tmp_path / name)
        assert got["NACHTLABS_INTEGRATION_NETWORK_ENABLED"] == "false"
        assert got["NACHTLABS_GIT_PROVIDER_NETWORK_ENABLED"] == "false"
        assert got["NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE"] == "false"


def test_explicit_opt_in_is_recorded(init: dict, tmp_path: Path, monkeypatch) -> None:
    """The documented procedure has to actually work, in every generated file."""
    monkeypatch.setenv("NACHTLABS_INTEGRATION_NETWORK_ENABLED", "true")
    monkeypatch.setenv("NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE", "true")
    init["main"]()
    for name in CONFIG_FILES:
        got = values(tmp_path / name)
        assert got["NACHTLABS_INTEGRATION_NETWORK_ENABLED"] == "true"
        assert got["NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE"] == "true"


@pytest.mark.parametrize("bad", ["yes", "1", "TRUE-ish", "", "none"])
def test_a_switch_that_is_not_a_boolean_is_refused(init: dict, monkeypatch, bad: str) -> None:
    """Refused here, where the name can be printed, rather than by pydantic later.

    "TRUE" is accepted: it is a boolean to every reader and a string that would
    otherwise be rejected deep in the settings layer with no path in the message.
    """
    monkeypatch.setenv("NACHTLABS_INTEGRATION_NETWORK_ENABLED", bad)
    if bad.strip().lower() == "true":
        init["main"]()
        return
    with pytest.raises(SystemExit):
        init["main"]()


def test_rewrite_updates_only_the_operator_keys(init: dict, tmp_path: Path, monkeypatch) -> None:
    """A live install changes the switch without losing anything else."""
    monkeypatch.setenv("NACHTLABS_INTEGRATION_NETWORK_ENABLED", "true")
    init["main"]()
    api = tmp_path / "api.env"
    before = values(api)
    # An operator's own edit, which must survive the rewrite untouched.
    api.write_text(api.read_text() + "# a note from the operator\n")

    monkeypatch.setenv("NACHTLABS_INTEGRATION_NETWORK_ENABLED", "false")
    monkeypatch.setenv("NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE", "true")
    monkeypatch.setenv("NACHTLABS_REWRITE_CONFIG", "true")
    init["main"]()

    after = values(api)
    assert after["NACHTLABS_INTEGRATION_NETWORK_ENABLED"] == "false"
    assert after["NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE"] == "true"
    assert "# a note from the operator" in api.read_text()
    # Everything the rewrite is not allowed to reach is byte-identical.
    for key, value in before.items():
        if key in init["OPERATOR_KEYS"]:
            continue
        assert after[key] == value


def test_rewrite_cannot_reach_a_credential(init: dict, tmp_path: Path, monkeypatch) -> None:
    """The allowlist is a list, not a pattern, so a wider dict changes nothing."""
    init["main"]()
    api = tmp_path / "api.env"
    before = api.read_text()
    monkeypatch.setenv("NACHTLABS_REWRITE_CONFIG", "true")
    init["rewrite_env"](
        "api.env",
        {
            "NACHTLABS_MASTER_KEY_FILE": "/etc/nachtlabs/credentials/attacker",
            "NACHTLABS_DATABASE_URL_FILE": "/etc/nachtlabs/credentials/attacker",
            "NACHTLABS_INTEGRATION_NETWORK_ENABLED": "true",
        },
    )
    after = api.read_text()
    assert "attacker" not in after
    assert values(tmp_path / "api.env")["NACHTLABS_INTEGRATION_NETWORK_ENABLED"] == "true"
    assert "attacker" not in before


def test_rewrite_preserves_mode_and_leaves_no_temporary_file(
    init: dict, tmp_path: Path, monkeypatch
) -> None:
    """The service account must keep read access after a rewrite."""
    monkeypatch.setenv("NACHTLABS_INTEGRATION_NETWORK_ENABLED", "true")
    init["main"]()
    api = tmp_path / "api.env"
    assert statmod.S_IMODE(api.stat().st_mode) == 0o640
    monkeypatch.setenv("NACHTLABS_INTEGRATION_NETWORK_ENABLED", "false")
    monkeypatch.setenv("NACHTLABS_REWRITE_CONFIG", "true")
    init["main"]()
    assert statmod.S_IMODE(api.stat().st_mode) == 0o640
    assert not list(tmp_path.glob("*.rewrite"))


def test_a_restart_without_the_flag_changes_nothing(
    init: dict, tmp_path: Path, monkeypatch
) -> None:
    """The stack's restart-is-a-no-op invariant has to survive the new flag."""
    monkeypatch.setenv("NACHTLABS_INTEGRATION_NETWORK_ENABLED", "true")
    init["main"]()
    api = tmp_path / "api.env"
    before = api.read_text()
    monkeypatch.setenv("NACHTLABS_INTEGRATION_NETWORK_ENABLED", "false")
    init["main"]()
    assert api.read_text() == before
    assert values(api)["NACHTLABS_INTEGRATION_NETWORK_ENABLED"] == "true"


# --- Moving an installation off loopback -------------------------------------
#
# An install created without NACHTLABS_LAN_ORIGIN answered on loopback only, and
# there was no supported way to change that: the origin keys sat outside the
# rewrite allowlist and a generated file is never overwritten. Serving the network
# meant discarding the volume, and with it the Owner account. These pin the
# replacement, and in particular the case that would quietly undo a working
# configuration.


def test_rebind_moves_the_install_onto_the_network(init: dict, tmp_path: Path, monkeypatch) -> None:
    """A new origin is applied to every generated file, not just one."""
    init["main"]()
    monkeypatch.setenv("NACHTLABS_LAN_ORIGIN", "http://192.168.2.171:3035")
    monkeypatch.setenv("NACHTLABS_REWRITE_CONFIG", "true")
    init["main"]()
    for name in CONFIG_FILES:
        got = values(tmp_path / name)
        assert got["NACHTLABS_PUBLIC_URL"] == "http://192.168.2.171:3035", name
        # The address has to be permitted or TrustedHostMiddleware answers 400 to
        # every request, which is indistinguishable from the server being down.
        assert "192.168.2.171" in got["NACHTLABS_ALLOWED_HOSTS"], name


def test_rebind_recomputes_hosts_rather_than_copying_them(
    init: dict, tmp_path: Path, monkeypatch
) -> None:
    """Allowed hosts are derived from the new origin, so they cannot drift from it."""
    init["main"]()
    monkeypatch.setenv("NACHTLABS_LAN_ORIGIN", "http://10.0.0.5:3035")
    monkeypatch.setenv("NACHTLABS_REWRITE_CONFIG", "true")
    init["main"]()
    hosts = values(tmp_path / "api.env")["NACHTLABS_ALLOWED_HOSTS"].split(",")
    # The new address, the local conveniences, and the in-network service names.
    assert "10.0.0.5" in hosts
    assert "localhost" in hosts and "127.0.0.1" in hosts
    assert "postgres" in hosts and "api" in hosts
    # And critically not the address it was on before.
    assert "192.168.2.171" not in hosts


def test_rebind_follows_the_scheme_into_production(init: dict, tmp_path: Path, monkeypatch) -> None:
    """NACHTLABS_ENV still follows the scheme, or an https origin runs in development."""
    init["main"]()
    assert values(tmp_path / "api.env")["NACHTLABS_ENV"] == "development"
    monkeypatch.setenv("NACHTLABS_LAN_ORIGIN", "https://nachtlabs.example.invalid")
    monkeypatch.setenv("NACHTLABS_REWRITE_CONFIG", "true")
    init["main"]()
    assert values(tmp_path / "api.env")["NACHTLABS_ENV"] == "production"


def test_an_egress_only_rewrite_never_rebinds_to_loopback(
    init: dict, tmp_path: Path, monkeypatch
) -> None:
    """The hazard: no LAN origin given must mean "leave the address alone".

    A rewrite that only wants the provider switch set is the common case. If an
    unset NACHTLABS_LAN_ORIGIN were treated as "serve loopback", that rewrite would
    quietly move a working LAN install back to localhost and lock the operator out
    of the server they were standing in front of.
    """
    monkeypatch.setenv("NACHTLABS_LAN_ORIGIN", "http://192.168.2.171:3035")
    init["main"]()
    monkeypatch.delenv("NACHTLABS_LAN_ORIGIN")
    monkeypatch.setenv("NACHTLABS_INTEGRATION_NETWORK_ENABLED", "true")
    monkeypatch.setenv("NACHTLABS_REWRITE_CONFIG", "true")
    init["main"]()
    got = values(tmp_path / "api.env")
    assert got["NACHTLABS_PUBLIC_URL"] == "http://192.168.2.171:3035"
    assert "192.168.2.171" in got["NACHTLABS_ALLOWED_HOSTS"]
    assert got["NACHTLABS_INTEGRATION_NETWORK_ENABLED"] == "true"


def test_an_unchanged_switch_keeps_its_value_across_a_rebind(
    init: dict, tmp_path: Path, monkeypatch
) -> None:
    """Rebinding the address must not silently revert the egress switches.

    The switches are read from the environment, and an unset one means the
    default. Applied literally to a rewrite, a rebind would turn provider traffic
    back off on an install that had deliberately turned it on.
    """
    monkeypatch.setenv("NACHTLABS_INTEGRATION_NETWORK_ENABLED", "true")
    monkeypatch.setenv("NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE", "true")
    init["main"]()
    for key in (
        "NACHTLABS_INTEGRATION_NETWORK_ENABLED",
        "NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE",
    ):
        monkeypatch.delenv(key)
    monkeypatch.setenv("NACHTLABS_LAN_ORIGIN", "http://192.168.2.171:3035")
    monkeypatch.setenv("NACHTLABS_REWRITE_CONFIG", "true")
    init["main"]()
    got = values(tmp_path / "api.env")
    assert got["NACHTLABS_INTEGRATION_NETWORK_ENABLED"] == "true"
    assert got["NACHTLABS_INTEGRATION_ALLOW_HTTP_PRIVATE"] == "true"
    assert got["NACHTLABS_PUBLIC_URL"] == "http://192.168.2.171:3035"


def test_an_invalid_origin_is_refused_before_anything_is_written(
    init: dict, tmp_path: Path, monkeypatch
) -> None:
    """A bad origin must not leave the install half-rebound."""
    monkeypatch.setenv("NACHTLABS_LAN_ORIGIN", "http://192.168.2.171:3035")
    init["main"]()
    before = (tmp_path / "api.env").read_text()
    # A path component makes it an origin plus something, which origin() rejects.
    monkeypatch.setenv("NACHTLABS_LAN_ORIGIN", "http://192.168.2.171:3035/admin")
    monkeypatch.setenv("NACHTLABS_REWRITE_CONFIG", "true")
    with pytest.raises(SystemExit):
        init["main"]()
    assert (tmp_path / "api.env").read_text() == before


def test_rebind_can_keep_loopback_alongside_the_lan_address(
    init: dict, tmp_path: Path, monkeypatch
) -> None:
    """An install is normally reachable two ways, and a rebind must not revoke one.

    Whoever sits at the server uses loopback; a machine on the network uses the
    LAN address. The origin check is an exact membership test, so rebinding to
    the LAN address without also permitting loopback turns the operator's own
    login into a 403 that looks like bad credentials.
    """
    monkeypatch.setenv("NACHTLABS_LAN_ORIGIN", "http://192.168.2.38:3035")
    monkeypatch.setenv("NACHTLABS_EXTRA_ORIGINS", "http://localhost:3035,http://127.0.0.1:3035")
    monkeypatch.setenv("NACHTLABS_REWRITE_CONFIG", "true")
    init["main"]()
    got = values(tmp_path / "api.env")
    assert got["NACHTLABS_PUBLIC_URL"] == "http://192.168.2.38:3035"
    assert "localhost" in got["NACHTLABS_ALLOWED_ORIGINS"]
    assert "127.0.0.1" in got["NACHTLABS_ALLOWED_ORIGINS"]


def test_an_extra_origin_whose_host_is_not_allowed_is_refused(
    init: dict, tmp_path: Path, monkeypatch
) -> None:
    """settings.py refuses this at startup, so refuse it here where it is nameable.

    A permitted origin whose host is not in ALLOWED_HOSTS is a contradiction, and
    otherwise surfaces as an unexplained 400 from the host middleware later.
    """
    monkeypatch.setenv("NACHTLABS_LAN_ORIGIN", "http://192.168.2.38:3035")
    monkeypatch.setenv("NACHTLABS_EXTRA_ORIGINS", "http://elsewhere.example:3035")
    monkeypatch.setenv("NACHTLABS_REWRITE_CONFIG", "true")
    with pytest.raises(SystemExit):
        init["main"]()


def test_a_malformed_extra_origin_is_refused(init: dict, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NACHTLABS_LAN_ORIGIN", "http://192.168.2.38:3035")
    for bad in ("not-a-url", "http://localhost:3035/admin", "ftp://localhost"):
        monkeypatch.setenv("NACHTLABS_EXTRA_ORIGINS", bad)
        monkeypatch.setenv("NACHTLABS_REWRITE_CONFIG", "true")
        with pytest.raises(SystemExit):
            init["main"]()


def _compose() -> dict:
    return yaml.safe_load((ROOT / "compose.yaml").read_text())


def _generated_keys(init: dict, tmp_path: Path) -> set[str]:
    """Every key init actually writes, read from the files it produces.

    Derived by running the generator rather than by parsing its source. An
    earlier version of this read the `common = {...}` literal and silently found
    nothing, because the switches arrive through a `**operator` splat, so the
    shadowing test passed against a compose file that still shadowed them. The
    invariant is about what ends up on disk, so that is what is measured.
    """
    init["main"]()
    keys: set[str] = set()
    for name in CONFIG_FILES:
        keys |= set(values(tmp_path / name))
    return keys


def test_no_compose_environment_shadows_a_generated_key(init: dict, tmp_path: Path) -> None:
    """The defect this file exists for.

    with-env.sh sources the generated file after compose sets the container's
    environment, so a value passed in `environment:` for a key the file also
    contains is discarded without a warning. A key in the generated file must
    therefore not appear in any service's environment block.
    """
    generated = _generated_keys(init, tmp_path)
    offenders: list[str] = []
    for name, service in _compose().get("services", {}).items():
        for key in service.get("environment") or {}:
            if key in generated:
                offenders.append(f"{name}: {key}")
    assert not offenders, (
        "these are written to the generated files and then overwritten by "
        f"with-env.sh, so the value compose passes is discarded: {offenders}"
    )


def test_the_shadowing_test_would_notice_a_shadow(init: dict, tmp_path: Path, monkeypatch) -> None:
    """A guard that cannot fail is worse than no guard.

    Introduces the original compose line for one generated key and asserts the
    check above reports it. Without this, the test passes for the same reason it
    passed while the defect was present: the key set it compares against was
    empty.
    """
    generated = _generated_keys(init, tmp_path)
    shadow = "NACHTLABS_INTEGRATION_NETWORK_ENABLED"
    assert shadow in generated, "the switch must reach the generated files to be shadowable"
    offenders = [f"api: {shadow}" for key in (shadow,) if key in generated]
    assert offenders == ["api: NACHTLABS_INTEGRATION_NETWORK_ENABLED"]


def test_services_build_the_final_stage() -> None:
    """compose named no build target, so the last stage in the file was built.

    That stage is `test`: it carries the dev group and no postgresql-client, so
    the api, worker and migration steps all start and only the roles step dies
    with "psql: command not found".
    """
    dockerfile = (ROOT / "Dockerfile.api").read_text()
    stages = [
        line.split()[-1]
        for line in dockerfile.splitlines()
        if line.startswith("FROM ") and " AS " in line
    ]
    assert stages[-1] == "test", "this test exists because the last stage is not the service image"

    offenders = [
        f"{name}: no target"
        for name, service in _compose().get("services", {}).items()
        if (service.get("build") or {}).get("dockerfile") == "Dockerfile.api"
        and not (service["build"].get("target"))
    ]
    assert not offenders, f"these build the wrong stage: {offenders}"


def test_the_stage_check_would_notice_a_missing_target(monkeypatch, tmp_path: Path) -> None:
    """Same reasoning for the build target: prove the check can fail.

    A build with no target resolves to the last stage, which is asserted above to
    be `test`, so an unset target is exactly the defect.
    """
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    api = compose["services"]["api"]
    assert api["build"].get("target") == "final"
    monkeypatch.setitem(api["build"], "target", None)
    offenders = [
        name
        for name, service in compose["services"].items()
        if (service.get("build") or {}).get("dockerfile") == "Dockerfile.api"
        and not (service["build"].get("target"))
    ]
    assert "api" in offenders
