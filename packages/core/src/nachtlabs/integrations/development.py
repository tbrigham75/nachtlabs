"""Explicit synthetic adapter for an operator-run development harness; never production discovery."""
from nachtlabs.errors import require
from nachtlabs.integrations.agents import Invocation
from nachtlabs.settings import get_settings


class DevelopmentAdapter:
    def invocation(self, prompt: str, timeout_seconds: int = 30) -> Invocation:
        require(get_settings().env in {"development", "test"}, 409, "development_only", "Synthetic adapter is unavailable in production")
        require(0 < len(prompt.encode()) <= 65536, 422, "prompt_size", "Bounded fixture prompt required")
        return Invocation(("/usr/bin/python3", "/opt/checks/development_agent.py"), prompt.encode(), timeout_seconds)
