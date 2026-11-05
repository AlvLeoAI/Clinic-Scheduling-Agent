"""Confirmation recovery through real sockets: the UI's client, a fault proxy, the API.

Service tests, not browser tests: the UI's own `ClinicApi` and `confirmation.confirm`
talk through `FaultProxy` to the real app under uvicorn on PostgreSQL, with a test
clock. Each case records where the fault hit, whether the one Idempotency-Key was
reused, which appointment was recovered and the database counts (no bearers or keys).
"""

from dataclasses import dataclass, field
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Appointment
from app.db.seed import seed_catalog
from tests.conftest import NOW
from tests.support.live_stack import (
    Bearer,
    Clock,
    FaultProxy,
    LiveApi,
    counts,
    delete_sessions,
    loopback_transport,
    slot_appointments,
    write_receipt,
)
from ui.client import ClinicApi
from ui.confirmation import ConfirmState, action, confirm

pytestmark = [pytest.mark.postgres, pytest.mark.service]
PRACTITIONER = UUID("00000000-0000-4000-8000-000000000101")
FOLLOW_UP = UUID("00000000-0000-4000-8000-000000000201")


@dataclass
class User:
    # Keys stay out of the repr; the bearer's own repr is redacted (see Bearer).
    api: ClinicApi
    token: str = field(repr=False)
    flows: dict = field(default_factory=dict)
    keys: dict = field(default_factory=dict, repr=False)


@pytest.fixture
def stack(engine):
    with Session(engine) as db:
        seed_catalog(db)
        db.commit()
    clock = Clock(NOW)
    api = LiveApi(engine, clock).start()
    proxy = FaultProxy(api.url)
    owned: list[UUID] = []

    def user():
        client = ClinicApi(proxy.url, transport=loopback_transport(), timeout=10)
        session = client.create_session()
        owned.append(session.session_id)
        return User(client, Bearer(session.token))

    def propose(who, hhmm):
        command = f"propose 2030-01-09 {hhmm} {PRACTITIONER} {FOLLOW_UP}"
        proposal = who.api.chat(who.token, command, uuid4()).proposal
        assert proposal is not None and proposal.status == "PENDING"
        return proposal

    yield SimpleNamespace(
        engine=engine, clock=clock, api=api, proxy=proxy, user=user, propose=propose, owned=owned
    )
    proxy.close()
    api.stop()
    delete_sessions(engine, owned)


def booked(engine, proposal_id):
    with Session(engine) as db:
        return db.scalar(select(Appointment.id).where(Appointment.proposal_id == proposal_id))


def receipt(stack, name, fault, who, proposal, flow, **extra):
    key = who.keys[str(proposal.proposal_id)]
    seen = stack.proxy.confirm_keys
    result = {
        "case": name,
        "evidence": "service",
        "fault_boundary": fault,
        "confirm_requests_reaching_api": len(seen),
        "key_reused": bool(seen) and set(seen) == {key},
        "recovered_appointment_id": str(flow.appointment.appointment_id)
        if flow.appointment
        else None,
        "db_appointment_id": str(booked(stack.engine, proposal.proposal_id)),
        **counts(stack.engine, stack.owned),
        **extra,
    }
    write_receipt(name, result)
    return result


def test_a_confirm_blocked_before_the_api_is_retried_with_the_same_key(stack):
    who = stack.user()
    proposal = stack.propose(who, "09:00")
    stack.proxy.arm("block")

    flow = confirm(who.api, who.token, proposal, who.flows, who.keys)
    assert flow.state is ConfirmState.UNCERTAIN and flow.error.code == "API_UNREACHABLE"
    assert stack.proxy.blocked == 1 and stack.proxy.confirm_keys == []
    assert counts(stack.engine, stack.owned) == {"appointments": 0, "idempotency_records": 0}
    key = who.keys[str(proposal.proposal_id)]

    flow = confirm(who.api, who.token, proposal, who.flows, who.keys)
    assert flow.state is ConfirmState.CONFIRMED
    assert who.keys[str(proposal.proposal_id)] == key, "the retry must resend the same key"
    result = receipt(
        stack, "blocked_before_api", "request dropped by the proxy", who, proposal, flow
    )
    assert result["key_reused"] and result["confirm_requests_reaching_api"] == 1
    assert result["recovered_appointment_id"] == result["db_appointment_id"]
    assert result["appointments"] == 1 and result["idempotency_records"] == 1


