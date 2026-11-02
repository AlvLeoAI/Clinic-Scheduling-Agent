"""Retention purge: removes stored chat text only, never bookings or replay records."""

import json
from datetime import timedelta
from uuid import UUID, uuid4

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
from app.db.seed import PRACTITIONER_IDS, TYPE_IDS, seed_catalog
from app.main import create_app
from app.services.retention import PURGED_REQUEST_HASH, purge_expired_chat
from scripts import purge_chat
from tests.conftest import NOW

pytestmark = [pytest.mark.postgres, pytest.mark.api]


class Retention:
    def __init__(self, engine, client):
        self.engine, self.client, self.owners = engine, client, []

    def session(self):
        data = self.client.post("/api/v1/sessions", json={}).json()
        self.owners.append(UUID(data["session_id"]))
        return UUID(data["session_id"]), {"Authorization": "Bearer " + data["session_token"]}

    def chat(self, headers, message, message_id=None):
        response = self.client.post(
            "/api/v1/chat/messages",
            headers=headers,
            json={"client_message_id": str(message_id or uuid4()), "message": message},
        )
        assert response.status_code == 200, response.text
        return response

    def expire(self, session_id, days_ago):
        # created_at moves too: the expiry CHECK requires expires_at > created_at.
        with Session(self.engine) as db, db.begin():
            db.execute(
                update(ChatSession)
                .where(ChatSession.id == session_id)
                .values(
                    created_at=NOW - timedelta(days=days_ago + 1),
                    expires_at=NOW - timedelta(days=days_ago),
                )
            )

    def snapshot(self, session_id):
        with Session(self.engine) as db:

            def rows(model):
                return sorted(
                    (
                        {c.name: str(getattr(row, c.key)) for c in model.__table__.columns}
                        for row in db.scalars(select(model).where(model.session_id == session_id))
                    ),
                    key=lambda row: row["id"],
                )

            return {
                "items": db.scalar(
                    select(func.count())
                    .select_from(ConversationItem)
                    .where(ConversationItem.session_id == session_id)
                ),
                "hashes": sorted(
                    db.scalars(
                        select(ChatTurn.request_hash).where(ChatTurn.session_id == session_id)
                    )
                ),
                "turn_ids": sorted(
                    str(i)
                    for i in db.scalars(
                        select(ChatTurn.id).where(ChatTurn.session_id == session_id)
                    )
                ),
                "session": db.get(ChatSession, session_id) is not None,
                "proposals": rows(BookingProposal),
                "appointments": rows(Appointment),
                "idempotency": rows(IdempotencyRecord),
            }

    def purge(self, *, apply, days=30):
        with Session(self.engine) as db, db.begin():
            return purge_expired_chat(db, now=NOW, retention_days=days, apply=apply)


@pytest.fixture
def retention(engine, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with Session(engine) as db:
        seed_catalog(db)
        db.commit()
    settings = Settings(
        _env_file=None,
        database_url=engine.url.render_as_string(hide_password=False),
        agent_provider="demo",
    )
    app = create_app(settings, engine, clock=lambda: NOW)
    with TestClient(app, raise_server_exceptions=False) as client:
        instance = Retention(engine, client)
        yield instance
    with Session(engine) as db:
        owners = instance.owners
        db.execute(
            update(ChatSession).where(ChatSession.id.in_(owners)).values(active_turn_id=None)
        )
        for model in [
            IdempotencyRecord,
            Appointment,
            BookingProposal,
            ConversationItem,
            ChatTurn,
        ]:
            db.execute(delete(model).where(model.session_id.in_(owners)))
        db.execute(delete(ChatSession).where(ChatSession.id.in_(owners)))
        db.commit()


def test_purge_removes_only_chat_text_of_sessions_expired_beyond_retention(retention):
    # Booked session: chat, proposal through chat, confirmed appointment, idempotency record.
    booked, booked_auth = retention.session()
    retention.chat(booked_auth, "catalog")
    proposal = retention.chat(
        booked_auth, f"propose 2030-01-09 09:00 {PRACTITIONER_IDS[0]} {TYPE_IDS[0]}"
    ).json()["proposal"]
    confirmed = retention.client.post(
        f"/api/v1/proposals/{proposal['proposal_id']}/confirm",
        headers={**booked_auth, "Idempotency-Key": "retention-key"},
    )
    assert confirmed.status_code == 201

    active, active_auth = retention.session()
    message_id = uuid4()
    first = retention.chat(active_auth, "catalog", message_id)
    in_window, in_window_auth = retention.session()
    retention.chat(in_window_auth, "catalog")
    leased, leased_auth = retention.session()
    retention.chat(leased_auth, "catalog")

    retention.expire(booked, days_ago=31)
    retention.expire(in_window, days_ago=29)
    retention.expire(leased, days_ago=31)
    with Session(retention.engine) as db, db.begin():
        turn = db.scalar(select(ChatTurn.id).where(ChatTurn.session_id == leased))
        db.execute(
            update(ChatSession)
            .where(ChatSession.id == leased)
            .values(active_turn_id=turn, lease_expires_at=NOW + timedelta(minutes=1))
        )

    before = {owner: retention.snapshot(owner) for owner in retention.owners}
    assert before[booked]["items"] > 0 and len(before[booked]["appointments"]) == 1

    dry = retention.purge(apply=False)
    assert dry.eligible_sessions >= 1 and dry.conversation_items >= before[booked]["items"]
    assert {owner: retention.snapshot(owner) for owner in retention.owners} == before

    applied = retention.purge(apply=True)
    assert applied == dry
    after = {owner: retention.snapshot(owner) for owner in retention.owners}

    purged = after[booked]
    assert purged["items"] == 0
    assert set(purged["hashes"]) == {PURGED_REQUEST_HASH}
    for kept in ["session", "turn_ids", "proposals", "appointments", "idempotency"]:
        assert purged[kept] == before[booked][kept], kept
    for untouched in [active, in_window, leased]:
        assert after[untouched] == before[untouched]

    rerun = retention.purge(apply=True)
    assert (rerun.conversation_items, rerun.turn_hashes) == (0, 0)

    # A session that was not purged still replays its completed turn byte-for-byte.
    replay = retention.chat(active_auth, "catalog", message_id)
    assert replay.json() == first.json()


def test_purge_command_defaults_to_dry_run(retention, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", retention.engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("AGENT_PROVIDER", "disabled")
    monkeypatch.setattr(purge_chat, "Settings", lambda: Settings(_env_file=None))
    calls = []
    original = purge_chat.purge_expired_chat
    monkeypatch.setattr(
        purge_chat,
        "purge_expired_chat",
        lambda db, **kwargs: calls.append(kwargs) or original(db, **kwargs),
    )
    assert purge_chat.main(["--retention-days", "45"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run" and output["retention_days"] == 45
    assert calls[0]["apply"] is False and calls[0]["retention_days"] == 45
    with pytest.raises(SystemExit):
        purge_chat.main(["--retention-days", "0"])
