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
