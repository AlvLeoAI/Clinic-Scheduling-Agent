"""UI confirmation states against a simulated API: no server, database or Streamlit.

The simulated server mirrors app/services/booking.py: a known Idempotency-Key returns
its stored outcome before the proposal's TTL or status is checked.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from ui.client import ClinicApi, Proposal
from ui.confirmation import ConfirmState, Flow, action, confirm, flow_for

pytestmark = pytest.mark.unit
NOW = datetime(2030, 1, 7, 15, tzinfo=UTC)
TOKEN = "synthetic-bearer"


def make_proposal(status="PENDING", ttl=timedelta(minutes=10)):
    return Proposal(
        proposal_id=uuid4(),
        practitioner_id=uuid4(),
        appointment_type_id=uuid4(),
        starts_at=NOW + timedelta(days=2),
        ends_at=NOW + timedelta(days=2, minutes=30),
        expires_at=NOW + ttl,
        status=status,
    )


def error_body(code):
    return {"error": {"code": code, "message": code, "retryable": False}, "trace_id": "t"}


class SimulatedServer:
    def __init__(self, proposal):
        self.proposal, self.now = proposal, NOW
        self.outcomes, self.keys, self.bookings = {}, [], 0
        self.drop_next_response = False

    def handle(self, request):
        key = request.headers["Idempotency-Key"]
        self.keys.append(key)
        if key not in self.outcomes:
            if self.now >= self.proposal.expires_at:
                self.outcomes[key] = (410, error_body("PROPOSAL_EXPIRED"))
            elif self.proposal.status == "SUPERSEDED":
                self.outcomes[key] = (409, error_body("PROPOSAL_SUPERSEDED"))
            else:
                self.bookings += 1
                self.outcomes[key] = (201, self.appointment())
        if self.drop_next_response:
            # Committed, but the response never reaches the UI.
            self.drop_next_response = False
            raise httpx.ReadTimeout("response lost")
        status, body = self.outcomes[key]
        return httpx.Response(status, json=body)

    def appointment(self):
        return {
            "status": "CONFIRMED",
            "appointment_id": str(uuid4()),
            "proposal_id": str(self.proposal.proposal_id),
            "starts_at": self.proposal.starts_at.isoformat(),
            "ends_at": self.proposal.ends_at.isoformat(),
            "confirmed_at": self.now.isoformat(),
            "trace_id": str(uuid4()),
        }


def setup(proposal):
    server = SimulatedServer(proposal)
    api = ClinicApi("http://api.test/", transport=httpx.MockTransport(server.handle))
    return server, api, {}, {}


def test_lost_response_before_the_ttl_is_uncertain_and_recovers_with_the_same_key():
    proposal = make_proposal()
    server, api, flows, keys = setup(proposal)
    server.drop_next_response = True

    flow = confirm(api, TOKEN, proposal, flows, keys)
    assert flow.state is ConfirmState.UNCERTAIN and flow.error.retryable
    check = action(proposal, flow, NOW)
    assert check.label == "Check booking status" and check.enabled

    flow = confirm(api, TOKEN, proposal, flows, keys)
    assert flow.state is ConfirmState.CONFIRMED
    assert server.bookings == 1 and len(set(server.keys)) == 1
    assert flow.appointment.proposal_id == proposal.proposal_id
    assert action(proposal, flow, NOW) is None


def test_lost_response_after_the_ttl_can_still_be_checked():
    proposal = make_proposal(ttl=timedelta(seconds=30))
    server, api, flows, keys = setup(proposal)
    server.drop_next_response = True
    assert confirm(api, TOKEN, proposal, flows, keys).state is ConfirmState.UNCERTAIN

    later = NOW + timedelta(minutes=5)
    server.now = later
    assert proposal.seconds_left(later) == 0
    check = action(proposal, flows[str(proposal.proposal_id)], later)
    assert check.label == "Check booking status" and check.enabled

    flow = confirm(api, TOKEN, proposal, flows, keys)
    assert flow.state is ConfirmState.CONFIRMED and server.bookings == 1
    assert len(set(server.keys)) == 1


def test_an_expired_proposal_that_was_never_sent_cannot_be_confirmed():
    proposal = make_proposal(ttl=timedelta(seconds=30))
    flow = Flow()
    later = NOW + timedelta(minutes=5)
    assert action(proposal, flow, later).enabled is False


def test_a_superseded_proposal_with_time_left_cannot_be_confirmed():
    proposal = make_proposal(status="SUPERSEDED")
    assert proposal.seconds_left(NOW) > 0
    blocked = action(proposal, Flow(), NOW)
    assert blocked.label == "Confirm booking" and blocked.enabled is False
    # Unless a confirm was already sent and its outcome is unknown.
    assert action(proposal, Flow(state=ConfirmState.UNCERTAIN), NOW).enabled


def test_a_superseded_answer_fails_the_card_without_a_retry():
    proposal = make_proposal()
    server, api, flows, keys = setup(proposal)
    server.proposal = make_proposal(status="SUPERSEDED")

    flow = confirm(api, TOKEN, proposal, flows, keys)
    assert flow.state is ConfirmState.FAILED and flow.error.code == "PROPOSAL_SUPERSEDED"
    assert action(proposal, flow, NOW) is None and server.bookings == 0


def test_a_confirm_interrupted_mid_request_is_treated_as_uncertain():
    proposal = make_proposal()
    flows = {str(proposal.proposal_id): Flow(state=ConfirmState.CONFIRMING)}
    assert flow_for(flows, proposal.proposal_id).state is ConfirmState.UNCERTAIN
