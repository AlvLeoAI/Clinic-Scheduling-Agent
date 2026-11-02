"""Server-side provider selection through AGENT_PROVIDER, without an injected factory."""

import ast
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.agent.demo_provider import DemoProvider
from app.agent.provider import HttpResponsesProvider, build_provider
from app.core.clock import utc_now
from app.core.config import Settings
from app.db.models import BookingProposal, ChatSession, ChatTurn, ConversationItem
from app.db.seed import PRACTITIONER_IDS, TYPE_IDS, seed_catalog
from app.domain.scheduling import CLINIC_ZONE
from app.main import create_app
from cli.fake_provider import DemoProvider as CliDemoProvider

ROOT = Path(__file__).resolve().parents[1]
LOCAL = "postgresql+psycopg://clinic_demo:synthetic@127.0.0.1:15432/clinic_scheduling_dev"


def test_registry_maps_each_provider_value(monkeypatch):
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("ENABLE_LIVE_OPENAI", raising=False)

    def build(**values):
        return build_provider(Settings(_env_file=None, database_url=LOCAL, **values))

    assert build() is None
    assert build(agent_provider="disabled") is None
    assert isinstance(build(agent_provider="demo"), DemoProvider)
    assert isinstance(
        build(agent_provider="openai", openai_api_key="synthetic-key", openai_model="m"),
        HttpResponsesProvider,
    )


def test_cli_import_path_is_the_application_demo_provider():
    assert CliDemoProvider is DemoProvider


def test_application_package_never_imports_cli():
    for path in (ROOT / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(name == "cli" or name.startswith("cli.") for name in names), path


def next_bookable_weekday(now):
    day = (now.astimezone(CLINIC_ZONE) + timedelta(days=3)).date()
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


@pytest.fixture
def demo_server(engine, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with Session(engine) as db:
        seed_catalog(db)
        db.commit()
    settings = Settings(
        _env_file=None,
        database_url=engine.url.render_as_string(hide_password=False),
        agent_provider="demo",
    )
    owners = []
    # Real clock and no provider_factory: exactly what a deployed demo server does.
    with TestClient(create_app(settings, engine), raise_server_exceptions=False) as client:
        yield client, owners
    with Session(engine) as db:
        for owner in owners:
            db.get(ChatSession, owner).active_turn_id = None
        db.flush()
        for model in [BookingProposal, ConversationItem, ChatTurn]:
            db.execute(delete(model).where(model.session_id.in_(owners)))
        db.execute(delete(ChatSession).where(ChatSession.id.in_(owners)))
        db.commit()


@pytest.mark.postgres
@pytest.mark.api
def test_demo_server_uses_real_clock_and_marks_responses(demo_server):
    client, owners = demo_server
    session = client.post("/api/v1/sessions", json={}).json()
    owners.append(UUID(session["session_id"]))
    headers = {"Authorization": "Bearer " + session["session_token"]}

    def chat(message):
        return client.post(
            "/api/v1/chat/messages",
            headers=headers,
            json={"client_message_id": str(uuid4()), "message": message},
        )

    catalog = chat("catalog")
    assert catalog.status_code == 200
    assert catalog.headers["X-Agent-Provider"] == "demo"
    assert "Practitioners:" in catalog.json()["assistant_message"]

    day = next_bookable_weekday(utc_now()).isoformat()
    available = chat(f"availability {day} {PRACTITIONER_IDS[0]} {TYPE_IDS[0]}")
    assert available.status_code == 200
    assert available.headers["X-Agent-Provider"] == "demo"
    assert "returned these intervals" in available.json()["assistant_message"]

    proposed = chat(f"propose {day} 09:00 {PRACTITIONER_IDS[0]} {TYPE_IDS[0]}")
    assert proposed.status_code == 200
    assert proposed.json()["proposal"]["status"] == "PENDING"
