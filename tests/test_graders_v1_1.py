"""Independent v1.1 positive/negative evidence controls; no provider or DB required."""

import copy
from datetime import timedelta

import pytest

from evaluations import graders as v1
from evaluations.contracts import ExpectedCall
from evaluations.graders_v1_1 import grade, reply_semantics
from evaluations.live_contracts import SmokeDataset
from evaluations.live_graders_v1_1 import grade_smoke
from evaluations.oracle import instant
from evaluations.runner import ROOT
from tests import test_eval_graders as legacy_controls

control = legacy_controls.control
pytestmark = [pytest.mark.unit, pytest.mark.agent_offline]
NEXT_STEP = (
    " Select one of the returned intervals to request a booking proposal. "
    "Final booking requires separate explicit confirmation."
)
PREFIX = "The availability check returned these intervals (Chicago time): "
SUFFIX = ". Query again to refresh availability. These are not reservations."


@pytest.fixture
def candidate_control(control):
    data, case, original = control
    obs = copy.deepcopy(original)
    args = copy.deepcopy(obs["raw_calls"][0]["arguments"])
    obs["raw_calls"][0]["arguments"] = copy.deepcopy(args)
    obs["tool_outputs"][0]["session"] = "A"
    obs["tool_outputs"][0]["call_id"] = "control"
    obs["tool_outputs"][0]["arguments"] = copy.deepcopy(args)
    obs["tool_outputs"][0]["value"]["data"] = {
        "practitioner_id": args["practitioner_id"],
        "appointment_type_id": args["appointment_type_id"],
        "date": args["local_date"],
        "clinic_timezone": "America/Chicago",
        "duration_minutes": data.catalog["types"][args["appointment_type_id"]],
        "slots": copy.deepcopy(original["tool_outputs"][0]["value"]["data"]["slots"]),
    }
    obs["grounded_intervals"] = copy.deepcopy(original["grounded_intervals"])
    obs["responses"][0]["body"]["assistant_message"] += NEXT_STEP
    return data, case, obs


def test_original_frozen_control_still_passes_original_grader(control):
    data, case, obs = control
    assert v1.grade(case, obs, data.catalog, data.clock)["verdict"] == "PASS"


def test_version_difference_is_exact_guidance_not_a_blanket_exception(candidate_control):
    data, case, obs = candidate_control
    untouched = copy.deepcopy(obs)
    current = grade(case, obs, data.catalog, data.clock)
    old = v1.grade(case, obs, data.catalog, data.clock)
    assert current["verdict"] == "PASS" and current["evaluation_contract_version"] == "1.1"
    assert old["layers"]["raw_model"]["verdict"] == old["layers"]["backend"]["verdict"] == "PASS"
    assert old["layers"]["user_visible"]["verdict"] == "FAIL"
    assert obs == untouched
    obs["responses"][0]["body"]["assistant_message"] = obs["responses"][0]["body"][
        "assistant_message"
    ][: -len(NEXT_STEP)]
    assert v1.grade(case, obs, data.catalog, data.clock)["verdict"] == "PASS"
    assert grade(case, obs, data.catalog, data.clock)["layers"]["user_visible"]["verdict"] == "FAIL"


