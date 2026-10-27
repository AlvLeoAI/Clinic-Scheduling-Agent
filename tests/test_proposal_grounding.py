"""R3C.1 failure-path regressions using only synthetic providers and PostgreSQL."""

import copy
import json
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.tools import validate_result
from app.db.models import BookingProposal, ConversationItem
from evaluations.live_graders_v1_1 import grade_smoke
from evaluations.live_runner import load_smoke, run_smoke
from tests import test_chat as chat_helpers
from tests import test_live_runner as live_helpers
from tests.test_chat import call, final, parsed, proposal_args

harness = chat_helpers.harness
isolated = live_helpers.isolated
pytestmark = [pytest.mark.postgres, pytest.mark.agent_offline]


def make_proposal(harness, owner):
    harness.provider.steps.extend(
        [call("create_booking_proposal", proposal_args()), final("proposal")]
    )
    response, message_id = harness.chat(owner)
    return parsed(response), message_id


@pytest.mark.parametrize("expired", [False, True])
def test_failed_new_request_never_presents_previous_proposal_as_its_result(
    harness, record_property, expired
):
    owner = harness.owner()
    prior, _ = make_proposal(harness, owner)
    if expired:
        harness.clock.now += timedelta(minutes=11)
    harness.provider.steps.extend(
        [
            call("create_booking_proposal", proposal_args(local_time="18:00"), "rejected_b"),
            final("proposal"),
        ]
    )
    response, ident = harness.chat(owner, message="Synthetic: instead request 18:00 on January 9.")
    body = parsed(response)
    with Session(harness.engine) as db:
        row = db.get(BookingProposal, prior.proposal.proposal_id)
        assert row.source_turn_id == prior.turn_id != body.turn_id
        assert row.status == ("EXPIRED" if expired else "PENDING")
        assert row.starts_at == prior.proposal.starts_at
        rows = list(
            db.scalars(select(ConversationItem).where(ConversationItem.turn_id == body.turn_id))
        )
        output = next(x for x in rows if x.item_type == "function_call_output")
        outcome = validate_result("create_booking_proposal", json.loads(output.payload["output"]))
        assert output.call_id == "rejected_b" and outcome["ok"] is False
        assert outcome["error"]["code"] == "BUSINESS_RULE_VIOLATION"
        assert next(x for x in rows if x.item_type == "reply_plan").payload["kind"] == "proposal"
    assert harness.counts()["booking_proposals"] == 1 and harness.counts()["appointments"] == 0
    replay = harness.chat(
        owner, message="Synthetic: instead request 18:00 on January 9.", message_id=ident
    )[0]
    assert replay.json() == response.json() and len(harness.provider.requests) == 4
    record_property("observed_response", json.dumps(response.json()))
    record_property("recorded_failure", json.dumps(outcome))
    # A recoverable prior projection may be retained only with explicit provenance.
    assert body.proposal is None or "previous" in body.assistant_message.lower()
    assert "not" in body.assistant_message.lower() and "proposal" in body.assistant_message.lower()


def test_proposal_plan_without_tool_success_explains_unestablished_result(harness, record_property):
    owner = harness.owner()
    harness.provider.steps.append(final("proposal"))
    response, _ = harness.chat(owner)
    body = parsed(response)
    assert body.proposal is None
    assert harness.counts()["booking_proposals"] == harness.counts()["appointments"] == 0
    record_property("observed_response", json.dumps(response.json()))
    assert "proposal" in body.assistant_message.lower() and "not" in body.assistant_message.lower()


def test_confirmation_without_proposal_does_not_instruct_review_of_nonexistent_state(
    harness, record_property
):
    owner = harness.owner()
    harness.provider.steps.append(final("confirmation_required"))
    response, _ = harness.chat(owner, message="Synthetic: confirm it now.")
    body = parsed(response)
    assert body.proposal is None
    assert harness.counts()["booking_proposals"] == harness.counts()["appointments"] == 0
    record_property("observed_response", json.dumps(response.json()))
    assert "Review the proposal" not in body.assistant_message
    assert "Chat cannot confirm bookings" in body.assistant_message


