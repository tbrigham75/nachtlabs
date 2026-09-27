from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NACHTLABS_", extra="ignore")
    env: Literal["development", "production", "test"] = "production"
    public_url: str = "https://nachtlabs.example.invalid"
    # Extra browser origins this installation answers on, comma separated and
    # exact. The origin check is a membership test against permitted_origins, so
    # every entry is an operator decision and there is no wildcard form. Empty
    # means "only public_url", which is what an existing installation gets.
    allowed_origins: str = ""
    allowed_hosts: str = "localhost,127.0.0.1"
    database_url_file: Path
    master_key_file: Path
    master_key_id: str = Field(default="v1", pattern=r"^[A-Za-z0-9_-]{1,40}$")
    previous_master_keys_file: Path | None = None
    integration_network_enabled: bool = False
    git_provider_network_enabled: bool = False
    integration_ca_file: Path | None = None
    bootstrap_token_file: Path | None = None
    # First-account creation is open by default so a fresh installation can be
    # used immediately. Set this on an installation reachable from an untrusted
    # network to require the one-time token instead.
    setup_token_required: bool = False
    session_idle_seconds: int = Field(default=1800, ge=60, le=86400)
    session_absolute_seconds: int = Field(default=43200, ge=300, le=604800)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password_file: Path | None = None
    smtp_from: str = "nachtlabs@example.invalid"
    smtp_tls_mode: Literal["starttls", "tls", "plain"] = "starttls"
    worker_name: str = "primary"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def secure_origin(self) -> "Settings":
        self.public_url = self.public_url.rstrip("/")
        permitted = self._permitted()
        for origin in permitted:
            self._check_origin(origin)
        if self.env == "production":
            for origin in permitted:
                parsed = urlparse(origin)
                hostname = parsed.hostname or ""
                if parsed.scheme != "https" or hostname.endswith(".invalid"):
                    raise ValueError(
                        f"Production requires a configured HTTPS origin; {origin} does not qualify"
                    )
            if self.smtp_host and self.smtp_tls_mode == "plain":
                raise ValueError("Production SMTP requires TLS")
        # A permitted origin whose host TrustedHostMiddleware would reject is a
        # contradiction that otherwise only shows up as an unexplained 400 much
        # later, so refuse to start instead.
        hosts = {h.strip().lower() for h in self.allowed_hosts.split(",") if h.strip()}
        for origin in permitted:
            origin_host = urlparse(origin).hostname or ""
            if origin_host.lower() not in hosts:
                raise ValueError(
                    f"Every permitted origin's host must appear in ALLOWED_HOSTS; "
                    f"'{origin_host}' from {origin} does not"
                )
        # One host on both schemes is the cookie-shadowing case: a Secure cookie
        # set on 443 is never sent on 80, while a non-Secure one is sent on both.
        # Rather than let the pair behave unpredictably, refuse the combination.
        schemes: dict[str, set[str]] = {}
        for origin in permitted:
            parsed = urlparse(origin)
            assert parsed.hostname is not None
            schemes.setdefault(parsed.hostname.lower(), set()).add(parsed.scheme)
        for hostname, found in schemes.items():
            if len(found) > 1:
                raise ValueError(
                    f"'{hostname}' is permitted on more than one scheme; "
                    "serve it on HTTPS only or use a distinct hostname"
                )
        return self

    def _permitted(self) -> tuple[str, ...]:
        """public_url first, then any extras, deduped and slash-normalised."""
        ordered = [self.public_url]
        ordered += [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]
        seen: dict[str, None] = {}
        for origin in ordered:
            seen.setdefault(origin, None)
        return tuple(seen)

    @staticmethod
    def _check_origin(origin: str) -> None:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"{origin} must be an absolute HTTP(S) origin")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(f"{origin} must not contain credentials, query, or fragment")
        if parsed.path not in {"", "/"}:
            raise ValueError(f"{origin} must not include a path")

    @property
    def permitted_origins(self) -> tuple[str, ...]:
        """Browser origins this installation accepts, for the Origin check.

        Exact membership only. SameSite=Lax already stops a cross-site request
        carrying the session cookie; this list is what covers the same-site case
        the cookie cannot, such as the same host on another port.
        """
        return self._permitted()

    @property
    def secure_cookies(self) -> bool:
        """Whether the session cookie may be marked Secure.

        True only when every permitted origin is HTTPS. A mixed set has to fall
        back to a cookie the HTTPS origins will still accept, which is the weaker
        but working choice, and the interface says so rather than staying quiet.
        """
        return all(urlparse(o).scheme == "https" for o in self._permitted())

    @property
    def database_url(self) -> SecretStr:
        value = self.database_url_file.read_text(encoding="utf-8").strip()
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("A PostgreSQL psycopg connection URL is required")
        return SecretStr(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
