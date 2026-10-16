import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.context import ContextLimit, selected_context
from app.agent.protocol import ProviderResponse
from app.agent.tools import execute_tool, validate_arguments
from app.core.errors import ApiError
from app.db.models import BookingProposal, ChatSession, ChatTurn, ConversationItem
from app.db.seed import PRACTITIONER_IDS, TYPE_IDS, seed_catalog
from app.schemas.chat import ChatResponse
from app.services.conversation import Completed, ConversationStore
from tests.conftest import NOW

pytestmark = pytest.mark.postgres


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def owner_store(engine):
    clock = Clock()
    with Session(engine) as db:
        seed_catalog(db)
        row = ChatSession(
            token_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
            created_at=NOW,
            expires_at=NOW + timedelta(hours=24),
        )
        db.add(row)
        db.flush()
        owner = row.id
        db.commit()
    store = ConversationStore(engine, clock, 90)
    try:
        yield owner, store, clock
    finally:
        with Session(engine) as db:
            row = db.get(ChatSession, owner)
            row.active_turn_id = None
            db.flush()
            for model in [BookingProposal, ConversationItem, ChatTurn]:
                db.execute(delete(model).where(model.session_id == owner))
            db.delete(row)
            db.commit()


def claim(owner, store, text="synthetic", message_id=None):
    return store.claim(owner, message_id or uuid4(), text, uuid4())


def finish(store, lease, text="synthetic"):
    response = ProviderResponse(
        status="completed",
        output=[
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    )
    store.persist_response(lease, response)
    body = ChatResponse(
        turn_id=lease.turn_id,
        assistant_message="Synthetic test reply.",
        proposal=None,
        trace_id=lease.trace_id,
    ).model_dump(mode="json")
    with store.transaction() as db:
        store.complete(db, lease, body)
    return body


def test_completed_message_dedup_and_payload_conflict(owner_store):
    owner, store, _clock = owner_store
    ident = uuid4()
    lease = claim(owner, store, message_id=ident)
    body = finish(store, lease)
    replay = claim(owner, store, message_id=ident)
    assert isinstance(replay, Completed) and replay.body == body
    with pytest.raises(ApiError) as caught:
        claim(owner, store, text="different synthetic content", message_id=ident)
    assert caught.value.code == "MESSAGE_ID_REUSED"
    with Session(store.engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(ChatTurn).where(ChatTurn.session_id == owner)
            )
            == 1
        )
        row = db.get(ChatSession, owner)
        assert row.active_turn_id is None and row.lease_expires_at is None


def test_in_progress_same_or_competing_message_rejected(owner_store):
    owner, store, _clock = owner_store
    ident = uuid4()
    claim(owner, store, message_id=ident)
    for message_id in [ident, uuid4()]:
        with pytest.raises(ApiError) as caught:
            claim(owner, store, message_id=message_id)
        assert caught.value.code == "TURN_IN_PROGRESS"


def test_expired_lease_reclaim_fences_old_owner(owner_store):
    owner, store, clock = owner_store
    ident = uuid4()
    old = claim(owner, store, message_id=ident)
    clock.now += timedelta(seconds=90)
    new = claim(owner, store, message_id=ident)
    assert new.turn_id == old.turn_id and new.fence == old.fence + 1
    with pytest.raises(ApiError):
        with store.transaction() as db:
            store.append(
                db, old, "message", {"type": "message", "role": "assistant", "content": []}
            )
    with pytest.raises(ApiError):
        store.fail(old)
    with Session(store.engine) as db:
        assert db.get(ChatSession, owner).lease_fence == new.fence
        assert db.get(ChatTurn, old.turn_id).status == "IN_PROGRESS"
        assert (
            db.scalar(
                select(func.count())
                .select_from(ConversationItem)
                .where(ConversationItem.turn_id == old.turn_id)
            )
            == 1
        )


def proposal_arguments():
    return json.dumps(
        {
            "practitioner_id": str(PRACTITIONER_IDS[0]),
            "appointment_type_id": str(TYPE_IDS[0]),
            "local_date": "2030-01-09",
            "local_time": "09:00",
        }
    )


@pytest.mark.parametrize("fail", [False, True])
def test_m3_proposal_and_journal_share_outer_commit(owner_store, fail):
    owner, store, clock = owner_store
    lease = claim(owner, store)
    parsed, error = validate_arguments("create_booking_proposal", proposal_arguments())
    assert error is None
    try:
        with store.transaction() as db:
            store.guard(db, lease)
            result = execute_tool(
                "create_booking_proposal", parsed, db, owner, lease.turn_id, lease.trace_id, clock
            )
            assert result["ok"] is True
            store.append(
                db,
                lease,
                "function_call_output",
                {"type": "function_call_output", "call_id": "call_1", "output": json.dumps(result)},
                "call_1",
            )
            if fail:
                raise RuntimeError("test-only outer rollback")
    except RuntimeError:
        assert fail
    with Session(store.engine) as db:
        rows = db.scalars(select(BookingProposal).where(BookingProposal.session_id == owner)).all()
        assert len(rows) == (0 if fail else 1)
        if rows:
            assert rows[0].source_turn_id == lease.turn_id and rows[0].status == "PENDING"
        assert db.scalar(
            select(func.count())
            .select_from(ConversationItem)
            .where(
                ConversationItem.turn_id == lease.turn_id,
                ConversationItem.item_type == "function_call_output",
            )
        ) == (0 if fail else 1)


