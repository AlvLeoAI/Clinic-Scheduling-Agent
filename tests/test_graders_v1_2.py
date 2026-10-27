"""Independent pre-implementation controls: hand-built facts, never rendered answers."""

import copy

import pytest

from evaluations import graders_v1_1, graders_v1_2
from evaluations.contracts import ExpectedCall
from evaluations.runner import load_dataset

pytestmark = [pytest.mark.unit, pytest.mark.agent_offline]
PID = "00000000-0000-4000-8000-000000000901"
OWNER = "00000000-0000-4000-8000-000000000902"
TURN = "00000000-0000-4000-8000-000000000903"
PREVIOUS = "00000000-0000-4000-8000-000000000904"
START, END = "2030-01-09T09:00:00-06:00", "2030-01-09T09:30:00-06:00"
CURRENT_TEXT = (
    f"Proposal {PID} covers {START} to {END}. Review its current status below. "
    "Confirmation is a separate explicit action; a proposal does not hold the interval."
)
PRIOR_TEXT = (
    f"Previous proposal {PID} covers {START} to {END}. Check its current status below; "
    "this is previous session state, not a result of this request. Only a PENDING "
    "proposal can be submitted for separate explicit confirmation."
)
ABSENT_TEXT = (
    "Chat cannot confirm bookings. There is no pending proposal to review. "
    "Request a booking proposal first, then use the explicit confirmation endpoint."
)
PRESENT_TEXT = (
    "Chat cannot confirm bookings. Check the proposal's current status below. "
    "Only if it is PENDING, review its details and use the explicit confirmation endpoint. "
    "Otherwise request a new proposal."
)
MISSING_TEXT = "A proposal result was not established for this request."
FAILED_TEXT = "The requested proposal operation did not succeed (BUSINESS_RULE_VIOLATION). "


def fixture(mode="current", status="PENDING"):
    data = load_dataset()
    args = dict(
        local_date="2030-01-09",
        local_time="09:00",
        practitioner_id=data.catalog["practitioners"][0],
        appointment_type_id=next(iter(data.catalog["types"])),
    )
    previous = mode in {"failed_prior", "confirmation_prior", "reused"}
    has_proposal = mode in {"current", "reused", "failed_prior", "confirmation_prior"}
    failed = mode in {"failed_prior", "failed_none"}
    has_call = failed or mode in {"current", "reused"}
    if failed:
        args["local_time"] = "18:00"
    stored = dict(
        id=PID,
        session="A",
        source_turn_id=PREVIOUS if previous else TURN,
        practitioner_id=args["practitioner_id"],
        appointment_type_id=args["appointment_type_id"],
        starts_at=START,
        ends_at=END,
        expires_at="2030-01-07T15:10:00+00:00",
        duration_minutes=30,
        status=status,
    )
    projected = {k: v for k, v in stored.items() if k not in {"id", "session", "source_turn_id"}}
    projected.update(proposal_id=PID, session_id=OWNER, clinic_timezone="America/Chicago")
    proposals = [stored] if has_proposal else []
    kind = "confirmation_required" if mode.startswith("confirmation") else "proposal"
    text = (
        (PRESENT_TEXT if has_proposal else ABSENT_TEXT)
        if kind == "confirmation_required"
        else (CURRENT_TEXT if mode in {"current", "reused"} else MISSING_TEXT)
    )
    if failed:
        text = FAILED_TEXT + text
    if previous and mode != "reused":
        text += " " + PRIOR_TEXT
    calls, outputs = [], []
    if has_call:
        calls = [
            dict(
                session="A",
                name="create_booking_proposal",
                arguments=args,
                call_id="create",
                client_message_id="message",
            )
        ]
        value = (
            {
                "ok": False,
                "error": dict(
                    code="BUSINESS_RULE_VIOLATION",
                    message="Outside business hours.",
                    retryable=False,
                ),
            }
            if failed
            else {"ok": True, "data": {k: v for k, v in projected.items() if k != "session_id"}}
        )
        outputs = [{**calls[0], "turn_id": TURN, "value": value}]
    case = data.cases[3].model_copy(
        update={
            "expected_tool_calls": [
                ExpectedCall.model_validate({k: c[k] for k in ("session", "name", "arguments")})
                for c in calls
            ],
            "expected_db_state": {"proposals": len(proposals), "appointments": 0},
            "expected_raw_verdict": "FAIL" if failed or mode == "no_result" else "PASS",
            "expected_response_constraints": {"raw_kind": kind, "http_statuses": [200]},
        }
    )
    snapshot = {"proposals": proposals, "appointments": []}
    obs = dict(
        initial={"proposals": copy.deepcopy(proposals) if previous else [], "appointments": []},
        final=copy.deepcopy(snapshot),
        raw_calls=calls,
        raw_plans=[
            dict(session="A", client_message_id="message", value=dict(kind=kind, missing_fields=[]))
        ],
        tool_outputs=outputs,
        explicit_confirmations=[],
        isolation_ok=True,
        recovery_ok=True,
        responses=[
            dict(
                session="A",
                client_message_id="message",
                status=200,
                phase="initial",
                body=dict(
                    turn_id=TURN,
                    assistant_message=text,
                    proposal=projected if has_proposal else None,
                ),
                snapshot=copy.deepcopy(snapshot),
            )
        ],
        catalog_ids=data.catalog["practitioners"] + list(data.catalog["types"]),
        grounded_times=[],
        grounded_intervals=[],
        catalog_truth={},
        session_ids={"A": OWNER},
    )
    return data, case, obs


