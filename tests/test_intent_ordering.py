"""Synthetic PostgreSQL recovery ordering; no timestamp-based authorization."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.agent.protocol import ProviderResponse
from app.core.errors import ApiError
from app.db.models import BookingProposal, ChatTurn, ConversationItem
from app.schemas.booking import ProposalRequest
from app.services.booking import BookingService
from app.services.chat import ChatService
from app.services.conversation import ConversationStore
from app.services.intent import STALE_INTENT
from tests import test_chat as helpers
from tests.test_chat import call, final, parsed, proposal_args

harness = helpers.harness
pytestmark = [pytest.mark.postgres, pytest.mark.agent_offline]
MESSAGE = "Synthetic older scheduling intention"


def interrupted(h, *, tool="create_booking_proposal"):
    owner = h.owner()
    store = ConversationStore(h.engine, h.clock, h.settings.turn_lease_seconds)
    ident = uuid4()
    lease = store.claim(h.owners[-1], ident, MESSAGE, uuid4())
    response = ProviderResponse.model_validate(
        call(tool, proposal_args() if tool == "create_booking_proposal" else {}, "older_call")
    )
    store.persist_response(lease, response)
    return owner, store, ident, lease, response.output[-1]


def expire(h):
    h.clock.now += timedelta(seconds=h.settings.turn_lease_seconds + 1)


def direct_proposal(h, owner, hour="10:00"):
    r = h.client.post("/api/v1/proposals", headers=owner, json=proposal_args(local_time=hour))
    assert r.status_code in {200, 201}, r.text
    return r.json()


def markers(h, lease):
    with Session(h.engine) as db:
        return db.scalars(
            select(ConversationItem).where(
                ConversationItem.turn_id == lease.turn_id,
                ConversationItem.item_type == STALE_INTENT,
            )
        ).all()


def assert_pending(h, ident):
    with Session(h.engine) as db:
        pending = db.scalars(
            select(BookingProposal).where(
                BookingProposal.status == "PENDING", BookingProposal.session_id.in_(h.owners)
            )
        ).all()
        assert len(pending) == 1 and str(pending[0].id) == ident
    assert h.counts()["appointments"] == 0


@pytest.mark.parametrize("newer_via_chat", [False, True])
def test_recovered_old_call_cannot_supersede_newer_accepted_proposal(harness, newer_via_chat):
    h = harness
    owner, store, ident, lease, _ = interrupted(h)
    expire(h)
    if newer_via_chat:
        h.provider.steps.extend(
            [call("create_booking_proposal", proposal_args(local_time="10:00")), final("proposal")]
        )
        newer = parsed(h.chat(owner, message="Synthetic newer intent")[0]).proposal.model_dump(
            mode="json"
        )
    else:
        newer = direct_proposal(h, owner)
    assert len(markers(h, lease)) == 1
    calls = len(h.provider.requests)
    for _ in range(2):
        r, _ = h.chat(owner, message=MESSAGE, message_id=ident)
        assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_INTENT"
        assert r.json()["error"]["retryable"] is False
        assert "Send a new message" in r.json()["error"]["message"]
        assert r.json()["trace_id"] == r.headers["X-Trace-ID"]
        assert set(r.json()) == {"error", "trace_id"}
    assert len(h.provider.requests) == calls
    assert_pending(h, newer["proposal_id"])
    assert h.counts()["booking_proposals"] == 1 and len(markers(h, lease)) == 1
    with store.transaction() as db:
        assert db.get(ChatTurn, lease.turn_id).status == "FAILED"
        with pytest.raises(ApiError, match="lease"):
            store.guard(db, lease)


def test_uncontested_recovery_and_completed_replay_remain_functional(harness):
    h = harness
    owner, _, ident, lease, _ = interrupted(h)
    expire(h)
    h.provider.steps.append(final("proposal"))
    restarted_engine, restarted = h.restart()
    try:
        with restarted:
            response, _ = h.chat(owner, message=MESSAGE, message_id=ident, client=restarted)
    finally:
        restarted_engine.dispose()
    body = parsed(response)
    assert body.proposal.status == "PENDING" and not markers(h, lease)
    before = h.counts()
    assert h.chat(owner, message=MESSAGE, message_id=ident)[0].content == response.content
    assert h.counts() == before and len(h.provider.requests) == 1


def test_committed_tool_result_recovers_after_newer_proposal_without_reexecution(harness):
    h = harness
    owner, _, ident, lease, pending_call = interrupted(h)
    service = ChatService(h.engine, h.settings, h.clock, h.provider)
    service._execute(lease, pending_call)  # Commit occurred; simulated response loss follows.
    with Session(h.engine) as db:
        original_output = db.scalar(
            select(ConversationItem.payload).where(
                ConversationItem.turn_id == lease.turn_id,
                ConversationItem.item_type == "function_call_output",
            )
        )
    newer = direct_proposal(h, owner)
    expire(h)
    h.provider.steps.append(final("proposal"))
    restarted_engine, restarted = h.restart()
    try:
        with restarted:
            body = parsed(h.chat(owner, message=MESSAGE, message_id=ident, client=restarted)[0])
    finally:
        restarted_engine.dispose()
    assert body.proposal.status == "SUPERSEDED"
    assert_pending(h, newer["proposal_id"])
    with Session(h.engine) as db:
        output = db.scalar(
            select(ConversationItem.payload).where(
                ConversationItem.turn_id == lease.turn_id,
                ConversationItem.item_type == "function_call_output",
            )
        )
    assert output == original_output and h.counts()["booking_proposals"] == 2
    assert len(h.provider.requests) == 1
    assert all(
        item.get("superseding_proposal_id") is None for item in h.provider.requests[0]["input"]
    )


def test_rejected_newer_proposal_does_not_obsolete_old_intent(harness):
    h = harness
    owner, _, ident, lease, _ = interrupted(h)
    response = h.client.post(
        "/api/v1/proposals", headers=owner, json=proposal_args(local_time="18:00")
    )
    assert response.status_code == 422 and not markers(h, lease)
    expire(h)
    h.provider.steps.append(final("proposal"))
    assert parsed(h.chat(owner, message=MESSAGE, message_id=ident)[0]).proposal.status == "PENDING"


def test_same_details_acceptance_also_fences_other_unfinished_intents(harness):
    h = harness
    owner = h.owner()
    newer = direct_proposal(h, owner)
    store = ConversationStore(h.engine, h.clock, h.settings.turn_lease_seconds)
    ident = uuid4()
    lease = store.claim(h.owners[0], ident, MESSAGE, uuid4())
    store.persist_response(
        lease, ProviderResponse.model_validate(call("create_booking_proposal", proposal_args()))
    )
    assert direct_proposal(h, owner)["proposal_id"] == newer["proposal_id"]
    assert len(markers(h, lease)) == 1
    expire(h)
    assert (
        h.chat(owner, message=MESSAGE, message_id=ident)[0].json()["error"]["code"]
        == "STALE_INTENT"
    )
    assert_pending(h, newer["proposal_id"])


def test_other_session_proposal_does_not_fence_owner(harness):
    h = harness
    owner, _, ident, lease, _ = interrupted(h)
    other = h.owner()
    direct_proposal(h, other)
    assert not markers(h, lease)
    expire(h)
    h.provider.steps.append(final("proposal"))
    assert (
        parsed(h.chat(owner, message=MESSAGE, message_id=ident)[0]).proposal.session_id
        == lease.session_id
    )


def test_read_only_recovery_remains_available_after_newer_intent(harness):
    h = harness
    owner, _, ident, lease, _ = interrupted(h, tool="get_clinic_catalog")
    newer = direct_proposal(h, owner)
    assert markers(h, lease)
    expire(h)
    h.provider.steps.append(final("catalog"))
    assert h.chat(owner, message=MESSAGE, message_id=ident)[0].status_code == 200
    assert_pending(h, newer["proposal_id"])


def test_intent_marker_and_proposal_rollback_together(harness):
    h = harness
    _, store, _, lease, _ = interrupted(h)
    with pytest.raises(RuntimeError, match="synthetic lost transaction"):
        with store.transaction() as db:
            BookingService(db, h.clock).create_proposal(
                lease.session_id,
                ProposalRequest.model_validate(proposal_args(local_time="10:00")),
                uuid4(),
            )
            assert db.scalar(
                select(ConversationItem.id).where(
                    ConversationItem.item_type == STALE_INTENT,
                    ConversationItem.turn_id == lease.turn_id,
                )
            )
            raise RuntimeError("synthetic lost transaction")
    assert not markers(h, lease) and h.counts()["booking_proposals"] == 0


def test_recovery_claim_before_newer_commit_still_checks_marker_at_mutation(harness):
    h = harness
    owner, store, ident, old, pending_call = interrupted(h)
    expire(h)
    recovered = store.claim(old.session_id, ident, MESSAGE, uuid4())
    newer = direct_proposal(h, owner)
    with pytest.raises(ApiError) as failure:
        ChatService(h.engine, h.settings, h.clock, h.provider)._execute(recovered, pending_call)
    assert failure.value.code == "STALE_INTENT"
    assert_pending(h, newer["proposal_id"])


def test_newer_proposal_commit_and_old_recovery_serialize_on_postgres_lock(harness, monkeypatch):
    import app.services.booking as booking

    h = harness
    owner, _, ident, _, _ = interrupted(h)
    expire(h)
    locked, release = Event(), Event()
    original = booking.supersede_unfinished_intents
    backend_pids = []

    def pause(db, *args):
        original(db, *args)
        backend_pids.append(db.scalar(text("select pg_backend_pid()")))
        locked.set()
        assert release.wait(5)

    monkeypatch.setattr(booking, "supersede_unfinished_intents", pause)
    with ThreadPoolExecutor(2) as pool:
        new = pool.submit(direct_proposal, h, owner)
        assert locked.wait(5)
        old = pool.submit(h.chat, owner, MESSAGE, ident)
        # Observe an actual different PostgreSQL connection waiting on this holder.
        import time

        deadline = time.monotonic() + 4
        waiting = []
        try:
            while time.monotonic() < deadline:
                with h.engine.connect() as c:
                    waiting = (
                        c.execute(
                            text(
                                "select pid from pg_stat_activity where wait_event_type='Lock' "
                                "and :holder = ANY(pg_blocking_pids(pid))"
                            ),
                            {"holder": backend_pids[0]},
                        )
                        .scalars()
                        .all()
                    )
                if waiting:
                    break
                time.sleep(0.01)
            assert waiting and all(pid != backend_pids[0] for pid in waiting)
        finally:
            release.set()
        newer = new.result(timeout=5)
        assert old.result(timeout=5)[0].json()["error"]["code"] == "STALE_INTENT"
    assert_pending(h, newer["proposal_id"])


def test_two_concurrent_old_retries_never_mutate_newer_proposal(harness):
    h = harness
    owner, _, ident, _, _ = interrupted(h)
    newer = direct_proposal(h, owner)
    expire(h)
    barrier = Barrier(2)

    def retry():
        barrier.wait(timeout=5)
        return h.chat(owner, message=MESSAGE, message_id=ident)[0]

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: retry(), range(2)))
    assert all(r.status_code == 409 for r in responses)
    assert {r.json()["error"]["code"] for r in responses} <= {"STALE_INTENT", "TURN_IN_PROGRESS"}
    assert any(r.json()["error"]["code"] == "STALE_INTENT" for r in responses)
    assert_pending(h, newer["proposal_id"])
    assert h.provider.requests == []