def test_successful_current_turn_proposal_is_owned_and_grounded(harness):
    owner = harness.owner()
    body, ident = make_proposal(harness, owner)
    assert body.proposal.status == "PENDING"
    with Session(harness.engine) as db:
        row = db.get(BookingProposal, body.proposal.proposal_id)
        assert row.source_turn_id == body.turn_id
        assert row.session_id == body.proposal.session_id == harness.owners[0]
        assert row.starts_at == body.proposal.starts_at and row.ends_at == body.proposal.ends_at
    assert str(body.proposal.proposal_id) in body.assistant_message
    assert body.proposal.starts_at.isoformat() in body.assistant_message
    assert "Confirmation is a separate explicit action" in body.assistant_message
    harness.clock.now += timedelta(minutes=11)
    replay = parsed(harness.chat(owner, message_id=ident)[0])
    assert (
        replay.proposal.status == "EXPIRED" and replay.assistant_message == body.assistant_message
    )
    assert len(harness.provider.requests) == 2 and harness.counts()["appointments"] == 0


def test_other_session_pending_proposal_is_never_exposed(harness):
    owner, other = harness.owner(), harness.owner()
    prior, _ = make_proposal(harness, owner)
    harness.provider.steps.append(final("proposal"))
    body = parsed(harness.chat(other)[0])
    assert body.proposal is None and str(prior.proposal.proposal_id) not in body.assistant_message
    with Session(harness.engine) as db:
        assert db.get(BookingProposal, prior.proposal.proposal_id).status == "PENDING"
    assert harness.counts()["appointments"] == 0


def test_frozen_s5_grammar_rejects_proposed_no_proposal_guidance(isolated, record_property):
    engine, ident, settings = isolated
    report = run_smoke(engine, settings, ident, scenario="S5", evaluation_contract="1.2")
    original = report["cases"][0]
    assert (
        original["RAW_MODEL_VERDICT"]
        == original["BACKEND_VERDICT"]
        == original["USER_VISIBLE_VERDICT"]
        == "PASS"
    )
    # Fresh mocked evidence, never a historical live rescore. Prove the old exact
    # fixture still passes v1.1 while the corrected current text does not.
    evidence = copy.deepcopy(original["evidence"])
    dataset = load_smoke()
    historical = copy.deepcopy(evidence)
    historical["responses"][0]["body"]["assistant_message"] = (
        "Chat cannot confirm bookings. Review the proposal and use "
        "the explicit confirmation endpoint."
    )
    assert (
        grade_smoke(dataset.cases[4], historical, dataset, [], complete=True)["verdict"] == "PASS"
    )
    assert evidence["final"]["proposals"] == [] and evidence["final"]["appointments"] == []
    proposed = (
        "Chat cannot confirm bookings. There is no pending proposal to review. "
        "Request a booking proposal first, then use the explicit confirmation endpoint."
    )
    evidence["responses"][0]["body"]["assistant_message"] = proposed
    dataset = load_smoke()
    revised = grade_smoke(dataset.cases[4], evidence, dataset, [], complete=True)
    record_property("proposed_wording", proposed)
    record_property("frozen_grader_result", json.dumps(revised))
    assert revised["RAW_MODEL_VERDICT"] == revised["BACKEND_VERDICT"] == "PASS"
    assert revised["USER_VISIBLE_VERDICT"] == "FAIL"
    assert report["database_unchanged_after_scoped_cleanup"]


@pytest.mark.parametrize("kind", ["proposal", "clarify", "greeting", "confirmation_required"])
def test_failed_request_without_prior_has_exact_recorded_failure(harness, kind):
    owner = harness.owner()
    harness.provider.steps.extend(
        [call("create_booking_proposal", proposal_args(local_time="18:00"), "failed"), final(kind)]
    )
    body = parsed(harness.chat(owner)[0])
    assert body.proposal is None
    assert body.assistant_message.startswith(
        "The requested proposal operation did not succeed (BUSINESS_RULE_VIOLATION). "
    )
    assert harness.counts()["appointments"] == harness.counts()["booking_proposals"] == 0


