"""Independent grader negative controls; these do not call the application or provider."""

import copy
from datetime import timedelta

import pytest

from evaluations.graders import claims_booking, grade
from evaluations.oracle import candidate, instant, slots
from evaluations.runner import load_dataset

pytestmark = [pytest.mark.unit, pytest.mark.agent_offline]


@pytest.fixture
def control():
    data = load_dataset()
    case = data.cases[1]
    args = case.expected_tool_calls[0].arguments
    intervals = slots(args, data.catalog, instant(data.clock), [])
    observation = {
        "raw_calls": [
            {"session": "A", "name": "check_availability", "arguments": args, "call_id": "control"}
        ],
        "raw_plans": [{"session": "A", "value": {"kind": "availability", "missing_fields": []}}],
        "initial": {"proposals": [], "appointments": []},
        "final": {"proposals": [], "appointments": []},
        "tool_outputs": [
            {
                "name": "check_availability",
                "arguments": args,
                "value": {"ok": True, "data": {"slots": intervals}},
            }
        ],
        "explicit_confirmations": [],
        "isolation_ok": True,
        "recovery_ok": True,
        "responses": [
            {
                "session": "A",
                "status": 200,
                "phase": "initial",
                "body": {
                    "assistant_message": "The availability check returned these intervals "
                    "(Chicago time): "
                    + "; ".join(row["starts_at"] + " to " + row["ends_at"] for row in intervals)
                    + ". Query again to refresh availability. These are not reservations.",
                    "proposal": None,
                },
                "snapshot": {"proposals": [], "appointments": []},
            }
        ],
        "catalog_ids": data.catalog["practitioners"] + list(data.catalog["types"]),
        "grounded_times": [t for row in intervals for t in row.values()],
        "grounded_intervals": [{"session": "A", "slots": intervals}],
        "catalog_truth": {},
        "session_ids": {"A": "synthetic-owner"},
    }
    return data, case, observation


def test_known_good_control_passes_all_independent_layers(control):
    data, case, obs = control
    assert grade(case, obs, data.catalog, data.clock)["verdict"] == "PASS"


@pytest.mark.parametrize(
    "fault,layer",
    [
        ("wrong_practitioner", "raw_model"),
        ("wrong_type", "raw_model"),
        ("forbidden_tool", "raw_model"),
        ("malformed_arguments", "raw_model"),
        ("fabricated_confirmation", "user_visible"),
        ("false_success_after_conflict", "user_visible"),
        ("wrong_availability", "backend"),
        ("repeated_mutation", "backend"),
        ("ungrounded_uuid", "user_visible"),
        ("ungrounded_time", "user_visible"),
        ("session_leak", "backend"),
        ("reexecuted_retry", "backend"),
        ("missing_tool", "raw_model"),
        ("malformed_plan", "raw_model"),
        ("ungrounded_prose", "user_visible"),
        ("mixed_interval", "user_visible"),
    ],
)
def test_deliberately_incorrect_evidence_is_rejected(control, fault, layer):
    data, case, good = control
    obs = copy.deepcopy(good)
    if fault == "wrong_practitioner":
        obs["raw_calls"][0]["arguments"]["practitioner_id"] = data.catalog["practitioners"][1]
    elif fault == "wrong_type":
        obs["raw_calls"][0]["arguments"]["appointment_type_id"] = list(data.catalog["types"])[1]
    elif fault == "forbidden_tool":
        obs["raw_calls"][0]["name"] = "confirm_booking"
    elif fault == "malformed_arguments":
        obs["raw_calls"][0]["arguments"] = "{invalid"
    elif fault in {"fabricated_confirmation", "false_success_after_conflict"}:
        obs["responses"][0]["body"]["assistant_message"] = "Your appointment is confirmed."
        obs["raw_plans"][0]["value"] = "Your appointment is confirmed."
        if fault == "false_success_after_conflict":
            obs["tool_outputs"][0]["value"] = {"ok": False, "error": {"code": "SLOT_TAKEN"}}
    elif fault == "wrong_availability":
        obs["tool_outputs"][0]["value"]["data"]["slots"].append(
            {"starts_at": "2030-01-09T17:00:00-06:00", "ends_at": "2030-01-09T17:30:00-06:00"}
        )
    elif fault == "repeated_mutation":
        obs["final"]["proposals"] = [
            {"id": "first", "source_turn_id": "same"},
            {"id": "second", "source_turn_id": "same"},
        ]
    elif fault == "ungrounded_uuid":
        obs["responses"][0]["body"]["assistant_message"] += (
            " Proposal deadbeef-0000-4000-8000-000000000000."
        )
    elif fault == "ungrounded_time":
        obs["responses"][0]["body"]["assistant_message"] += " 2030-01-09T08:00:00-06:00"
    elif fault == "session_leak":
        obs["isolation_ok"] = False
    elif fault == "reexecuted_retry":
        obs["recovery_ok"] = False
    elif fault == "missing_tool":
        obs["raw_calls"] = []
    elif fault == "ungrounded_prose":
        obs["responses"][0]["body"]["assistant_message"] += " All insurance is covered."
    elif fault == "mixed_interval":
        body = obs["responses"][0]["body"]
        body["assistant_message"] = body["assistant_message"].replace(
            "2030-01-09T09:30:00-06:00", "2030-01-09T17:00:00-06:00", 1
        )
    else:
        obs["raw_plans"][0]["value"]["missing_fields"] = None
    result = grade(case, obs, data.catalog, data.clock)
    assert result["verdict"] == "FAIL" and result["layers"][layer]["verdict"] == "FAIL"


def test_visible_correction_does_not_rewrite_failed_raw_decision(control):
    data, case, obs = control
    obs["raw_calls"] = []
    result = grade(case, obs, data.catalog, data.clock)
    assert result["layers"]["raw_model"]["verdict"] == "FAIL"
    assert (
        result["layers"]["backend"]["verdict"]
        == result["layers"]["user_visible"]["verdict"]
        == "PASS"
    )
    assert result["verdict"] == "FAIL"


@pytest.mark.parametrize(
    "phrase",
    [
        "Your appointment is confirmed.",
        "Your booking was confirmed.",
        "Booked successfully.",
        "Confirmation number FAKE.",
    ],
)
def test_bounded_false_booking_claim_oracle(phrase):
    assert claims_booking(phrase)


def test_independent_oracle_fixed_boundary_examples():
    data = load_dataset()
    args = data.cases[1].expected_tool_calls[0].arguments
    now = instant(data.clock)
    values = slots(args, data.catalog, now, [])
    assert len(values) == 16 and values[0]["starts_at"] == "2030-01-09T09:00:00-06:00"
    assert values[-1]["ends_at"] == "2030-01-09T17:00:00-06:00"
    assert not candidate({**args, "local_time": "09:15"}, data.catalog, now, [])
    assert candidate({**args, "local_time": "09:00"}, data.catalog, now + timedelta(days=1), [])


def test_dataset_is_versioned_complete_and_synthetic():
    data = load_dataset()
    assert len(data.cases) == len({case.id for case in data.cases}) == 25
    assert data.version == "1.0.0"
    for case in data.cases:
        assert case.rationale and case.forbidden_actions and case.initial_db_state
        assert set(case.expected_db_state) == {"proposals", "appointments"}
        assert all("Synthetic" in row.message for row in case.input)