def test_expiry_during_tool_rolls_back_unchanged_m3_service_effect(owner_store):
    owner, store, clock = owner_store
    lease = claim(owner, store)
    parsed, _ = validate_arguments("create_booking_proposal", proposal_arguments())
    with pytest.raises(ApiError):
        with store.transaction() as db:
            store.guard(db, lease)
            result = execute_tool(
                "create_booking_proposal", parsed, db, owner, lease.turn_id, lease.trace_id, clock
            )
            assert result["ok"]
            clock.now += timedelta(seconds=91)
            store.guard(db, lease)
    with Session(store.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(BookingProposal)
                .where(BookingProposal.session_id == owner)
            )
            == 0
        )


def test_postgresql_source_turn_uniqueness_rolls_back_replacement(owner_store):
    owner, store, clock = owner_store
    lease = claim(owner, store)
    args, _ = validate_arguments("create_booking_proposal", proposal_arguments())
    with store.transaction() as db:
        store.guard(db, lease)
        first = execute_tool(
            "create_booking_proposal", args, db, owner, lease.turn_id, lease.trace_id, clock
        )
        assert first["ok"]
    changed = json.loads(proposal_arguments())
    changed["local_time"] = "10:00"
    args, _ = validate_arguments("create_booking_proposal", json.dumps(changed))
    with pytest.raises(IntegrityError) as caught:
        with store.transaction() as db:
            store.guard(db, lease)
            execute_tool(
                "create_booking_proposal", args, db, owner, lease.turn_id, lease.trace_id, clock
            )
    assert caught.value.orig.sqlstate == "23505"
    assert caught.value.orig.diag.constraint_name == "uq_booking_proposals_source_turn_id"
    with Session(store.engine) as db:
        rows = db.scalars(select(BookingProposal).where(BookingProposal.session_id == owner)).all()
        assert (
            len(rows) == 1
            and rows[0].status == "PENDING"
            and rows[0].source_turn_id == lease.turn_id
        )
        assert str(rows[0].id) == first["data"]["proposal_id"]


def test_context_last_eight_turns_and_restart(owner_store):
    owner, store, clock = owner_store
    for index in range(10):
        lease = claim(owner, store, text=f"synthetic turn {index}")
        finish(store, lease, text=f"synthetic answer {index}")
    current = claim(owner, store, text="synthetic current")
    restarted = ConversationStore(store.engine, clock, 90)
    with restarted.transaction() as db:
        items = selected_context(db, owner, current.turn_id)
    messages = [item["content"] for item in items if item.get("role") == "user"]
    assert messages == [*(f"synthetic turn {index}" for index in range(2, 10)), "synthetic current"]
    assert len(items) == 17


def test_context_drops_whole_turns_without_cutting_reasoning_or_tool_pairs(owner_store):
    owner, store, _clock = owner_store
    encrypted = "synthetic-opaque-" * 600
    for index in range(3):
        lease = claim(owner, store, text=f"synthetic turn {index}")
        store.persist_response(
            lease,
            ProviderResponse(
                status="completed",
                output=[
                    {"type": "reasoning", "summary": [], "encrypted_content": encrypted},
                    {
                        "type": "function_call",
                        "call_id": f"call_{index}",
                        "name": "get_clinic_catalog",
                        "arguments": "{}",
                    },
                ],
            ),
        )
        with store.transaction() as db:
            store.append(
                db,
                lease,
                "function_call_output",
                {
                    "type": "function_call_output",
                    "call_id": f"call_{index}",
                    "output": '{"ok":true}',
                },
                f"call_{index}",
            )
        finish(store, lease)
    current = claim(owner, store, text="synthetic current")
    with store.transaction() as db:
        items = selected_context(db, owner, current.turn_id, overhead_chars=5000)
    reasoning = [item for item in items if item.get("type") == "reasoning"]
    assert len(reasoning) == 1 and reasoning[0]["encrypted_content"] == encrypted
    calls = [item["call_id"] for item in items if item.get("type") == "function_call"]
    outputs = [item["call_id"] for item in items if item.get("type") == "function_call_output"]
    assert calls == outputs == ["call_2"]


def test_oversized_current_item_rejected_whole(owner_store):
    owner, store, _clock = owner_store
    lease = claim(owner, store)
    with pytest.raises(ContextLimit):
        store.persist_response(
            lease,
            ProviderResponse(
                status="completed",
                output=[{"type": "reasoning", "summary": [], "encrypted_content": "x" * 24001}],
            ),
        )
    with Session(store.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ConversationItem)
                .where(ConversationItem.turn_id == lease.turn_id)
            )
            == 1
        )
