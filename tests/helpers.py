import hashlib
from datetime import timedelta
from uuid import uuid4

from app.db.models import Appointment, BookingProposal, ChatSession, ChatTurn
from app.db.seed import CLINIC_ID, PRACTITIONER_IDS, TYPE_IDS
from tests.conftest import NOW


def session_row(db):
    row = ChatSession(
        token_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        created_at=NOW,
        expires_at=NOW + timedelta(hours=24),
    )
    db.add(row)
    db.flush()
    return row


def proposal_row(
    db, *, session=None, practitioner=None, start=None, duration=30, status="CONFIRMED"
):
    row = BookingProposal(
        session_id=(session or session_row(db)).id,
        clinic_id=CLINIC_ID,
        practitioner_id=practitioner or PRACTITIONER_IDS[0],
        appointment_type_id=TYPE_IDS[0 if duration == 30 else 1],
        starts_at=start or NOW + timedelta(days=2),
        ends_at=(start or NOW + timedelta(days=2)) + timedelta(minutes=duration),
        duration_minutes=duration,
        status=status,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    db.add(row)
    db.flush()
    return row


def appointment_row(db, proposal):
    row = Appointment(
        proposal_id=proposal.id,
        session_id=proposal.session_id,
        practitioner_id=proposal.practitioner_id,
        starts_at=proposal.starts_at,
        ends_at=proposal.ends_at,
        duration_minutes=proposal.duration_minutes,
    )
    db.add(row)
    db.flush()
    return row


def turn_row(db, session=None, message_id=None):
    row = ChatTurn(
        session_id=(session or session_row(db)).id,
        client_message_id=message_id or uuid4(),
        request_hash="a" * 64,
        status="IN_PROGRESS",
        trace_id=uuid4(),
    )
    db.add(row)
    db.flush()
    return row
