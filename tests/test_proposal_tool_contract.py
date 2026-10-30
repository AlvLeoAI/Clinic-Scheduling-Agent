"""Offline contract checks: tool JSON strings must match the existing HH:MM API contract."""

import json
import re
from datetime import time, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.tools import TOOL_NAMES, ProposalArguments, tool_definitions, validate_arguments
from app.db.models import Appointment, BookingProposal
from app.schemas.booking import ProposalRequest
from app.services.booking import BookingService
from tests import test_chat as chat_helpers
from tests.conftest import NOW
from tests.test_chat import call, final, parsed, proposal_args

harness = chat_helpers.harness

PATTERN = r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"
VALID_TIMES = ["00:00", "00:01", "09:00", "09:30", "12:59", "19:59", "20:00", "23:59"]
INVALID_TIMES = [
    "09:00:00",
    "9:00",
    "24:00",
    "09:60",
    "09:00Z",
    "09:00+00:00",
    "09:00:00-06:00",
    "09:00:00.0000000000+00:00",
    "09:00:00.0000000000Z",
    " 09:00",
    "09:00 ",
    "09:00\n",
    "09:00\r\n",
    "٠٩:٠٠",
    "",
    None,
    900,
    True,
]


def proposal_schema():
    return next(t for t in tool_definitions() if t["name"] == "create_booking_proposal")


def schema_accepts_time(value):
    """Check the emitted string constraints independently of Pydantic's regex engine."""
    schema = proposal_schema()["parameters"]["properties"]["local_time"]
    return (
        isinstance(value, str)
        and schema["minLength"] <= len(value) <= schema["maxLength"]
        and re.search(schema["pattern"], value) is not None
    )


