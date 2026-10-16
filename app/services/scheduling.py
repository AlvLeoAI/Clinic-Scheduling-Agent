"""Read-only PostgreSQL availability, independent of HTTP and provider APIs."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.db.models import Appointment, AppointmentType, Clinic, Practitioner, WeeklySchedule
from app.domain.scheduling import (
    CLINIC_TIMEZONE,
    Interval,
    PolicyViolation,
    candidate_slots,
    subtract_reservations,
    validate_start,
)


class SchedulingConfigurationError(ValueError):
    pass


class SlotUnavailable(PolicyViolation):
    pass


@dataclass(frozen=True)
class Candidate:
    clinic_id: UUID
    practitioner_id: UUID
    appointment_type_id: UUID
    duration_minutes: int
    interval: Interval


@dataclass(frozen=True)
class Availability:
    clinic_id: UUID
    practitioner_id: UUID
    appointment_type_id: UUID
    local_date: date
    clinic_timezone: str
    duration_minutes: int
    slots: list[Interval]


class SchedulingService:
    def __init__(self, db: Session, clock: Callable[[], datetime] = utc_now):
        self.db = db
        self.clock = clock

    def _selection(self, practitioner_id, appointment_type_id):
        practitioner = self.db.get(Practitioner, practitioner_id, populate_existing=True)
        appointment_type = self.db.get(AppointmentType, appointment_type_id, populate_existing=True)
        if practitioner is None or not practitioner.is_active:
            raise PolicyViolation("A valid active practitioner is required.")
        if appointment_type is None or not appointment_type.is_active:
            raise PolicyViolation("A valid active appointment type is required.")
        if appointment_type.clinic_id != practitioner.clinic_id:
            raise PolicyViolation("The practitioner and appointment type must share a clinic.")
        clinic = self.db.get(Clinic, practitioner.clinic_id, populate_existing=True)
        if clinic is None or clinic.timezone != CLINIC_TIMEZONE:
            raise SchedulingConfigurationError("Clinic scheduling configuration is unavailable.")
        return clinic, appointment_type

    def candidate(
        self,
        *,
        local_date: date,
        local_time: time,
        practitioner_id: UUID,
        appointment_type_id: UUID,
        now_utc: datetime,
        expected_duration: int | None = None,
        exclude_appointment_id: UUID | None = None,
    ) -> Candidate:
        with self.db.no_autoflush:
            clinic, appointment_type = self._selection(practitioner_id, appointment_type_id)
            if (
                expected_duration is not None
                and appointment_type.duration_minutes != expected_duration
            ):
                raise PolicyViolation("Appointment type changed; a new proposal is required.")
            schedule = self.db.scalar(
                select(WeeklySchedule)
                .where(
                    WeeklySchedule.practitioner_id == practitioner_id,
                    WeeklySchedule.weekday == local_date.isoweekday(),
                )
                .execution_options(populate_existing=True)
            )
            if schedule is None:
                raise PolicyViolation("The clinic has no working schedule for this date.")
            interval = validate_start(
                local_date,
                local_time,
                opens_at=schedule.opens_at,
                closes_at=schedule.closes_at,
                duration_minutes=appointment_type.duration_minutes,
                now_utc=now_utc,
            )
            occupied = select(Appointment.id).where(
                Appointment.practitioner_id == practitioner_id,
                Appointment.starts_at < interval.ends_at,
                Appointment.ends_at > interval.starts_at,
            )
            if exclude_appointment_id is not None:
                occupied = occupied.where(Appointment.id != exclude_appointment_id)
            taken = self.db.scalar(occupied.limit(1))
            if taken is not None:
                raise SlotUnavailable("The requested interval is no longer available.")
            return Candidate(
                clinic.id,
                practitioner_id,
                appointment_type_id,
                appointment_type.duration_minutes,
                interval,
            )

    def availability(
        self, *, local_date: date, practitioner_id: UUID, appointment_type_id: UUID
    ) -> Availability:
        # Avoid even an implicit flush if reused with a session containing pending work.
        with self.db.no_autoflush:
            clinic, appointment_type = self._selection(practitioner_id, appointment_type_id)
            schedule = self.db.scalar(
                select(WeeklySchedule).where(
                    WeeklySchedule.practitioner_id == practitioner_id,
                    WeeklySchedule.weekday == local_date.isoweekday(),
                )
            )
            slots = []
            if schedule is not None:
                slots = candidate_slots(
                    local_date,
                    opens_at=schedule.opens_at,
                    closes_at=schedule.closes_at,
                    duration_minutes=appointment_type.duration_minutes,
                    now_utc=self.clock(),
                )
            if slots:
                bookings = self.db.execute(
                    select(Appointment.starts_at, Appointment.ends_at).where(
                        Appointment.practitioner_id == practitioner_id,
                        Appointment.starts_at < slots[-1].ends_at,
                        Appointment.ends_at > slots[0].starts_at,
                    )
                ).all()
                slots = subtract_reservations(slots, [Interval(*row) for row in bookings])
            return Availability(
                clinic_id=clinic.id,
                practitioner_id=practitioner_id,
                appointment_type_id=appointment_type_id,
                local_date=local_date,
                clinic_timezone=clinic.timezone,
                duration_minutes=appointment_type.duration_minutes,
                slots=slots,
            )
