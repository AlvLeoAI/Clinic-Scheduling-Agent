from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.agent.provider import HttpResponsesProvider, build_provider
from app.api.auth import require_session
from app.api.booking import ReplayJSONResponse
from app.db.models import ChatSession
from app.db.session import get_db
from app.schemas.chat import ChatFailureResponse, ChatRequest, ChatResponse
from app.schemas.foundation import ErrorResponse
from app.services.chat import ChatService

router = APIRouter(prefix="/api/v1")
PROVIDER_HEADER = {
    "X-Agent-Provider": {
        "description": "Agent provider configured when this response was served.",
        "schema": {"type": "string", "enum": ["demo", "openai"]},
    }
}


@router.post(
    "/chat/messages",
    response_model=ChatResponse,
    responses={
        200: {"headers": PROVIDER_HEADER},
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse | ChatFailureResponse},
        503: {"model": ChatFailureResponse, "headers": PROVIDER_HEADER},
    },
)
def chat_message(
    request: Request,
    payload: ChatRequest,
    owner: ChatSession = Depends(require_session),
    db: Session = Depends(get_db),
):
    owner_id = owner.id
    # Release the auth SELECT transaction before claiming or contacting a provider.
    db.rollback()
    settings = request.app.state.settings
    factory = request.app.state.provider_factory
    provider = (
        factory()
        if factory is not None
        else build_provider(settings) or HttpResponsesProvider(settings)
    )
    status, body = ChatService(
        request.app.state.engine, settings, request.app.state.clock, provider
    ).handle(owner_id, payload, request.state.trace_id)
    request.state.response_trace_id = body["trace_id"]
    request.state.outcome_code = body.get("error", {}).get("code", "COMPLETED")
    headers = {"X-Trace-ID": body["trace_id"]}
    name = getattr(provider, "name", None)
    if name is not None:
        headers["X-Agent-Provider"] = name
    return ReplayJSONResponse(status_code=status, content=body, headers=headers)
