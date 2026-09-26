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
        parsed = urlparse(self.public_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("PUBLIC_URL must be an absolute HTTP(S) origin")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("PUBLIC_URL must not contain credentials, query, or fragment")
        if parsed.path not in {"", "/"}:
            raise ValueError("PUBLIC_URL must not include a path")
        if self.env == "production":
            if parsed.scheme != "https" or parsed.hostname.endswith(".invalid"):
                raise ValueError("Production requires a configured HTTPS origin")
            if self.smtp_host and self.smtp_tls_mode == "plain":
                raise ValueError("Production SMTP requires TLS")
        self.public_url = self.public_url.rstrip("/")
        return self

    @property
    def database_url(self) -> SecretStr:
        value = self.database_url_file.read_text(encoding="utf-8").strip()
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("A PostgreSQL psycopg connection URL is required")
        return SecretStr(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
