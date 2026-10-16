"""foundation

Revision ID: 0001
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Install the UUID GiST operator class before creating the exclusion constraint.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "chat_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_turn_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_fence", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_chat_sessions_token_hash")
        ),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_chat_sessions_expiry")),
        sa.CheckConstraint("lease_fence >= 0", name=op.f("ck_chat_sessions_lease_fence")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_chat_sessions_token_hash")),
    )
    op.create_table(
        "clinics",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinics")),
    )
    op.create_table(
        "appointment_types",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "duration_minutes IN (30,60)", name=op.f("ck_appointment_types_duration")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_appointment_types_clinic_id_clinics")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment_types")),
        sa.UniqueConstraint("clinic_id", "code", name="uq_type_clinic_code"),
        sa.UniqueConstraint("id", "clinic_id", name="uq_type_clinic"),
    )
    op.create_table(
        "chat_turns",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("client_message_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assistant_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_chat_turns_request_hash")
        ),
        sa.CheckConstraint(
            "status IN ('IN_PROGRESS','COMPLETED','FAILED')", name=op.f("ck_chat_turns_status")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_chat_turns_session_id_chat_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_turns")),
        sa.UniqueConstraint("id", "session_id", name="uq_turn_session"),
        sa.UniqueConstraint("session_id", "client_message_id", name="uq_turn_session_message"),
    )
    op.create_table(
        "practitioners",
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_practitioners_clinic_id_clinics")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practitioners")),
        sa.UniqueConstraint("id", "clinic_id", name="uq_practitioner_clinic"),
    )
    op.create_table(
        "booking_proposals",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("clinic_id", sa.Uuid(), nullable=False),
        sa.Column("practitioner_id", sa.Uuid(), nullable=False),
        sa.Column("appointment_type_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_turn_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ends_at - starts_at = duration_minutes * INTERVAL '1 minute'",
            name=op.f("ck_booking_proposals_duration_match"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','CONFIRMED','CONFLICTED','EXPIRED','SUPERSEDED')",
            name=op.f("ck_booking_proposals_status"),
        ),
        sa.CheckConstraint(
            "duration_minutes IN (30,60)", name=op.f("ck_booking_proposals_duration")
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_booking_proposals_interval")),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_booking_proposals_expiry")),
        sa.ForeignKeyConstraint(
            ["appointment_type_id", "clinic_id"],
            ["appointment_types.id", "appointment_types.clinic_id"],
            name="fk_proposal_type_clinic",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.id"], name=op.f("fk_booking_proposals_clinic_id_clinics")
        ),
        sa.ForeignKeyConstraint(
            ["practitioner_id", "clinic_id"],
            ["practitioners.id", "practitioners.clinic_id"],
            name="fk_proposal_practitioner_clinic",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_booking_proposals_session_id_chat_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["source_turn_id", "session_id"],
            ["chat_turns.id", "chat_turns.session_id"],
            name="fk_proposal_turn_owner",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_proposals")),
        sa.UniqueConstraint(
            "id",
            "session_id",
            "practitioner_id",
            "starts_at",
            "ends_at",
            "duration_minutes",
            name="uq_proposal_booking_snapshot",
        ),
        sa.UniqueConstraint("source_turn_id", name=op.f("uq_booking_proposals_source_turn_id")),
    )
    op.create_index(
        "uq_proposal_pending_session",
        "booking_proposals",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_table(
        "conversation_items",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("call_id", sa.String(length=200), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("sequence >= 0", name=op.f("ck_conversation_items_sequence")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_conversation_items_session_id_chat_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["turn_id", "session_id"],
            ["chat_turns.id", "chat_turns.session_id"],
            name="fk_item_turn_owner",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_items")),
        sa.UniqueConstraint("turn_id", "sequence", name="uq_item_turn_sequence"),
    )
    op.create_index(
        "uq_item_turn_call",
        "conversation_items",
        ["turn_id", "call_id", "item_type"],
        unique=True,
        postgresql_where=sa.text("call_id IS NOT NULL"),
    )
    op.create_table(
        "weekly_schedules",
        sa.Column("practitioner_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("opens_at", sa.Time(), nullable=False),
        sa.Column("closes_at", sa.Time(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("opens_at < closes_at", name=op.f("ck_weekly_schedules_hours")),
        sa.CheckConstraint("weekday BETWEEN 1 AND 7", name=op.f("ck_weekly_schedules_weekday")),
        sa.ForeignKeyConstraint(
            ["practitioner_id"],
            ["practitioners.id"],
            name=op.f("fk_weekly_schedules_practitioner_id_practitioners"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weekly_schedules")),
        sa.UniqueConstraint("practitioner_id", "weekday", name="uq_schedule_practitioner_day"),
    )
    op.create_table(
        "appointments",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("practitioner_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        postgresql.ExcludeConstraint(
            (sa.column("practitioner_id"), "="),
            (sa.text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            using="gist",
            name="appointments_no_overlap",
        ),
        sa.CheckConstraint(
            "ends_at - starts_at = duration_minutes * INTERVAL '1 minute'",
            name=op.f("ck_appointments_duration_match"),
        ),
        sa.CheckConstraint("duration_minutes IN (30,60)", name=op.f("ck_appointments_duration")),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_appointments_interval")),
        sa.ForeignKeyConstraint(
            ["practitioner_id"],
            ["practitioners.id"],
            name=op.f("fk_appointments_practitioner_id_practitioners"),
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_appointments_session_id_chat_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
        sa.UniqueConstraint("id", "session_id", name="uq_appointment_session"),
        sa.UniqueConstraint("proposal_id", name=op.f("uq_appointments_proposal_id")),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("outcome_code", sa.String(length=50), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("appointment_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_idempotency_records_request_hash")
        ),
        sa.CheckConstraint(
            "http_status BETWEEN 100 AND 599", name=op.f("ck_idempotency_records_http_status")
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 200",
            name=op.f("ck_idempotency_records_key_length"),
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id", "session_id"],
            ["appointments.id", "appointments.session_id"],
            name="fk_idempotency_appointment_owner",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_idempotency_records_session_id_chat_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_records")),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_idempotency_session_key"),
    )
    # Break the session/turn FK cycle explicitly, after both tables exist.
    op.create_foreign_key(
        "fk_session_active_turn_owner",
        "chat_sessions",
        "chat_turns",
        ["active_turn_id", "id"],
        ["id", "session_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_session_active_turn_owner", "chat_sessions", type_="foreignkey")
    op.drop_table("idempotency_records")
    op.drop_table("appointments")
    op.drop_table("weekly_schedules")
    op.drop_index(
        "uq_item_turn_call",
        table_name="conversation_items",
        postgresql_where=sa.text("call_id IS NOT NULL"),
    )
    op.drop_table("conversation_items")
    op.drop_index(
        "uq_proposal_pending_session",
        table_name="booking_proposals",
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.drop_table("booking_proposals")
    op.drop_table("practitioners")
    op.drop_table("chat_turns")
    op.drop_table("appointment_types")
    op.drop_table("clinics")
    op.drop_table("chat_sessions")
    # Retain btree_gist: it may have pre-existed or be used by other schemas.
