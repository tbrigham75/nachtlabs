"""Authored contract tests. Execution is deferred to the Linux operator."""

from pathlib import Path
from uuid import uuid4

import pytest
from nachtlabs.errors import DomainError
from nachtlabs.execution.files import candidate, manifest, scope_gate
from nachtlabs.integrations.contracts import ProviderError
from nachtlabs.integrations.delivery import PullRequests
from nachtlabs.workflows.policy import ProjectExecutionPolicy, safe_ref, safe_relative


@pytest.mark.parametrize(
    "path",
    ["../outside", "/etc/passwd", ".", "./", "docs/../secret", "docs/line\nbreak", "C:\\secret"],
)
def test_candidate_path_rejects_escapes(path: str) -> None:
    with pytest.raises(ValueError):
        safe_relative(path)


@pytest.mark.parametrize(
    "ref", ["--upload-pack=evil", "main..other", "main.lock", "main/../private", "main\nother"]
)
def test_ref_rejects_option_and_revision_injection(ref: str) -> None:
    with pytest.raises(ValueError):
        safe_ref(ref)


def test_candidate_changes_with_content_and_executable_bit(tmp_path: Path) -> None:
    file = tmp_path / "readme.md"
    file.write_text("one")
    first = candidate(tmp_path, 1024)
    file.write_text("two")
    second = candidate(tmp_path, 1024)
    assert first != second
    file.chmod(0o755)
    assert candidate(tmp_path, 1024) != second


def test_scope_gate_catches_deletion_outside_scope() -> None:
    policy = ProjectExecutionPolicy().model_dump()
    with pytest.raises(DomainError, match="approved scope"):
        scope_gate({"src/auth.py": {"sha256": "before"}}, {}, policy)


def test_protected_policy_cannot_be_changed_even_if_allowlisted() -> None:
    policy = ProjectExecutionPolicy(allowed_paths=[".github/"]).model_dump()
    with pytest.raises(DomainError):
        scope_gate({}, {".github/workflows/build.yml": {"sha256": "new"}}, policy)


def test_symlink_candidate_rejected(tmp_path: Path) -> None:
    (tmp_path / "escape").symlink_to("/etc/passwd")
    with pytest.raises(DomainError):
        manifest(tmp_path, 1024)


class Transport:
    def __init__(self, rows):
        self.rows = rows
        self.writes = 0

    def request(self, method, path, body=None):
        if method == "POST":
            self.writes += 1
            raise AssertionError("Reconciliation must not create another pull request")
        return self.rows


def test_existing_pr_is_reconciled_without_mutation() -> None:
    branch, commit, marker = "nachtlabs/" + str(uuid4()), "a" * 40, "<!-- fixture -->"
    transport = Transport(
        [
            {
                "head": {"ref": branch, "sha": commit},
                "base": {"ref": "main"},
                "body": marker,
                "state": "open",
                "number": 7,
                "html_url": "https://example.invalid/pr/7",
            }
        ]
    )
    value = PullRequests(transport, "gitea", "fixture/repo").reconcile(
        branch, "main", marker, "Title", marker, commit
    )
    assert value["number"] == 7 and transport.writes == 0


def test_matching_branch_without_ownership_marker_blocks() -> None:
    transport = Transport(
        [
            {
                "head": {"ref": "nachtlabs/fixture", "sha": "a" * 40},
                "base": {"ref": "main"},
                "body": "Unrelated",
                "state": "open",
            }
        ]
    )
    with pytest.raises(ProviderError):
        PullRequests(transport, "github", "fixture/repo").reconcile(
            "nachtlabs/fixture", "main", "ownership", "Title", "body", "a" * 40
        )
    assert transport.writes == 0