def test_a_lost_response_is_recovered_after_the_proposal_expires(stack):
    who = stack.user()
    proposal = stack.propose(who, "09:30")
    stack.proxy.arm("lose_response")

    flow = confirm(who.api, who.token, proposal, who.flows, who.keys)
    assert flow.state is ConfirmState.UNCERTAIN and stack.proxy.lost == 1
    assert counts(stack.engine, stack.owned) == {"appointments": 1, "idempotency_records": 1}

    # Past the 10-minute proposal TTL, well inside the 24-hour session (bearer still valid).
    stack.clock.advance(timedelta(minutes=11))
    assert stack.clock.now > proposal.expires_at and proposal.seconds_left(stack.clock.now) == 0
    assert action(proposal, flow, stack.clock.now).enabled

    flow = confirm(who.api, who.token, proposal, who.flows, who.keys)
    assert flow.state is ConfirmState.CONFIRMED
    result = receipt(
        stack,
        "lost_response_after_expiry",
        "response lost after commit",
        who,
        proposal,
        flow,
        clock_advanced_minutes=11,
    )
    assert result["key_reused"] and result["confirm_requests_reaching_api"] == 2
    assert result["recovered_appointment_id"] == result["db_appointment_id"]
    assert result["appointments"] == 1 and result["idempotency_records"] == 1


def test_two_sessions_confirming_the_same_slot_book_it_once(stack):
    first, second = stack.user(), stack.user()
    mine, theirs = stack.propose(first, "10:00"), stack.propose(second, "10:00")

    won = confirm(first.api, first.token, mine, first.flows, first.keys)
    lost = confirm(second.api, second.token, theirs, second.flows, second.keys)
    assert won.state is ConfirmState.CONFIRMED
    assert lost.state is ConfirmState.FAILED and lost.error.status == 409
    assert lost.error.code == "SLOT_TAKEN" and not lost.error.retryable
    assert slot_appointments(stack.engine, PRACTITIONER, mine.starts_at) == 1
    write_receipt(
        "two_sessions_same_slot",
        {
            "case": "two_sessions_same_slot",
            "evidence": "service",
            "first": "201 CONFIRMED",
            "second": f"{lost.error.status} {lost.error.code}",
            "appointments_for_slot": 1,
            **counts(stack.engine, stack.owned),
        },
    )


def test_an_api_restart_after_commit_recovers_the_same_appointment(stack):
    who = stack.user()
    proposal = stack.propose(who, "10:30")
    stack.proxy.arm("lose_response")
    assert (
        confirm(who.api, who.token, proposal, who.flows, who.keys).state is ConfirmState.UNCERTAIN
    )
    committed = booked(stack.engine, proposal.proposal_id)
    assert committed is not None

    # While the API is down, a check is still uncertain, never a failure.
    stack.api.stop()
    down = confirm(who.api, who.token, proposal, who.flows, who.keys)
    assert down.state is ConfirmState.UNCERTAIN and down.error.retryable
    # A fresh app instance on the same port: nothing survives in process memory.
    stack.api.start()

    flow = confirm(who.api, who.token, proposal, who.flows, who.keys)
    assert flow.state is ConfirmState.CONFIRMED and flow.appointment.appointment_id == committed
    result = receipt(
        stack,
        "api_restart_after_commit",
        "response lost after commit, then API restarted",
        who,
        proposal,
        flow,
        checks_while_api_down=1,
    )
    assert result["key_reused"] and result["confirm_requests_reaching_api"] == 2
    assert result["appointments"] == 1 and result["idempotency_records"] == 1
