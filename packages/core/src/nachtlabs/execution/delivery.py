"""Controlled branch delivery. No force push, merge, default-branch write or agent credentials."""
import base64
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from nachtlabs.database import session
from nachtlabs.errors import require
from nachtlabs.execution.files import manifest
from nachtlabs.execution.process import bounded
from nachtlabs.execution.repository import GIT_ENV, git
from nachtlabs.factory_models import Run
from nachtlabs.integrations.delivery import PullRequests
from nachtlabs.integrations.transport import Endpoint, PinnedJSON
from nachtlabs.models import IntegrationConnection, ProjectIntegration
from nachtlabs.security import decrypt
from nachtlabs.settings import get_settings
from nachtlabs.workflows.engine import delivery_gate, enforce_approval

JOURNAL = Path("/var/lib/nachtlabs-executor/delivery")


def write_journal(path: Path, value: dict) -> None:
    # Publish intent durably before a network mutation, and completion atomically after it.
    fd, name = tempfile.mkstemp(prefix="intent-", dir=JOURNAL)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(JOURNAL, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_commit(repository: Path, source: Path, spec: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="index-", dir=JOURNAL) as name:
        env = {**GIT_ENV, "GIT_INDEX_FILE": str(Path(name) / "index"),
               "GIT_AUTHOR_NAME": "NachtLabs", "GIT_AUTHOR_EMAIL": "nachtlabs@localhost",
               "GIT_COMMITTER_NAME": "NachtLabs", "GIT_COMMITTER_EMAIL": "nachtlabs@localhost",
               "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z"}
        def invoke(args: list[str], data: bytes = b"") -> str:
            result = bounded(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                              "--git-dir=" + str(repository), *args], 60, 1048576, stdin=data, env=env)
            require(result.code == 0, 409, "commit_failed", "Controlled commit preparation failed")
            return result.output.decode().strip()
        invoke(["read-tree", "--empty"])
        index = bytearray()
        for relative, metadata in sorted(manifest(source, spec["policy"]["max_workspace_bytes"]).items()):
            oid = invoke(["hash-object", "-w", "--stdin"], (source / relative).read_bytes())
            mode = "100755" if metadata["executable"] else "100644"
            index.extend((mode + " " + oid + "\t" + relative).encode() + b"\x00")
        invoke(["update-index", "-z", "--index-info"], bytes(index))
        tree = invoke(["write-tree"])
        return invoke(["commit-tree", tree, "-p", spec["base_commit"]],
                      ("NachtLabs run " + spec["run_id"] + "\n\nCandidate: " + spec["candidate"] + "\n").encode())