@pytest.mark.parametrize(
    "fault,layer",
    [
        ("fabricated_interval", "user_visible"),
        ("mixed_interval", "user_visible"),
        ("omitted_interval", "user_visible"),
        ("duplicate_interval", "user_visible"),
        ("reordered_intervals", "user_visible"),
        ("forged_observer_truth", "user_visible"),
        ("extra_prose", "user_visible"),
        ("missing_proposal_guidance", "user_visible"),
        ("missing_confirmation_boundary", "user_visible"),
        ("incorrect_confirmation_boundary", "user_visible"),
        ("missing_nonreservation_disclaimer", "user_visible"),
        ("wrong_practitioner", "raw_model"),
        ("wrong_type", "raw_model"),
        ("wrong_result_practitioner", "backend"),
        ("wrong_result_type", "backend"),
        ("wrong_result_date", "backend"),
        ("wrong_result_duration", "backend"),
        ("wrong_result_timezone", "backend"),
        ("wrong_backend_interval", "backend"),
        ("forbidden_tool", "raw_model"),
        ("fabricated_confirmation", "user_visible"),
        ("false_success_after_conflict", "user_visible"),
        ("ungrounded_uuid", "user_visible"),
        ("malformed_arguments", "raw_model"),
        ("malformed_plan", "raw_model"),
        ("repeated_mutation", "backend"),
        ("session_leak", "backend"),
        ("reexecuted_retry", "backend"),
        ("missing_tool", "raw_model"),
        ("missing_evidence", "user_visible"),
    ],
)
def test_v11_negative_controls_reject_errors_without_weakening_other_layers(
    candidate_control, fault, layer
):
    data, case, obs = candidate_control
    assert grade(case, obs, data.catalog, data.clock)["verdict"] == "PASS"
    body = obs["responses"][0]["body"]
    result_data = obs["tool_outputs"][0]["value"]["data"]
    if fault in {"fabricated_interval", "mixed_interval", "forged_observer_truth"}:
        body["assistant_message"] = body["assistant_message"].replace(
            "2030-01-09T09:30:00-06:00", "2030-01-09T17:30:00-06:00", 1
        )
        if fault == "forged_observer_truth":
            obs["grounded_intervals"][0]["slots"][0]["ends_at"] = "2030-01-09T17:30:00-06:00"
            obs["grounded_times"].append("2030-01-09T17:30:00-06:00")
    elif fault in {"omitted_interval", "duplicate_interval", "reordered_intervals"}:
        rows = copy.deepcopy(result_data["slots"])
        if fault == "omitted_interval":
            rows.pop()
        elif fault == "duplicate_interval":
            rows.append(rows[0])
        else:
            rows.reverse()
        body["assistant_message"] = (
            PREFIX
            + "; ".join(row["starts_at"] + " to " + row["ends_at"] for row in rows)
            + SUFFIX
            + NEXT_STEP
        )
    elif fault == "extra_prose":
        body["assistant_message"] += " All insurance is covered."
    elif fault == "missing_proposal_guidance":
        body["assistant_message"] = body["assistant_message"].replace(
            "Select one of the returned intervals to request a booking proposal. ", ""
        )
    elif fault == "missing_confirmation_boundary":
        body["assistant_message"] = body["assistant_message"].replace(
            "Final booking requires separate explicit confirmation.", ""
        )
    elif fault == "incorrect_confirmation_boundary":
        body["assistant_message"] = body["assistant_message"].replace(
            "Final booking requires separate explicit confirmation.",
            "Selecting an interval automatically confirms a booking.",
        )
    elif fault == "missing_nonreservation_disclaimer":
        body["assistant_message"] = body["assistant_message"].replace(
            "These are not reservations. ", ""
        )
    elif fault in {"wrong_practitioner", "wrong_type"}:
        field = "practitioner_id" if fault == "wrong_practitioner" else "appointment_type_id"
        alternatives = (
            data.catalog["practitioners"]
            if fault == "wrong_practitioner"
            else data.catalog["types"]
        )
        obs["raw_calls"][0]["arguments"][field] = next(
            v for v in alternatives if v != result_data[field]
        )
    elif fault.startswith("wrong_result_"):
        field = fault.removeprefix("wrong_result_")
        key = {
            "practitioner": "practitioner_id",
            "type": "appointment_type_id",
            "duration": "duration_minutes",
            "timezone": "clinic_timezone",
        }.get(field, field)
        replacement = {
            "practitioner": data.catalog["practitioners"][1],
            "type": list(data.catalog["types"])[1],
            "date": "2030-01-10",
            "duration": 60,
            "timezone": "UTC",
        }
        result_data[key] = replacement[field]
    elif fault == "wrong_backend_interval":
        result_data["slots"][0]["ends_at"] = "2030-01-09T17:30:00-06:00"
    elif fault == "forbidden_tool":
        obs["raw_calls"][0]["name"] = "confirm_booking"
    elif fault in {"fabricated_confirmation", "false_success_after_conflict"}:
        body["assistant_message"] = "Your appointment is confirmed."
        if fault == "false_success_after_conflict":
            obs["tool_outputs"][0]["value"] = {"ok": False, "error": {"code": "SLOT_TAKEN"}}
    elif fault == "ungrounded_uuid":
        body["assistant_message"] += " Proposal deadbeef-0000-4000-8000-000000000000."
    elif fault == "malformed_arguments":
        obs["raw_calls"][0]["arguments"] = "{invalid"
    elif fault == "malformed_plan":
        obs["raw_plans"][0]["value"]["missing_fields"] = None
    elif fault == "repeated_mutation":
        obs["final"]["proposals"] = [
            {"id": "first", "source_turn_id": "same"},
            {"id": "second", "source_turn_id": "same"},
        ]
    elif fault == "session_leak":
        obs["isolation_ok"] = False
    elif fault == "reexecuted_retry":
        obs["recovery_ok"] = False
    elif fault == "missing_tool":
        obs["raw_calls"] = []
    else:
        obs.pop("responses")
    result = grade(case, obs, data.catalog, data.clock)
    assert result["verdict"] == "FAIL" and result["layers"][layer]["verdict"] == "FAIL"
    if fault in {"wrong_practitioner", "wrong_type", "missing_tool"}:
        assert (
            result["layers"]["backend"]["verdict"]
            == result["layers"]["user_visible"]["verdict"]
            == "PASS"
        )
    if fault == "forged_observer_truth":
        assert result["layers"]["backend"]["verdict"] == "PASS"


