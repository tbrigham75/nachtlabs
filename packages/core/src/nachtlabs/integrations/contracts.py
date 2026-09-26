from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    """Only a fixed classification is safe to return to callers."""

    def __init__(self, code: str, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class Repository:
    provider_id: str
    full_name: str
    default_branch: str
    private: bool


@dataclass(frozen=True)
class Model:
    name: str
    digest: str | None = None


@dataclass(frozen=True)
class Discovery:
    identity: str
    repositories: list[Repository] = field(default_factory=list)
    models: list[Model] = field(default_factory=list)
    next_page: int | None = None
    provider_version: str | None = None


class JSONTransport(Protocol):
    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any: ...


class GitProvider(Protocol):
    def discover(self, page: int = 1) -> Discovery: ...
    def repository(self, full_name: str) -> Repository: ...


@dataclass(frozen=True)
class ModelResult:
    model: str
    text: str
    input_tokens: int | None
    output_tokens: int | None
    duration_ns: int | None


class ModelProvider(Protocol):
    def discover(self, page: int = 1) -> Discovery: ...
    def chat(
        self, model: str, messages: list[dict[str, str]], temperature: float = 0.2
    ) -> ModelResult: ...