def deliver(spec: dict, context: dict, catalog: dict, source: Path, cancelled) -> dict:
    settings = get_settings()
    require(settings.git_provider_network_enabled, 409, "git_network_disabled", "Provider delivery is disabled by operator policy")
    require(not cancelled(), 409, "cancelled", "Delivery cancelled")
    with session() as db:
        run = db.get(Run, UUID(spec["run_id"]))
        enforce_approval(db, run)
        delivery_gate(db, run)
        binding = db.get(ProjectIntegration, run.project_id)
        require(binding is not None, 409, "repository_binding", "Provider repository binding required")
        connection = db.get(IntegrationConnection, binding.connection_id)
        require(connection is not None and connection.active, 409, "connection_disabled", "Provider connection unavailable")
        credentials = decrypt(connection.credential, f"integration:{connection.id}") if connection.credential else {}
        require(bool(credentials.get("token")), 409, "provider_credential", "Scoped provider credential required")
        provider, full_name = connection.provider, binding.full_name
        endpoint = Endpoint(connection.base_url, tuple(connection.pinned_addresses), connection.allow_private,
                            connection.allow_http, connection.timeout_seconds)
        # Only trusted Git receives this credential. It never enters agent environment or args.
        token = credentials["token"]
        transport = PinnedJSON(endpoint, {"Authorization": ("Bearer " if provider == "github" else "token ") + token,
                                         "Accept": "application/json"}, settings.integration_ca_file)
    repository = catalog["repositories"][spec["repository_key"]]
    require(repository.get("provider") == provider and repository.get("full_name") == full_name,
            409, "delivery_binding", "Qualified catalog must match provider repository")
    remote = repository.get("remote_url", "")
    parsed = urlparse(remote)
    require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment and parsed.path.rstrip("/") == "/" + full_name + ".git",
            409, "remote_url", "Use the exact qualified HTTPS repository URL")
    pins = repository.get("remote_addresses", [])
    require(bool(pins), 409, "remote_pins", "Pin the remote Git endpoint")
    import ipaddress
    Endpoint(parsed.scheme + "://" + parsed.netloc, tuple(pins), bool(repository.get("remote_allow_private", False))).validate()
    resolved_addresses = [("[" + str(ipaddress.ip_address(address)) + "]") if ":" in address else address for address in pins]
    JOURNAL.mkdir(mode=0o700, parents=True, exist_ok=True)
    journal = JOURNAL / (spec["run_id"] + "-" + str(spec["attempt"]) + ".json")
    branch = "nachtlabs/" + spec["run_id"] + "-" + str(spec["attempt"])
    mirror = Path(repository["mirror"])
    # A refreshed mirror is required at delivery, avoiding commits against a changed base.
    current = git(mirror, "rev-parse", "--verify", "--end-of-options", spec["target_ref"] + "^{commit}").decode().strip()
    require(current == spec["base_commit"], 409, "base_changed", "Target base changed; create a new run")
    commit = prepare_commit(mirror, source, spec)
    intent = {"candidate": spec["candidate"], "commit": commit, "branch": branch, "state": "prepared"}
    if journal.exists():
        old = json.loads(journal.read_text())
        require(all(old.get(k) == intent[k] for k in ("candidate", "commit", "branch")), 409, "delivery_conflict", "Existing delivery intent differs")
        if old.get("state") == "complete":
            return old["result"]
    write_journal(journal, intent)
    journal.chmod(0o600)
    # Curl's resolve table pins Git HTTPS without proxies, redirects or DNS fallback.
    # Trusted Git alone runs here; no repository code, hooks, checkout filters or shell.
    env = {**GIT_ENV, "HOME": "/nonexistent", "GIT_CONFIG_COUNT": "4",
           "GIT_CONFIG_KEY_0": "http.extraHeader",
           "GIT_CONFIG_VALUE_0": "Authorization: Basic " + base64.b64encode(("x-access-token:" + token).encode()).decode(),
           "GIT_CONFIG_KEY_1": "http.curloptResolve",
           "GIT_CONFIG_VALUE_1": str(parsed.hostname) + ":" + str(parsed.port or 443) + ":" + ",".join(resolved_addresses),
           "GIT_CONFIG_KEY_2": "http.followRedirects", "GIT_CONFIG_VALUE_2": "false",
           "GIT_CONFIG_KEY_3": "http.proxy", "GIT_CONFIG_VALUE_3": ""}
    if settings.integration_ca_file:
        env["GIT_SSL_CAINFO"] = str(settings.integration_ca_file)
    def remote_git(args: list[str]):
        return bounded(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "--git-dir=" + str(mirror), *args],
                       60, 65536, cancelled, env=env)
    target = "refs/heads/" + branch
    base = remote_git(["ls-remote", "--exit-code", remote, "refs/heads/" + spec["target_ref"]])
    require(base.code == 0 and base.output.decode().split()[0] == spec["base_commit"],
            409, "remote_base_changed", "Remote base changed; create a new reviewed run")
    advertised = remote_git(["ls-remote", "--exit-code", remote, target])
    if advertised.code == 0:
        require(advertised.output.decode().split()[0] == commit, 409, "remote_branch_conflict", "Run branch already has different content")
    else:
        require(advertised.code == 2, 409, "remote_unavailable", "Cannot reconcile remote branch")
        intent["state"] = "push_intent"
        write_journal(journal, intent)
        result = remote_git(["push", "--porcelain", remote, commit + ":" + target])
        require(result.code == 0, 409, "push_uncertain", "Push requires reconciliation")
    require(not cancelled(), 409, "delivery_uncertain", "Reconcile pushed branch before continuing")
    marker = "<!-- nachtlabs-run:" + spec["run_id"] + " candidate:" + spec["candidate"] + " -->"
    # Provider summary contains fixed evidence metadata, never raw logs/holdouts.
    body = marker + "\n\nCandidate: " + spec["candidate"] + "\n\nApproved plan digest: " + spec["plan_digest"]
    warning_accepted = any(e["kind"] == "policy_exception" and e["status"] == "approved" for e in context["evidence"])
    body += "\n\nRequired validation passed. " + ("The Owner accepted independent-verifier warnings under project policy." if warning_accepted else "Independent verification passed.")
    body += "\n\nReview run evidence: " + settings.public_url + "/runs/" + spec["run_id"]
    intent["state"] = "pr_intent"
    write_journal(journal, intent)
    result = PullRequests(transport, provider, full_name).reconcile(branch, spec["target_ref"], marker,
                                                                context["request"]["title"], body, commit)
    result["candidate"] = spec["candidate"]
    write_journal(journal, {**intent, "state": "complete", "result": result})
    return result