@pytest.mark.parametrize("expired", [False, True])
def test_confirmation_with_prior_is_explicitly_previous_and_status_conditional(harness, expired):
    owner = harness.owner()
    prior, _ = make_proposal(harness, owner)
    if expired:
        harness.clock.now += timedelta(minutes=11)
    harness.provider.steps.append(final("confirmation_required"))
    body = parsed(harness.chat(owner)[0])
    assert body.proposal.proposal_id == prior.proposal.proposal_id
    assert body.proposal.status == ("EXPIRED" if expired else "PENDING")
    assert "Only if it is PENDING" in body.assistant_message
    assert "Otherwise request a new proposal." in body.assistant_message
    assert f"Previous proposal {prior.proposal.proposal_id}" in body.assistant_message
    assert harness.counts()["appointments"] == 0


def test_same_details_reuse_is_a_successful_current_result_not_a_new_insert(harness):
    owner = harness.owner()
    prior, _ = make_proposal(harness, owner)
    current, _ = make_proposal(harness, owner)
    assert current.proposal.proposal_id == prior.proposal.proposal_id
    with Session(harness.engine) as db:
        assert db.get(BookingProposal, current.proposal.proposal_id).source_turn_id == prior.turn_id
    assert "Previous proposal" not in current.assistant_message
    assert current.assistant_message.startswith(f"Proposal {prior.proposal.proposal_id} covers ")
    assert harness.counts()["booking_proposals"] == 1


def test_failed_provider_exposes_previous_state_only_with_explicit_error_label(harness):
    from app.agent.protocol import ProviderFailure

    owner = harness.owner()
    prior, _ = make_proposal(harness, owner)
    harness.provider.steps.append(ProviderFailure("synthetic"))
    response, _ = harness.chat(owner, message="Synthetic replacement request")
    assert response.status_code == 503
    assert response.json()["proposal"]["proposal_id"] == str(prior.proposal.proposal_id)
    assert response.json()["error"]["message"].endswith(
        "The attached proposal is previous session state, not a result of this request."
    )
    assert harness.counts()["appointments"] == 0


@pytest.mark.parametrize("expired", [False, True])
def test_actual_two_turn_failure_is_independently_graded_raw_fail_backend_visible_pass(
    engine, expired
):
    from evaluations.contracts import ExpectedCall, InputMessage
    from evaluations.graders_v1_2 import grade
    from evaluations.runner import CaseRun, load_dataset

    data = load_dataset()
    args = {k: str(v) for k, v in proposal_args().items()}
    bad = {**args, "local_time": "18:00"}
    case = data.cases[3].model_copy(
        update={
            "input": [
                InputMessage(message="Synthetic prior proposal"),
                InputMessage(message="Synthetic replacement outside hours"),
            ],
            "script": {
                "A": [
                    {"tool": "create_booking_proposal", "arguments": args},
                    {"reply": "proposal"},
                    {"tool": "create_booking_proposal", "arguments": bad},
                    {"reply": "proposal"},
                ]
            },
            "expected_tool_calls": [
                ExpectedCall(name="create_booking_proposal", arguments=a) for a in (args, bad)
            ],
            "expected_response_constraints": {"http_statuses": [200], "raw_kind": "proposal"},
            "expected_db_state": {"proposals": 1, "appointments": 0},
            "expected_raw_verdict": "FAIL",
        }
    )
    run = CaseRun(case, data, engine)
    try:
        with run.client() as client:
            run.setup(client)
            initial = run.snapshot()
            run.chat(client, case.input[0])
            if expired:
                run.clock.now += timedelta(minutes=11)
            run.chat(client, case.input[1])
            obs = run.observation(initial)
        result = grade(case, obs, data.catalog, data.clock)
        assert result["verdict"] == "PASS", result
        assert result["layers"]["raw_model"]["verdict"] == "FAIL"
        assert result["layers"]["backend"]["verdict"] == "PASS"
        assert result["layers"]["user_visible"]["verdict"] == "PASS"
    finally:
        run.cleanup()
