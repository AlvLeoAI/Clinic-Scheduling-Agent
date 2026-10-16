import re
from datetime import date as LocalDate
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BeforeValidator

from app.schemas.foundation import Contract


def parse_local_date(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return LocalDate.fromisoformat(value)
    if type(value) is LocalDate:
        return value
    raise ValueError("An unambiguous YYYY-MM-DD clinic-local date is required.")


class AvailabilityRequest(Contract):
    date: Annotated[LocalDate, BeforeValidator(parse_local_date)]
    practitioner_id: UUID
    appointment_type_id: UUID


class AvailabilitySlot(Contract):
    starts_at: AwareDatetime
    ends_at: AwareDatetime


class AvailabilityResponse(Contract):
    clinic_id: UUID
    practitioner_id: UUID
    appointment_type_id: UUID
    date: LocalDate
    clinic_timezone: Literal["America/Chicago"]
    duration_minutes: Literal[30, 60]
    slots: list[AvailabilitySlot]
    trace_id: UUID
