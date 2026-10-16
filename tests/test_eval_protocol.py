"""Synthetic wire fixtures and actual httpx adapter, with no network fallback."""

import copy
import json

import httpx
import pytest

from app.agent.protocol import ProviderFailure
from app.agent.provider import HttpResponsesProvider
from app.agent.replies import reply_format
from app.agent.tools import tool_definitions
from app.core.config import Settings
from evaluations.runner import ROOT

pytestmark = [pytest.mark.unit, pytest.mark.agent_offline]
FIXTURE = json.loads((ROOT / "evaluations/fixtures/responses_v1.json").read_text())


def config():
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://clinic_demo:synthetic@127.0.0.1:15432/clinic_scheduling_test",
        enable_live_openai=True,
        openai_api_key="synthetic-protocol-credential",
        openai_model="synthetic-protocol-model",
        provider_timeout_seconds=7,
    )


def test_unchanged_rest_adapter_preserves_wire_and_stateless_continuation():
    requests, responses = [], iter([FIXTURE["tool"], FIXTURE["final"]])

    def transport(request):
        assert request.method == "POST"
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.extensions["timeout"]["read"] == 7
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=next(responses))

    provider = HttpResponsesProvider(config(), httpx.MockTransport(transport))
    request = {
        "model": config().openai_model,
        "store": False,
        "parallel_tool_calls": False,
        "include": ["reasoning.encrypted_content"],
        "tools": tool_definitions(),
        "text": reply_format(),
        "input": [{"role": "user", "content": "Synthetic availability request."}],
        "truncation": "disabled",
    }
    first = provider.respond(request)
    assert first.output == FIXTURE["tool"]["output"]
    assert first.usage.total_tokens == 30  # Explicit mock fixture values only.
    output = {
        "type": "function_call_output",
        "call_id": "call_synthetic_01",
        "output": json.dumps({"ok": True, "data": {"slots": []}}),
    }
    continued = {**request, "input": [*request["input"], *first.output, output]}
    assert provider.respond(continued).output == FIXTURE["final"]["output"]
    assert requests[1]["input"][1:] == [*FIXTURE["tool"]["output"], output]
    assert "previous_response_id" not in requests[1] and "conversation" not in requests[1]
    assert {t["name"] for t in request["tools"]} == {
        "get_clinic_catalog",
        "check_availability",
        "create_booking_proposal",
    }
    for definition in request["tools"]:
        assert definition["strict"] is True
        schema = definition["parameters"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


@pytest.mark.parametrize(
    "fault",
    [
        "http_429",
        "http_500",
        "connect_timeout",
        "read_timeout",
        "invalid_json",
        "incomplete",
        "parallel_calls",
        "missing_call_id",
        "invalid_reasoning",
        "oversized",
    ],
)
def test_rest_errors_and_timeouts_are_safe_provider_failures(fault):
    marker = "synthetic-private-provider-marker"

    def transport(request):
        if fault in {"http_429", "http_500"}:
            return httpx.Response(int(fault[-3:]), json={"error": marker})
        if fault.endswith("timeout"):
            kind = httpx.ConnectTimeout if fault.startswith("connect") else httpx.ReadTimeout
            raise kind(marker, request=request)
        if fault == "invalid_json":
            return httpx.Response(200, content=marker)
        response = copy.deepcopy(FIXTURE["tool"])
        if fault == "incomplete":
            response["status"] = "incomplete"
        elif fault == "parallel_calls":
            response["output"].append({**response["output"][1], "call_id": "second"})
        elif fault == "missing_call_id":
            response["output"][1].pop("call_id")
        elif fault == "invalid_reasoning":
            response["output"][0]["encrypted_content"] = {"invalid": True}
        else:
            response["output"][0]["encrypted_content"] = "x" * 1_048_577
        return httpx.Response(200, json=response)

    with pytest.raises(ProviderFailure) as caught:
        HttpResponsesProvider(config(), httpx.MockTransport(transport)).respond({})
    assert marker not in str(caught.value)
    assert config().openai_api_key.get_secret_value() not in str(caught.value)
