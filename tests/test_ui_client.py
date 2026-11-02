"""UI HTTP client against httpx.MockTransport: no server, database or Streamlit."""

import json
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from ui.client import ApiError, ClinicApi, confirmation_key

pytestmark = pytest.mark.unit
PROPOSAL_ID, APPOINTMENT_ID = uuid4(), uuid4()
PRACTITIONER, KIND = uuid4(), uuid4()
NOW = datetime(2030, 1, 7, 15, tzinfo=UTC)


def proposal_body(**overrides):
    return {
        "proposal_id": str(PROPOSAL_ID),
        "practitioner_id": str(PRACTITIONER),
        "appointment_type_id": str(KIND),
        "starts_at": "2030-01-09T15:00:00Z",
        "ends_at": "2030-01-09T15:30:00Z",
        "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
        "status": "PENDING",
        **overrides,
    }


def appointment_body():
    return {
        "status": "CONFIRMED",
        "appointment_id": str(APPOINTMENT_ID),
        "proposal_id": str(PROPOSAL_ID),
        "starts_at": "2030-01-09T15:00:00Z",
        "ends_at": "2030-01-09T15:30:00Z",
        "confirmed_at": NOW.isoformat(),
        "trace_id": str(uuid4()),
    }


def error(status, code, retryable=False, **extra):
    body = {"error": {"code": code, "message": f"{code} message", "retryable": retryable}}
    return httpx.Response(status, json={**body, "trace_id": str(uuid4()), **extra})


def api(handler):
    seen = []

    def record(request):
        seen.append(request)
        return handler(request)

    return ClinicApi("http://api.test/", transport=httpx.MockTransport(record)), seen


def test_info_session_and_catalog_parse_the_contracts():
    def handler(request):
        return {
            "/api/v1/info": httpx.Response(
                200, json={"agent_provider": "demo", "min_notice_hours": 24, "max_horizon_days": 90}
            ),
            "/api/v1/sessions": httpx.Response(
                201,
                json={
                    "session_id": str(uuid4()),
                    "session_token": "synthetic-bearer",
                    "expires_at": NOW.isoformat(),
                },
            ),
            "/api/v1/catalog": httpx.Response(
                200,
                json={
                    "clinic": {"id": str(uuid4()), "name": "Clinic", "timezone": "America/Chicago"},
                    "practitioners": [{"id": str(PRACTITIONER), "display_name": "Dr. A"}],
                    "appointment_types": [
                        {"id": str(KIND), "code": "consult", "duration_minutes": 30}
                    ],
                },
            ),
        }[request.url.path]

    client, seen = api(handler)
    assert client.info().agent_provider == "demo"
    assert client.create_session().token == "synthetic-bearer"
    catalog = client.catalog()
    assert catalog.practitioners[0].label == "Dr. A"
    assert catalog.appointment_types[0].label == "consult (30 min)"
    assert [r.method for r in seen] == ["GET", "POST", "GET"]
    assert all("Authorization" not in r.headers for r in seen)


def test_availability_sends_query_and_parses_slots():
    def handler(request):
        assert dict(request.url.params) == {
            "date": "2030-01-09",
            "practitioner_id": str(PRACTITIONER),
            "appointment_type_id": str(KIND),
        }
        return httpx.Response(
            200,
            json={
                "slots": [{"starts_at": "2030-01-09T15:00:00Z", "ends_at": "2030-01-09T15:30:00Z"}]
            },
        )

    client, _ = api(handler)
    slots = client.availability(date(2030, 1, 9), PRACTITIONER, KIND)
    assert slots[0].starts_at == datetime(2030, 1, 9, 15, tzinfo=UTC)


def test_chat_sends_bearer_and_message_id_and_reads_provider_and_proposal():
    message_id = uuid4()

    def handler(request):
        assert request.headers["Authorization"] == "Bearer synthetic-bearer"
        assert json.loads(request.content) == {
            "client_message_id": str(message_id),
            "message": "catalog",
        }
        return httpx.Response(
            200,
            headers={"X-Agent-Provider": "demo"},
            json={
                "turn_id": str(uuid4()),
                "assistant_message": "Practitioners: …",
                "proposal": proposal_body(),
                "trace_id": str(uuid4()),
            },
        )

    client, _ = api(handler)
    reply = client.chat("synthetic-bearer", "catalog", message_id)
    assert reply.provider == "demo" and reply.proposal.proposal_id == PROPOSAL_ID
    assert reply.proposal.seconds_left(NOW) == 600
    assert reply.proposal.seconds_left(NOW + timedelta(hours=1)) == 0


def test_confirmation_key_is_stable_per_proposal_across_reruns():
    store = {}
    first = confirmation_key(store, PROPOSAL_ID)
    assert confirmation_key(store, PROPOSAL_ID) == first
    assert confirmation_key(store, uuid4()) != first
    assert store[str(PROPOSAL_ID)] == first and len(store) == 2


def test_double_confirm_reuses_one_key_and_returns_the_same_appointment():
    keys = []

    def handler(request):
        keys.append(request.headers["Idempotency-Key"])
        return httpx.Response(201, json=appointment_body())

    client, _ = api(handler)
    store = {}
    first = client.confirm("synthetic-bearer", PROPOSAL_ID, confirmation_key(store, PROPOSAL_ID))
    second = client.confirm("synthetic-bearer", PROPOSAL_ID, confirmation_key(store, PROPOSAL_ID))
    assert len(keys) == 2 and keys[0] == keys[1]
    assert first == second and first.appointment_id == APPOINTMENT_ID


def test_already_confirmed_returns_the_existing_appointment():
    client, _ = api(lambda _: error(409, "ALREADY_CONFIRMED", appointment=appointment_body()))
    appointment = client.confirm("synthetic-bearer", PROPOSAL_ID, "other-key")
    assert appointment.already_confirmed and appointment.appointment_id == APPOINTMENT_ID


@pytest.mark.parametrize(
    ("status", "code", "retryable", "fragment"),
    [
        (409, "SLOT_TAKEN", False, "just taken"),
        (410, "PROPOSAL_EXPIRED", False, "expired"),
        (409, "PROPOSAL_SUPERSEDED", False, "newer proposal"),
        (501, "AGENT_PROVIDER_DISABLED", False, "Chat is disabled"),
        (503, "SERVICE_UNAVAILABLE", True, "Retry"),
    ],
)
def test_errors_map_to_codes_and_user_messages(status, code, retryable, fragment):
    client, _ = api(lambda _: error(status, code, retryable))
    with pytest.raises(ApiError) as caught:
        client.confirm("synthetic-bearer", PROPOSAL_ID, "key")
    assert (caught.value.status, caught.value.code) == (status, code)
    assert caught.value.retryable is retryable and fragment in caught.value.user_message


def test_unreachable_and_malformed_responses_are_typed():
    def down(_):
        raise httpx.ConnectError("refused")

    client, _ = api(down)
    with pytest.raises(ApiError) as caught:
        client.info()
    assert caught.value.code == "API_UNREACHABLE" and caught.value.retryable
    client, _ = api(lambda _: httpx.Response(502, text="<html>bad gateway</html>"))
    with pytest.raises(ApiError) as caught:
        client.info()
    assert caught.value.code == "UNEXPECTED_RESPONSE" and caught.value.retryable
    assert "html" not in caught.value.user_message
