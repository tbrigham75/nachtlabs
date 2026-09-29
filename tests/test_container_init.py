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