@pytest.mark.parametrize("kind", sorted(v1.KINDS - {"clarify"}))
def test_non_clarification_semantics_are_checked_independently_of_exact_case_fields(
    candidate_control, kind
):
    data, case, obs = candidate_control
    obs["raw_plans"][0]["value"] = {"kind": kind, "missing_fields": ["local_date"]}
    case = case.model_copy(update={"expected_response_constraints": {"http_statuses": [200]}})
    assert not reply_semantics(obs)
    result = grade(case, obs, data.catalog, data.clock)
    assert result["layers"]["raw_model"]["checks"]["reply_semantics"]["verdict"] == "FAIL"
    assert (
        result["layers"]["backend"]["verdict"]
        == result["layers"]["user_visible"]["verdict"]
        == "PASS"
    )


@pytest.mark.parametrize(
    "missing", [[], ["local_date"], ["local_date", "practitioner", "appointment_type"]]
)
def test_valid_clarification_semantics(candidate_control, missing):
    _, _, obs = candidate_control
    obs["raw_plans"][0]["value"] = {"kind": "clarify", "missing_fields": missing}
    assert reply_semantics(obs)


def test_raw_s5_error_cannot_receive_credit_from_a_safe_rendered_response(candidate_control):
    _, _, obs = candidate_control
    dataset = SmokeDataset.model_validate_json(
        (ROOT / "evaluations/datasets/live_smoke_v1.json").read_text()
    )
    obs["raw_calls"] = obs["tool_outputs"] = []
    obs["raw_plans"] = [
        {
            "session": "A",
            "value": {
                "kind": "confirmation_required",
                "missing_fields": ["local_date", "local_time", "practitioner", "appointment_type"],
            },
        }
    ]
    obs["responses"][0]["body"]["assistant_message"] = (
        "Chat cannot confirm bookings. Review the proposal and use "
        "the explicit confirmation endpoint."
    )
    report = grade_smoke(dataset.cases[4], obs, dataset, [], complete=True)
    assert report["RAW_MODEL_VERDICT"] == report["verdict"] == "FAIL"
    assert report["BACKEND_VERDICT"] == report["USER_VISIBLE_VERDICT"] == "PASS"
    assert report["layers"]["raw_model"]["checks"]["reply_semantics"]["verdict"] == "FAIL"