def score(data, case, obs):
    return graders_v1_2.grade(case, obs, data.catalog, data.clock)


@pytest.mark.parametrize(
    "mode",
    [
        "current",
        "reused",
        "failed_prior",
        "failed_none",
        "no_result",
        "confirmation_none",
        "confirmation_prior",
    ],
)
def test_independent_positive_controls(mode):
    data, case, obs = fixture(mode)
    before = copy.deepcopy(obs)
    result = score(data, case, obs)
    assert result["verdict"] == "PASS", result
    assert result["layers"]["raw_model"]["verdict"] == case.expected_raw_verdict
    assert result["layers"]["backend"]["verdict"] == "PASS"
    assert result["layers"]["user_visible"]["verdict"] == "PASS"
    assert obs == before


@pytest.mark.parametrize("status", ["EXPIRED", "SUPERSEDED", "CONFLICTED"])
@pytest.mark.parametrize("mode", ["failed_prior", "confirmation_prior"])
def test_nonactionable_prior_is_only_conditionally_actionable(mode, status):
    data, case, obs = fixture(mode, status)
    assert score(data, case, obs)["verdict"] == "PASS"


@pytest.mark.parametrize(
    "fault,layer",
    [
        ("stale_as_new", "user_visible"),
        ("omit_previous", "user_visible"),
        ("invent_failure", "user_visible"),
        ("different_failure", "user_visible"),
        ("extra_prose", "user_visible"),
        ("false_confirmation", "user_visible"),
        ("wrong_owner", "user_visible"),
        ("wrong_practitioner", "user_visible"),
        ("wrong_type", "user_visible"),
        ("wrong_status", "user_visible"),
        ("wrong_interval", "user_visible"),
        ("unconfirmed_appointment", "user_visible"),
        ("missing_output", "raw_model"),
        ("wrong_call_id", "backend"),
        ("wrong_turn", "raw_model"),
        ("wrong_message", "raw_model"),
        ("missing_error_message", "backend"),
        ("string_retryable", "backend"),
        ("invalid_error_code", "backend"),
        ("reexecuted_effect", "backend"),
        ("session_leak", "backend"),
        ("nonempty_missing_fields", "raw_model"),
        ("review_absent", "user_visible"),
        ("unsupported_success", "raw_model"),
        ("forged_success_tuple", "backend"),
        ("missing_projection", "user_visible"),
    ],
)
def test_adversarial_controls(fault, layer):
    mode = "current"
    if fault in {
        "stale_as_new",
        "omit_previous",
        "different_failure",
        "missing_error_message",
        "string_retryable",
        "invalid_error_code",
    }:
        mode = "failed_prior"
    if fault == "review_absent":
        mode = "confirmation_none"
    data, case, obs = fixture(mode)
    assert score(data, case, obs)["verdict"] == "PASS"
    body = obs["responses"][0]["body"]
    if fault == "stale_as_new":
        body["assistant_message"] = CURRENT_TEXT
    elif fault == "omit_previous":
        body["assistant_message"] = FAILED_TEXT + MISSING_TEXT
    elif fault == "invent_failure":
        body["assistant_message"] = FAILED_TEXT + body["assistant_message"]
    elif fault == "different_failure":
        body["assistant_message"] = body["assistant_message"].replace(
            "BUSINESS_RULE_VIOLATION", "SLOT_TAKEN"
        )
    elif fault == "extra_prose":
        body["assistant_message"] += " All insurance is covered."
    elif fault == "false_confirmation":
        body["assistant_message"] = "Your appointment is confirmed."
    elif fault.startswith("wrong_") and fault not in {
        "wrong_call_id",
        "wrong_turn",
        "wrong_message",
    }:
        key = {
            "wrong_owner": "session_id",
            "wrong_practitioner": "practitioner_id",
            "wrong_type": "appointment_type_id",
            "wrong_status": "status",
            "wrong_interval": "starts_at",
        }[fault]
        body["proposal"][key] = {
            "wrong_status": "EXPIRED",
            "wrong_interval": "2030-01-09T10:00:00-06:00",
        }.get(fault, PREVIOUS)
    elif fault == "unconfirmed_appointment":
        body["proposal"]["status"] = "CONFIRMED"
        obs["responses"][0]["snapshot"]["proposals"][0]["status"] = "CONFIRMED"
    elif fault in {"missing_output", "unsupported_success"}:
        obs["tool_outputs"] = []
    elif fault == "wrong_call_id":
        obs["tool_outputs"][0]["call_id"] = "other"
    elif fault == "wrong_turn":
        obs["tool_outputs"][0]["turn_id"] = PREVIOUS
    elif fault == "wrong_message":
        obs["raw_plans"][0]["client_message_id"] = "another"
    elif fault == "missing_error_message":
        del obs["tool_outputs"][0]["value"]["error"]["message"]
    elif fault == "string_retryable":
        obs["tool_outputs"][0]["value"]["error"]["retryable"] = "false"
    elif fault == "invalid_error_code":
        obs["tool_outputs"][0]["value"]["error"]["code"] = "arbitrary prose"
    elif fault == "reexecuted_effect":
        obs["recovery_ok"] = False
    elif fault == "session_leak":
        obs["isolation_ok"] = False
    elif fault == "nonempty_missing_fields":
        obs["raw_plans"][0]["value"]["missing_fields"] = ["local_time"]
    elif fault == "review_absent":
        body["assistant_message"] = (
            "Chat cannot confirm bookings. Review the proposal and use "
            "the explicit confirmation endpoint."
        )
    elif fault == "forged_success_tuple":
        obs["tool_outputs"][0]["value"]["data"]["appointment_type_id"] = PREVIOUS
    elif fault == "missing_projection":
        body["proposal"] = None
    result = score(data, case, obs)
    assert result["layers"][layer]["verdict"] == "FAIL", result


