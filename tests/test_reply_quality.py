"""R2C.1 deterministic contract/renderer checks, never live model quality evidence."""

import copy
import json
import re
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.replies import ReplyPlan, reply_format
from app.db.models import BookingProposal, ChatSession, ChatTurn, ConversationItem
from app.services import chat as chat_module
from evaluations.live_runner import run_smoke
from tests import test_chat as chat_helpers
from tests import test_live_runner as live_helpers
from tests.conftest import NOW
from tests.helpers import appointment_row, proposal_row
from tests.test_chat import availability_args, call, final, parsed, proposal_args

harness = chat_helpers.harness
isolated = live_helpers.isolated
pytestmark = pytest.mark.agent_offline
NON_CLARIFICATION_KINDS = [
    "greeting",
    "catalog",
    "availability",
    "proposal",
    "confirmation_required",
    "out_of_scope",
]
FIELDS = ["local_date", "local_time", "practitioner", "appointment_type"]
GUIDANCE = (
    "Select one of the returned intervals to request a booking proposal. "
    "Final booking requires separate explicit confirmation."
)


@pytest.mark.parametrize("missing", [[], ["local_date"], ["local_time", "practitioner"], FIELDS])
def test_clarification_can_identify_missing_scheduling_fields(missing):
    assert ReplyPlan(kind="clarify", missing_fields=missing).missing_fields == missing


@pytest.mark.parametrize("kind", NON_CLARIFICATION_KINDS)
def test_non_clarification_plans_accept_only_empty_metadata(kind):
    assert ReplyPlan(kind=kind, missing_fields=[]).model_dump() == {
        "kind": kind,
        "missing_fields": [],
    }


@pytest.mark.parametrize("kind", NON_CLARIFICATION_KINDS)
@pytest.mark.parametrize("field", FIELDS)
def test_irrelevant_metadata_is_rejected_without_normalizing_model_decision(kind, field):
    raw = {"kind": kind, "missing_fields": [field]}
    before = copy.deepcopy(raw)
    with pytest.raises(ValidationError, match="Only clarify replies"):
        ReplyPlan.model_validate(raw)
    with pytest.raises(ValidationError, match="Only clarify replies"):
        ReplyPlan.model_validate_json(json.dumps(raw))
    assert raw == before


def assert_strict_reply_schema(payload):
    assert payload["store"] is False and payload["parallel_tool_calls"] is False
    wire = payload["text"]["format"]
    assert wire["type"] == "json_schema" and wire["strict"] is True
    schema = wire["schema"]
    # This exact flat subset needs no conditional keywords or root unions.
    assert set(schema) == {"type", "title", "properties", "required", "additionalProperties"}
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"]) == {"kind", "missing_fields"}
    kind, missing = schema["properties"]["kind"], schema["properties"]["missing_fields"]
    assert set(kind) == {"type", "title", "enum", "description"}
    assert set(missing) == {"type", "title", "items", "maxItems", "description"}
    assert kind["type"] == "string" and set(kind["enum"]) == set(NON_CLARIFICATION_KINDS) | {
        "clarify"
    }
    assert missing["type"] == "array" and missing["maxItems"] == 4
    assert missing["items"] == {"type": "string", "enum": FIELDS}
    assert "confirmation_required" in missing["description"]
    assert "kind=clarify" in payload["instructions"]
    assert "missing_fields must be an empty array []" in payload["instructions"]


def test_strict_wire_schema_separates_syntax_from_application_semantics():
    assert_strict_reply_schema(
        {
            "store": False,
            "parallel_tool_calls": False,
            "text": reply_format(),
            "instructions": chat_module.INSTRUCTIONS,
        }
    )
    # The wire schema's independent enum/array constraints permit this shape.
    # Pydantic adds the cross-field invariant, without advertising unsupported JSON Schema.
    raw = {"kind": "confirmation_required", "missing_fields": FIELDS.copy()}
    assert raw["kind"] in reply_format()["format"]["schema"]["properties"]["kind"]["enum"]
    with pytest.raises(ValidationError):
        ReplyPlan.model_validate(raw)


