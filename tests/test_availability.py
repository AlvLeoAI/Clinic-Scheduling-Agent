from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    Appointment,
    AppointmentType,
    Base,
    BookingProposal,
    ChatSession,
    Clinic,
    Practitioner,
    WeeklySchedule,
)
from app.db.seed import CLINIC_ID, PRACTITIONER_IDS, TYPE_IDS, seed_catalog
from app.db.session import get_db
from app.domain.scheduling import candidate_slots
from app.main import create_app
from app.schemas.scheduling import AvailabilityResponse
from app.services.scheduling import SchedulingService
from tests.conftest import NOW
from tests.helpers import appointment_row, proposal_row

pytestmark = [pytest.mark.postgres, pytest.mark.api]
DAY = date(2030, 1, 9)
START = datetime(2030, 1, 9, 15, tzinfo=UTC)


def app_for(db, engine, now=NOW):
    settings = Settings(
        _env_file=None, database_url=engine.url.render_as_string(hide_password=False)
    )
    app = create_app(settings, engine, clock=lambda: now)
    app.dependency_overrides[get_db] = lambda: db
    return app


@pytest.fixture
def application(db, engine, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    return app_for(db, engine)


@pytest.fixture
def client(application):
    with TestClient(application, raise_server_exceptions=False) as instance:
        yield instance


def query(client, day=DAY, practitioner=PRACTITIONER_IDS[0], appointment_type=TYPE_IDS[0], **extra):
    return client.get(
        "/api/v1/availability",
        params={
            "date": str(day),
            "practitioner_id": str(practitioner),
            "appointment_type_id": str(appointment_type),
            **extra,
        },
    )


def starts(response):
    assert response.status_code == 200, response.text
    body = AvailabilityResponse.model_validate(response.json())
    assert str(body.trace_id) == response.headers["X-Trace-ID"]
    return [row.starts_at.time().replace(tzinfo=None) for row in body.slots]


def assert_error(response, code, status=422):
    assert response.status_code == status
    assert set(response.json()) == {"error", "trace_id"}
    assert response.json()["error"]["code"] == code
    assert str(UUID(response.json()["trace_id"])) == response.headers["X-Trace-ID"]


@pytest.mark.parametrize("type_index,count,last", [(0, 16, time(16, 30)), (1, 15, time(16))])
def test_api_business_hours_duration_and_policy_parity(client, db, type_index, count, last):
    response = query(client, appointment_type=TYPE_IDS[type_index])
    times = starts(response)
    assert len(times) == count and times[0] == time(9) and times[-1] == last
    body = AvailabilityResponse.model_validate(response.json())
    assert body.clinic_timezone == "America/Chicago" and body.date == DAY
    assert body.practitioner_id == PRACTITIONER_IDS[0]
    assert body.clinic_id == CLINIC_ID and body.duration_minutes == (30 if type_index == 0 else 60)
    expected = candidate_slots(
        DAY,
        opens_at=time(9),
        closes_at=time(17),
        duration_minutes=body.duration_minutes,
        now_utc=NOW,
    )
    assert [(row.starts_at.astimezone(UTC), row.ends_at.astimezone(UTC)) for row in body.slots] == [
        (row.starts_at, row.ends_at) for row in expected
    ]
    assert times == sorted(set(times)) and all(at.minute in (0, 30) for at in times)
    assert (
        query(client, appointment_type=TYPE_IDS[type_index]).json()["slots"]
        == response.json()["slots"]
    )


@pytest.mark.parametrize(
    "day",
    [date(2030, 1, 12), date(2030, 1, 13), date(2029, 1, 1), date(2031, 1, 1), date.min, date.max],
)
def test_closed_past_or_out_of_horizon_dates_empty(client, day):
    assert starts(query(client, day)) == []


@pytest.mark.parametrize(
    "now_offset,expected_first,expected_count",
    [
        (-timedelta(hours=24), time(9), 16),
        (-timedelta(hours=24) + timedelta(microseconds=1), time(9, 30), 15),
        (-timedelta(days=90), time(9), 1),
        (-timedelta(days=90) - timedelta(microseconds=1), None, 0),
        (-timedelta(hours=16), None, 0),
    ],
)
def test_notice_horizon_and_exhausted_boundaries(
    client, application, now_offset, expected_first, expected_count
):
    application.state.clock = lambda: START + now_offset
    times = starts(query(client))
    assert len(times) == expected_count
    assert (times[0] if times else None) == expected_first


@pytest.mark.parametrize(
    "day,offset",
    [
        (date(2030, 3, 8), -6),
        (date(2030, 3, 11), -5),
        (date(2030, 11, 1), -5),
        (date(2030, 11, 4), -6),
    ],
)
def test_chicago_dst_api(client, application, db, day, offset):
    now = datetime.combine(day - timedelta(days=3), time(0), UTC)
    application.state.clock = lambda: now
    # Change PostgreSQL's presentation zone too; TIMESTAMPTZ remains an instant.
    db.execute(text("SET LOCAL TIME ZONE 'Asia/Tokyo'"))
    response = query(client, day)
    assert len(starts(response)) == 16
    body = AvailabilityResponse.model_validate(response.json())
    assert all(row.starts_at.utcoffset() == timedelta(hours=offset) for row in body.slots)
    assert body.slots[0].starts_at.astimezone(UTC).hour == 9 - offset


@pytest.mark.parametrize("duration", [30, 60])
def test_occupied_partial_overlap_adjacency_and_other_practitioner(client, db, duration):
    appointment_row(db, proposal_row(db, start=START + timedelta(minutes=75), duration=30))
    own = starts(query(client, appointment_type=TYPE_IDS[duration == 60]))
    removed = {time(10), time(10, 30)} | ({time(9, 30)} if duration == 60 else set())
    assert not removed.intersection(own)
    assert time(9) in own and time(11) in own
    assert len(own) == (12 if duration == 60 else 14)
    other = starts(
        query(client, practitioner=PRACTITIONER_IDS[1], appointment_type=TYPE_IDS[duration == 60])
    )
    assert len(other) == (15 if duration == 60 else 16)
    assert removed.issubset(set(other))


def test_reservations_crossing_day_bounds(client, db):
    for start in [START - timedelta(minutes=15), START + timedelta(hours=7, minutes=45)]:
        appointment_row(db, proposal_row(db, start=start))
    times = starts(query(client))
    assert len(times) == 14 and time(9) not in times and time(16, 30) not in times


@pytest.mark.parametrize("type_index,adjacent_before", [(0, time(9, 30)), (1, time(9))])
def test_adjacent_non_overlapping_appointments_remain_available(
    client, db, type_index, adjacent_before
):
    appointment_row(db, proposal_row(db, start=START + timedelta(hours=1), duration=60))
    times = starts(query(client, appointment_type=TYPE_IDS[type_index]))
    assert adjacent_before in times and time(11) in times
    assert time(10) not in times and time(10, 30) not in times
    if type_index == 1:
        assert time(9, 30) not in times


@pytest.mark.parametrize("type_index", [0, 1])
def test_fully_booked_day(client, db, type_index):
    for hour in range(8):
        appointment_row(db, proposal_row(db, start=START + timedelta(hours=hour), duration=60))
    assert starts(query(client, appointment_type=TYPE_IDS[type_index])) == []


def test_pending_proposal_never_holds_slot(client, db):
    proposal_row(db, start=START, status="PENDING")
    assert time(9) in starts(query(client))


@pytest.mark.parametrize("field", ["practitioner_id", "appointment_type_id"])
def test_unknown_ids(client, field):
    assert_error(query(client, **{field: uuid4()}), "BUSINESS_RULE_VIOLATION")


@pytest.mark.parametrize(
    "model,key", [(Practitioner, PRACTITIONER_IDS[0]), (AppointmentType, TYPE_IDS[0])]
)
def test_inactive_catalog_rejected(client, db, model, key):
    db.get(model, key).is_active = False
    db.flush()
    assert_error(query(client), "BUSINESS_RULE_VIOLATION")


@pytest.mark.parametrize("field", ["date", "practitioner_id", "appointment_type_id"])
def test_missing_parameters_not_inferred(client, field):
    params = {
        "date": str(DAY),
        "practitioner_id": str(PRACTITIONER_IDS[0]),
        "appointment_type_id": str(TYPE_IDS[0]),
    }
    del params[field]
    assert_error(client.get("/api/v1/availability", params=params), "VALIDATION_ERROR")


@pytest.mark.parametrize(
    "day",
    [
        "next Friday",
        "01/09/2030",
        "2030-02-30",
        "20300109",
        "2030-01-09T00:00:00Z",
        "null",
        "",
        "1894147200",
    ],
)
def test_invalid_or_ambiguous_date_not_inferred(client, day, caplog):
    with caplog.at_level("INFO", logger="clinic.requests"):
        response = query(client, day)
    assert_error(response, "VALIDATION_ERROR")
    assert "next Friday" not in response.text + caplog.text


@pytest.mark.parametrize(
    "extra",
    [
        {"duration_minutes": "60"},
        {"local_time": "10:15"},
        {"practitioner_id": "dr_smith"},
        {"appointment_type_id": "follow_up"},
    ],
)
def test_unsupported_override_or_non_uuid_rejected(client, extra):
    assert_error(query(client, **extra), "VALIDATION_ERROR")


def test_clinic_mismatch_rejected(client, db):
    clinic = Clinic(name="Synthetic Other Clinic", timezone="America/Chicago")
    db.add(clinic)
    db.flush()
    appointment_type = AppointmentType(
        clinic_id=clinic.id, code="synthetic_other", duration_minutes=30
    )
    db.add(appointment_type)
    db.flush()
    assert_error(query(client, appointment_type=appointment_type.id), "BUSINESS_RULE_VIOLATION")


def test_unsupported_clinic_timezone_safe_error(client, db):
    db.get(Clinic, CLINIC_ID).timezone = "America/New_York"
    db.flush()
    response = query(client)
    assert_error(response, "SERVICE_UNAVAILABLE", 503)
    assert response.json()["error"]["retryable"] is True


def test_duration_and_hours_come_from_db(client, db):
    db.get(AppointmentType, TYPE_IDS[0]).duration_minutes = 60
    schedule = db.scalar(
        select(WeeklySchedule).where(
            WeeklySchedule.practitioner_id == PRACTITIONER_IDS[0], WeeklySchedule.weekday == 3
        )
    )
    schedule.opens_at = time(10)
    schedule.closes_at = time(16)
    db.flush()
    response = query(client)
    assert response.json()["duration_minutes"] == 60
    times = starts(response)
    assert len(times) == 11 and times[0] == time(10) and times[-1] == time(15)


def test_db_hours_cannot_expand_approved_window_or_weekends(client, db):
    schedule = db.scalar(
        select(WeeklySchedule).where(
            WeeklySchedule.practitioner_id == PRACTITIONER_IDS[0], WeeklySchedule.weekday == 3
        )
    )
    schedule.opens_at = time(8)
    schedule.closes_at = time(18)
    db.add(
        WeeklySchedule(
            practitioner_id=PRACTITIONER_IDS[0], weekday=6, opens_at=time(9), closes_at=time(17)
        )
    )
    db.flush()
    assert starts(query(client))[0] == time(9)
    assert starts(query(client))[-1] == time(16, 30)
    assert starts(query(client, date(2030, 1, 12))) == []


def test_missing_weekly_schedule_closed(client, db):
    db.execute(
        delete(WeeklySchedule).where(
            WeeklySchedule.practitioner_id == PRACTITIONER_IDS[0], WeeklySchedule.weekday == 3
        )
    )
    assert starts(query(client)) == []


def table_snapshot(db):
    return {
        name: db.execute(text(f'SELECT row_to_json(t)::text FROM "{name}" t ORDER BY id'))
        .scalars()
        .all()
        for name in sorted(Base.metadata.tables)
    }


def test_availability_preserves_every_table_and_issues_only_selects(client, db):
    proposal_row(db, start=START, status="PENDING")
    appointment_row(db, proposal_row(db, start=START + timedelta(hours=1)))
    before = table_snapshot(db)
    statements = []
    connection = db.connection()

    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(connection, "before_cursor_execute", observe)
    try:
        for type_id in TYPE_IDS:
            assert starts(query(client, appointment_type=type_id))
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    assert statements and set(statements) == {"SELECT"}
    assert table_snapshot(db) == before


def test_service_does_not_autoflush_pending_work(db):
    row = ChatSession(token_hash="f" * 64, created_at=NOW, expires_at=NOW + timedelta(hours=24))
    db.add(row)
    result = SchedulingService(db, clock=lambda: NOW).availability(
        local_date=DAY, practitioner_id=PRACTITIONER_IDS[0], appointment_type_id=TYPE_IDS[0]
    )
    assert len(result.slots) == 16 and row.id is None and row in db.new


def test_committed_reservation_from_separate_connection_and_postgres_read_only(engine):
    # Direct synthetic fixture inserts only; this is not an M3 booking service.
    owner_id = proposal_id = appointment_id = None
    try:
        with Session(engine) as writer:
            seed_catalog(writer)
            proposal = proposal_row(writer, start=START)
            appointment = appointment_row(writer, proposal)
            owner_id, proposal_id, appointment_id = proposal.session_id, proposal.id, appointment.id
            writer.commit()
        with engine.connect() as connection, connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            with Session(bind=connection) as reader:
                assert reader.scalar(text("SHOW transaction_read_only")) == "on"
                before = table_snapshot(reader)
                with TestClient(app_for(reader, engine), raise_server_exceptions=False) as client:
                    own = starts(query(client))
                    other = starts(query(client, practitioner=PRACTITIONER_IDS[1]))
                assert time(9) not in own and len(own) == 15
                assert time(9) in other and len(other) == 16
                assert table_snapshot(reader) == before
    finally:
        if appointment_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(delete(Appointment).where(Appointment.id == appointment_id))
                cleanup.execute(delete(BookingProposal).where(BookingProposal.id == proposal_id))
                cleanup.execute(delete(ChatSession).where(ChatSession.id == owner_id))
                cleanup.commit()
