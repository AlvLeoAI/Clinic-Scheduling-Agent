import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.auth import token_hash
from app.core.errors import ApiError
from app.db.models import AppointmentType, ChatSession, Clinic, Practitioner
from app.db.session import get_db
from app.domain.scheduling import CLINIC_ZONE, PolicyViolation
from app.schemas.foundation import (
    AppointmentTypeCatalog,
    CatalogResponse,
    ClinicCatalog,
    ErrorResponse,
    HealthResponse,
    PractitionerCatalog,
    SessionCreateRequest,
    SessionResponse,
)
from app.schemas.scheduling import AvailabilityRequest, AvailabilityResponse, AvailabilitySlot
from app.services.scheduling import SchedulingConfigurationError, SchedulingService

router = APIRouter(prefix="/api/v1")
error_docs = {
    422: {"model": ErrorResponse, "description": "Sanitized validation error"},
    503: {"model": ErrorResponse, "description": "Sanitized service/database error"},
}


@router.post("/sessions", response_model=SessionResponse, status_code=201, responses=error_docs)
def create_session(
    request: Request,
    payload: SessionCreateRequest = Body(default=SessionCreateRequest()),
    db: Session = Depends(get_db),
) -> SessionResponse:
    token = secrets.token_urlsafe(32)
    now = request.app.state.clock()
    row = ChatSession(
        token_hash=token_hash(token),
        created_at=now,
        expires_at=now + timedelta(hours=request.app.state.settings.session_ttl_hours),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return SessionResponse(
        session_id=row.id,
        session_token=token,
        expires_at=row.expires_at,
        trace_id=request.state.trace_id,
    )


@router.get("/catalog", response_model=CatalogResponse, responses=error_docs)
def catalog(request: Request, db: Session = Depends(get_db)) -> CatalogResponse:
    clinic = db.scalar(select(Clinic).order_by(Clinic.id).limit(1))
    if clinic is None:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "Synthetic catalog is not initialized.", True)
    practitioners = db.scalars(
        select(Practitioner)
        .where(Practitioner.clinic_id == clinic.id, Practitioner.is_active.is_(True))
        .order_by(Practitioner.id)
    ).all()
    types = db.scalars(
        select(AppointmentType)
        .where(AppointmentType.clinic_id == clinic.id, AppointmentType.is_active.is_(True))
        .order_by(AppointmentType.id)
    ).all()
    return CatalogResponse(
        clinic=ClinicCatalog.model_validate(clinic),
        practitioners=[PractitionerCatalog.model_validate(row) for row in practitioners],
        appointment_types=[AppointmentTypeCatalog.model_validate(row) for row in types],
        trace_id=request.state.trace_id,
    )


@router.get("/health", response_model=HealthResponse, responses=error_docs)
def health(request: Request, db: Session = Depends(get_db)) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(status="ok", database="ok", trace_id=request.state.trace_id)


@router.get("/availability", response_model=AvailabilityResponse, responses=error_docs)
def availability(
    request: Request,
    query: Annotated[AvailabilityRequest, Query()],
    db: Session = Depends(get_db),
) -> AvailabilityResponse:
    try:
        result = SchedulingService(db, clock=request.app.state.clock).availability(
            local_date=query.date,
            practitioner_id=query.practitioner_id,
            appointment_type_id=query.appointment_type_id,
        )
    except PolicyViolation as exc:
        raise ApiError(422, "BUSINESS_RULE_VIOLATION", str(exc)) from None
    except SchedulingConfigurationError as exc:
        raise ApiError(503, "SERVICE_UNAVAILABLE", str(exc), True) from None
    return AvailabilityResponse(
        clinic_id=result.clinic_id,
        practitioner_id=result.practitioner_id,
        appointment_type_id=result.appointment_type_id,
        date=result.local_date,
        clinic_timezone=result.clinic_timezone,
        duration_minutes=result.duration_minutes,
        slots=[
            AvailabilitySlot(
                starts_at=slot.starts_at.astimezone(CLINIC_ZONE),
                ends_at=slot.ends_at.astimezone(CLINIC_ZONE),
            )
            for slot in result.slots
        ],
        trace_id=request.state.trace_id,
    )
