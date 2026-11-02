"""Runtime settings; no vendor credentials are needed and chat is disabled by default."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

AgentProvider = Literal["disabled", "demo", "openai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: SecretStr
    test_database_url: SecretStr | None = None
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

    @field_validator("openai_model")
    @classmethod
    def optional_model(cls, value):
        return value.strip() or None if value is not None else None

    @field_validator("agent_provider", mode="before")
    @classmethod
    def optional_provider(cls, value):
        return value.strip().lower() or None if isinstance(value, str) else value

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
