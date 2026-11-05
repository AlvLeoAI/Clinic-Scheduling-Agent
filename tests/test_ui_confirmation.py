"""UI confirmation states against a simulated API: no server, database or Streamlit.

The simulated server mirrors app/services/booking.py: a known Idempotency-Key returns
its stored outcome before the proposal's TTL or status is checked.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from ui.client import ClinicApi, Proposal
from ui.confirmation import (
    ConfirmState,
    Flow,
    action,
    blocked_by_unresolved,
    cards,
    carry_over,
    confirm,
    flow_for,
    send_confirm,
    stale_notice,
    uncertain_message,
)

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


def error_body(code, retryable=False):
    return {"error": {"code": code, "message": code, "retryable": retryable}, "trace_id": "t"}


class SimulatedServer:
    def __init__(self, proposal):
        self.proposal, self.now = proposal, NOW
        self.outcomes, self.keys, self.bookings = {}, [], 0
        self.drop_next_response = False
        # Answered before the key is looked up, as an auth or server failure would be.
        self.next_failure = None

    def handle(self, request):
        key = request.headers["Idempotency-Key"]
        self.keys.append(key)
        if self.next_failure is not None:
            response, self.next_failure = self.next_failure, None
            return response
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


def test_a_new_proposal_keeps_the_uncertain_card_and_its_key():
    first, second = make_proposal(), make_proposal()
    server, api, flows, keys = setup(first)
    server.drop_next_response = True
    assert confirm(api, TOKEN, first, flows, keys).state is ConfirmState.UNCERTAIN
    key = keys[str(first.proposal_id)]

    # The agent proposes again; the uncertain card stays above the new one.
    proposals = {str(first.proposal_id): first, str(second.proposal_id): second}
    assert cards(proposals, flows, second.proposal_id) == [first, second]
    check = action(first, flows[str(first.proposal_id)], NOW)
    assert check.label == "Check booking status" and check.enabled

    # The new proposal cannot be confirmed while the earlier outcome is unknown.
    assert blocked_by_unresolved(flows, second.proposal_id)
    new = action(second, flow_for(flows, second.proposal_id), NOW, blocked=True)
    assert new.label == "Confirm booking" and new.enabled is False

    # Checking resends the original key and returns the original booking.
    flow = confirm(api, TOKEN, first, flows, keys)
    assert flow.state is ConfirmState.CONFIRMED and server.bookings == 1
    assert keys[str(first.proposal_id)] == key and set(server.keys) == {key}
    assert not blocked_by_unresolved(flows, second.proposal_id)
    assert cards(proposals, flows, second.proposal_id) == [first, second]


def test_a_confirm_cut_off_mid_request_also_blocks_the_new_proposal():
    first, second = make_proposal(), make_proposal()
    flows = {str(first.proposal_id): Flow(state=ConfirmState.CONFIRMING)}
    assert blocked_by_unresolved(flows, second.proposal_id)
    assert not blocked_by_unresolved(flows, first.proposal_id)


def test_an_earlier_proposal_that_was_never_sent_is_not_shown():
    first, second = make_proposal(), make_proposal()
    proposals = {str(first.proposal_id): first, str(second.proposal_id): second}
    flows = {}
    assert cards(proposals, flows, second.proposal_id) == [second]
    assert not blocked_by_unresolved(flows, second.proposal_id)


def lose_first_response(proposal):
    server, api, flows, keys = setup(proposal)
    server.drop_next_response = True
    assert confirm(api, TOKEN, proposal, flows, keys).state is ConfirmState.UNCERTAIN
    return server, api, flows, keys


def test_a_401_on_the_status_check_stays_uncertain_and_cannot_be_verified_here():
    first, second = make_proposal(), make_proposal()
    server, api, flows, keys = lose_first_response(first)
    server.next_failure = httpx.Response(401, json=error_body("UNAUTHORIZED"))

    flow = confirm(api, TOKEN, first, flows, keys)
    assert flow.state is ConfirmState.UNCERTAIN and flow.unverifiable
    assert server.bookings == 1, "the first request committed; nothing says otherwise"
    message = uncertain_message(flow)
    assert "session expired" in message and "may exist" in message
    check = action(first, flow, NOW)
    assert check.label == "Check booking status" and check.enabled is False
    # The next proposal stays blocked while the outcome is unknown.
    assert blocked_by_unresolved(flows, second.proposal_id)
    assert action(second, flow_for(flows, second.proposal_id), NOW, blocked=True).enabled is False


def test_a_structured_500_on_the_status_check_stays_uncertain_and_can_be_checked_again():
    proposal = make_proposal()
    server, api, flows, keys = lose_first_response(proposal)
    server.next_failure = httpx.Response(500, json=error_body("INTERNAL_ERROR"))

    flow = confirm(api, TOKEN, proposal, flows, keys)
    assert flow.state is ConfirmState.UNCERTAIN and not flow.unverifiable
    assert action(proposal, flow, NOW).enabled
    assert "unknown" in uncertain_message(flow)

    flow = confirm(api, TOKEN, proposal, flows, keys)
    assert flow.state is ConfirmState.CONFIRMED and server.bookings == 1
    assert len(set(server.keys)) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(409, json=error_body("SOMETHING_NEW")),
        httpx.Response(404, json=error_body("PROPOSAL_NOT_FOUND")),
        httpx.Response(502, text="<html>bad gateway</html>"),
        httpx.Response(400, json={"detail": "not our envelope"}),
        httpx.Response(201, json={"status": "CONFIRMED"}),
    ],
    ids=["unknown-code", "not-found", "html-502", "foreign-4xx", "malformed-201"],
)
def test_any_other_answer_leaves_the_outcome_unknown(response):
    proposal = make_proposal()
    server, api, flows, keys = lose_first_response(proposal)
    server.next_failure = response
    flow = confirm(api, TOKEN, proposal, flows, keys)
    assert flow.state is ConfirmState.UNCERTAIN


@pytest.mark.parametrize("code", ["PROPOSAL_EXPIRED", "PROPOSAL_SUPERSEDED", "SLOT_TAKEN"])
def test_only_the_three_not_booked_codes_fail_the_card(code):
    proposal = make_proposal()
    server, api, flows, keys = lose_first_response(proposal)
    server.next_failure = httpx.Response(409, json=error_body(code))
    flow = confirm(api, TOKEN, proposal, flows, keys)
    assert flow.state is ConfirmState.FAILED and action(proposal, flow, NOW) is None


def test_a_new_session_keeps_only_unresolved_cards_and_marks_them_unverifiable():
    sent, booked, idle = make_proposal(), make_proposal(), make_proposal()
    flows = {
        str(sent.proposal_id): Flow(state=ConfirmState.UNCERTAIN),
        str(booked.proposal_id): Flow(state=ConfirmState.CONFIRMED),
    }
    proposals = {str(p.proposal_id): p for p in (sent, booked, idle)}
    keys = {str(sent.proposal_id): "k1", str(booked.proposal_id): "k2"}

    flows, proposals, keys = carry_over(flows, proposals, keys)
    assert list(flows) == list(proposals) == list(keys) == [str(sent.proposal_id)]
    flow = flows[str(sent.proposal_id)]
    assert flow.unverifiable and action(sent, flow, NOW).enabled is False
    assert blocked_by_unresolved(flows, idle.proposal_id)


def page_state(session_id, token=TOKEN, flows=None, keys=None):
    # The keys ui/app.py keeps in st.session_state for the live session.
    flows, keys = ({} if flows is None else flows), ({} if keys is None else keys)
    return {"token": token, "session_id": session_id, "flows": flows, "confirm_keys": keys}


@pytest.mark.parametrize("stale", ["bearer-dropped", "session-replaced", "no-owner"])
def test_a_button_from_another_session_sends_nothing(stale):
    proposal = make_proposal()
    server, api, _, _ = setup(proposal)
    old = uuid4()
    state = page_state(old)
    owner = old
    if stale == "bearer-dropped":
        del state["token"]  # what show_error does after a 401
    elif stale == "session-replaced":
        state["session_id"] = uuid4()
    else:
        owner = None

    assert send_confirm(api, state, proposal, owner) is None
    assert server.keys == [] and state["flows"] == {} and state["confirm_keys"] == {}
    assert "was not sent" in stale_notice(state["flows"].get(str(proposal.proposal_id)))


def test_an_unresolved_confirm_is_not_checked_with_a_replacement_bearer():
    first, second = make_proposal(), make_proposal()
    server, api, flows, keys = lose_first_response(first)
    old, new = uuid4(), uuid4()
    flows, proposals, keys = carry_over(flows, {str(first.proposal_id): first}, keys)
    state = page_state(new, "replacement", flows, keys)

    assert send_confirm(api, state, first, old) is None
    assert len(server.keys) == 1, "only the original confirm reached the server"
    flow = flows[str(first.proposal_id)]
    assert flow.state is ConfirmState.UNCERTAIN and flow.unverifiable
    assert "may exist" in stale_notice(flow)
    assert cards(proposals, flows, first.proposal_id) == [first]
    # The replacement session's own proposal stays blocked while the outcome is unknown.
    assert blocked_by_unresolved(flows, second.proposal_id)
    assert action(second, flow_for(flows, second.proposal_id), NOW, blocked=True).enabled is False


def test_the_replacement_session_confirms_its_own_proposal():
    stale, fresh = make_proposal(), make_proposal()
    server, api, flows, keys = setup(fresh)
    old, new = uuid4(), uuid4()
    flows, _, keys = carry_over({str(stale.proposal_id): Flow()}, {}, {})
    state = page_state(new, "replacement", flows, keys)

    assert send_confirm(api, state, stale, old) is None and flows == {}
    assert not blocked_by_unresolved(flows, fresh.proposal_id)
    flow = send_confirm(api, state, fresh, new)
    assert flow.state is ConfirmState.CONFIRMED and server.bookings == 1
