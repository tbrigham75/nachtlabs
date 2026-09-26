"""Contract definitions only. Synthetic transports never contact providers."""

import asyncio
import hashlib
import hmac
import json
from typing import Any

import pytest
from nachtlabs.integrations.agents import AgentAdapter
from nachtlabs.integrations.contracts import ProviderError
from nachtlabs.integrations.providers import GitAdapter, OllamaAdapter
from nachtlabs.integrations.transport import Endpoint, PinnedJSON
from nachtlabs.integrations.webhooks import delivery_fingerprint, verify_signature
from nachtlabs.security import new_token


class FixtureTransport:
    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        self.calls.append((method, path, body))
        return self.responses[path]


@pytest.mark.parametrize("provider,prefix", [("github", ""), ("gitea", "/api/v1")])
def test_git_contract_projects_only_known_fields(provider: str, prefix: str) -> None:
    transport = FixtureTransport(
        {
            prefix + "/user": {"login": "fixture", "unexpected_secret": new_token()},
            prefix + "/user/repos?per_page=50&limit=50&page=1": [
                {
                    "id": 12,
                    "full_name": "fixture/repo",
                    "private": True,
                    "default_branch": "main",
                    "token": new_token(),
                },
            ],
        }
    )
    result = GitAdapter(transport, provider).discover()
    assert result.identity == "fixture"
    assert result.repositories[0].full_name == "fixture/repo"
    assert result.next_page is None
    assert "token" not in repr(result)
    assert all(call[0] == "GET" for call in transport.calls)


def test_ollama_unknown_usage_stays_unknown() -> None:
    transport = FixtureTransport(
        {
            "/api/chat": {
                "done": True,
                "model": "fixture",
                "message": {"content": "Synthetic answer"},
            }
        }
    )
    result = OllamaAdapter(transport).chat(
        "fixture", [{"role": "user", "content": "Synthetic input"}]
    )
    assert (
        result.input_tokens is None and result.output_tokens is None and result.duration_ns is None
    )
    assert transport.calls[0][2]["stream"] is False


@pytest.mark.parametrize(
    "url,ip,private,http",
    [
        ("http://127.0.0.1", "127.0.0.1", False, True),
        ("http://10.0.0.5", "10.0.0.5", True, True),
        ("https://169.254.169.254", "169.254.169.254", True, False),
        ("https://100.100.100.200", "100.100.100.200", True, False),
        ("https://example.com/path", "1.1.1.1", False, False),
        ("https://user:password@example.com", "1.1.1.1", False, False),
        ("https://example.com", "0.0.0.0", True, False),
        ("https://example.com", "::ffff:127.0.0.1", True, False),
    ],
)
def test_endpoint_rejects_unsafe_destinations(url: str, ip: str, private: bool, http: bool) -> None:
    with pytest.raises(ProviderError):
        Endpoint(url, (ip,), private, http).validate()


def test_approved_loopback_and_private_tls() -> None:
    Endpoint("http://127.0.0.1:11434", ("127.0.0.1",), True, True).validate()
    Endpoint("https://git.internal", ("10.0.0.5",), True).validate()


def test_redirect_never_follows_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    import nachtlabs.integrations.transport as module

    calls = []

    class Response:
        status = 302

        def close(self) -> None:
            pass

    class Connection:
        def __init__(self, *args: Any):
            pass

        def request(self, *args: Any, **kwargs: Any) -> None:
            calls.append(args)

        def getresponse(self) -> Response:
            return Response()

        def abort(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(module, "PinnedConnection", Connection)
    with pytest.raises(ProviderError, match="redirect_blocked"):
        PinnedJSON(
            Endpoint("https://example.com", ("1.1.1.1",)),
            {"Authorization": "Bearer " + new_token()},
        ).request("GET", "/user")
    assert len(calls) == 1


@pytest.mark.parametrize("provider", ["github", "gitea"])
def test_webhook_raw_body_signature(provider: str) -> None:
    secret, body = new_token(), b'{"action":"synthetic"}'
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    signature = "sha256=" + digest if provider == "github" else digest
    verify_signature(provider, body, signature, secret)
    with pytest.raises(ProviderError):
        verify_signature(provider, body + b" ", signature, secret)
    key, payload = delivery_fingerprint("connection", "delivery-1", body)
    other_key, other_payload = delivery_fingerprint("connection", "delivery-1", body + b" ")
    assert key == other_key and payload != other_payload


@pytest.mark.parametrize("provider", ["hermes", "opencode"])
def test_agent_prompt_is_not_process_argument(provider: str) -> None:
    canary = new_token()
    invocation = AgentAdapter(provider).invocation(
        "/usr/local/bin/" + provider, "fixture/model", canary, 300
    )
    assert canary not in repr(invocation.argv)
    assert invocation.requires_isolation
    assert (
        invocation.stdin if provider == "hermes" else invocation.input_files[0][1]
    ) == canary.encode()
    event = AgentAdapter(provider).event(
        json.dumps({"type": "text", "part": {"text": canary}}).encode()
    )
    assert canary not in repr(event)


def test_agent_cancel_does_not_claim_validation() -> None:
    class Execution:
        cancelled = False

        async def cancel(self) -> None:
            self.cancelled = True

        async def wait(self) -> int:
            return -15

        async def events(self):
            yield b"synthetic"

    execution = Execution()
    result = asyncio.run(AgentAdapter("hermes").cancel(execution))
    assert execution.cancelled and result.status == "cancelled" and not result.evidence_verified


def test_ollama_preserves_multiline_structured_content() -> None:
    content = '{\n  "summary": "A bounded plan"\n}'
    transport = FixtureTransport(
        {"/api/chat": {"done": True, "model": "fixture", "message": {"content": content}}}
    )
    result = OllamaAdapter(transport).chat(
        "fixture", [{"role": "user", "content": "First line\nSecond line"}]
    )
    assert result.text == content
