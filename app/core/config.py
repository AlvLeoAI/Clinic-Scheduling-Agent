"""Runtime settings; no vendor credentials are needed and chat is disabled by default."""

import re
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

AgentProvider = Literal["disabled", "demo", "openai"]
HOSTNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: SecretStr
    # Optional password merged into a password-less DATABASE_URL, so a secret store can
    # inject it on its own (ECS secrets) without building a URL in a shell.
    database_password: SecretStr | None = None
    test_database_url: SecretStr | None = None
    # Comma-separated exact hostnames that migrations and seeding may target besides
    # loopback (a compose service name, an RDS endpoint). Empty by default.
    database_allowed_hosts: str = ""
    session_ttl_hours: int = Field(default=24, gt=0)
    agent_provider: AgentProvider | None = None
    # Deprecated alias: true selects "openai" when AGENT_PROVIDER is unset.
    enable_live_openai: bool = False
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    provider_timeout_seconds: float = Field(default=30, gt=0, le=120)
    turn_lease_seconds: int = Field(default=90, ge=10, le=600)
    provider_max_output_tokens: int = Field(default=2048, ge=256, le=4096)
    chat_retention_days: int = Field(default=30, ge=1)
    # Swagger UI, ReDoc and the OpenAPI document; the deployed API turns them off.
    api_docs_enabled: bool = True

    @field_validator("openai_model")
    @classmethod
    def optional_model(cls, value):
        return value.strip() or None if value is not None else None

    @field_validator("agent_provider", mode="before")
    @classmethod
    def optional_provider(cls, value):
        return value.strip().lower() or None if isinstance(value, str) else value

    @field_validator("database_allowed_hosts")
    @classmethod
    def exact_hostnames(cls, value: str) -> str:
        for host in filter(None, (part.strip() for part in value.split(","))):
            if not HOSTNAME.fullmatch(host):
                raise ValueError("DATABASE_ALLOWED_HOSTS takes exact hostnames only.")
        return value

    @property
    def allowed_database_hosts(self) -> frozenset[str]:
        return frozenset(
            filter(None, (part.strip() for part in self.database_allowed_hosts.split(",")))
        )

    @property
    def effective_agent_provider(self) -> AgentProvider:
        # A property, not a validator: evaluation runners switch providers via model_copy.
        if self.agent_provider is not None:
            return self.agent_provider
        return "openai" if self.enable_live_openai else "disabled"

    @model_validator(mode="after")
    def provider_is_consistent(self):
        if self.agent_provider not in (None, "openai") and self.enable_live_openai:
            raise ValueError("ENABLE_LIVE_OPENAI conflicts with the selected AGENT_PROVIDER.")
        if self.agent_provider == "openai" and (
            self.openai_api_key is None
            or not self.openai_api_key.get_secret_value()
            or not self.openai_model
        ):
            raise ValueError("AGENT_PROVIDER=openai requires OPENAI_API_KEY and OPENAI_MODEL.")
        return self

    @model_validator(mode="after")
    def merge_database_password(self):
        if self.database_password is None or not self.database_password.get_secret_value():
            return self
        url = make_url(self.database_url.get_secret_value())
        if url.password is not None:
            raise ValueError("Set the database password in DATABASE_URL or DATABASE_PASSWORD.")
        merged = url.set(password=self.database_password.get_secret_value())
        self.database_url = SecretStr(merged.render_as_string(hide_password=False))
        return self

    @model_validator(mode="after")
    def lease_covers_timeout(self):
        if self.turn_lease_seconds <= self.provider_timeout_seconds:
            raise ValueError("The turn lease must exceed the provider timeout.")
        return self

    @field_validator("database_url", "test_database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        try:
            parsed = make_url(value.get_secret_value())
        except Exception:
            raise ValueError("A PostgreSQL psycopg URL is required") from None
        if parsed.drivername != "postgresql+psycopg" or not parsed.database:
            raise ValueError("A PostgreSQL psycopg URL is required")
        return value
