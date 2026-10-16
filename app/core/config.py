"""Foundation needs no vendor credentials; live agent access is explicitly disabled by default."""

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: SecretStr
    test_database_url: SecretStr | None = None
    session_ttl_hours: int = Field(default=24, gt=0)
    enable_live_openai: bool = False
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    provider_timeout_seconds: float = Field(default=30, gt=0, le=120)
    turn_lease_seconds: int = Field(default=90, ge=10, le=600)
    provider_max_output_tokens: int = Field(default=2048, ge=256, le=4096)

    @field_validator("openai_model")
    @classmethod
    def optional_model(cls, value):
        return value.strip() or None if value is not None else None

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
