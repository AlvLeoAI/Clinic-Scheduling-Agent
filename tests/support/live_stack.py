"""Test-only live stack: the real app over real sockets, with a fault proxy in front.

The API runs `create_app` under uvicorn in a thread on 127.0.0.1, against the throwaway
test database, with an adjustable clock. `FaultProxy` sits between a client and the API
and can lose a confirm's response after the API committed it, or drop a confirm before
it reaches the API. No fault endpoint exists in the app itself.

The offline guard patches httpx's real transport, so `loopback_transport()` sends the
UI client's requests with http.client and refuses anything but 127.0.0.1.
"""

import http.client
import http.server
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import uvicorn
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    Appointment,
    BookingProposal,
    ChatSession,
    ChatTurn,
    ConversationItem,
    IdempotencyRecord,
)
from app.main import create_app

LOOPBACK = "127.0.0.1"


class Bearer(str):
    """A session bearer that pytest's assertion rewriting and tracebacks cannot print."""

    def __repr__(self) -> str:
        return "'<bearer>'"


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class LiveApi:
    """uvicorn in a thread. `restart()` serves a fresh app instance on the same port."""

    def __init__(self, engine: Engine, clock: Callable[[], datetime]):
        self.engine, self.clock, self.port = engine, clock, 0
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{LOOPBACK}:{self.port}"

    def start(self) -> "LiveApi":
        settings = Settings(
            _env_file=None,
            database_url=self.engine.url.render_as_string(hide_password=False),
            agent_provider="demo",
        )
        app = create_app(settings, self.engine, clock=self.clock)
        config = uvicorn.Config(app, host=LOOPBACK, port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError("the test API did not start")
            time.sleep(0.02)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        return self

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
            self.thread.join(timeout=15)
            self.server = None

    def restart(self) -> None:
        self.stop()
        self.start()


@dataclass
class FaultProxy:
    """Forwards to the API; a one-shot fault applies to the next POST .../confirm.

    - "lose_response": forward, let the API commit, then close without answering.
    - "block": close without forwarding; the API never sees the request.
    `confirm_keys` lists the Idempotency-Key of every confirm that reached the API, and
    `session_ids` the sessions created through it (IDs only, never the bearer).
    """

    upstream: str
    fault: str | None = None
    confirm_keys: list[str] = field(default_factory=list)
    session_ids: list[UUID] = field(default_factory=list)
    blocked: int = 0
    lost: int = 0

    def __post_init__(self) -> None:
        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:
                pass

            def forward(self) -> None:
                proxy.handle(self)

            do_GET = do_POST = forward

        self.server = http.server.ThreadingHTTPServer((LOOPBACK, 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://{LOOPBACK}:{self.server.server_address[1]}"

    def arm(self, fault: str) -> None:
        assert fault in {"lose_response", "block"}
        self.fault = fault

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def handle(self, handler: http.server.BaseHTTPRequestHandler) -> None:
        body = handler.rfile.read(int(handler.headers.get("Content-Length") or 0))
        is_confirm = handler.command == "POST" and handler.path.endswith("/confirm")
        fault = None
        if is_confirm:
            fault, self.fault = self.fault, None
        if fault == "block":
            self.blocked += 1
            handler.close_connection = True
            return
        target = urlsplit(self.upstream)
        connection = http.client.HTTPConnection(target.hostname, target.port, timeout=30)
        headers = {k: v for k, v in handler.headers.items() if k.lower() != "host"}
        try:
            connection.request(handler.command, handler.path, body=body or None, headers=headers)
            response = connection.getresponse()
            data = response.read()
        except OSError:
            handler.close_connection = True  # the API is down: the client sees a dropped hop
            return
        finally:
            connection.close()
        if is_confirm:
            self.confirm_keys.append(handler.headers["Idempotency-Key"])
        if handler.path == "/api/v1/sessions" and response.status == 201:
            self.session_ids.append(UUID(json.loads(data)["session_id"]))
        if fault == "lose_response":
            self.lost += 1
            handler.close_connection = True
            return
        handler.send_response(response.status)
        for key, value in response.getheaders():
            if key.lower() not in {"transfer-encoding", "connection", "content-length"}:
                handler.send_header(key, value)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)


def loopback_transport() -> httpx.MockTransport:
    def send(request: httpx.Request) -> httpx.Response:
        if request.url.host != LOOPBACK:
            raise AssertionError("the live-stack transport only reaches 127.0.0.1")
        connection = http.client.HTTPConnection(LOOPBACK, request.url.port, timeout=30)
        try:
            connection.request(
                request.method,
                request.url.raw_path.decode(),
                body=request.content or None,
                headers=dict(request.headers),
            )
            response = connection.getresponse()
            return httpx.Response(
                response.status, headers=response.getheaders(), content=response.read()
            )
        except (OSError, http.client.HTTPException) as error:
            # A dropped or refused hop, as httpx's own transport would report it.
            raise httpx.ReadError(type(error).__name__, request=request) from None
        finally:
            connection.close()

    return httpx.MockTransport(send)


def counts(engine: Engine, session_ids: list[UUID]) -> dict[str, int]:
    """Appointments and stored idempotency outcomes owned by these sessions."""
    with Session(engine) as db:
        return {
            name: db.scalar(
                select(func.count()).select_from(model).where(model.session_id.in_(session_ids))
            )
            for name, model in [
                ("appointments", Appointment),
                ("idempotency_records", IdempotencyRecord),
            ]
        }


def slot_appointments(engine: Engine, practitioner_id: UUID, starts_at: datetime) -> int:
    with Session(engine) as db:
        return db.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.practitioner_id == practitioner_id, Appointment.starts_at == starts_at
            )
        )


def delete_sessions(engine: Engine, session_ids: list[UUID]) -> None:
    with Session(engine) as db:
        db.execute(
            update(ChatSession).where(ChatSession.id.in_(session_ids)).values(active_turn_id=None)
        )
        for model in [IdempotencyRecord, Appointment, BookingProposal, ConversationItem, ChatTurn]:
            db.execute(delete(model).where(model.session_id.in_(session_ids)))
        db.execute(delete(ChatSession).where(ChatSession.id.in_(session_ids)))
        db.commit()


def write_receipt(name: str, receipt: dict) -> None:
    """Recovery evidence (no bearers or keys), written only when a directory is given."""
    directory = os.environ.get("CLINIC_RECOVERY_EVIDENCE_DIR")
    if directory:
        path = Path(directory) / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, indent=2, default=str) + "\n")
