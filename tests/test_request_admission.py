"""Bounded synthetic ASGI streams; never an exhaustion or external traffic test."""

import asyncio
import json
import logging
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import Depends
from starlette.requests import Request

from app.core.admission import MAX_REQUEST_BODY_BYTES, RequestBodyLimitMiddleware
from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.unit
LIMIT = MAX_REQUEST_BODY_BYTES


def stream(app, body, headers=(), chunk=4096):
    async def run():
        offset, messages = 0, []
        done = asyncio.Event()

        async def receive():
            nonlocal offset
            if offset < len(body):
                value = body[offset : offset + chunk]
                offset += len(value)
                return {"type": "http.request", "body": value, "more_body": offset < len(body)}
            await done.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body"):
                done.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/probe",
            "raw_path": b"/probe",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json"), *headers],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
        }
        await asyncio.wait_for(app(scope, receive, send), 5)
        start = next(m for m in messages if m["type"] == "http.response.start")
        result = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return start["status"], json.loads(result), dict(start["headers"]), offset

    return asyncio.run(run())


@pytest.fixture
def probe():
    app = create_app(Settings(_env_file=None))
    events = []

    def authenticate():
        events.append("authentication")

    @app.post("/probe", dependencies=[Depends(authenticate)])
    def endpoint(payload: dict):
        events.append("endpoint")
        return {"accepted": True}

    yield app, events
    app.state.engine.dispose()


@pytest.mark.parametrize(
    "declared",
    [None, b"1", b"0", b"invalid", b"-1", b"70000", b"9" * 5000],
    ids=["missing", "understated", "zero", "invalid", "negative", "oversized", "integer-limit"],
)
@pytest.mark.parametrize("valid_json", [True, False])
def test_oversize_rejected_before_json_auth_and_endpoint(probe, declared, valid_json, caplog):
    caplog.set_level(logging.INFO, logger="clinic.requests")
    app, events = probe
    marker = "SYNTHETIC_OVERSIZE_PAYLOAD"
    body = (
        json.dumps({"message": marker + "x" * (LIMIT + 12288)}).encode()
        if valid_json
        else b'{"message":"' + b"x" * (LIMIT + 12288)
    )
    headers = [] if declared is None else [(b"content-length", declared)]
    with patch.object(Request, "json", side_effect=AssertionError("Must not parse")) as parser:
        status, result, response_headers, consumed = stream(app, body, headers)
    assert status == 413 and parser.call_count == 0 and events == []
    assert result["error"] == {
        "code": "REQUEST_TOO_LARGE",
        "message": "Request body exceeds the 65536-byte limit.",
        "retryable": False,
    }
    assert str(UUID(result["trace_id"])) == response_headers[b"x-trace-id"].decode()
    assert marker not in json.dumps(result) and marker not in caplog.text
    assert consumed < len(body) and consumed <= LIMIT + 4096
    assert '"status": 413' in caplog.text and result["trace_id"] in caplog.text


@pytest.mark.parametrize("size", [2, LIMIT - 1, LIMIT])
@pytest.mark.parametrize("declared", [False, True])
def test_valid_body_at_or_below_exact_byte_limit_preserves_normal_parsing(probe, size, declared):
    app, events = probe
    body = b"{}" + b" " * (size - 2)
    headers = [(b"content-length", str(size).encode())] if declared else []
    status, result, _, consumed = stream(app, body, headers)
    assert status == 200 and result == {"accepted": True} and consumed == size
    assert events == ["authentication", "endpoint"]


def test_multibyte_limit_counts_encoded_bytes_not_characters(probe):
    app, _ = probe
    body = json.dumps({"message": "é" * (LIMIT // 2 + 1)}, ensure_ascii=False).encode()
    assert len(body.decode()) < LIMIT < len(body)
    assert stream(app, body)[0] == 413


def test_single_oversized_asgi_frame_is_never_forwarded_or_parsed(probe):
    app, events = probe
    body = b" " * (LIMIT + 1024)
    with patch.object(Request, "json", side_effect=AssertionError("Must not parse")):
        status, _, _, consumed = stream(app, body, chunk=len(body))
    assert status == 413 and consumed == len(body) and events == []
    # The ASGI server already allocated that one frame; the application cannot
    # bound it, but never appends it to the admitted buffer or calls the parser.


def test_disconnected_body_is_not_forwarded():
    called = []

    async def app(*args):
        called.append(True)

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        pytest.fail("No response should be written after the client disconnects")

    asyncio.run(RequestBodyLimitMiddleware(app)({"type": "http", "headers": []}, receive, send))
    assert called == []


def test_non_http_scope_is_unchanged():
    called = []

    async def app(scope, receive, send):
        called.append(scope)

    scope = {"type": "lifespan"}
    asyncio.run(RequestBodyLimitMiddleware(app)(scope, None, None))
    assert called == [scope]
