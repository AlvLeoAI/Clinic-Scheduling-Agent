from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.agent.provider import build_provider
from app.api.auth import require_session
from app.api.booking import ReplayJSONResponse
from app.core.errors import ApiError
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
        501: {"model": ErrorResponse, "description": "No agent provider is configured"},
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
    provider = factory() if factory is not None else build_provider(settings)
    if provider is None:
        # Checked before any turn is claimed: no state is written, and the same
        # client_message_id is processed normally once a provider is configured.
        raise ApiError(
            501,
            "AGENT_PROVIDER_DISABLED",
            "Chat is disabled on this server: no agent provider is configured.",
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
