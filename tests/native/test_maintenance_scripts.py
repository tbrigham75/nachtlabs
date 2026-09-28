"""Linux-only shell orchestration checks using a disposable tree and fake tools.

Every installed path is rewritten into tmp_path in test copies. No real service,
database, package manager, remote Git operation, or /opt installation is touched.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="operator-run Linux shell checks")
ROOT = Path(__file__).resolve().parents[2]

STUB = r'''
import json
import os
import sys
import tarfile
from pathlib import Path

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
home = Path(os.environ["TEST_AREA"])
root = home / "nachtlabs"
failure = os.environ.get("FAILURE", "")
with (home / "events").open("a") as out:
    out.write(json.dumps([tool, *args]) + "\n")
if tool == "systemctl":
    states_path = home / "states.json"
    states = json.loads(states_path.read_text()) if states_path.exists() else {}
    if args[0] == "show":
        unit = args[1]
        state = states.get(unit, "inactive" if unit == "nachtlabs-executor" else "active")
        if failure == "executor" and unit == "nachtlabs-executor":
            state = "active"
        if failure == "unknown" and unit == "nachtlabs-executor":
            sys.exit(1)
        if "--property=LoadState" in args:
            print("loaded")
        elif "--property=MainPID" in args:
            print(123 if state == "active" else 0)
        else:
            print(state)
    elif args[0] == "list-units":
        if failure == "job":
            print("nachtlabs-job-test.service loaded active running job")
    elif args[0] in {"stop", "start"}:
        if failure == "stop" and args[0] == "stop":
            sys.exit(1)
        for unit in args[1:]:
            states[unit] = "active" if args[0] == "start" else "inactive"
        states_path.write_text(json.dumps(states))
elif tool == "git":
    before, target = "a" * 40, "b" * 40
    current = home / "commit"
    if args[0] == "status":
        pass
    elif args[0] == "symbolic-ref":
        print("main")
    elif args[0] == "rev-parse":
        if args[-1] == "HEAD":
            print(current.read_text() if current.exists() else before)
        elif "--abbrev-ref" in args:
            print("origin/main")
        else:
            print(target)
    elif args[0] == "fetch" and failure == "fetch":
        sys.exit(1)
    elif args[0] == "archive":
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
            for item in (home / "target").iterdir():
                archive.add(item, arcname=item.name)
    elif args[0] == "merge":
        current.write_text(target)
        (root / "release.txt").write_text("new")
    elif args[0] == "reset":
        current.write_text(before)
elif tool == "node":
    print("24")
elif tool == "pnpm":
    if args == ["-v"]:
        print("10.0.0")
    elif args == ["build"]:
        if failure == "build":
            sys.exit(1)
        output = Path.cwd() / "apps/web/.next"
        output.mkdir(parents=True, exist_ok=True)
        (output / "bundle").write_text("new")
        (Path.cwd() / "apps/web/public/docs-assets").mkdir(parents=True, exist_ok=True)
elif tool == "uv":
    if failure == "dependencies" or (failure == "activation" and "--project" not in args):
        (root / ".venv/damaged").write_text("partial install") if failure == "activation" else None
        sys.exit(1)
elif tool == "python":
    action = args[1] if len(args) > 1 else ""
    if failure == "database" or (failure == "migration" and action == "check-migrations") or (failure == "grants" and action == "grants"):
        sys.exit(1)
    if action == "reset":
        (home / "database-reset").touch()
elif tool == "sleep":
    pass
'''


@pytest.fixture
def installed(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "nachtlabs"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    replacements = {
        "/opt/nachtlabs": str(root),
        "/var/lib/nachtlabs-maintenance": str(tmp_path / "maintenance"),
        "/var/lib/nachtlabs-executor": str(tmp_path / "executor"),
        "/etc/nachtlabs": str(tmp_path / "etc"),
        '"$EUID"': '"${TEST_EUID}"',
    }
    for name in (
        "common.sh", "maintenance-common.sh", "reset-first-run.sh", "update.sh",
        "recover-update.sh", "maintenance_db.py",
    ):
        source = (ROOT / "scripts" / name).read_text()
        for old, new in replacements.items():
            source = source.replace(old, new)
        (scripts / name).write_text(source)
    (scripts / "build.sh").write_text("#!/usr/bin/env bash\nset -e\npnpm build\n")
    (scripts / "healthcheck.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    for directory in ("executor", "etc", "bin"):
        (tmp_path / directory).mkdir()
    (tmp_path / "etc/migration.env").write_text(
        f"NACHTLABS_MIGRATION_DATABASE_URL_FILE='{tmp_path}/unused-credential'\n"
    )
    (root / ".venv/bin").mkdir(parents=True)
    for name in ("systemctl", "git", "node", "pnpm", "uv", "sleep", "sync", "python"):
        path = root / ".venv/bin/python" if name == "python" else tmp_path / "bin" / name
        path.write_text(f"#!{sys.executable}\n{STUB}")
        path.chmod(0o755)
    (root / "apps/web/.next").mkdir(parents=True)
    (root / "apps/web/.next/bundle").write_text("old")
    (root / "release.txt").write_text("old")
    shutil.copytree(root, tmp_path / "target")
    env = {**os.environ, "PATH": f"{tmp_path}/bin:{os.environ['PATH']}",
           "TEST_AREA": str(tmp_path), "TEST_EUID": "0"}
    env.pop("NACHTLABS_ENV_FILE", None)
    return root, env


def run_script(installed: tuple[Path, dict[str, str]], name: str, failure: str = ""):
    root, env = installed
    return subprocess.run(
        ["bash", str(root / "scripts" / name), "--yes"] if name == "update.sh"
        else ["bash", str(root / "scripts" / name)],
        input="RESET\n", capture_output=True, text=True, timeout=30,
        env={**env, "FAILURE": failure}, cwd=root,
    )


def events(installed: tuple[Path, dict[str, str]]) -> list[list[str]]:
    path = installed[0].parent / "events"
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize("failure", ["executor", "unknown", "job", "stop", "database"])
def test_reset_refuses_uncertain_or_live_state(installed, failure: str) -> None:
    result = run_script(installed, "reset-first-run.sh", failure)
    assert result.returncode != 0
    assert not (installed[0].parent / "database-reset").exists()
    assert not any(event[:2] == ["systemctl", "start"] for event in events(installed))


def test_reset_restores_grants_before_starting_services(installed) -> None:
    result = run_script(installed, "reset-first-run.sh")
    assert result.returncode == 0, result.stderr
    calls = events(installed)
    grants = next(i for i, event in enumerate(calls) if event[0] == "python" and event[2:3] == ["grants"])
    start = next(i for i, event in enumerate(calls) if event[:2] == ["systemctl", "start"])
    assert grants < start


def test_reset_grant_failure_keeps_services_stopped(installed) -> None:
    result = run_script(installed, "reset-first-run.sh", "grants")
    assert result.returncode != 0
    assert (installed[0].parent / "database-reset").exists()
    assert not any(event[:2] == ["systemctl", "start"] for event in events(installed))


def test_reset_refuses_a_broker_lock_even_if_the_unit_reports_inactive(installed) -> None:
    import fcntl

    with (installed[0].parent / "executor/broker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_script(installed, "reset-first-run.sh")
    assert result.returncode != 0
    assert not (installed[0].parent / "database-reset").exists()


@pytest.mark.parametrize("failure", ["fetch", "dependencies", "build", "migration"])
def test_update_preparation_failure_keeps_live_release(installed, failure: str) -> None:
    result = run_script(installed, "update.sh", failure)
    assert result.returncode != 0
    assert not any(event[:2] == ["systemctl", "stop"] for event in events(installed))
    assert (installed[0] / "apps/web/.next/bundle").read_text() == "old"
    assert (installed[0] / "release.txt").read_text() == "old"


def test_failed_activation_requires_recovery_and_restores_runtime(installed) -> None:
    root, env = installed
    result = run_script(installed, "update.sh", "activation")
    assert result.returncode != 0
    pending = root.parent / "maintenance/update-pending"
    assert pending.is_dir()
    assert (root / "release.txt").read_text() == "new"
    retry = run_script(installed, "update.sh")
    assert retry.returncode != 0
    assert "interrupted" in retry.stderr
    reset = run_script(installed, "reset-first-run.sh")
    assert reset.returncode != 0
    assert not (root.parent / "database-reset").exists()
    recovered = subprocess.run(
        ["bash", str(pending / "recover-update.sh")], env=env, cwd=root,
        capture_output=True, text=True, timeout=30,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert (root / "release.txt").read_text() == "old"
    assert (root / "apps/web/.next/bundle").read_text() == "old"
    assert not (root / ".venv/damaged").exists()
    assert not pending.exists()


def test_successful_update_activates_prepared_bundle(installed) -> None:
    result = run_script(installed, "update.sh")
    assert result.returncode == 0, result.stderr
    assert (installed[0] / "apps/web/.next/bundle").read_text() == "new"
    calls = events(installed)
    built = next(i for i, event in enumerate(calls) if event == ["pnpm", "build"])
    stopped = next(i for i, event in enumerate(calls) if event[:2] == ["systemctl", "stop"])
    assert built < stopped


def test_recovery_of_interruption_before_snapshot_does_not_require_an_archive(installed) -> None:
    root, env = installed
    result = run_script(installed, "update.sh", "stop")
    assert result.returncode != 0
    pending = root.parent / "maintenance/update-pending"
    assert not (pending / "snapshot-ready").exists()
    recovered = subprocess.run(
        ["bash", str(pending / "recover-update.sh")], env=env, cwd=root,
        capture_output=True, text=True, timeout=30,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert (root / "release.txt").read_text() == "old"
    assert not pending.exists()
