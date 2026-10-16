from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.booking import ProposalResponse
from app.schemas.foundation import Contract, ErrorResponse


class ChatRequest(Contract):
    client_message_id: UUID
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("A non-empty message is required.")
        return value


class ChatResponse(Contract):
    turn_id: UUID
    assistant_message: str = Field(max_length=8000)
    proposal: ProposalResponse | None
    trace_id: UUID


class ChatFailureResponse(ErrorResponse):
    turn_id: UUID
    proposal: ProposalResponse | None
