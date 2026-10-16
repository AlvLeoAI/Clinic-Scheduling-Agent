"""Three typed tools only. Session and turn identities never come from model arguments."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BeforeValidator, Field, ValidationError
from sqlalchemy import select

from app.core.errors import ApiError
from app.db.models import AppointmentType, BookingProposal, Clinic, Practitioner
from app.domain.scheduling import CLINIC_ZONE, PolicyViolation
from app.schemas.booking import ProposalRequest, ProposalResponse
from app.schemas.foundation import (
    AppointmentTypeCatalog,
    ClinicCatalog,
    Contract,
    ErrorDetail,
    PractitionerCatalog,
)
from app.schemas.scheduling import AvailabilityResponse, AvailabilitySlot, parse_local_date
from app.services.booking import BookingService
from app.services.scheduling import SchedulingConfigurationError, SchedulingService

TOOL_NAMES = ("get_clinic_catalog", "check_availability", "create_booking_proposal")


class CatalogArguments(Contract):
    pass


class AvailabilityArguments(Contract):
    local_date: Annotated[date, BeforeValidator(parse_local_date)]
    practitioner_id: UUID
    appointment_type_id: UUID


class ToolCatalog(Contract):
    clinic: ClinicCatalog
    practitioners: list[PractitionerCatalog] = Field(max_length=2)
    appointment_types: list[AppointmentTypeCatalog] = Field(max_length=2)


class ToolProposal(Contract):
    proposal_id: UUID
    practitioner_id: UUID
    appointment_type_id: UUID
    duration_minutes: Literal[30, 60]
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    clinic_timezone: Literal["America/Chicago"]
    expires_at: AwareDatetime
    status: Literal["PENDING", "CONFIRMED", "CONFLICTED", "EXPIRED", "SUPERSEDED"]


class ToolFailure(Contract):
    ok: Literal[False] = False
    error: ErrorDetail


class CatalogResult(Contract):
    ok: Literal[True]
    data: ToolCatalog


class AvailabilityResult(Contract):
    ok: Literal[True]
    data: AvailabilityResponse


class ProposalResult(Contract):
    ok: Literal[True]
    data: ToolProposal


RESULT_MODELS = dict(zip(TOOL_NAMES, (CatalogResult, AvailabilityResult, ProposalResult)))


def validate_result(name, value):
    try:
        model = ToolFailure if value.get("ok") is False else RESULT_MODELS[name]
        return model.model_validate(value).model_dump(mode="json")
    except (ValidationError, KeyError, AttributeError):
        raise ValueError("Tool result failed application validation.") from None


INPUT_MODELS = dict(zip(TOOL_NAMES, (CatalogArguments, AvailabilityArguments, ProposalRequest)))


def failure(code, message, retryable=False):
    return ToolFailure(
        error=ErrorDetail(code=code, message=message, retryable=retryable)
    ).model_dump(mode="json")


def tool_definitions():
    descriptions = (
        "Read the synthetic clinic catalog and machine IDs.",
        "Read available intervals for an explicit date, practitioner and appointment type.",
        "Create an unconfirmed proposal for this authenticated session; never confirms a booking.",
    )
    definitions = []
    for name, description in zip(TOOL_NAMES, descriptions):
        schema = INPUT_MODELS[name].model_json_schema()
        schema.setdefault("required", list(schema["properties"]))
        definitions.append(
            {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": schema,
                "strict": True,
            }
        )
    return definitions


def validate_arguments(name: str, arguments: str):
    if name not in INPUT_MODELS:
        return None, failure("TOOL_NOT_ALLOWED", "The requested tool is not permitted.")
    try:
        return INPUT_MODELS[name].model_validate_json(arguments), None
    except (ValidationError, ValueError):
        return None, failure("INVALID_TOOL_ARGUMENTS", "Tool arguments failed validation.")


def execute_tool(name, arguments, db, session_id, turn_id, trace_id, clock):
    try:
        if name == "get_clinic_catalog":
            clinic = db.scalar(select(Clinic).order_by(Clinic.id).limit(1))
            if clinic is None:
                raise ApiError(
                    503, "SERVICE_UNAVAILABLE", "Synthetic catalog is unavailable.", True
                )
            value = ToolCatalog(
                clinic=ClinicCatalog.model_validate(clinic),
                practitioners=[
                    PractitionerCatalog.model_validate(row)
                    for row in db.scalars(
                        select(Practitioner)
                        .where(
                            Practitioner.clinic_id == clinic.id, Practitioner.is_active.is_(True)
                        )
                        .order_by(Practitioner.id)
                    )
                ],
                appointment_types=[
                    AppointmentTypeCatalog.model_validate(row)
                    for row in db.scalars(
                        select(AppointmentType)
                        .where(
                            AppointmentType.clinic_id == clinic.id,
                            AppointmentType.is_active.is_(True),
                        )
                        .order_by(AppointmentType.id)
                    )
                ],
            )
        elif name == "check_availability":
            result = SchedulingService(db, clock).availability(
                local_date=arguments.local_date,
                practitioner_id=arguments.practitioner_id,
                appointment_type_id=arguments.appointment_type_id,
            )
            value = AvailabilityResponse(
                clinic_id=result.clinic_id,
                practitioner_id=result.practitioner_id,
                appointment_type_id=result.appointment_type_id,
                date=result.local_date,
                clinic_timezone=result.clinic_timezone,
                duration_minutes=result.duration_minutes,
                slots=[
                    AvailabilitySlot(
                        starts_at=row.starts_at.astimezone(CLINIC_ZONE),
                        ends_at=row.ends_at.astimezone(CLINIC_ZONE),
                    )
                    for row in result.slots
                ],
                trace_id=trace_id,
            )
        elif name == "create_booking_proposal":
            outcome = BookingService(db, clock).create_proposal(session_id, arguments, trace_id)
            snapshot = ProposalResponse.model_validate(outcome.body)
            if outcome.status == 201:
                row = db.get(BookingProposal, snapshot.proposal_id)
                row.source_turn_id = turn_id
                db.flush()
            full = snapshot.model_dump(mode="json")
            value = ToolProposal.model_validate(
                {field: full[field] for field in ToolProposal.model_fields}
            )
        else:
            return failure("TOOL_NOT_ALLOWED", "The requested tool is not permitted.")
        return {"ok": True, "data": value.model_dump(mode="json")}
    except ApiError as exc:
        return failure(exc.code, exc.message, exc.retryable)
    except PolicyViolation as exc:
        return failure("BUSINESS_RULE_VIOLATION", str(exc))
    except SchedulingConfigurationError:
        return failure("SERVICE_UNAVAILABLE", "Scheduling configuration is unavailable.", True)
    except ValidationError:
        return failure("INVALID_TOOL_RESULT", "Tool output failed validation.")
