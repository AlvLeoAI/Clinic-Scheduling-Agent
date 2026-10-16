"""M1 relational structure only; no scheduling or confirmation service."""

from datetime import datetime, time
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "ix": "ix_%(table_name)s_%(column_0_name)s",
        }
    )


class Identified:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class Created:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Clinic(Identified, Created, Base):
    __tablename__ = "clinics"
    name: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64))


class Practitioner(Identified, Created, Base):
    __tablename__ = "practitioners"
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"))
    display_name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    __table_args__ = (UniqueConstraint("id", "clinic_id", name="uq_practitioner_clinic"),)


class AppointmentType(Identified, Created, Base):
    __tablename__ = "appointment_types"
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"))
    code: Mapped[str] = mapped_column(String(50))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    __table_args__ = (
        UniqueConstraint("clinic_id", "code", name="uq_type_clinic_code"),
        UniqueConstraint("id", "clinic_id", name="uq_type_clinic"),
        CheckConstraint("duration_minutes IN (30,60)", name="duration"),
    )


class WeeklySchedule(Identified, Created, Base):
    __tablename__ = "weekly_schedules"
    practitioner_id: Mapped[UUID] = mapped_column(ForeignKey("practitioners.id"))
    weekday: Mapped[int] = mapped_column(Integer)
    opens_at: Mapped[time] = mapped_column(Time)
    closes_at: Mapped[time] = mapped_column(Time)
    __table_args__ = (
        UniqueConstraint("practitioner_id", "weekday", name="uq_schedule_practitioner_day"),
        CheckConstraint("weekday BETWEEN 1 AND 7", name="weekday"),
        CheckConstraint("opens_at < closes_at", name="hours"),
    )


class ChatSession(Identified, Created, Base):
    __tablename__ = "chat_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active_turn_id: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_fence: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expiry"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash"),
        CheckConstraint("lease_fence >= 0", name="lease_fence"),
        ForeignKeyConstraint(
            ["active_turn_id", "id"],
            ["chat_turns.id", "chat_turns.session_id"],
            name="fk_session_active_turn_owner",
            use_alter=True,
        ),
    )


class ChatTurn(Identified, Created, Base):
    __tablename__ = "chat_turns"
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id"))
    client_message_id: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assistant_message: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[UUID] = mapped_column()
    __table_args__ = (
        UniqueConstraint("session_id", "client_message_id", name="uq_turn_session_message"),
        UniqueConstraint("id", "session_id", name="uq_turn_session"),
        CheckConstraint("status IN ('IN_PROGRESS','COMPLETED','FAILED')", name="status"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="request_hash"),
    )


class ConversationItem(Identified, Created, Base):
    __tablename__ = "conversation_items"
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id"))
    turn_id: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(Integer)
    item_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSONB)
    call_id: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (
        ForeignKeyConstraint(
            ["turn_id", "session_id"],
            ["chat_turns.id", "chat_turns.session_id"],
            name="fk_item_turn_owner",
        ),
        UniqueConstraint("turn_id", "sequence", name="uq_item_turn_sequence"),
        CheckConstraint("sequence >= 0", name="sequence"),
        Index(
            "uq_item_turn_call",
            "turn_id",
            "call_id",
            "item_type",
            unique=True,
            postgresql_where=text("call_id IS NOT NULL"),
        ),
    )


class BookingProposal(Identified, Created, Base):
    __tablename__ = "booking_proposals"
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id"))
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id"))
    practitioner_id: Mapped[UUID] = mapped_column()
    appointment_type_id: Mapped[UUID] = mapped_column()
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_turn_id: Mapped[UUID | None] = mapped_column(unique=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["practitioner_id", "clinic_id"],
            ["practitioners.id", "practitioners.clinic_id"],
            name="fk_proposal_practitioner_clinic",
        ),
        ForeignKeyConstraint(
            ["appointment_type_id", "clinic_id"],
            ["appointment_types.id", "appointment_types.clinic_id"],
            name="fk_proposal_type_clinic",
        ),
        ForeignKeyConstraint(
            ["source_turn_id", "session_id"],
            ["chat_turns.id", "chat_turns.session_id"],
            name="fk_proposal_turn_owner",
        ),
        UniqueConstraint(
            "id",
            "session_id",
            "practitioner_id",
            "starts_at",
            "ends_at",
            "duration_minutes",
            name="uq_proposal_booking_snapshot",
        ),
        CheckConstraint(
            "status IN ('PENDING','CONFIRMED','CONFLICTED','EXPIRED','SUPERSEDED')", name="status"
        ),
        CheckConstraint("duration_minutes IN (30,60)", name="duration"),
        CheckConstraint("ends_at > starts_at", name="interval"),
        CheckConstraint(
            "ends_at - starts_at = duration_minutes * INTERVAL '1 minute'", name="duration_match"
        ),
        CheckConstraint("expires_at > created_at", name="expiry"),
        Index(
            "uq_proposal_pending_session",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )


class Appointment(Identified, Base):
    __tablename__ = "appointments"
    proposal_id: Mapped[UUID] = mapped_column(unique=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id"))
    practitioner_id: Mapped[UUID] = mapped_column(ForeignKey("practitioners.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "proposal_id",
                "session_id",
                "practitioner_id",
                "starts_at",
                "ends_at",
                "duration_minutes",
            ],
            [
                "booking_proposals.id",
                "booking_proposals.session_id",
                "booking_proposals.practitioner_id",
                "booking_proposals.starts_at",
                "booking_proposals.ends_at",
                "booking_proposals.duration_minutes",
            ],
            name="fk_appointment_proposal_snapshot",
        ),
        UniqueConstraint("id", "session_id", name="uq_appointment_session"),
        CheckConstraint("duration_minutes IN (30,60)", name="duration"),
        CheckConstraint("ends_at > starts_at", name="interval"),
        CheckConstraint(
            "ends_at - starts_at = duration_minutes * INTERVAL '1 minute'", name="duration_match"
        ),
        ExcludeConstraint(
            ("practitioner_id", "="),
            (func.tstzrange(starts_at, ends_at, "[)"), "&&"),
            name="appointments_no_overlap",
            using="gist",
        ),
    )


class IdempotencyRecord(Identified, Created, Base):
    __tablename__ = "idempotency_records"
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    outcome_code: Mapped[str] = mapped_column(String(50))
    http_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict] = mapped_column(JSONB)
    appointment_id: Mapped[UUID | None] = mapped_column()
    __table_args__ = (
        ForeignKeyConstraint(
            ["appointment_id", "session_id"],
            ["appointments.id", "appointments.session_id"],
            name="fk_idempotency_appointment_owner",
        ),
        UniqueConstraint("session_id", "idempotency_key", name="uq_idempotency_session_key"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="request_hash"),
        CheckConstraint("http_status BETWEEN 100 AND 599", name="http_status"),
        CheckConstraint("length(idempotency_key) BETWEEN 1 AND 200", name="key_length"),
    )
