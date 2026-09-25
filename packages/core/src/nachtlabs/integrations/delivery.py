"""Deterministic PR reconciliation. Transport never retries mutations automatically."""
from typing import Any
from urllib.parse import quote

from nachtlabs.integrations.contracts import JSONTransport, ProviderError
from nachtlabs.integrations.providers import repository_name


class PullRequests:
    def __init__(self, transport: JSONTransport, provider: str, repository: str):
        if provider not in {"github", "gitea"}:
            raise ProviderError("unsupported_provider")
        self.transport, self.provider = transport, provider
        self.path = ("" if provider == "github" else "/api/v1") + "/repos/" + quote(repository_name(repository), safe="/")
        self.owner = repository.split("/")[0]

    def reconcile(self, branch: str, base: str, marker: str, title: str, body: str, commit: str) -> dict[str, Any]:
        # Bounded pagination; never infer absence from a truncated result set.
        found = []
        for page in range(1, 21):
            rows = self.transport.request("GET", self.path + "/pulls?state=all&limit=50&per_page=50&page=" + str(page))
            if not isinstance(rows, list):
                raise ProviderError("provider_format")
            for row in rows:
                if not isinstance(row, dict):
                    raise ProviderError("provider_format")
                if row.get("head", {}).get("ref") == branch:
                    found.append(row)
            if len(rows) < 50:
                break
        else:
            raise ProviderError("pr_reconciliation_limit")
        if len(found) > 1:
            raise ProviderError("pr_ambiguous")
        if found:
            row = found[0]
            if (marker not in (row.get("body") or "") or row.get("base", {}).get("ref") != base
                    or row.get("head", {}).get("sha") != commit or row.get("state") != "open"):
                raise ProviderError("pr_conflict")
        else:
            row = self.transport.request("POST", self.path + "/pulls",
                    {"head": branch, "base": base, "title": title[:200], "body": body})
        if not isinstance(row, dict) or not isinstance(row.get("number"), int) or not isinstance(row.get("html_url"), str):
            raise ProviderError("provider_format")
        return {"number": row["number"], "url": row["html_url"], "head": commit, "branch": branch, "base": base, "status": row.get("state", "open")}
