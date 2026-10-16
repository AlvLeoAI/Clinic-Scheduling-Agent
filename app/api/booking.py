"""Explicit HTTP confirmation only; ownership is derived from the bearer."""

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.auth import require_session
from app.db.models import ChatSession
from app.db.session import get_db
from app.schemas.booking import (
    AlreadyConfirmedResponse,
    AppointmentResponse,
    EmptyConfirmationRequest,
    ProposalRequest,
    ProposalResponse,
)
from app.schemas.foundation import ErrorResponse
from app.services.booking import BookingService, Outcome

router = APIRouter(prefix="/api/v1")
errors = {status: {"model": ErrorResponse} for status in (401, 404, 409, 410, 422, 503)}
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"^[!-~]+$")
]


class ReplayJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(
            content, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")


def result_response(request: Request, result: Outcome):
    # Replay preserves the durable body, status and original response trace.
    request.state.response_trace_id = result.body["trace_id"]
    request.state.outcome_code = result.body.get("error", {}).get(
        "code", result.body.get("status", "PENDING")
    )
    return ReplayJSONResponse(
        status_code=result.status,
        content=result.body,
        headers={"X-Trace-ID": result.body["trace_id"]},
    )


@router.post(
    "/proposals",
    response_model=ProposalResponse,
    status_code=201,
    responses={**errors, 200: {"model": ProposalResponse}},
)
def create_proposal(
    request: Request,
    payload: ProposalRequest,
    owner: ChatSession = Depends(require_session),
    db: Session = Depends(get_db),
):
    result = BookingService(db, request.app.state.clock).create_proposal(
        owner.id, payload, request.state.trace_id
    )
    return result_response(request, result)


@router.get("/proposals/{id}", response_model=ProposalResponse, responses=errors)
def get_proposal(
    request: Request,
    id: UUID,
    owner: ChatSession = Depends(require_session),
    db: Session = Depends(get_db),
):
    result = BookingService(db, request.app.state.clock).get_proposal(
        owner.id, id, request.state.trace_id
    )
    return result_response(request, result)


@router.post(
    "/proposals/{id}/confirm",
    response_model=AppointmentResponse,
    status_code=201,
    responses={**errors, 409: {"model": ErrorResponse | AlreadyConfirmedResponse}},
)
def confirm_proposal(
    request: Request,
    id: UUID,
    key: IdempotencyKey,
    payload: EmptyConfirmationRequest = Body(default=EmptyConfirmationRequest()),
    owner: ChatSession = Depends(require_session),
    db: Session = Depends(get_db),
):
    result = BookingService(db, request.app.state.clock).confirm(
        owner.id, id, key, request.state.trace_id
    )
    return result_response(request, result)


@router.get("/appointments/{id}", response_model=AppointmentResponse, responses=errors)
def get_appointment(
    request: Request,
    id: UUID,
    owner: ChatSession = Depends(require_session),
    db: Session = Depends(get_db),
):
    result = BookingService(db, request.app.state.clock).get_appointment(
        owner.id, id, request.state.trace_id
    )
    return result_response(request, result)