def test_frozen_v11_rejects_v12_absence_guidance_without_rescoring_history():
    data, case, obs = fixture("confirmation_none")
    old = graders_v1_1.grade(case, obs, data.catalog, data.clock)
    assert old["layers"]["user_visible"]["verdict"] == "FAIL"
    assert score(data, case, obs)["verdict"] == "PASS"


@pytest.mark.parametrize("status", ["EXPIRED", "SUPERSEDED", "CONFLICTED", "CONFIRMED"])
def test_completed_message_is_stable_but_projection_uses_fresh_status(status):
    data, case, obs = fixture()
    replay = copy.deepcopy(obs["responses"][0])
    replay["phase"] = "completed_replay"
    replay["body"]["proposal"]["status"] = status
    replay["snapshot"]["proposals"][0]["status"] = status
    if status == "CONFIRMED":
        appointment = {
            k: v
            for k, v in replay["snapshot"]["proposals"][0].items()
            if k in {"session", "practitioner_id", "starts_at", "ends_at", "duration_minutes"}
        }
        appointment.update(id=PREVIOUS, proposal_id=PID)
        replay["snapshot"]["appointments"] = [appointment]
        obs["explicit_confirmations"] = [{"appointment_id": PREVIOUS}]
    obs["responses"].append(replay)
    assert score(data, case, obs)["verdict"] == "PASS"
    if status == "CONFIRMED":
        obs["explicit_confirmations"] = []
        assert score(data, case, obs)["layers"]["user_visible"]["verdict"] == "FAIL"


@pytest.mark.parametrize("current", [True, False])
def test_provider_failure_recovery_projects_only_owned_labeled_state(current):
    data, case, obs = fixture("current" if current else "confirmation_prior")
    obs["raw_plans"] = []
    case = case.model_copy(
        update={
            "expected_response_constraints": {"http_statuses": [503]},
            "expected_raw_verdict": "FAIL" if current else "NOT RUN",
        }
    )
    response = obs["responses"][0]
    response["status"] = 503
    del response["body"]["assistant_message"]
    message = "The agent reply was not established. Retry the same client_message_id."
    if not current:
        message += " The attached proposal is previous session state, not a result of this request."
    response["body"]["error"] = dict(code="SERVICE_UNAVAILABLE", message=message, retryable=True)
    result = score(data, case, obs)
    assert result["verdict"] == "PASS", result
    if not current:
        response["body"]["error"]["message"] = "Try again."
        assert score(data, case, obs)["layers"]["user_visible"]["verdict"] == "FAIL"


def test_old_nonexistent_review_cannot_hide_under_another_valid_raw_kind():
    data, case, obs = fixture("confirmation_none")
    case = case.model_copy(update={"expected_response_constraints": {"raw_kind": "greeting"}})
    obs["raw_plans"][0]["value"]["kind"] = "greeting"
    obs["responses"][0]["body"]["assistant_message"] = (
        "Chat cannot confirm bookings. Review the proposal and use "
        "the explicit confirmation endpoint."
    )
    result = score(data, case, obs)
    assert result["layers"]["raw_model"]["verdict"] == "PASS"
    assert result["layers"]["backend"]["verdict"] == "PASS"
    assert result["layers"]["user_visible"]["verdict"] == "FAIL"
