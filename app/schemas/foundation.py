from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SessionCreateRequest(Contract):
    pass


class SessionResponse(Contract):
    session_id: UUID
    session_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_at: AwareDatetime
    trace_id: UUID


class ClinicCatalog(Contract):
    id: UUID
    name: str
    timezone: str


class PractitionerCatalog(Contract):
    id: UUID
    display_name: str


class AppointmentTypeCatalog(Contract):
    id: UUID
    code: str
    duration_minutes: Literal[30, 60]


class CatalogResponse(Contract):
    clinic: ClinicCatalog
    practitioners: list[PractitionerCatalog]
    appointment_types: list[AppointmentTypeCatalog]
    trace_id: UUID


class HealthResponse(Contract):
    status: Literal["ok"]
    database: Literal["ok"]
    trace_id: UUID


class ErrorDetail(Contract):
    code: str
    message: str
    retryable: bool


class ErrorResponse(Contract):
    error: ErrorDetail
    trace_id: UUID
