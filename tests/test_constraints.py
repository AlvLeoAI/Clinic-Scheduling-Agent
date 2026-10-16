from datetime import time, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Appointment,
    AppointmentType,
    ChatSession,
    Clinic,
    ConversationItem,
    IdempotencyRecord,
    Practitioner,
    WeeklySchedule,
)
from app.db.seed import CLINIC_ID, PRACTITIONER_IDS, seed_catalog
from tests.conftest import NOW
from tests.helpers import appointment_row, proposal_row, session_row, turn_row

pytestmark = pytest.mark.postgres


def rejected(db, code, operation):
    with pytest.raises(IntegrityError) as caught:
        with db.begin_nested():
            operation()
            db.flush()
    assert caught.value.orig.sqlstate == code
    return caught.value.orig.diag.constraint_name


def test_seed_idempotent_and_artificial(db):
    seed_catalog(db)
    seed_catalog(db)
    for model, count in [
        (Clinic, 1),
        (Practitioner, 2),
        (AppointmentType, 2),
        (WeeklySchedule, 10),
    ]:
        assert db.scalar(select(func.count()).select_from(model)) == count
    assert db.scalar(select(Clinic.name)) == "Synthetic Demo Clinic"
    assert set(db.scalars(select(Practitioner.display_name))) == {
        "Demo Clinician 01",
        "Demo Clinician 02",
    }
    assert db.scalar(select(func.count()).select_from(Appointment)) == 0
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 0


def test_overlap_rejected(db):
    appointment_row(db, proposal_row(db, duration=60))
    other = proposal_row(db, start=NOW + timedelta(days=2, minutes=30))
    assert rejected(db, "23P01", lambda: appointment_row(db, other)) == "appointments_no_overlap"
    assert db.scalar(select(func.count()).select_from(Appointment)) == 1


def test_adjacent_accepted(db):
    first = proposal_row(db, duration=60)
    appointment_row(db, first)
    appointment_row(db, proposal_row(db, start=first.ends_at))
    assert db.scalar(select(func.count()).select_from(Appointment)) == 2


def test_different_practitioners_can_overlap(db):
    appointment_row(db, proposal_row(db, duration=60))
    appointment_row(db, proposal_row(db, practitioner=PRACTITIONER_IDS[1]))
    assert db.scalar(select(func.count()).select_from(Appointment)) == 2


def test_proposal_only_one_appointment(db):
    proposal = proposal_row(db)
    appointment_row(db, proposal)
    # Adjacent candidate avoids exclusion so the proposal uniqueness is independently exercised.
    duplicate = Appointment(
        proposal_id=proposal.id,
        session_id=proposal.session_id,
        practitioner_id=proposal.practitioner_id,
        starts_at=proposal.ends_at,
        ends_at=proposal.ends_at + timedelta(minutes=30),
        duration_minutes=30,
    )
    assert rejected(db, "23505", lambda: db.add(duplicate)) == "uq_appointments_proposal_id"


def test_one_pending_per_session(db):
    owner = session_row(db)
    proposal_row(db, session=owner, status="PENDING")
    assert rejected(db, "23505", lambda: proposal_row(db, session=owner, status="PENDING")) == (
        "uq_proposal_pending_session"
    )
    proposal_row(db, status="PENDING")  # Other session is independent.


def test_terminal_proposals_not_in_pending_index(db):
    owner = session_row(db)
    proposal_row(db, session=owner, status="SUPERSEDED")
    proposal_row(db, session=owner, status="EXPIRED")
    proposal_row(db, session=owner, status="PENDING")


@pytest.mark.parametrize(
    "field,value",
    [
        ("duration_minutes", 20),
        ("weekday", 0),
        ("hours", "reversed"),
    ],
)
def test_catalog_checks(db, field, value):
    if field == "duration_minutes":
        row = AppointmentType(clinic_id=CLINIC_ID, code="synthetic_invalid", duration_minutes=value)
    else:
        row = WeeklySchedule(
            practitioner_id=PRACTITIONER_IDS[0],
            weekday=0 if field == "weekday" else 6,
            opens_at=time(17) if field == "hours" else time(9),
            closes_at=time(9) if field == "hours" else time(17),
        )
    rejected(db, "23514", lambda: db.add(row))


def test_foreign_key(db):
    rejected(
        db, "23503", lambda: db.add(Practitioner(clinic_id=uuid4(), display_name="Demo Invalid"))
    )


@pytest.mark.parametrize("change", ["duration", "interval", "status"])
def test_proposal_checks(db, change):
    def invalid():
        row = proposal_row(db)
        if change == "duration":
            row.duration_minutes = 60  # interval snapshot still 30.
        elif change == "interval":
            row.ends_at = row.starts_at
        else:
            row.status = "INVALID"

    rejected(db, "23514", invalid)


def test_appointment_snapshot_cannot_change_session(db):
    proposal = proposal_row(db)
    other = session_row(db)
    row = Appointment(
        proposal_id=proposal.id,
        session_id=other.id,
        practitioner_id=proposal.practitioner_id,
        starts_at=proposal.starts_at,
        ends_at=proposal.ends_at,
        duration_minutes=30,
    )
    rejected(db, "23503", lambda: db.add(row))


def test_appointment_duration_check(db):
    proposal = proposal_row(db)
    row = Appointment(
        proposal_id=proposal.id,
        session_id=proposal.session_id,
        practitioner_id=proposal.practitioner_id,
        starts_at=proposal.starts_at,
        ends_at=proposal.ends_at,
        duration_minutes=60,
    )
    rejected(db, "23514", lambda: db.add(row))


def test_turn_message_key_and_ownership(db):
    owner = session_row(db)
    message_id = uuid4()
    turn = turn_row(db, owner, message_id)
    rejected(db, "23505", lambda: turn_row(db, owner, message_id))
    other = session_row(db)
    rejected(db, "23503", lambda: setattr(other, "active_turn_id", turn.id))


def test_conversation_sequence_and_owner(db):
    turn = turn_row(db)
    db.add(
        ConversationItem(
            session_id=turn.session_id, turn_id=turn.id, sequence=0, item_type="message", payload={}
        )
    )
    db.flush()
    rejected(
        db,
        "23505",
        lambda: db.add(
            ConversationItem(
                session_id=turn.session_id,
                turn_id=turn.id,
                sequence=0,
                item_type="message",
                payload={},
            )
        ),
    )
    other = session_row(db)
    rejected(
        db,
        "23503",
        lambda: db.add(
            ConversationItem(
                session_id=other.id, turn_id=turn.id, sequence=1, item_type="message", payload={}
            )
        ),
    )


def test_idempotency_key_scoped_to_session(db):
    owner = session_row(db)

    def record(ident):
        return IdempotencyRecord(
            session_id=ident,
            idempotency_key="synthetic-request",
            request_hash="a" * 64,
            outcome_code="SYNTHETIC_TEST",
            http_status=409,
            response_body={},
        )

    db.add(record(owner.id))
    db.flush()
    rejected(db, "23505", lambda: db.add(record(owner.id)))
    db.add(record(session_row(db).id))
    db.flush()


def test_session_hash_and_expiry_checks(db):
    rejected(
        db,
        "23514",
        lambda: db.add(
            ChatSession(
                token_hash="not-a-hash", created_at=NOW, expires_at=NOW + timedelta(hours=24)
            )
        ),
    )
    rejected(
        db,
        "23514",
        lambda: db.add(ChatSession(token_hash="a" * 64, created_at=NOW, expires_at=NOW)),
    )