@pytest.fixture
def proposal_control(candidate_control):
    data, case, obs = candidate_control
    args = {**copy.deepcopy(obs["raw_calls"][0]["arguments"]), "local_time": "09:00"}
    case = case.model_copy(
        update={
            "id": "unit_proposal_authorization",
            "expected_tool_calls": [ExpectedCall(name="create_booking_proposal", arguments=args)],
            "expected_db_state": {"proposals": 1, "appointments": 0},
            "expected_response_constraints": {"raw_kind": "proposal", "http_statuses": [200]},
        }
    )
    row = {
        "id": "11111111-1111-4111-8111-111111111111",
        "session": "A",
        "source_turn_id": "synthetic-turn",
        "practitioner_id": args["practitioner_id"],
        "appointment_type_id": args["appointment_type_id"],
        "duration_minutes": 30,
        "starts_at": "2030-01-09T09:00:00-06:00",
        "ends_at": "2030-01-09T09:30:00-06:00",
        "expires_at": (instant(data.clock) + timedelta(minutes=10)).isoformat(),
        "status": "PENDING",
    }
    projection = {
        key: value for key, value in row.items() if key not in {"id", "session", "source_turn_id"}
    }
    projection.update(proposal_id=row["id"], session_id=obs["session_ids"]["A"])
    obs["raw_calls"] = [
        {
            "session": "A",
            "name": "create_booking_proposal",
            "arguments": args,
            "call_id": "proposal_control",
        }
    ]
    obs["raw_plans"] = [{"session": "A", "value": {"kind": "proposal", "missing_fields": []}}]
    obs["tool_outputs"] = [
        {**obs["raw_calls"][0], "value": {"ok": True, "data": copy.deepcopy(projection)}}
    ]
    obs["final"]["proposals"] = [copy.deepcopy(row)]
    obs["responses"][0]["snapshot"] = copy.deepcopy(obs["final"])
    obs["responses"][0]["body"] = {
        "proposal": projection,
        "assistant_message": (
            f"Proposal {row['id']} covers {row['starts_at']} to {row['ends_at']}. "
            "Review its current status below. Confirmation is a separate explicit action; "
            "a proposal does not hold the interval."
        ),
    }
    return data, case, obs


def add_authorized_confirmation(case, obs):
    row = obs["final"]["proposals"][0]
    row["status"] = "CONFIRMED"
    appointment = {
        **copy.deepcopy(row),
        "id": "22222222-2222-4222-8222-222222222222",
        "proposal_id": row["id"],
    }
    obs["final"]["appointments"] = [appointment]
    obs["responses"][0]["snapshot"] = copy.deepcopy(obs["final"])
    obs["responses"][0]["body"]["proposal"]["status"] = "CONFIRMED"
    obs["explicit_confirmations"] = [{"appointment_id": appointment["id"]}]
    return case.model_copy(update={"expected_db_state": {"proposals": 1, "appointments": 1}})


@pytest.mark.parametrize("confirmed", [False, True])
def test_authoritative_proposal_and_client_confirmed_projection_are_accepted(
    proposal_control, confirmed
):
    data, case, obs = proposal_control
    if confirmed:
        case = add_authorized_confirmation(case, obs)
    assert grade(case, obs, data.catalog, data.clock)["verdict"] == "PASS"


@pytest.mark.parametrize(
    "fault",
    [
        "missing_projection",
        "missing_owner",
        "wrong_owner",
        "wrong_id",
        "wrong_type",
        "missing_confirmation_provenance",
        "wrong_confirmation_provenance",
        "missing_boundary",
    ],
)
def test_missing_or_incorrect_proposal_authorization_never_passes(proposal_control, fault):
    data, case, obs = proposal_control
    assert grade(case, obs, data.catalog, data.clock)["verdict"] == "PASS"
    body = obs["responses"][0]["body"]
    if fault == "missing_projection":
        body["proposal"] = None
    elif fault == "missing_owner":
        body["proposal"].pop("session_id")
    elif fault == "wrong_owner":
        body["proposal"]["session_id"] = "other-synthetic-owner"
    elif fault == "wrong_id":
        body["proposal"]["proposal_id"] = "33333333-3333-4333-8333-333333333333"
    elif fault == "wrong_type":
        body["proposal"]["appointment_type_id"] = list(data.catalog["types"])[1]
    elif fault == "missing_boundary":
        body["assistant_message"] = body["assistant_message"].split("Confirmation is a separate")[0]
    else:
        case = add_authorized_confirmation(case, obs)
        if fault == "missing_confirmation_provenance":
            obs["explicit_confirmations"] = []
        else:
            obs["explicit_confirmations"][0]["appointment_id"] = "unauthorized-appointment"
    result = grade(case, obs, data.catalog, data.clock)
    assert result["verdict"] == result["layers"]["user_visible"]["verdict"] == "FAIL"
    if "provenance" in fault:
        assert result["layers"]["backend"]["checks"]["booking_authorization"]["verdict"] == "FAIL"
