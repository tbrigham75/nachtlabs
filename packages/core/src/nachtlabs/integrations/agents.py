"""Agent invocation contracts. A restricted M6 runner must be supplied; nothing spawns here."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol

from nachtlabs.integrations.contracts import ProviderError


@dataclass(frozen=True)
class Invocation:
    argv: tuple[str, ...]
    stdin: bytes
    timeout_seconds: int
    input_files: tuple[tuple[str, bytes], ...] = ()
    output_limit: int = 1048576
    # Runner MUST use an empty environment, fresh home/config, no inherited credentials,
    # no repo plugins/hooks, bounded process group and an approved network/filesystem policy.
    requires_isolation: bool = True


@dataclass(frozen=True)
class AgentEvent:
    kind: str
    # Raw text/tool arguments/results are NOT safe telemetry.
    output_bytes: int = 0


@dataclass(frozen=True)
class AgentResult:
    status: str
    exit_code: int | None
    evidence_verified: bool = False


class AgentExecution(Protocol):
    def events(self) -> AsyncIterator[bytes]: ...
    async def cancel(self) -> None: ...
    async def wait(self) -> int: ...


class ExecutionRunner(Protocol):
    async def start(self, invocation: Invocation) -> AgentExecution: ...


def capabilities(provider: str) -> dict[str, Any]:
    if provider not in {"hermes", "opencode"}:
        raise ProviderError("unsupported_provider")
    return {
        "provider": provider,
        "configured_transport": "cli",
        "documented_single_query": True,
        "structured_events": provider == "opencode",
        "cancellation": "runner_process_group",
        "tool_isolation_verified": False,
        "compatibility": "unverified",
        "execution_available": False,
        "limitations": [
            "Restricted runner and pinned-version acceptance are required",
            "Hermes output is opaque; full tool-event visibility is not established",
        ]
        if provider == "hermes"
        else ["Permission/configuration semantics require pinned-version acceptance"],
    }


class AgentAdapter:
    def __init__(self, provider: str):
        capabilities(provider)
        self.provider = provider

    def invocation(
        self, executable: str, model: str, prompt: str, timeout_seconds: int
    ) -> Invocation:
        path = PurePosixPath(executable)
        if (
            not path.is_absolute()
            or ".." in path.parts
            or not model
            or model.startswith("-")
            or any(ord(c) < 32 for c in executable + model)
        ):
            raise ProviderError("agent_configuration")
        if not 10 <= timeout_seconds <= 3600 or not prompt or len(prompt.encode()) > 65536:
            raise ProviderError("agent_configuration")
        # Runner creates the fixed input file read-only in a fresh isolated /run mount.
        if self.provider == "opencode":
            args = (
                executable,
                "run",
                "--format",
                "json",
                "--model",
                model,
                "--file",
                "/run/nachtlabs/input/request.txt",
                "--",
                "Follow the task in the attached request file.",
            )
            return Invocation(
                args, b"", timeout_seconds, (("/run/nachtlabs/input/request.txt", prompt.encode()),)
            )
        return Invocation(
            (executable, "chat", "--query-file", "-", "--model", model),
            prompt.encode(),
            timeout_seconds,
        )

    def event(self, raw: bytes) -> AgentEvent:
        if len(raw) > 65536:
            raise ProviderError("agent_output_limit")
        if self.provider == "hermes":
            return AgentEvent("opaque_output", len(raw))
        try:
            value = json.loads(raw)
            kind = value.get("type") if isinstance(value, dict) else None
            if not isinstance(kind, str) or kind not in {
                "text",
                "tool_use",
                "step_start",
                "step_finish",
                "error",
            }:
                return AgentEvent("unknown_event", len(raw))
            return AgentEvent(kind, len(raw))
        except (ValueError, UnicodeError):
            raise ProviderError("agent_event_format") from None

    async def invoke(self, runner: ExecutionRunner, invocation: Invocation) -> AgentExecution:
        return await runner.start(invocation)

    async def cancel(self, execution: AgentExecution) -> AgentResult:
        await execution.cancel()
        return AgentResult("cancelled", await execution.wait())

    async def result(self, execution: AgentExecution) -> AgentResult:
        code = await execution.wait()
        # Process success is an agent claim, never validation or independent evidence.
        return AgentResult("agent_completed" if code == 0 else "agent_failed", code)
