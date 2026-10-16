import json
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.api.auth import require_session, token_hash
from app.core.config import Settings
from app.db.models import ChatSession
from app.db.session import get_db
from app.main import create_app
from tests.conftest import NOW

pytestmark = [pytest.mark.postgres, pytest.mark.api]


@pytest.fixture
def application(db, engine, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    settings = Settings(
        _env_file=None, database_url=engine.url.render_as_string(hide_password=False)
    )
    app = create_app(settings, engine, clock=lambda: NOW)
    app.dependency_overrides[get_db] = lambda: db

    @app.get("/test-auth", include_in_schema=False)
    def auth_probe(owner=Depends(require_session)):
        return {"session_id": str(owner.id)}

    return app


@pytest.fixture
def client(application):
    with TestClient(application, raise_server_exceptions=False) as test_client:
        yield test_client


def assert_error(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error", "trace_id"}
    assert body["error"]["code"] == code
    assert set(body["error"]) == {"code", "message", "retryable"}
    assert str(UUID(body["trace_id"])) == response.headers["X-Trace-ID"]


def test_health_and_catalog(client):
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    catalog = client.get("/api/v1/catalog")
    assert catalog.status_code == 200
    body = catalog.json()
    assert body["clinic"]["timezone"] == "America/Chicago"
    assert len(body["practitioners"]) == 2
    assert {t["duration_minutes"] for t in body["appointment_types"]} == {30, 60}
    assert str(UUID(body["trace_id"])) == catalog.headers["X-Trace-ID"]


def test_session_secret_hash_ttl_and_no_renewal(client, db, application, caplog):
    with caplog.at_level("INFO", logger="clinic.requests"):
        response = client.post("/api/v1/sessions", json={})
        assert response.status_code == 201
        body = response.json()
        token = body["session_token"]
        assert len(token) == 43 and body["token_type"] == "Bearer"
        row = db.get(ChatSession, UUID(body["session_id"]))
        assert row.token_hash == token_hash(token) and row.token_hash != token
        assert row.expires_at == NOW + timedelta(hours=24)
        dump = db.scalar(
            text("SELECT row_to_json(s)::text FROM chat_sessions s WHERE id=:id"), {"id": row.id}
        )
        assert token not in dump
        application.state.clock = lambda: NOW + timedelta(hours=1)
        auth = client.get("/test-auth", headers={"Authorization": f"Bearer {token}"})
        assert auth.status_code == 200 and auth.json() == {"session_id": body["session_id"]}
        db.refresh(row)
        assert row.expires_at == NOW + timedelta(hours=24)
        assert token not in auth.text and token not in caplog.text
        logs = [json.loads(r.message) for r in caplog.records if r.name == "clinic.requests"]
        assert logs and all("trace_id" in record for record in logs)
    assert client.post("/api/v1/sessions", json={}).json()["session_token"] != token


@pytest.mark.parametrize("header", [None, "Bearer invalid", "Basic invalid", "Bearer " + "a" * 43])
def test_invalid_bearer(client, header):
    headers = {} if header is None else {"Authorization": header}
    assert_error(client.get("/test-auth", headers=headers), 401, "UNAUTHORIZED")


def test_expired_bearer(client, db, application):
    body = client.post("/api/v1/sessions", json={}).json()
    application.state.clock = lambda: NOW + timedelta(hours=24)
    assert_error(
        client.get("/test-auth", headers={"Authorization": f"Bearer {body['session_token']}"}),
        401,
        "UNAUTHORIZED",
    )
    assert db.scalar(select(ChatSession.expires_at)) == NOW + timedelta(hours=24)


@pytest.mark.parametrize("content", ['{"unexpected":"sensitive-marker"}', "{malformed"])
def test_malformed_request_sanitized(client, content, caplog):
    with caplog.at_level("INFO", logger="clinic.requests"):
        response = client.post(
            "/api/v1/sessions", content=content, headers={"Content-Type": "application/json"}
        )
    assert_error(response, 422, "VALIDATION_ERROR")
    assert "sensitive-marker" not in response.text + caplog.text


def test_only_authorized_routes_in_openapi(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) == {
        "/api/v1/sessions",
        "/api/v1/catalog",
        "/api/v1/health",
        "/api/v1/availability",
        "/api/v1/proposals",
        "/api/v1/proposals/{id}",
        "/api/v1/proposals/{id}/confirm",
        "/api/v1/appointments/{id}",
        "/api/v1/chat/messages",
    }
    for path in ["/api/v1/unimplemented"]:
        assert_error(client.get(path), 404, "NOT_FOUND")


def test_database_outage_sanitized(client, application):
    def unavailable():
        raise OperationalError(
            "sensitive-sql-marker", {"secret": "sensitive-db-marker"}, Exception()
        )

    application.dependency_overrides[get_db] = unavailable
    response = client.get("/api/v1/health")
    assert_error(response, 503, "SERVICE_UNAVAILABLE")
    assert response.json()["error"]["retryable"] is True
    assert "sensitive" not in response.text


def test_unexpected_exception_not_logged(client, application, caplog):
    def failure():
        raise RuntimeError("sensitive-exception-marker")

    application.dependency_overrides[get_db] = failure
    with caplog.at_level("INFO", logger="clinic.requests"):
        response = client.get("/api/v1/health")
    assert_error(response, 500, "INTERNAL_ERROR")
    assert "sensitive-exception-marker" not in response.text + caplog.text
    assert not any(record.exc_info for record in caplog.records)


def test_no_vendor_or_legacy_imports(client):
    import sys

    assert client.get("/api/v1/health").status_code == 200
    assert not {
        "openai",
        "elevenlabs",
        "src.conversation_engine",
        "src.voice_handler",
    }.intersection(sys.modules)
