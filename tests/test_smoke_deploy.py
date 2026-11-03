"""Post-deploy smoke against the real app on PostgreSQL, through an in-process client.

Faulty APIs are simulated by wrapping the client: an altered replay, a second booking
and a failing readiness check must each make the smoke exit non-zero.
"""

import json
from datetime import date, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    Appointment,
    BookingProposal,
    ChatSession,
    ChatTurn,
    ConversationItem,
    IdempotencyRecord,
)
from app.db.seed import seed_catalog
from app.main import create_app
from scripts import smoke_deploy
from tests.conftest import NOW

pytestmark = [pytest.mark.postgres, pytest.mark.api]
BASE = "http://api.test"


@pytest.fixture
def deployed(engine, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with Session(engine) as db:
        seed_catalog(db)
        db.commit()
    settings = Settings(
        _env_file=None,
        database_url=engine.url.render_as_string(hide_password=False),
        agent_provider="demo",
    )
    owners: list[UUID] = []
    with TestClient(create_app(settings, engine, clock=lambda: NOW)) as client:

        def http(method, url, body, headers):
            response = client.request(method, url.removeprefix(BASE), json=body, headers=headers)
            if method == "POST" and url.endswith("/sessions") and response.status_code == 201:
                owners.append(UUID(response.json()["session_id"]))
            return response.status_code, response.content

        yield http
    with Session(engine) as db:
        db.execute(
            update(ChatSession).where(ChatSession.id.in_(owners)).values(active_turn_id=None)
        )
        for model in [IdempotencyRecord, Appointment, BookingProposal, ConversationItem, ChatTurn]:
            db.execute(delete(model).where(model.session_id.in_(owners)))
        db.execute(delete(ChatSession).where(ChatSession.id.in_(owners)))
        db.commit()


def run(http, capsys):
    code = smoke_deploy.main(["--api", BASE, "--wait", "0"], http=http, today=NOW.date())
    return code, capsys.readouterr().out


def test_smoke_books_once_and_requires_an_identical_replay(deployed, engine, capsys):
    code, out = run(deployed, capsys)
    assert code == 0, out
    result = json.loads(out.strip().splitlines()[-1])
    assert result["smoke"] == "ok"
    with Session(engine) as db:
        booked = db.get(Appointment, UUID(result["appointment_id"]))
        assert booked is not None
        assert (
            db.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.appointment_id == booked.id)
            )
            == 1
        )
    # The last free slot of the horizon, away from the dates a demo would pick.
    _, raw = deployed("GET", f"{BASE}/api/v1/info", None, {})
    horizon_end = NOW.date() + timedelta(days=json.loads(raw)["max_horizon_days"])
    assert 0 <= (horizon_end - date.fromisoformat(result["slot"][:10])).days < 7
    assert "synthetic-bearer" not in out and "Bearer" not in out


def test_an_altered_replay_fails_the_smoke(deployed, capsys):
    confirms = []

    def http(method, url, body, headers):
        status, raw = deployed(method, url, body, headers)
        if url.endswith("/confirm"):
            confirms.append(raw)
            if len(confirms) == 2:
                raw = raw.replace(b'"trace_id":"', b'"trace_id":"0', 1)
        return status, raw

    code, out = run(http, capsys)
    assert code == 1 and "FAIL replay has a byte-identical body" in out


def test_a_second_booking_on_replay_fails_the_smoke(deployed, capsys):
    # A client or proxy that drops the key's reuse books again instead of replaying.
    def http(method, url, body, headers):
        if url.endswith("/confirm") and headers.get("Idempotency-Key", "").startswith("smoke-"):
            http.calls = getattr(http, "calls", 0) + 1
            if http.calls == 2:
                headers = {**headers, "Idempotency-Key": "smoke-other"}
        return deployed(method, url, body, headers)

    code, out = run(http, capsys)
    assert code == 1 and "FAIL replay has the same status" in out


def test_failing_readiness_fails_the_smoke(deployed, capsys):
    def http(method, url, body, headers):
        if url.endswith("/health"):
            return 503, b'{"error":{"code":"SERVICE_UNAVAILABLE"}}'
        return deployed(method, url, body, headers)

    code, out = run(http, capsys)
    assert code == 1 and "FAIL readiness" in out
