"""Explicit opt-in Linux/root qualification tests. Never part of unattended acceptance."""
import json
import os
from pathlib import Path
import time

import pytest

from nachtlabs.errors import DomainError
from nachtlabs.execution import sandbox
from nachtlabs.execution.catalog import CATALOG, trusted_file

pytestmark = pytest.mark.skipif(
    os.name != "posix" or os.environ.get("NACHTLABS_NATIVE_ACCEPTANCE") != "1",
    reason="Requires explicit operator opt-in on a disposable Linux qualification host",
)


@pytest.fixture
def native():
    if os.geteuid() != 0:
        pytest.skip("Native qualification requires Linux root")
    import fcntl
    sandbox.ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (sandbox.ROOT / "broker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sandbox.recover()
        configuration = json.loads(trusted_file(CATALOG))
        policy = {"timeout_seconds": 10, "max_output_bytes": 4096, "max_workspace_bytes": 1048576}
        with sandbox.Workspace(policy["max_workspace_bytes"]) as workspace:
            import tempfile
            with tempfile.TemporaryDirectory(dir=sandbox.ROOT) as name:
                inputs = Path(name)
                inputs.chmod(0o755)
                yield workspace, inputs, configuration, policy


def test_control_plane_secret_is_unavailable(native):
    work, inputs, configuration, policy = native
    code = """from pathlib import Path
p=Path('/etc/nachtlabs/credentials/master-key')
try:
    p.read_bytes()
except (PermissionError,FileNotFoundError):
    Path('/work/observation').write_text('denied')
else:
    raise SystemExit(7)
"""
    result = sandbox.run(["/usr/bin/python3", "-c", code], work, inputs, configuration, policy, lambda: False)
    assert result.code == 0 and (work / "observation").read_text() == "denied"


def test_output_limit_stops_job(native):
    work, inputs, configuration, policy = native
    with pytest.raises(DomainError) as raised:
        sandbox.run(["/usr/bin/python3", "-c", "print('x'*100000)"], work, inputs, configuration, policy, lambda: False)
    assert raised.value.code == "output_budget"
    assert not sandbox.ACTIVE.exists()


def test_cancel_covers_forked_child(native):
    work, inputs, configuration, policy = native
    started = time.monotonic()
    code = "import subprocess,time; subprocess.Popen(['/usr/bin/python3','-c','import time; time.sleep(60)']); time.sleep(60)"
    with pytest.raises(DomainError) as raised:
        sandbox.run(["/usr/bin/python3", "-c", code], work, inputs, configuration, policy,
                    lambda: time.monotonic() - started > 2)
    assert raised.value.code == "cancelled"
    assert not sandbox.ACTIVE.exists()


def test_network_disabled_has_no_ipv4_socket(native):
    work, inputs, configuration, policy = native
    code = """import socket
try:
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
except OSError:
    pass
else:
    raise SystemExit(8)
"""
    result = sandbox.run(["/usr/bin/python3", "-c", code], work, inputs, configuration, policy, lambda: False)
    assert result.code == 0
