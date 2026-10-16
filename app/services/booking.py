"""Short PostgreSQL transactions; success is returned only after commit completes."""

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.errors import ApiError
from app.db.models import Appointment, BookingProposal, ChatSession, IdempotencyRecord
from app.domain.proposals import PROPOSAL_TTL, transition
from app.domain.scheduling import CLINIC_TIMEZONE, CLINIC_ZONE, PolicyViolation, as_utc
from app.schemas.booking import AlreadyConfirmedResponse, AppointmentResponse, ProposalResponse
from app.schemas.foundation import ErrorDetail, ErrorResponse
from app.services.scheduling import SchedulingConfigurationError, SchedulingService, SlotUnavailable

logger = logging.getLogger("clinic.requests")


class ExpiredDuringConfirmation(ValueError):
    pass


@dataclass(frozen=True)
class Outcome:
    status: int
    body: dict


def confirmation_fingerprint(session_id: UUID, proposal_id: UUID) -> str:
    canonical = json.dumps(
        {
            "operation": "confirm",
            "version": 1,
            "session_id": str(session_id),
            "proposal_id": str(proposal_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class BookingService:
    def __init__(self, db: Session, clock: Callable[[], datetime] = utc_now):
        self.db = db
        self.clock = clock

    def _transaction(self, operation, *, confirmation=False):
        # The auth SELECT may already have started this request's transaction.
        # This service owns that unit of work, including its commit/rollback.
        for attempt in range(3):
            try:
                outcome = operation()
                self.db.commit()
                return outcome
            except SQLAlchemyError as exc:
                self.db.rollback()
                code = getattr(getattr(exc, "orig", None), "sqlstate", None)
                if code in {"40P01", "40001"} and attempt < 2:
                    continue
                message = (
                    "Confirmation outcome is not established. Retry with the same Idempotency-Key."
                    if confirmation
                    else "Database unavailable; no result is established."
                )
                raise ApiError(503, "SERVICE_UNAVAILABLE", message, True) from None
            except Exception:
                self.db.rollback()
                raise

    def _session(self, session_id):
        row = self.db.scalar(
            select(ChatSession)
            .where(ChatSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.expires_at <= as_utc(self.clock()):
            raise ApiError(401, "UNAUTHORIZED", "A valid session bearer is required.")
        return row

    def _proposal(self, session_id, proposal_id):
        row = self.db.scalar(
            select(BookingProposal)
            .where(
                BookingProposal.id == proposal_id,
                BookingProposal.session_id == session_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise ApiError(404, "PROPOSAL_NOT_FOUND", "Proposal not found.")
        return row

    def _expire(self, row, now):
        if row.status == "PENDING" and row.expires_at <= now:
            row.status = transition(row.status, "EXPIRED")

    def _proposal_body(self, row, trace_id):
        return ProposalResponse(
            proposal_id=row.id,
            session_id=row.session_id,
            clinic_id=row.clinic_id,
            practitioner_id=row.practitioner_id,
            appointment_type_id=row.appointment_type_id,
            duration_minutes=row.duration_minutes,
            starts_at=row.starts_at.astimezone(CLINIC_ZONE),
            ends_at=row.ends_at.astimezone(CLINIC_ZONE),
            clinic_timezone=CLINIC_TIMEZONE,
            created_at=row.created_at,
            expires_at=row.expires_at,
            status=row.status,
            trace_id=trace_id,
        ).model_dump(mode="json")

    def _appointment_body(self, row, trace_id):
        return AppointmentResponse(
            appointment_id=row.id,
            proposal_id=row.proposal_id,
            starts_at=row.starts_at.astimezone(CLINIC_ZONE),
            ends_at=row.ends_at.astimezone(CLINIC_ZONE),
            confirmed_at=row.confirmed_at,
            trace_id=trace_id,
        ).model_dump(mode="json")

    def _error(self, status, code, message, trace_id):
        return Outcome(
            status,
            ErrorResponse(
                error=ErrorDetail(code=code, message=message, retryable=False), trace_id=trace_id
            ).model_dump(mode="json"),
        )

    def create_proposal(self, session_id, payload, trace_id):
        def create():
            self._session(session_id)
            now = as_utc(self.clock())
            try:
                candidate = SchedulingService(self.db).candidate(
                    local_date=payload.local_date,
                    local_time=payload.local_time,
                    practitioner_id=payload.practitioner_id,
                    appointment_type_id=payload.appointment_type_id,
                    now_utc=now,
                )
            except SlotUnavailable:
                raise ApiError(
                    409, "SLOT_TAKEN", "The requested interval is no longer available."
                ) from None
            except PolicyViolation as exc:
                raise ApiError(422, "BUSINESS_RULE_VIOLATION", str(exc)) from None
            except SchedulingConfigurationError as exc:
                raise ApiError(503, "SERVICE_UNAVAILABLE", str(exc), True) from None
            pending = self.db.scalar(
                select(BookingProposal)
                .where(
                    BookingProposal.session_id == session_id,
                    BookingProposal.status == "PENDING",
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if pending is not None:
                self._expire(pending, now)
                same = (
                    pending.clinic_id == candidate.clinic_id
                    and pending.practitioner_id == candidate.practitioner_id
                    and pending.appointment_type_id == candidate.appointment_type_id
                    and pending.duration_minutes == candidate.duration_minutes
                    and pending.starts_at == candidate.interval.starts_at
                    and pending.ends_at == candidate.interval.ends_at
                )
                if pending.status == "PENDING" and same:
                    return Outcome(200, self._proposal_body(pending, trace_id))
                if pending.status == "PENDING":
                    pending.status = transition(pending.status, "SUPERSEDED")
                self.db.flush()  # Release partial uniqueness before inserting the replacement.
            row = BookingProposal(
                session_id=session_id,
                clinic_id=candidate.clinic_id,
                practitioner_id=candidate.practitioner_id,
                appointment_type_id=candidate.appointment_type_id,
                duration_minutes=candidate.duration_minutes,
                starts_at=candidate.interval.starts_at,
                ends_at=candidate.interval.ends_at,
                created_at=now,
                expires_at=now + PROPOSAL_TTL,
                status="PENDING",
            )
            self.db.add(row)
            self.db.flush()
            return Outcome(201, self._proposal_body(row, trace_id))

        return self._transaction(create)

    def get_proposal(self, session_id, proposal_id, trace_id):
        def get():
            self._session(session_id)
            row = self._proposal(session_id, proposal_id)
            self._expire(row, as_utc(self.clock()))
            return Outcome(200, self._proposal_body(row, trace_id))

        return self._transaction(get)

    def get_appointment(self, session_id, appointment_id, trace_id):
        def get():
            self._session(session_id)
            row = self.db.scalar(
                select(Appointment).where(
                    Appointment.id == appointment_id, Appointment.session_id == session_id
                )
            )
            if row is None:
                raise ApiError(404, "APPOINTMENT_NOT_FOUND", "Appointment not found.")
            return Outcome(200, self._appointment_body(row, trace_id))

        return self._transaction(get)

    def _insert_appointment(self, row, now):
        appointment = Appointment(
            proposal_id=row.id,
            session_id=row.session_id,
            practitioner_id=row.practitioner_id,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            duration_minutes=row.duration_minutes,
            confirmed_at=now,
        )
        self.db.add(appointment)
        self.db.flush()
        return appointment

    def confirm(self, session_id, proposal_id, key, trace_id):
        fingerprint = confirmation_fingerprint(session_id, proposal_id)

        def confirm_locked():
            self._session(session_id)
            row = self._proposal(session_id, proposal_id)
            existing = self.db.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.session_id == session_id,
                    IdempotencyRecord.idempotency_key == key,
                )
            )
            if existing is not None:
                if existing.request_hash != fingerprint:
                    return self._error(
                        409,
                        "IDEMPOTENCY_KEY_REUSED",
                        "The Idempotency-Key belongs to a different request.",
                        trace_id,
                    )
                return Outcome(existing.http_status, existing.response_body)
            now = as_utc(self.clock())
            self._expire(row, now)
            appointment_id = None
            if row.status == "CONFIRMED":
                appointment = self.db.scalar(
                    select(Appointment).where(Appointment.proposal_id == row.id)
                )
                if appointment is None:
                    raise ApiError(
                        503, "SERVICE_UNAVAILABLE", "Booking state is unavailable.", True
                    )
                appointment_id = appointment.id
                body = AlreadyConfirmedResponse(
                    error=ErrorDetail(
                        code="ALREADY_CONFIRMED",
                        message="Proposal is already confirmed.",
                        retryable=False,
                    ),
                    trace_id=trace_id,
                    appointment=self._appointment_body(appointment, trace_id),
                ).model_dump(mode="json")
                outcome = Outcome(409, body)
            elif row.status == "EXPIRED":
                outcome = self._error(410, "PROPOSAL_EXPIRED", "Proposal has expired.", trace_id)
            elif row.status == "SUPERSEDED":
                outcome = self._error(
                    409, "PROPOSAL_SUPERSEDED", "Proposal was superseded.", trace_id
                )
            elif row.status == "CONFLICTED":
                outcome = self._error(
                    409, "SLOT_TAKEN", "The requested interval is no longer available.", trace_id
                )
            else:
                outcome, appointment_id = self._confirm_pending(row, now, trace_id)
            self.db.add(
                IdempotencyRecord(
                    session_id=session_id,
                    idempotency_key=key,
                    request_hash=fingerprint,
                    outcome_code=outcome.body.get("error", {}).get("code", "CONFIRMED"),
                    http_status=outcome.status,
                    response_body=outcome.body,
                    appointment_id=appointment_id,
                    created_at=now,
                )
            )
            self.db.flush()
            return outcome

        return self._transaction(confirm_locked, confirmation=True)

    def _validate_snapshot(self, row, now, exclude_appointment_id=None):
        local_start = row.starts_at.astimezone(CLINIC_ZONE)
        candidate = SchedulingService(self.db).candidate(
            local_date=local_start.date(),
            local_time=local_start.time().replace(tzinfo=None),
            practitioner_id=row.practitioner_id,
            appointment_type_id=row.appointment_type_id,
            now_utc=now,
            expected_duration=row.duration_minutes,
            exclude_appointment_id=exclude_appointment_id,
        )
        if (
            candidate.clinic_id != row.clinic_id
            or candidate.interval.starts_at != row.starts_at
            or candidate.interval.ends_at != row.ends_at
        ):
            raise PolicyViolation("Booking details changed; a new proposal is required.")

    def _confirm_pending(self, row, now, trace_id):
        try:
            self._validate_snapshot(row, now)
        except SlotUnavailable:
            row.status = transition(row.status, "CONFLICTED")
            return self._error(
                409, "SLOT_TAKEN", "The requested interval is no longer available.", trace_id
            ), None
        except PolicyViolation as exc:
            return self._error(422, "BUSINESS_RULE_VIOLATION", str(exc), trace_id), None
        except SchedulingConfigurationError as exc:
            raise ApiError(503, "SERVICE_UNAVAILABLE", str(exc), True) from None
        try:
            with self.db.begin_nested():
                appointment = self._insert_appointment(row, now)
                # A constraint wait may have consumed TTL/notice. Keep this
                # second validation inside the insert savepoint so rejection
                # removes the appointment, then records its durable outcome.
                decision_now = as_utc(self.clock())
                if row.expires_at <= decision_now:
                    raise ExpiredDuringConfirmation()
                self._validate_snapshot(row, decision_now, appointment.id)
                appointment.confirmed_at = decision_now
                self.db.flush()
        except ExpiredDuringConfirmation:
            row.status = transition(row.status, "EXPIRED")
            return self._error(410, "PROPOSAL_EXPIRED", "Proposal has expired.", trace_id), None
        except SlotUnavailable:
            row.status = transition(row.status, "CONFLICTED")
            return self._error(
                409, "SLOT_TAKEN", "The requested interval is no longer available.", trace_id
            ), None
        except PolicyViolation as exc:
            return self._error(422, "BUSINESS_RULE_VIOLATION", str(exc), trace_id), None
        except SchedulingConfigurationError as exc:
            raise ApiError(503, "SERVICE_UNAVAILABLE", str(exc), True) from None
        except IntegrityError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None)
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if sqlstate != "23P01" or constraint != "appointments_no_overlap":
                raise
            logger.info(
                json.dumps(
                    {
                        "event": "booking_conflict",
                        "trace_id": str(trace_id),
                        "sqlstate": sqlstate,
                        "constraint": constraint,
                    }
                )
            )
            row.status = transition(row.status, "CONFLICTED")
            return self._error(
                409, "SLOT_TAKEN", "The requested interval is no longer available.", trace_id
            ), None
        row.status = transition(row.status, "CONFIRMED")
        return Outcome(201, self._appointment_body(appointment, trace_id)), appointment.id
