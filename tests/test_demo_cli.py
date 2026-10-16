import json
from uuid import UUID

import httpx
import pytest

from cli.client import ClinicClient, StateFile

pytestmark = pytest.mark.unit
PROPOSAL = "00000000-0000-4000-8000-000000000301"
APPOINTMENT = "00000000-0000-4000-8000-000000000401"
OWNER = "00000000-0000-4000-8000-000000000501"
TRACE = "00000000-0000-4000-8000-000000000601"
START, END = "2030-01-09T09:00:00-06:00", "2030-01-09T09:30:00-06:00"


def appointment():
    return {
        "status": "CONFIRMED",
        "appointment_id": APPOINTMENT,
        "proposal_id": PROPOSAL,
        "starts_at": START,
        "ends_at": END,
        "confirmed_at": "2030-01-07T15:00:00Z",
        "trace_id": TRACE,
    }


def private_state(tmp_path):
    state = StateFile(tmp_path / "state.json", "synthetic")
    state.value["session"] = {"session_id": OWNER, "session_token": "synthetic-private-bearer"}
    state.save()
    return state


@pytest.mark.parametrize("uncertainty", ["read_error", "http_503"])
def test_confirmation_retry_persists_key_and_bypasses_chat(tmp_path, uncertainty):
    state, keys, output = private_state(tmp_path), [], []

    def transport(request):
        assert "chat" not in request.url.path
        if request.method == "GET":
            return httpx.Response(200, json=appointment())
        assert request.url.path == f"/api/v1/proposals/{PROPOSAL}/confirm"
        key = request.headers["Idempotency-Key"]
        assert json.loads(state.path.read_text())["confirmations"][PROPOSAL]["key"] == key
        keys.append(key)
        if len(keys) == 1:
            if uncertainty == "read_error":
                raise httpx.ReadError("synthetic loss", request=request)
            return httpx.Response(
                503, json={"error": {"code": "SERVICE_UNAVAILABLE"}, "trace_id": TRACE}
            )
        return httpx.Response(201, json=appointment())

    with httpx.Client(
        base_url="http://testserver", transport=httpx.MockTransport(transport)
    ) as http:
        client = ClinicClient(http, state, output.append)
        assert client.dispatch("confirm " + PROPOSAL) is None
        assert output[-1].startswith("UNCERTAIN")
        assert not any(line.startswith("CONFIRMED") for line in output)
        restarted = ClinicClient(http, StateFile(state.path, "synthetic"), output.append)
        assert restarted.dispatch("confirm " + PROPOSAL).status_code == 201
        assert restarted.dispatch("confirm " + PROPOSAL).status_code == 201
    assert len(keys) == 3 and len(set(keys)) == 1
    assert output[-1].startswith("CONFIRMED verified")
    assert state.value["session"]["session_token"] not in "\n".join(output)
    UUID(keys[0])


def test_unverifiable_success_stays_uncertain(tmp_path):
    output = []

    def transport(request):
        return (
            httpx.Response(201, json=appointment())
            if request.method == "POST"
            else httpx.Response(503, json={})
        )

    with httpx.Client(
        base_url="http://testserver", transport=httpx.MockTransport(transport)
    ) as http:
        state = private_state(tmp_path)
        assert ClinicClient(http, state, output.append).confirm(PROPOSAL) is None
    assert state.value["confirmations"][PROPOSAL]["outcome"] == "UNCERTAIN"
    assert not any(line.startswith("CONFIRMED") for line in output)


@pytest.mark.parametrize("bad", ["confirm", "confirm not-a-uuid", "confirm one two"])
def test_invalid_confirm_never_reaches_chat_or_network(tmp_path, bad):
    with httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(lambda _: pytest.fail("Invalid confirm was sent")),
    ) as http:
        with pytest.raises(ValueError):
            ClinicClient(http, private_state(tmp_path)).dispatch(bad)


def test_chat_retry_retains_original_message_identity(tmp_path):
    state, payloads = private_state(tmp_path), []

    def transport(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(
                503, json={"error": {"code": "SERVICE_UNAVAILABLE"}, "trace_id": TRACE}
            )
        return httpx.Response(
            200,
            json={
                "turn_id": OWNER,
                "assistant_message": "Synthetic reply.",
                "proposal": None,
                "trace_id": TRACE,
            },
        )

    with httpx.Client(
        base_url="http://testserver", transport=httpx.MockTransport(transport)
    ) as http:
        client = ClinicClient(http, state, lambda _: None)
        assert client.chat("synthetic text").status_code == 503
        assert client.chat("different text") is None and len(payloads) == 1
        restored = ClinicClient(http, StateFile(state.path, "synthetic"), lambda _: None)
        assert restored.dispatch("retry-chat").status_code == 200
    assert payloads[0] == payloads[1] and restored.state.value["pending_chat"] is None