def test_proposal_schema_is_strict_hhmm_without_time_format():
    tool = proposal_schema()
    assert tuple(t["name"] for t in tool_definitions()) == TOOL_NAMES
    assert tool["strict"] is True
    schema = tool["parameters"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["local_time"] == {
        "type": "string",
        "title": "Local Time",
        "pattern": PATTERN,
        "minLength": 5,
        "maxLength": 5,
    }
    assert "session_id" not in schema["properties"]


@pytest.mark.parametrize("value", VALID_TIMES)
def test_valid_tool_times_remain_strings_and_convert_through_existing_request(value):
    args, error = validate_arguments(
        "create_booking_proposal", json.dumps(proposal_args(local_time=value))
    )
    assert error is None and isinstance(args, ProposalArguments)
    assert args.local_time == value and isinstance(args.local_time, str)
    assert schema_accepts_time(value)
    request = ProposalRequest.model_validate(args.model_dump())
    assert request.local_time == time.fromisoformat(value)
    assert request.local_time.tzinfo is None


@pytest.mark.parametrize("value", INVALID_TIMES)
def test_malformed_times_reject_without_normalization_in_tool_and_existing_api(value):
    payload = proposal_args(local_time=value)
    args, error = validate_arguments("create_booking_proposal", json.dumps(payload))
    assert args is None and error["error"]["code"] == "INVALID_TOOL_ARGUMENTS"
    assert not schema_accepts_time(value)
    with pytest.raises(ValidationError):
        ProposalRequest.model_validate(payload)


def test_schema_tool_model_and_backend_agree_on_all_1440_valid_minutes():
    for hour in range(24):
        for minute in range(60):
            value = f"{hour:02}:{minute:02}"
            args = ProposalArguments.model_validate(proposal_args(local_time=value))
            assert schema_accepts_time(value)
            assert ProposalRequest.model_validate(args.model_dump()).local_time == time(
                hour, minute
            )


def assert_fake_provider_schema(payload):
    assert payload["store"] is False and payload["parallel_tool_calls"] is False
    assert payload["tools"] == tool_definitions()
    for tool in payload["tools"]:
        assert tool["strict"] is True
        assert tool["parameters"]["additionalProperties"] is False
        assert set(tool["parameters"]["required"]) == set(tool["parameters"]["properties"])
    local_time = next(t for t in payload["tools"] if t["name"] == "create_booking_proposal")[
        "parameters"
    ]["properties"]["local_time"]
    assert "format" not in local_time and local_time["pattern"] == PATTERN


@pytest.mark.postgres
@pytest.mark.agent_offline
def test_fake_provider_strict_contract_creates_one_owned_pending_proposal(harness, monkeypatch):
    owner = harness.owner()
    converted = []
    source_turns = []
    original = BookingService.create_proposal

    def capture(service, session_id, request, trace_id, *, source_turn_id):
        assert source_turn_id is not None
        assert session_id == harness.owners[0]
        source_turns.append(source_turn_id)
        converted.append(request)
        return original(service, session_id, request, trace_id, source_turn_id=source_turn_id)

    monkeypatch.setattr(BookingService, "create_proposal", capture)

    def decision(payload):
        assert_fake_provider_schema(payload)
        assert schema_accepts_time("09:00")
        return call("create_booking_proposal", proposal_args(), call_id="hhmm_proposal")

    def reply(payload):
        assert_fake_provider_schema(payload)
        output = next(i for i in payload["input"] if i.get("type") == "function_call_output")
        assert output["call_id"] == "hhmm_proposal"
        result = json.loads(output["output"])
        assert result["ok"] is True and result["data"]["status"] == "PENDING"
        return final("proposal")

    harness.provider.steps.extend([decision, reply])
    response, _ = harness.chat(owner)
    body = parsed(response)
    assert source_turns == [body.turn_id]
    proposal = body.proposal
    assert proposal.status == "PENDING" and proposal.duration_minutes == 30
    assert proposal.expires_at == NOW + timedelta(minutes=10)
    assert "Confirmation is a separate explicit action" in body.assistant_message
    assert len(converted) == 1 and isinstance(converted[0], ProposalRequest)
    assert converted[0].local_time == time(9) and converted[0].local_time.tzinfo is None
    with Session(harness.engine) as db:
        row = db.get(BookingProposal, proposal.proposal_id)
        assert row.session_id == harness.owners[0]
        assert row.source_turn_id == body.turn_id
        assert row.status == "PENDING" and row.expires_at == NOW + timedelta(minutes=10)
        assert row.ends_at - row.starts_at == timedelta(minutes=30)
        assert len(list(db.scalars(select(Appointment)))) == 0
    assert harness.counts()["booking_proposals"] == 1


@pytest.mark.postgres
@pytest.mark.agent_offline
@pytest.mark.parametrize("value", INVALID_TIMES[:9])
def test_fake_malformed_tool_arguments_create_no_proposal_or_appointment(harness, value):
    owner = harness.owner()

    def rejected(payload):
        output = next(i for i in payload["input"] if i.get("type") == "function_call_output")
        assert output["call_id"] == "hhmm_rejected"
        result = json.loads(output["output"])
        assert result["ok"] is False and result["error"]["code"] == "INVALID_TOOL_ARGUMENTS"
        return final("clarify", missing=["local_time"])

    harness.provider.steps.extend(
        [
            call(
                "create_booking_proposal", proposal_args(local_time=value), call_id="hhmm_rejected"
            ),
            rejected,
        ]
    )
    response, _ = harness.chat(owner)
    assert parsed(response).proposal is None
    counts = harness.counts()
    assert counts["booking_proposals"] == counts["appointments"] == 0


@pytest.mark.postgres
@pytest.mark.agent_offline
@pytest.mark.parametrize("value", ["00:00", "09:15", "17:00", "23:59"])
def test_valid_time_syntax_still_obeys_unchanged_scheduling_policies(harness, value):
    owner = harness.owner()

    def rejected(payload):
        output = next(i for i in payload["input"] if i.get("type") == "function_call_output")
        result = json.loads(output["output"])
        assert result["ok"] is False
        assert result["error"]["code"] != "INVALID_TOOL_ARGUMENTS"
        return final("clarify", missing=["local_time"])

    harness.provider.steps.extend(
        [call("create_booking_proposal", proposal_args(local_time=value)), rejected]
    )
    response, _ = harness.chat(owner)
    assert parsed(response).proposal is None
    assert harness.counts()["booking_proposals"] == harness.counts()["appointments"] == 0
