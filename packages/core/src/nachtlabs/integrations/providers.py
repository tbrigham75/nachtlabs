"""Documented read-only discovery plus an internal Ollama chat contract. No Git mutations."""

import re
from typing import Any
from urllib.parse import quote

from nachtlabs.integrations.contracts import (
    Discovery,
    JSONTransport,
    Model,
    ModelResult,
    ProviderError,
    Repository,
)


def string(value: Any, limit: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ProviderError("provider_format")
    return value


def text_content(value: Any, limit: int = 64000) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or any(ord(c) < 32 and c not in "\n\r\t" for c in value)
    ):
        raise ProviderError("provider_format")
    return value


def repository_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) or any(
        p in {".", ".."} for p in value.split("/")
    ):
        raise ProviderError("repository_name")
    return value


def repo(value: Any) -> Repository:
    if not isinstance(value, dict) or not isinstance(value.get("private"), bool):
        raise ProviderError("provider_format")
    identifier = value.get("id")
    if type(identifier) not in {str, int} or (isinstance(identifier, int) and identifier < 1):
        raise ProviderError("provider_format")
    return Repository(
        string(str(identifier)),
        repository_name(string(value.get("full_name"))),
        string(value.get("default_branch")),
        value["private"],
    )


class GitAdapter:
    def __init__(self, transport: JSONTransport, provider: str):
        if provider not in {"github", "gitea"}:
            raise ProviderError("unsupported_provider")
        self.transport, self.prefix = transport, "" if provider == "github" else "/api/v1"

    def discover(self, page: int = 1) -> Discovery:
        if not 1 <= page <= 100:
            raise ProviderError("page_limit")
        identity = self.transport.request("GET", self.prefix + "/user")
        if not isinstance(identity, dict):
            raise ProviderError("provider_format")
        rows = self.transport.request(
            "GET", self.prefix + f"/user/repos?per_page=50&limit=50&page={page}"
        )
        if not isinstance(rows, list) or len(rows) > 50:
            raise ProviderError("provider_format")
        return Discovery(
            identity=string(identity.get("login")),
            repositories=[repo(r) for r in rows],
            next_page=page + 1 if len(rows) == 50 and page < 100 else None,
        )

    def repository(self, full_name: str) -> Repository:
        name = repository_name(full_name)
        return repo(self.transport.request("GET", self.prefix + "/repos/" + quote(name, safe="/")))


def count(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    return value if type(value) is int and value >= 0 else None


class OllamaAdapter:
    def __init__(self, transport: JSONTransport):
        self.transport = transport

    def discover(self, page: int = 1) -> Discovery:
        if page != 1:
            raise ProviderError("page_limit")
        version = self.transport.request("GET", "/api/version")
        data = self.transport.request("GET", "/api/tags")
        if (
            not isinstance(version, dict)
            or not isinstance(data, dict)
            or not isinstance(data.get("models"), list)
        ):
            raise ProviderError("provider_format")
        if len(data["models"]) > 1000:
            raise ProviderError("response_too_large")
        models = []
        for row in data["models"]:
            if not isinstance(row, dict):
                raise ProviderError("provider_format")
            models.append(
                Model(string(row.get("name")), string(row["digest"]) if row.get("digest") else None)
            )
        return Discovery("ollama", models=models, provider_version=string(version.get("version")))

    def chat(
        self, model: str, messages: list[dict[str, str]], temperature: float = 0.2
    ) -> ModelResult:
        string(model)
        if not 0 <= temperature <= 2 or not 1 <= len(messages) <= 100:
            raise ProviderError("request_policy")
        for message in messages:
            if set(message) != {"role", "content"} or message["role"] not in {
                "system",
                "user",
                "assistant",
            }:
                raise ProviderError("request_policy")
            text_content(message["content"], 64000)
        data = self.transport.request(
            "POST",
            "/api/chat",
            {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": 2048},
            },
        )
        if (
            not isinstance(data, dict)
            or data.get("done") is not True
            or not isinstance(data.get("message"), dict)
        ):
            raise ProviderError("provider_incomplete")
        return ModelResult(
            string(data.get("model")),
            text_content(data["message"].get("content"), 1048576),
            count(data, "prompt_eval_count"),
            count(data, "eval_count"),
            count(data, "total_duration"),
        )