@pytest.mark.postgres
@pytest.mark.parametrize("missing", [[], FIELDS])
def test_mocked_responses_transport_preserves_raw_failure_classification(isolated, missing):
    engine, ident, settings = isolated
    captured = []
    raw = {"kind": "confirmation_required", "missing_fields": missing.copy()}

    def transport(request):
        payload = json.loads(request.content)
        assert_strict_reply_schema(payload)
        captured.append(copy.deepcopy(raw))
        return httpx.Response(
            200,
            json={
                **final("confirmation_required", missing),
                "model": "gpt-6-luna",
                "usage": {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130},
            },
        )

    report = run_smoke(
        engine,
        settings,
        ident,
        scenario="S5",
        transport_factory=lambda _: httpx.MockTransport(transport),
    )
    case = report["cases"][0]
    assert report["mode"] == "MOCKED_DRY_RUN" and report["live_openai_evals"] == "NOT RUN"
    assert captured == [raw] and case["evidence"]["raw_plans"][0]["value"] == raw
    assert report["scenario_selection"]["selected"] == ["S5"]
    assert case["BACKEND_VERDICT"] == "PASS"
    assert case["evidence"]["final"]["proposals"] == []
    assert case["evidence"]["final"]["appointments"] == []
    assert case["evidence"]["explicit_confirmations"] == []
    assert case["evidence"]["raw_calls"] == []
    assert report["database_unchanged_after_scoped_cleanup"]
    response = case["evidence"]["responses"][0]
    if missing:
        assert case["RAW_MODEL_VERDICT"] == case["USER_VISIBLE_VERDICT"] == "FAIL"
        assert response["status"] == 503
        assert response["body"]["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "assistant_message" not in response["body"]
        assert case["layers"]["raw_model"]["checks"]["response_grounding"]["verdict"] == "FAIL"
    else:
        assert case["RAW_MODEL_VERDICT"] == case["USER_VISIBLE_VERDICT"] == "PASS"
        assert response["status"] == 200
        assert "cannot confirm" in response["body"]["assistant_message"]


@pytest.mark.postgres
def test_semantic_rejection_after_proposal_fails_turn_and_keeps_pending_effect_recoverable(harness):
    owner = harness.owner()
    harness.provider.steps.extend(
        [
            call("create_booking_proposal", proposal_args(), "quality_proposal"),
            final("confirmation_required", FIELDS),
            final("confirmation_required"),
        ]
    )
    failed, ident = harness.chat(owner)
    assert failed.status_code == 503 and failed.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "assistant_message" not in failed.json()
    pending = failed.json()["proposal"]
    assert pending["status"] == "PENDING"
    with Session(harness.engine) as db:
        turn_id = UUID(failed.json()["turn_id"])
        assert db.get(ChatTurn, turn_id).status == "FAILED"
        assert (
            list(
                db.scalars(
                    select(ConversationItem).where(
                        ConversationItem.turn_id == turn_id,
                        ConversationItem.item_type.in_(["reply_plan", "chat_result"]),
                    )
                )
            )
            == []
        )
        assert db.get(BookingProposal, UUID(pending["proposal_id"])).status == "PENDING"
    assert harness.counts()["booking_proposals"] == 1 and harness.counts()["appointments"] == 0
    recovered = parsed(harness.chat(owner, message_id=ident)[0])
    assert str(recovered.proposal.proposal_id) == pending["proposal_id"]
    assert (
        recovered.proposal.status == "PENDING" and "cannot confirm" in recovered.assistant_message
    )
    assert len(harness.provider.requests) == 3
    assert harness.counts()["booking_proposals"] == 1 and harness.counts()["appointments"] == 0


def rendered_intervals(message):
    prefix = "The availability check returned these intervals (Chicago time): "
    assert message.startswith(prefix)
    values, _ = message[len(prefix) :].split(". Query again to refresh availability.", 1)
    return [dict(zip(("starts_at", "ends_at"), pair.split(" to "))) for pair in values.split("; ")]


@pytest.mark.postgres
def test_availability_guidance_uses_only_postgres_intervals_and_creates_no_booking(harness):
    owner = harness.owner()
    harness.provider.steps.extend(
        [call("check_availability", availability_args()), final("availability")]
    )
    body = parsed(harness.chat(owner)[0])
    expected = harness.client.get(
        "/api/v1/availability",
        params={
            "date": availability_args()["local_date"],
            **{k: v for k, v in availability_args().items() if k != "local_date"},
        },
    )
    assert expected.status_code == 200
    assert rendered_intervals(body.assistant_message) == expected.json()["slots"]
    assert (
        GUIDANCE in body.assistant_message
        and "These are not reservations" in body.assistant_message
    )
    assert re.search(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", body.assistant_message) is None
    assert body.proposal is None
    assert harness.counts()["booking_proposals"] == harness.counts()["appointments"] == 0


@pytest.mark.postgres
@pytest.mark.parametrize("date", ["2030-01-12", "2029-01-01", "2031-01-01"])
def test_empty_or_expired_availability_never_invites_selection_of_invalid_intervals(harness, date):
    owner = harness.owner()
    args = {**availability_args(), "local_date": date}
    harness.provider.steps.extend([call("check_availability", args), final("availability")])
    body = parsed(harness.chat(owner)[0])
    assert body.assistant_message == (
        "The availability check found no valid intervals on that date. "
        "Query again to refresh availability."
    )
    assert GUIDANCE not in body.assistant_message
    assert body.proposal is None
    assert harness.counts()["booking_proposals"] == harness.counts()["appointments"] == 0


@pytest.mark.postgres
@pytest.mark.parametrize("change", ["occupied", "exhausted"])
def test_renderer_refreshes_postgres_when_availability_changes(harness, monkeypatch, change):
    if change == "exhausted":
        # Tomorrow's last 16:30 start is 24h15s away; the turn lease remains valid.
        harness.clock.now += timedelta(hours=7, minutes=29, seconds=45)
    owner = harness.owner()
    before_render, after_render = [], []
    original = chat_module.render_reply

    def render(*args, **kwargs):
        before_render.append(harness.counts())
        result = original(*args, **kwargs)
        after_render.append(harness.counts())
        return result

    monkeypatch.setattr(chat_module, "render_reply", render)

    def change_after_query(payload):
        output = next(i for i in payload["input"] if i.get("type") == "function_call_output")
        assert len(json.loads(output["output"])["data"]["slots"]) == (
            16 if change == "occupied" else 1
        )
        if change == "occupied":
            # Independent, explicitly constructed synthetic reservation fixture.
            with Session(harness.engine) as db:
                proposal = proposal_row(
                    db,
                    session=db.get(ChatSession, harness.owners[0]),
                    start=NOW + timedelta(days=2),
                )
                appointment_row(db, proposal)
                db.commit()
        else:
            harness.clock.now += timedelta(seconds=30)
        return final("availability")

    args = availability_args()
    if change == "exhausted":
        args = {**args, "local_date": "2030-01-08"}
    harness.provider.steps.extend([call("check_availability", args), change_after_query])
    body = parsed(harness.chat(owner)[0])
    assert before_render == after_render  # Rendering adds no proposal or appointment.
    if change == "occupied":
        actual = rendered_intervals(body.assistant_message)
        assert len(actual) == 15 and actual[0]["starts_at"] == "2030-01-09T09:30:00-06:00"
        assert "2030-01-09T09:00:00-06:00" not in body.assistant_message
        assert GUIDANCE in body.assistant_message
        assert harness.counts()["appointments"] == harness.counts()["booking_proposals"] == 1
    else:
        assert (
            "no valid intervals" in body.assistant_message
            and GUIDANCE not in body.assistant_message
        )
        assert harness.counts()["appointments"] == harness.counts()["booking_proposals"] == 0
    assert body.proposal is None


@pytest.mark.postgres
def test_completed_availability_replay_is_historical_with_refresh_and_confirmation_boundary(
    harness,
):
    owner = harness.owner()
    harness.provider.steps.extend(
        [
            call("check_availability", {**availability_args(), "local_date": "2030-01-08"}),
            final("availability"),
        ]
    )
    first, ident = harness.chat(owner)
    harness.clock.now += timedelta(hours=9)
    replay = parsed(harness.chat(owner, message_id=ident)[0])
    assert replay == parsed(first) and len(harness.provider.requests) == 2
    assert "check returned" in replay.assistant_message
    assert "Query again to refresh availability" in replay.assistant_message
    assert "These are not reservations" in replay.assistant_message
    assert GUIDANCE in replay.assistant_message
    assert harness.counts()["appointments"] == harness.counts()["booking_proposals"] == 0


@pytest.mark.postgres
def test_candidate_s2_wording_does_not_silently_change_the_frozen_visible_grader(isolated):
    engine, ident, settings = isolated
    report = run_smoke(engine, settings, ident, scenario="S2")
    case = report["cases"][0]
    assert report["mode"] == "MOCKED_DRY_RUN" and report["live_openai_evals"] == "NOT RUN"
    assert case["RAW_MODEL_VERDICT"] == case["BACKEND_VERDICT"] == "PASS"
    assert case["USER_VISIBLE_VERDICT"] == "FAIL"  # Frozen v1 finite text grammar rejects new CTA.
    assert GUIDANCE in case["evidence"]["responses"][0]["body"]["assistant_message"]
    assert report["database_unchanged_after_scoped_cleanup"]
