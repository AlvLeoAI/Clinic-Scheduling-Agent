import json

import httpx
import pytest
from pydantic import ValidationError

from app.agent.protocol import ProviderFailure, ProviderResponse
from app.agent.provider import HttpResponsesProvider
from app.agent.tools import TOOL_NAMES, tool_definitions, validate_arguments
from app.core.config import Settings

LOCAL = "postgresql+psycopg://clinic_demo:synthetic@127.0.0.1:15432/clinic_scheduling_dev"


def settings(**changes):
    return Settings(_env_file=None, database_url=LOCAL, **changes)


def test_tool_definitions_are_strict_required_and_allowlisted():
    definitions = tool_definitions()
    assert tuple(tool["name"] for tool in definitions) == TOOL_NAMES
    assert len(definitions) == 3
    for tool in definitions:
        assert tool["type"] == "function" and tool["strict"] is True
        schema = tool["parameters"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert "session_id" not in schema["properties"]
    assert not any("confirm" in name for name in TOOL_NAMES)


@pytest.mark.parametrize(
    "name,args,code",
    [
        ("confirm_booking", "{}", "TOOL_NOT_ALLOWED"),
        ("execute_sql", '{"sql":"synthetic"}', "TOOL_NOT_ALLOWED"),
        ("get_clinic_catalog", '{"session_id":"synthetic"}', "INVALID_TOOL_ARGUMENTS"),
        ("check_availability", "{}", "INVALID_TOOL_ARGUMENTS"),
        ("create_booking_proposal", "{invalid", "INVALID_TOOL_ARGUMENTS"),
        ("check_availability", "null", "INVALID_TOOL_ARGUMENTS"),
    ],
)
def test_malformed_and_unapproved_tools_rejected(name, args, code):
    parsed, error = validate_arguments(name, args)
    assert parsed is None and error["error"]["code"] == code and error["ok"] is False


def test_opaque_reasoning_and_complete_message_are_preserved():
    output = [
        {
            "type": "reasoning",
            "id": "reason_1",
            "summary": [],
            "encrypted_content": "synthetic-opaque-payload",
            "future_metadata": {"safe": True},
        },
        {
            "type": "message",
            "id": "message_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "synthetic", "annotations": []}],
        },
    ]
    assert ProviderResponse(status="completed", output=output).output == output


def test_parallel_response_calls_rejected():
    calls = [
        {"type": "function_call", "name": "get_clinic_catalog", "arguments": "{}", "call_id": key}
        for key in ["call_1", "call_2"]
    ]
    with pytest.raises(ValidationError):
        ProviderResponse(status="completed", output=calls)


@pytest.mark.parametrize("status", ["failed", "incomplete", "in_progress"])
def test_noncompleted_provider_response_rejected(status):
    with pytest.raises(ValidationError):
        ProviderResponse(status=status, output=[{"type": "reasoning", "summary": []}])


def test_disabled_provider_does_not_open_transport():
    def transport(_request):
        pytest.fail("Disabled live provider attempted HTTP.")

    with pytest.raises(ProviderFailure):
        HttpResponsesProvider(settings(), httpx.MockTransport(transport)).respond({})


def test_provider_transport_is_mocked_and_uses_configured_timeout_model():
    observed = []

    def transport(request):
        observed.append(request)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "synthetic"}],
                    }
                ],
            },
        )

    config = settings(
        enable_live_openai=True,
        openai_model="synthetic-test-model",
        openai_api_key="synthetic-test-credential",
        provider_timeout_seconds=12,
    )
    payload = {
        "model": config.openai_model,
        "store": False,
        "parallel_tool_calls": False,
        "input": [{"role": "user", "content": "synthetic"}],
        "tools": tool_definitions(),
    }
    response = HttpResponsesProvider(config, httpx.MockTransport(transport)).respond(payload)
    assert response.status == "completed" and len(observed) == 1
    request = observed[0]
    assert str(request.url) == "https://api.openai.com/v1/responses"
    assert json.loads(request.content) == payload
    assert request.extensions["timeout"]["read"] == 12


def test_provider_error_details_and_credentials_are_sanitized():
    def transport(_request):
        return httpx.Response(500, json={"error": "synthetic-private-marker"})

    config = settings(
        enable_live_openai=True,
        openai_model="synthetic-test-model",
        openai_api_key="synthetic-test-credential",
    )
    with pytest.raises(ProviderFailure) as caught:
        HttpResponsesProvider(config, httpx.MockTransport(transport)).respond({})
    assert "private-marker" not in str(caught.value)
    assert "synthetic-test-credential" not in str(caught.value)


def test_lease_must_outlast_timeout():
    with pytest.raises(ValidationError):
        settings(provider_timeout_seconds=90, turn_lease_seconds=90)
    assert settings().enable_live_openai is False and settings().openai_model is None
