import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.db.safety import require_demo_database

LOCAL = "postgresql+psycopg://clinic_demo:synthetic@127.0.0.1:15432/clinic_scheduling_dev"


def test_config_no_provider_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    settings = Settings(_env_file=None, database_url=LOCAL)
    assert settings.session_ttl_hours == 24
    assert "synthetic" not in repr(settings)


@pytest.mark.parametrize("url", ["sqlite:///local.db", "postgresql://localhost/demo", "bad-value"])
def test_postgres_driver_required(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)


def test_config_errors_hide_values():
    sensitive = "sensitive-config-marker"
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, database_url=sensitive)
    assert sensitive not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    [
        LOCAL.replace("clinic_scheduling_dev", "production"),
        LOCAL.replace("127.0.0.1", "remote.example"),
        LOCAL.replace("clinic_demo:", "other_user:"),
        LOCAL + "?host=remote.example",
        "sqlite:///clinic_scheduling_test",
    ],
)
def test_seed_refuses_non_demo_targets(url):
    with pytest.raises(ValueError):
        require_demo_database(url)


def test_tests_refuse_development_database():
    with pytest.raises(ValueError):
        require_demo_database(LOCAL, test_only=True)


@pytest.fixture(autouse=True)
def no_provider_environment(monkeypatch):
    # Explicit AGENT_PROVIDER in the environment (CI, Makefile) must not leak into these.
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("ENABLE_LIVE_OPENAI", raising=False)


def settings(**values):
    return Settings(_env_file=None, database_url=LOCAL, **values)


def test_agent_provider_defaults_to_disabled():
    assert settings().effective_agent_provider == "disabled"


@pytest.mark.parametrize("value", ["demo", " Demo ", "DEMO"])
def test_agent_provider_values_are_normalized(value):
    assert settings(agent_provider=value).effective_agent_provider == "demo"


def test_empty_agent_provider_means_unset():
    assert settings(agent_provider="").agent_provider is None


def test_unknown_agent_provider_rejected():
    with pytest.raises(ValidationError):
        settings(agent_provider="anthropic")


def test_deprecated_live_flag_selects_openai():
    configured = settings(
        enable_live_openai=True, openai_api_key="synthetic-key", openai_model="synthetic-model"
    )
    assert configured.effective_agent_provider == "openai"
    # Evaluation runners switch providers with model_copy, which skips validators.
    assert settings().model_copy(update={"enable_live_openai": True}).effective_agent_provider == (
        "openai"
    )


@pytest.mark.parametrize("provider", ["disabled", "demo"])
def test_live_flag_conflicting_with_provider_rejected(provider):
    with pytest.raises(ValidationError):
        settings(agent_provider=provider, enable_live_openai=True)


@pytest.mark.parametrize(
    "values",
    [{}, {"openai_model": "synthetic-model"}, {"openai_api_key": "synthetic-key"}],
)
def test_openai_provider_requires_key_and_model(values):
    with pytest.raises(ValidationError):
        settings(agent_provider="openai", **values)
