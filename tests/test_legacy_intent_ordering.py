"""Pre-fix journal fixtures: no birth marker, no timestamp-derived mutation right.

The private transition harness additionally creates A-F with the actual old app.
These small fixtures keep the legacy-state regressions runnable from source alone.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.agent.protocol import ProviderResponse
from app.core.errors import ApiError
from app.db.models import BookingProposal, ChatSession, ChatTurn, ConversationItem
from app.services.chat import ChatService
from app.services.conversation import ConversationStore, Lease, message_fingerprint
from app.services.intent import INTENT_ORIGIN, STALE_INTENT
from app.services.scheduling import SchedulingService
from tests import test_chat as helpers
from tests.test_chat import call, final, parsed, proposal_args

harness = helpers.harness
pytestmark = [pytest.mark.postgres, pytest.mark.agent_offline]
MESSAGE = "Synthetic pre-fix scheduling request"


def legacy_turn(h, *, pending=True, tool="create_booking_proposal"):
    owner = h.owner()
    sid, ident = h.owners[-1], uuid4()
    store = ConversationStore(h.engine, h.clock, h.settings.turn_lease_seconds)
    with store.transaction() as db:
        session = db.scalar(select(ChatSession).where(ChatSession.id == sid).with_for_update())
        turn = ChatTurn(
            session_id=sid,
            client_message_id=ident,
            request_hash=message_fingerprint(MESSAGE),
            status="IN_PROGRESS",
            trace_id=uuid4(),
            created_at=h.clock(),
        )
        db.add(turn)
        db.flush()
        db.add(
            ConversationItem(
                session_id=sid,
                turn_id=turn.id,
                sequence=0,
                item_type="user_message",
                payload={"role": "user", "content": MESSAGE},
                created_at=h.clock(),
            )
        )
        session.active_turn_id = turn.id
        session.lease_fence += 1
        session.lease_expires_at = h.clock() + timedelta(seconds=h.settings.turn_lease_seconds)
        lease = Lease(sid, turn.id, session.lease_fence, turn.trace_id)
    item = None
    if pending:
        response = ProviderResponse.model_validate(
            call(tool, proposal_args() if tool == "create_booking_proposal" else {}, "legacy_call")
        )
        store.persist_response(lease, response)
        item = response.output[-1]
    assert not origin(h, lease)
    return owner, store, ident, lease, item


def expire(h):
    h.clock.now += timedelta(seconds=h.settings.turn_lease_seconds + 1)


def origin(h, lease):
    with Session(h.engine) as db:
        return db.scalars(
            select(ConversationItem).where(
                ConversationItem.turn_id == lease.turn_id,
                ConversationItem.item_type == INTENT_ORIGIN,
            )
        ).all()


def legacy_history(db, h, sid, *, status="PENDING"):
    """Persist the baseline proposal shape without the later marker feature."""
    db.scalar(select(ChatSession).where(ChatSession.id == sid).with_for_update())
    from app.schemas.booking import ProposalRequest

    args = ProposalRequest.model_validate(proposal_args(local_time="10:00"))
    candidate = SchedulingService(db).candidate(
        local_date=args.local_date,
        local_time=args.local_time,
        practitioner_id=args.practitioner_id,
        appointment_type_id=args.appointment_type_id,
        now_utc=h.clock(),
    )
    for pending in db.scalars(
        select(BookingProposal).where(
            BookingProposal.session_id == sid,
            BookingProposal.status == "PENDING",
        )
    ):
        pending.status = "SUPERSEDED"
    db.flush()
    row = BookingProposal(
        session_id=sid,
        clinic_id=candidate.clinic_id,
        practitioner_id=candidate.practitioner_id,
        appointment_type_id=candidate.appointment_type_id,
        duration_minutes=candidate.duration_minutes,
        starts_at=candidate.interval.starts_at,
        ends_at=candidate.interval.ends_at,
        created_at=h.clock(),
        expires_at=h.clock() + timedelta(minutes=10),
        status=status,
    )
    db.add(row)
    db.flush()
    return row.id


def accepted_history(h, sid, **kw):
    with Session(h.engine) as db, db.begin():
        return legacy_history(db, h, sid, **kw)


def proposals(h):
    with Session(h.engine) as db:
        return list(
            db.execute(
                select(
                    BookingProposal.id,
                    BookingProposal.status,
                    BookingProposal.starts_at,
                    BookingProposal.ends_at,
                    BookingProposal.source_turn_id,
                )
                .where(BookingProposal.session_id.in_(h.owners))
                .order_by(BookingProposal.id)
            )
        )


def assert_uncertain(response):
    assert response.status_code == 409
    body = response.json()
    assert set(body) == {"error", "trace_id"}
    assert body["error"]["code"] == "STALE_INTENT" and body["error"]["retryable"] is False
    assert (
        "ordering" in body["error"]["message"] and "cannot be verified" in body["error"]["message"]
    )
    assert "Send a new message" in body["error"]["message"]
    assert body["trace_id"] == response.headers["X-Trace-ID"]


@pytest.mark.parametrize("status", ["PENDING", "EXPIRED", "SUPERSEDED"])
def test_legacy_unknown_order_preserves_all_proposal_history_on_restart(harness, status):
    h = harness
    owner, _, ident, lease, _ = legacy_turn(h)
    expire(h)
    accepted_history(h, lease.session_id, status=status)
    before = proposals(h)
    restarted_engine, client = h.restart()
    try:
        with client:
            for _ in range(2):
                assert_uncertain(h.chat(owner, MESSAGE, ident, client=client)[0])
    finally:
        restarted_engine.dispose()
    assert proposals(h) == before and h.provider.requests == [] and not origin(h, lease)
    assert h.counts()["appointments"] == 0


@pytest.mark.parametrize("pending", [False, True])
def test_legacy_uncontested_recovery_and_result_replay(harness, pending):
    h = harness
    owner, store, ident, lease, _ = legacy_turn(h, pending=pending)
    if not pending:
        store.fail(lease)
        h.provider.steps.append(call("create_booking_proposal", proposal_args()))
    expire(h)
    h.provider.steps.append(final("proposal"))
    r, _ = h.chat(owner, MESSAGE, ident)
    body = parsed(r)
    assert body.proposal.status == "PENDING" and body.proposal.session_id == lease.session_id
    assert not origin(h, lease)
    state, counts = proposals(h), h.counts()
    assert h.chat(owner, MESSAGE, ident)[0].content == r.content
    assert proposals(h) == state and h.counts() == counts


def test_legacy_without_pending_call_cannot_get_new_origin_on_retry(harness):
    h = harness
    owner, store, ident, lease, _ = legacy_turn(h, pending=False)
    store.fail(lease)
    accepted_history(h, lease.session_id)
    before = proposals(h)
    h.provider.steps.append(call("create_booking_proposal", proposal_args()))
    assert_uncertain(h.chat(owner, MESSAGE, ident)[0])
    assert not origin(h, lease) and proposals(h) == before
    assert len(h.provider.requests) == 1  # F2 aggregate attempts remain a separate limitation.


def test_legacy_journaled_effect_recovers_without_mutating_newer_proposal(harness):
    h = harness
    owner, store, ident, lease, item = legacy_turn(h)
    ChatService(h.engine, h.settings, h.clock, h.provider)._execute(lease, item)
    with store.transaction() as db:
        original = [
            (r.call_id, r.payload)
            for r in store.rows(db, lease)
            if r.item_type == "function_call_output"
        ]
    expire(h)
    accepted_history(h, lease.session_id)
    before = proposals(h)
    h.provider.steps.append(final("proposal"))
    body = parsed(h.chat(owner, MESSAGE, ident)[0])
    assert body.proposal.status == "SUPERSEDED" and proposals(h) == before
    with store.transaction() as db:
        assert [
            (r.call_id, r.payload)
            for r in store.rows(db, lease)
            if r.item_type == "function_call_output"
        ] == original
    assert len(h.provider.requests) == 1 and not origin(h, lease)


def test_completed_legacy_response_replays_before_unknown_order_guard(harness):
    h = harness
    owner, _, ident, lease, _ = legacy_turn(h)
    expire(h)
    h.provider.steps.append(final("proposal"))
    first = parsed(h.chat(owner, MESSAGE, ident)[0])
    accepted_history(h, lease.session_id)
    before, counts, calls = proposals(h), h.counts(), len(h.provider.requests)
    replay = parsed(h.chat(owner, MESSAGE, ident)[0])
    assert replay.proposal.proposal_id == first.proposal.proposal_id
    assert replay.proposal.status == "SUPERSEDED"
    assert (replay.assistant_message, replay.trace_id, replay.turn_id) == (
        first.assistant_message,
        first.trace_id,
        first.turn_id,
    )
    assert proposals(h) == before and h.counts() == counts and len(h.provider.requests) == calls


def test_other_session_history_cannot_block_legacy_owner(harness):
    h = harness
    owner, _, ident, lease, _ = legacy_turn(h)
    h.owner()
    accepted_history(h, h.owners[-1])
    expire(h)
    h.provider.steps.append(final("proposal"))
    assert parsed(h.chat(owner, MESSAGE, ident)[0]).proposal.session_id == lease.session_id


def test_expired_legacy_session_cannot_recover_or_mutate(harness):
    h = harness
    owner, _, ident, lease, _ = legacy_turn(h)
    accepted_history(h, lease.session_id)
    before, counts = proposals(h), h.counts()
    h.clock.now += timedelta(hours=25)
    assert h.chat(owner, MESSAGE, ident)[0].status_code == 401
    assert proposals(h) == before and h.counts() == counts and h.provider.requests == []


def test_read_only_legacy_recovery_still_works_with_proposal_history(harness):
    h = harness
    owner, _, ident, lease, _ = legacy_turn(h, tool="get_clinic_catalog")
    accepted_history(h, lease.session_id)
    before = proposals(h)
    expire(h)
    h.provider.steps.append(final("catalog"))
    assert h.chat(owner, MESSAGE, ident)[0].status_code == 200 and proposals(h) == before
    assert not origin(h, lease)


def test_fresh_message_after_legacy_rejection_has_trusted_origin_and_recovers(harness):
    h = harness
    owner, _, ident, lease, _ = legacy_turn(h)
    accepted_history(h, lease.session_id)
    expire(h)
    assert_uncertain(h.chat(owner, MESSAGE, ident)[0])
    fresh_store = ConversationStore(h.engine, h.clock, h.settings.turn_lease_seconds)
    fresh_id = uuid4()
    fresh = fresh_store.claim(lease.session_id, fresh_id, "Synthetic fresh intent", uuid4())
    assert len(origin(h, fresh)) == 1
    expire(h)
    h.provider.steps.extend([call("create_booking_proposal", proposal_args()), final("proposal")])
    restarted_engine, client = h.restart()
    try:
        with client:
            body = parsed(h.chat(owner, "Synthetic fresh intent", fresh_id, client=client)[0])
    finally:
        restarted_engine.dispose()
    assert body.proposal.status == "PENDING" and len(origin(h, fresh)) == 1
    assert all("ordering_version" not in item for p in h.provider.requests for item in p["input"])
    before = proposals(h)
    assert h.chat(owner, MESSAGE, ident)[0].json()["error"]["code"] == STALE_INTENT.upper()
    assert proposals(h) == before


@pytest.mark.parametrize("payload", [{}, {"ordering_version": 0}, {"ordering_version": 2}])
def test_invalid_origin_metadata_does_not_authorize_legacy_mutation(harness, payload):
    h = harness
    owner, store, ident, lease, _ = legacy_turn(h)
    with store.transaction() as db:
        store.append(db, lease, INTENT_ORIGIN, payload)
    accepted_history(h, lease.session_id)
    before = proposals(h)
    expire(h)
    assert_uncertain(h.chat(owner, MESSAGE, ident)[0])
    assert proposals(h) == before and h.provider.requests == []


def test_concurrent_legacy_retries_fail_without_mutation(harness):
    h = harness
    owner, _, ident, lease, _ = legacy_turn(h)
    accepted_history(h, lease.session_id)
    before = proposals(h)
    expire(h)
    barrier = Barrier(2)

    def retry():
        barrier.wait(timeout=5)
        return h.chat(owner, MESSAGE, ident)[0]

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: retry(), range(2)))
    assert all(r.status_code == 409 for r in responses)
    assert {r.json()["error"]["code"] for r in responses} <= {"STALE_INTENT", "TURN_IN_PROGRESS"}
    assert any("cannot be verified" in r.json()["error"]["message"] for r in responses)
    assert proposals(h) == before and h.provider.requests == []


def test_legacy_guard_waits_for_pre_fix_acceptance_commit(harness):
    import time

    h = harness
    owner, _, ident, lease, _ = legacy_turn(h)
    expire(h)
    locked, release = Event(), Event()
    holder = []

    def accept():
        with Session(h.engine) as db, db.begin():
            result = legacy_history(db, h, lease.session_id)
            holder.append(db.scalar(text("select pg_backend_pid()")))
            locked.set()
            assert release.wait(5)
        return result

    with ThreadPoolExecutor(2) as pool:
        new = pool.submit(accept)
        assert locked.wait(5)
        old = pool.submit(h.chat, owner, MESSAGE, ident)
        try:
            waiting = []
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                with h.engine.connect() as db:
                    waiting = (
                        db.execute(
                            text(
                                "select pid from pg_stat_activity where wait_event_type='Lock' "
                                "and :holder = ANY(pg_blocking_pids(pid))"
                            ),
                            {"holder": holder[0]},
                        )
                        .scalars()
                        .all()
                    )
                if waiting:
                    break
                time.sleep(0.01)
            assert waiting and all(pid != holder[0] for pid in waiting)
        finally:
            release.set()
        new_id = new.result(timeout=5)
        assert_uncertain(old.result(timeout=5)[0])
    assert proposals(h)[0][:2] == (new_id, "PENDING") and h.provider.requests == []


def test_reclaimed_legacy_lease_still_fenced_by_new_corrected_acceptance(harness):
    h = harness
    owner, store, ident, old, item = legacy_turn(h)
    expire(h)
    recovered = store.claim(old.session_id, ident, MESSAGE, uuid4())
    with store.transaction() as db:
        with pytest.raises(ApiError):
            store.guard(db, old)
    response = h.client.post(
        "/api/v1/proposals", headers=owner, json=proposal_args(local_time="10:00")
    )
    assert response.status_code == 201
    before = proposals(h)
    with pytest.raises(ApiError) as failure:
        ChatService(h.engine, h.settings, h.clock, h.provider)._execute(recovered, item)
    assert failure.value.code == "STALE_INTENT" and proposals(h) == before
    assert not origin(h, old)


def test_provider_cannot_supply_trusted_source_turn_identity(harness):
    h = harness
    owner = h.owner()
    h.provider.steps.extend(
        [
            call("create_booking_proposal", {**proposal_args(), "source_turn_id": str(uuid4())}),
            final("clarify", missing=["local_time"]),
        ]
    )
    response, _ = h.chat(owner)
    assert response.status_code == 200
    outputs = [
        item
        for item in h.provider.requests[-1]["input"]
        if item.get("type") == "function_call_output"
    ]
    import json

    assert json.loads(outputs[0]["output"])["error"]["code"] == "INVALID_TOOL_ARGUMENTS"
    assert h.counts()["booking_proposals"] == h.counts()["appointments"] == 0
