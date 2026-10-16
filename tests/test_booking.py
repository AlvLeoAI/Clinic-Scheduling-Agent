"""M3 uses committed synthetic fixtures and actual separate PostgreSQL connections."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from pathlib import Path
from threading import Barrier, Event
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    Appointment,
    AppointmentType,
    BookingProposal,
    ChatSession,
    IdempotencyRecord,
    Practitioner,
    WeeklySchedule,
)
from app.db.seed import PRACTITIONER_IDS, TYPE_IDS, seed_catalog
from app.db.session import build_engine
from app.main import create_app
from app.schemas.booking import AppointmentResponse, ProposalResponse
from app.services.booking import BookingService, confirmation_fingerprint
from tests.conftest import NOW

pytestmark = [pytest.mark.postgres, pytest.mark.api]


@pytest.fixture(scope="session")
def case_evidence():
    cases = []
    yield cases
    # Preserve accepted evidence; later milestone reruns have their own artifact.
    filename = os.environ.get("CLINIC_BOOKING_EVIDENCE_FILE", "M3_case_results.json")
    if filename not in {
        "M3_case_results.json",
        "M4_booking_regression_cases.json",
        "M5_booking_regression_cases.json",
        "M6_booking_regression_cases.json",
    }:
        raise ValueError("Only approved local booking evidence filenames are accepted.")
    path = Path(__file__).resolve().parents[1] / "docs/evidence" / filename
    if filename == "M3_case_results.json" and path.exists():
        return
    path.write_text(
        json.dumps({"cases": cases, "scope": "synthetic M3 PostgreSQL integration"}, indent=2)
        + "\n"
    )


class Harness:
    def __init__(self, engine, client, app):
        self.engine, self.client, self.app = engine, client, app
        self.owners = []

    def owner(self):
        response = self.client.post("/api/v1/sessions", json={})
        assert response.status_code == 201
        data = response.json()
        self.owners.append(UUID(data["session_id"]))
        return {"Authorization": "Bearer " + data["session_token"]}

    def propose(self, owner, **changes):
        body = {
            "practitioner_id": str(PRACTITIONER_IDS[0]),
            "appointment_type_id": str(TYPE_IDS[0]),
            "local_date": "2030-01-09",
            "local_time": "09:00",
            **changes,
        }
        return self.client.post("/api/v1/proposals", headers=owner, json=body)

    def proposal(self, owner, **changes):
        response = self.propose(owner, **changes)
        assert response.status_code == 201, response.text
        data = ProposalResponse.model_validate(response.json())
        assert str(data.trace_id) == response.headers["X-Trace-ID"]
        return str(data.proposal_id)

    def confirm(self, owner, proposal, key="synthetic-key", client=None, **kwargs):
        return (client or self.client).post(
            f"/api/v1/proposals/{proposal}/confirm",
            headers={**owner, "Idempotency-Key": key},
            **kwargs,
        )

    def counts(self):
        with Session(self.engine) as db:
            return {
                model.__tablename__: db.scalar(
                    select(func.count()).select_from(model).where(model.session_id.in_(self.owners))
                )
                for model in [BookingProposal, Appointment, IdempotencyRecord]
            }

    def row(self, proposal):
        with Session(self.engine) as db:
            row = db.get(BookingProposal, UUID(proposal))
            db.expunge(row)
            return row

    def restart(self):
        settings = Settings(
            _env_file=None, database_url=self.engine.url.render_as_string(hide_password=False)
        )
        engine = build_engine(settings)
        app = create_app(settings, engine, clock=lambda: self.app.state.clock())
        return engine, TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def harness(engine, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with Session(engine) as db:
        seed_catalog(db)
        db.commit()
    settings = Settings(
        _env_file=None, database_url=engine.url.render_as_string(hide_password=False)
    )
    app = create_app(settings, engine, clock=lambda: NOW)
    with TestClient(app, raise_server_exceptions=False) as client:
        instance = Harness(engine, client, app)
        try:
            yield instance
        finally:
            with Session(engine) as db:
                for model in [IdempotencyRecord, Appointment, BookingProposal]:
                    db.execute(delete(model).where(model.session_id.in_(instance.owners)))
                db.execute(delete(ChatSession).where(ChatSession.id.in_(instance.owners)))
                db.commit()


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["error"]["code"] == code
    assert str(UUID(body["trace_id"])) == response.headers["X-Trace-ID"]


def snapshot(row):
    return tuple(
        getattr(row, field)
        for field in [
            "id",
            "session_id",
            "clinic_id",
            "practitioner_id",
            "appointment_type_id",
            "starts_at",
            "ends_at",
            "duration_minutes",
            "created_at",
            "expires_at",
        ]
    )


def test_proposal_snapshot_ttl_reuse_and_no_booking(harness):
    owner = harness.owner()
    proposal = harness.proposal(owner)
    before = harness.row(proposal)
    assert before.status == "PENDING" and before.expires_at == NOW + timedelta(minutes=10)
    harness.app.state.clock = lambda: NOW + timedelta(minutes=5)
    response = harness.propose(owner)
    assert response.status_code == 200 and response.json()["proposal_id"] == proposal
    assert snapshot(harness.row(proposal)) == snapshot(before)
    assert harness.counts() == {"booking_proposals": 1, "appointments": 0, "idempotency_records": 0}


@pytest.mark.parametrize(
    "change",
    [
        {"local_time": "10:00"},
        {"local_date": "2030-01-10"},
        {"practitioner_id": str(PRACTITIONER_IDS[1])},
        {"appointment_type_id": str(TYPE_IDS[1])},
    ],
)
def test_changed_details_create_new_snapshot_and_supersede(harness, change):
    owner = harness.owner()
    first = harness.proposal(owner)
    before = snapshot(harness.row(first))
    second = harness.proposal(owner, **change)
    assert second != first and harness.row(first).status == "SUPERSEDED"
    assert harness.row(second).status == "PENDING" and snapshot(harness.row(first)) == before
    assert_error(harness.confirm(owner, first), 409, "PROPOSAL_SUPERSEDED")
    assert harness.counts()["appointments"] == 0


@pytest.mark.parametrize(
    "change,code",
    [
        ({"local_time": "10:15"}, "BUSINESS_RULE_VIOLATION"),
        (
            {"local_time": "16:30", "appointment_type_id": str(TYPE_IDS[1])},
            "BUSINESS_RULE_VIOLATION",
        ),
        ({"local_date": "next Friday"}, "VALIDATION_ERROR"),
        ({"practitioner_id": str(uuid4())}, "BUSINESS_RULE_VIOLATION"),
        ({"duration_minutes": 60}, "VALIDATION_ERROR"),
        ({"session_id": str(uuid4())}, "VALIDATION_ERROR"),
    ],
)
def test_invalid_new_request_preserves_pending_snapshot(harness, change, code):
    owner = harness.owner()
    first = harness.proposal(owner)
    before = snapshot(harness.row(first))
    assert_error(harness.propose(owner, **change), 422, code)
    assert harness.row(first).status == "PENDING" and snapshot(harness.row(first)) == before
    assert harness.counts()["booking_proposals"] == 1


@pytest.mark.parametrize(
    "offset,expired",
    [(timedelta(minutes=10) - timedelta(microseconds=1), False), (timedelta(minutes=10), True)],
)
def test_ttl_inclusive_expiry_and_effective_get(harness, offset, expired):
    owner = harness.owner()
    proposal = harness.proposal(owner)
    harness.app.state.clock = lambda: NOW + offset
    response = harness.client.get(f"/api/v1/proposals/{proposal}", headers=owner)
    assert response.status_code == 200
    assert response.json()["status"] == ("EXPIRED" if expired else "PENDING")
    if expired:
        assert_error(harness.confirm(owner, proposal), 410, "PROPOSAL_EXPIRED")
        harness.app.state.clock = lambda: NOW
        assert (
            harness.client.get(f"/api/v1/proposals/{proposal}", headers=owner).json()["status"]
            == "EXPIRED"
        )
        assert_error(harness.confirm(owner, proposal, key="another"), 410, "PROPOSAL_EXPIRED")
        assert harness.counts()["appointments"] == 0
    else:
        assert harness.confirm(owner, proposal).status_code == 201


def test_expired_pending_replaced_by_new_proposal(harness):
    owner = harness.owner()
    first = harness.proposal(owner)
    harness.app.state.clock = lambda: NOW + timedelta(minutes=10)
    second = harness.proposal(owner)
    assert second != first and harness.row(first).status == "EXPIRED"
    assert harness.row(second).status == "PENDING"


def test_confirm_commit_readback_restart_and_sequential_replay(harness, case_evidence):
    owner = harness.owner()
    proposal = harness.proposal(owner)
    first = harness.confirm(owner, proposal)
    assert first.status_code == 201
    body = AppointmentResponse.model_validate(first.json())
    with Session(harness.engine) as db:
        row = db.get(Appointment, body.appointment_id)
        assert row is not None and row.proposal_id == UUID(proposal)
        record = db.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.session_id == harness.owners[0])
        )
        assert record.response_body == first.json() and record.http_status == 201
        assert record.request_hash == confirmation_fingerprint(harness.owners[0], UUID(proposal))
    replay = harness.confirm(owner, proposal)
    assert replay.status_code == first.status_code and replay.json() == first.json()
    assert replay.content == first.content
    assert replay.headers["X-Trace-ID"] == first.headers["X-Trace-ID"]
    engine, restarted = harness.restart()
    try:
        with restarted:
            recovered = harness.confirm(owner, proposal, client=restarted)
            assert recovered.json() == first.json() and recovered.status_code == 201
            assert recovered.content == first.content
            fetched = restarted.get(f"/api/v1/appointments/{body.appointment_id}", headers=owner)
            assert fetched.status_code == 200 and fetched.json()["appointment_id"] == str(
                body.appointment_id
            )
    finally:
        engine.dispose()
    assert harness.counts() == {"booking_proposals": 1, "appointments": 1, "idempotency_records": 1}
    case_evidence.append(
        {
            "case": "sequential_replay_and_restart",
            "status": "PASS",
            "trace_id": first.json()["trace_id"],
            "counts": harness.counts(),
        }
    )


def test_new_key_on_confirmed_proposal_cannot_book_twice(harness):
    owner = harness.owner()
    proposal = harness.proposal(owner)
    first = harness.confirm(owner, proposal)
    again = harness.confirm(owner, proposal, key="new-key")
    assert_error(again, 409, "ALREADY_CONFIRMED")
    assert again.json()["appointment"]["appointment_id"] == first.json()["appointment_id"]
    assert harness.confirm(owner, proposal, key="new-key").json() == again.json()
    assert harness.counts()["appointments"] == 1 and harness.counts()["idempotency_records"] == 2


def test_key_reused_for_different_proposal_cannot_overwrite_result(harness):
    owner = harness.owner()
    first = harness.proposal(owner)
    original = harness.confirm(owner, first)
    second = harness.proposal(owner, local_time="10:00")
    assert_error(harness.confirm(owner, second), 409, "IDEMPOTENCY_KEY_REUSED")
    assert harness.confirm(owner, first).json() == original.json()
    assert harness.counts()["appointments"] == 1 and harness.counts()["idempotency_records"] == 1


def test_cross_session_and_unknown_resources_concealed(harness):
    owner, other = harness.owner(), harness.owner()
    proposal = harness.proposal(owner)
    assert_error(
        harness.client.get(f"/api/v1/proposals/{proposal}", headers=other),
        404,
        "PROPOSAL_NOT_FOUND",
    )
    assert_error(harness.confirm(other, proposal), 404, "PROPOSAL_NOT_FOUND")
    assert_error(harness.confirm(owner, str(uuid4())), 404, "PROPOSAL_NOT_FOUND")
    assert harness.counts()["idempotency_records"] == 0 and harness.counts()["appointments"] == 0
    booked = harness.confirm(owner, proposal).json()
    assert_error(
        harness.client.get(f"/api/v1/appointments/{booked['appointment_id']}", headers=other),
        404,
        "APPOINTMENT_NOT_FOUND",
    )
    assert_error(
        harness.client.get(f"/api/v1/appointments/{uuid4()}", headers=owner),
        404,
        "APPOINTMENT_NOT_FOUND",
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/proposals",
        "/api/v1/proposals/{id}",
        "/api/v1/proposals/{id}/confirm",
        "/api/v1/appointments/{id}",
    ],
)
def test_missing_bearer_rejected(harness, path):
    path = path.replace("{id}", str(uuid4()))
    response = (
        harness.client.post(path, json={}, headers={"Idempotency-Key": "key"})
        if path.endswith("confirm") or path.endswith("proposals")
        else harness.client.get(path)
    )
    assert_error(response, 401, "UNAUTHORIZED")


@pytest.mark.parametrize("key", [None, "", "has space", "a" * 201])
def test_required_idempotency_header_validation(harness, key):
    owner = harness.owner()
    proposal = harness.proposal(owner)
    response = harness.client.post(
        f"/api/v1/proposals/{proposal}/confirm",
        headers={**owner, **({"Idempotency-Key": key} if key is not None else {})},
    )
    assert_error(response, 422, "VALIDATION_ERROR")
    assert harness.counts()["appointments"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {"local_time": "10:00"},
        {"status": "CONFIRMED"},
        {"duration_minutes": 60},
        {"session_id": str(uuid4())},
    ],
)
def test_confirmation_cannot_change_snapshot(harness, body):
    owner = harness.owner()
    proposal = harness.proposal(owner)
    assert_error(harness.confirm(owner, proposal, json=body), 422, "VALIDATION_ERROR")
    assert harness.counts()["appointments"] == 0 and harness.row(proposal).status == "PENDING"


def test_notice_revalidated_when_exact_24h_becomes_too_near(harness):
    owner = harness.owner()
    proposal = harness.proposal(owner, local_date="2030-01-08")
    harness.app.state.clock = lambda: NOW + timedelta(seconds=1)
    response = harness.confirm(owner, proposal)
    assert_error(response, 422, "BUSINESS_RULE_VIOLATION")
    assert harness.counts()["appointments"] == 0 and harness.row(proposal).status == "PENDING"
    assert harness.confirm(owner, proposal).json() == response.json()


@pytest.mark.parametrize("change", ["inactive_practitioner", "inactive_type", "hours", "duration"])
def test_db_policy_and_duration_revalidated_at_confirmation(harness, change):
    owner = harness.owner()
    proposal = harness.proposal(owner)
    with Session(harness.engine) as db:
        if change == "inactive_practitioner":
            row, attr, value = db.get(Practitioner, PRACTITIONER_IDS[0]), "is_active", False
        elif change in {"inactive_type", "duration"}:
            row, attr, value = (
                db.get(AppointmentType, TYPE_IDS[0]),
                ("is_active" if change == "inactive_type" else "duration_minutes"),
                (False if change == "inactive_type" else 60),
            )
        else:
            row = db.scalar(
                select(WeeklySchedule).where(
                    WeeklySchedule.practitioner_id == PRACTITIONER_IDS[0],
                    WeeklySchedule.weekday == 3,
                )
            )
            attr, value = "opens_at", time(10)
        setattr(row, attr, value)
        db.commit()
    before = snapshot(harness.row(proposal))
    assert_error(harness.confirm(owner, proposal), 422, "BUSINESS_RULE_VIOLATION")
    assert harness.counts()["appointments"] == 0 and snapshot(harness.row(proposal)) == before


@pytest.mark.parametrize("duration,next_time", [(30, "09:30"), (60, "10:00")])
def test_adjacent_confirmations(harness, duration, next_time):
    first_owner, second_owner = harness.owner(), harness.owner()
    first = harness.proposal(first_owner, appointment_type_id=str(TYPE_IDS[duration == 60]))
    second = harness.proposal(second_owner, local_time=next_time)
    assert harness.confirm(first_owner, first).status_code == 201
    assert harness.confirm(second_owner, second).status_code == 201
    assert harness.counts()["appointments"] == 2


def test_same_time_different_practitioners_confirm(harness):
    first_owner, second_owner = harness.owner(), harness.owner()
    first = harness.proposal(first_owner)
    second = harness.proposal(second_owner, practitioner_id=str(PRACTITIONER_IDS[1]))
    assert harness.confirm(first_owner, first).status_code == 201
    assert harness.confirm(second_owner, second).status_code == 201
    assert harness.counts()["appointments"] == 2


def parallel(actions):
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(action) for action in actions]
        return [future.result(timeout=15) for future in futures]


@pytest.mark.parametrize("iteration", range(5))
def test_coordinated_overlap_exclusion_race(harness, monkeypatch, case_evidence, caplog, iteration):
    first_owner, second_owner = harness.owner(), harness.owner()
    first = harness.proposal(first_owner, appointment_type_id=str(TYPE_IDS[1]))
    second = harness.proposal(second_owner, local_time="09:30")
    barrier, inserted = Barrier(2), Event()
    pids = []
    original = BookingService._insert_appointment

    def coordinated(service, row, now):
        pids.append(service.db.scalar(text("SELECT pg_backend_pid()")))
        assert service.db.scalar(select(func.count()).select_from(Appointment)) == 0
        barrier.wait(timeout=5)  # Both have passed the policy/availability preflight.
        if row.duration_minutes == 60:
            result = original(service, row, now)
            inserted.set()
            return result
        assert inserted.wait(timeout=5)
        return original(service, row, now)  # Real GiST conflict after winner's insert/commit.

    monkeypatch.setattr(BookingService, "_insert_appointment", coordinated)
    with caplog.at_level("INFO", logger="clinic.requests"):
        winner, loser = parallel(
            [
                lambda: harness.confirm(first_owner, first),
                lambda: harness.confirm(second_owner, second),
            ]
        )
    assert winner.status_code == 201
    assert_error(loser, 409, "SLOT_TAKEN")
    assert len(set(pids)) == 2
    assert harness.counts() == {"booking_proposals": 2, "appointments": 1, "idempotency_records": 2}
    assert harness.row(first).status == "CONFIRMED" and harness.row(second).status == "CONFLICTED"
    events = [
        json.loads(record.message) for record in caplog.records if record.name == "clinic.requests"
    ]
    assert any(
        record.get("sqlstate") == "23P01" and record.get("constraint") == "appointments_no_overlap"
        for record in events
    )
    assert harness.confirm(second_owner, second).json() == loser.json()
    case_evidence.append(
        {
            "case": "overlap_race",
            "iteration": iteration,
            "status": "PASS",
            "postgres_backend_pids": pids,
            "sqlstate": "23P01",
            "constraint": "appointments_no_overlap",
            "counts": harness.counts(),
            "winner_trace_id": winner.json()["trace_id"],
            "loser_trace_id": loser.json()["trace_id"],
        }
    )


@pytest.mark.parametrize("same_key", [True, False])
def test_same_session_concurrent_confirmation_serializes_and_replays(
    harness, monkeypatch, case_evidence, same_key
):
    owner = harness.owner()
    proposal = harness.proposal(owner)
    barrier, pids = Barrier(2), []
    original = BookingService._session

    def coordinated(service, session_id):
        pids.append(service.db.scalar(text("SELECT pg_backend_pid()")))
        barrier.wait(timeout=5)
        return original(service, session_id)

    with monkeypatch.context() as patch:
        patch.setattr(BookingService, "_session", coordinated)
        results = parallel(
            [
                lambda: harness.confirm(owner, proposal),
                lambda: harness.confirm(
                    owner, proposal, key="synthetic-key" if same_key else "other"
                ),
            ]
        )
    assert len(set(pids)) == 2
    if same_key:
        assert [response.status_code for response in results] == [201, 201]
        assert results[0].json() == results[1].json()
    else:
        assert sorted(response.status_code for response in results) == [201, 409]
        assert_error(
            next(response for response in results if response.status_code == 409),
            409,
            "ALREADY_CONFIRMED",
        )
    assert harness.counts()["appointments"] == 1
    assert harness.counts()["idempotency_records"] == (1 if same_key else 2)
    case_evidence.append(
        {
            "case": "concurrent_confirm",
            "same_key": same_key,
            "status": "PASS",
            "postgres_backend_pids": pids,
            "counts": harness.counts(),
            "trace_ids": [response.json()["trace_id"] for response in results],
        }
    )


def test_precommit_database_failure_rolls_back_and_same_key_can_retry(
    harness, monkeypatch, case_evidence
):
    owner = harness.owner()
    proposal = harness.proposal(owner)
    insert = BookingService._insert_appointment
    commit = Session.commit

    def mark(service, row, now):
        result = insert(service, row, now)
        service.db.info["test_fail_before_commit"] = True
        return result

    def failure(db):
        if db.info.pop("test_fail_before_commit", False):
            raise OperationalError(
                "test-only-private-marker", {}, Exception("test-only-private-marker")
            )
        return commit(db)

    with monkeypatch.context() as patch:
        patch.setattr(BookingService, "_insert_appointment", mark)
        patch.setattr(Session, "commit", failure)
        failed = harness.confirm(owner, proposal)
    assert_error(failed, 503, "SERVICE_UNAVAILABLE")
    assert "CONFIRMED" not in failed.text and "private-marker" not in failed.text
    assert harness.counts() == {"booking_proposals": 1, "appointments": 0, "idempotency_records": 0}
    assert harness.row(proposal).status == "PENDING"
    restarted_engine, restarted = harness.restart()
    try:
        with restarted:
            recovered = harness.confirm(owner, proposal, client=restarted)
            assert recovered.status_code == 201
    finally:
        restarted_engine.dispose()
    assert harness.counts()["appointments"] == 1
    case_evidence.append(
        {
            "case": "precommit_failure_and_restart",
            "status": "PASS",
            "failure_trace_id": failed.json()["trace_id"],
            "recovered_trace_id": recovered.json()["trace_id"],
            "before_retry_appointments": 0,
            "counts": harness.counts(),
        }
    )


def test_http_response_lost_after_commit_recovers_original_key(harness, case_evidence):
    owner = harness.owner()
    proposal = harness.proposal(owner)
    received = []

    def response_lost():
        response = harness.confirm(owner, proposal)
        assert response.status_code == 201
        received.append(response.json())
        raise httpx.ReadError("test-only dropped HTTP response")

    with pytest.raises(httpx.ReadError):
        response_lost()
    assert harness.counts()["appointments"] == 1 and harness.row(proposal).status == "CONFIRMED"
    engine, restarted = harness.restart()
    try:
        with restarted:
            replay = harness.confirm(owner, proposal, client=restarted)
            assert replay.status_code == 201 and replay.json() == received[0]
    finally:
        engine.dispose()
    assert harness.counts()["appointments"] == 1 and harness.counts()["idempotency_records"] == 1
    case_evidence.append(
        {
            "case": "lost_http_response_after_commit",
            "status": "PASS",
            "trace_id": replay.json()["trace_id"],
            "counts": harness.counts(),
        }
    )


def test_commit_acknowledgement_unknown_returns_no_claim_then_recovers(
    harness, monkeypatch, case_evidence
):
    owner = harness.owner()
    proposal = harness.proposal(owner)
    insert, commit = BookingService._insert_appointment, Session.commit

    def mark(service, row, now):
        result = insert(service, row, now)
        service.db.info["test_drop_commit_ack"] = True
        return result

    def lost_ack(db):
        lose = db.info.pop("test_drop_commit_ack", False)
        commit(db)
        if lose:
            raise OperationalError("test-only commit acknowledgement lost", {}, Exception())

    with monkeypatch.context() as patch:
        patch.setattr(BookingService, "_insert_appointment", mark)
        patch.setattr(Session, "commit", lost_ack)
        unknown = harness.confirm(owner, proposal)
    assert_error(unknown, 503, "SERVICE_UNAVAILABLE")
    assert "CONFIRMED" not in unknown.text and unknown.json()["error"]["retryable"] is True
    assert harness.counts()["appointments"] == 1
    recovered = harness.confirm(owner, proposal)
    assert recovered.status_code == 201
    assert harness.counts()["appointments"] == 1 and harness.counts()["idempotency_records"] == 1
    case_evidence.append(
        {
            "case": "lost_commit_acknowledgement",
            "status": "PASS",
            "unknown_trace_id": unknown.json()["trace_id"],
            "recovered_trace_id": recovered.json()["trace_id"],
            "counts": harness.counts(),
        }
    )


def test_logs_hide_bearer_and_no_agent_debug_routes(harness, caplog):
    owner = harness.owner()
    with caplog.at_level("INFO", logger="clinic.requests"):
        proposal = harness.proposal(owner)
        assert harness.confirm(owner, proposal).status_code == 201
    assert owner["Authorization"] not in caplog.text
    assert owner["Authorization"].split()[1] not in caplog.text
    paths = harness.client.get("/openapi.json").json()["paths"]
    assert not any("debug" in path or "failpoint" in path for path in paths)
    assert "/api/v1/chat/messages" in paths


@pytest.mark.parametrize("same_tuple", [True, False])
def test_concurrent_proposal_creation_has_one_pending(harness, monkeypatch, same_tuple):
    owner = harness.owner()
    barrier, pids = Barrier(2), []
    original = BookingService._session

    def coordinated(service, session_id):
        pids.append(service.db.scalar(text("SELECT pg_backend_pid()")))
        barrier.wait(timeout=5)
        return original(service, session_id)

    with monkeypatch.context() as patch:
        patch.setattr(BookingService, "_session", coordinated)
        responses = parallel(
            [
                lambda: harness.propose(owner),
                lambda: harness.propose(owner, local_time="09:00" if same_tuple else "10:00"),
            ]
        )
    assert len(set(pids)) == 2
    assert sorted(response.status_code for response in responses) == (
        [200, 201] if same_tuple else [201, 201]
    )
    with Session(harness.engine) as db:
        states = list(
            db.scalars(
                select(BookingProposal.status).where(
                    BookingProposal.session_id == harness.owners[0]
                )
            )
        )
    assert states.count("PENDING") == 1
    assert sorted(states) == (["PENDING"] if same_tuple else ["PENDING", "SUPERSEDED"])
    assert harness.counts()["appointments"] == 0


@pytest.mark.parametrize(
    "day,at,type_index",
    [
        ("2030-01-12", "09:00", 0),
        ("2030-01-09", "08:30", 0),
        ("2030-01-09", "10:15", 0),
        ("2030-01-09", "16:30", 1),
        ("2030-01-07", "09:00", 0),
        ("2030-05-01", "09:00", 0),
    ],
)
def test_invalid_persisted_snapshot_cannot_bypass_confirmation_rules(harness, day, at, type_index):
    from datetime import date

    from app.db.seed import CLINIC_ID
    from app.domain.scheduling import local_to_utc

    owner = harness.owner()
    start = local_to_utc(date.fromisoformat(day), time.fromisoformat(at))
    duration = 30 if type_index == 0 else 60
    with Session(harness.engine) as db:
        row = BookingProposal(
            session_id=harness.owners[0],
            clinic_id=CLINIC_ID,
            practitioner_id=PRACTITIONER_IDS[0],
            appointment_type_id=TYPE_IDS[type_index],
            starts_at=start,
            ends_at=start + timedelta(minutes=duration),
            duration_minutes=duration,
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
            status="PENDING",
        )
        db.add(row)
        db.flush()
        proposal = str(row.id)
        db.commit()
    assert_error(harness.confirm(owner, proposal), 422, "BUSINESS_RULE_VIOLATION")
    assert harness.counts()["appointments"] == 0 and harness.row(proposal).status == "PENDING"


@pytest.mark.parametrize("value", ["9:00", "25:00", "09:00:00", "09:00-05:00", "next morning"])
def test_ambiguous_or_invalid_proposal_time_rejected(harness, value):
    owner = harness.owner()
    assert_error(harness.propose(owner, local_time=value), 422, "VALIDATION_ERROR")
    assert harness.counts()["booking_proposals"] == 0


def test_definite_serialization_abort_retries_entire_transaction(harness, monkeypatch):
    owner = harness.owner()
    proposal = harness.proposal(owner)
    original = BookingService._insert_appointment
    calls = []

    def abort_once(service, row, now):
        calls.append(1)
        if len(calls) == 1:
            service.db.execute(
                text("DO $$ BEGIN RAISE EXCEPTION 'test-only abort' USING ERRCODE='40001'; END $$")
            )
        return original(service, row, now)

    monkeypatch.setattr(BookingService, "_insert_appointment", abort_once)
    response = harness.confirm(owner, proposal)
    assert response.status_code == 201 and len(calls) == 2
    assert harness.counts() == {"booking_proposals": 1, "appointments": 1, "idempotency_records": 1}


@pytest.mark.parametrize("expired", [True, False])
def test_deadline_crossing_during_insert_rolls_back_appointment(harness, monkeypatch, expired):
    clock = [NOW]
    harness.app.state.clock = lambda: clock[0]
    owner = harness.owner()
    proposal = harness.proposal(owner, local_date="2030-01-09" if expired else "2030-01-08")
    original = BookingService._insert_appointment

    def delayed(service, row, now):
        result = original(service, row, now)
        clock[0] = NOW + (timedelta(minutes=10) if expired else timedelta(seconds=1))
        return result

    monkeypatch.setattr(BookingService, "_insert_appointment", delayed)
    response = harness.confirm(owner, proposal)
    assert_error(
        response,
        410 if expired else 422,
        "PROPOSAL_EXPIRED" if expired else "BUSINESS_RULE_VIOLATION",
    )
    assert harness.counts() == {"booking_proposals": 1, "appointments": 0, "idempotency_records": 1}
    assert harness.row(proposal).status == ("EXPIRED" if expired else "PENDING")
    assert harness.confirm(owner, proposal).content == response.content
