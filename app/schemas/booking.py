import re
from datetime import date, time
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BeforeValidator

from app.domain.proposals import ProposalStatus
from app.schemas.foundation import Contract, ErrorResponse
from app.schemas.scheduling import parse_local_date


def parse_local_time(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{2}:[0-9]{2}", value):
        return time.fromisoformat(value)
    if type(value) is time and value.tzinfo is None:
        return value
    raise ValueError("An unambiguous HH:MM clinic-local time is required.")


class ProposalRequest(Contract):
    practitioner_id: UUID
    appointment_type_id: UUID
    local_date: Annotated[date, BeforeValidator(parse_local_date)]
    local_time: Annotated[time, BeforeValidator(parse_local_time)]


class EmptyConfirmationRequest(Contract):
    pass


class ProposalResponse(Contract):
    proposal_id: UUID
    session_id: UUID
    clinic_id: UUID
    practitioner_id: UUID
    appointment_type_id: UUID
    duration_minutes: Literal[30, 60]
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    clinic_timezone: Literal["America/Chicago"]
    created_at: AwareDatetime
    expires_at: AwareDatetime
    status: ProposalStatus
    trace_id: UUID


class AppointmentResponse(Contract):
    status: Literal["CONFIRMED"] = "CONFIRMED"
    appointment_id: UUID
    proposal_id: UUID
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    confirmed_at: AwareDatetime
    trace_id: UUID


class AlreadyConfirmedResponse(ErrorResponse):
    appointment: AppointmentResponse
