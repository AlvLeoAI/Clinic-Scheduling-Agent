"""Responses wire items are retained whole, including opaque reasoning content."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TOOL_CALLS = 5
MAX_COMPLETED_TURNS = 8
MAX_CONTEXT_CHARS = 24_000


class ProviderFailure(Exception):
    pass


class ProtocolFailure(ProviderFailure):
    pass


class FunctionCall(BaseModel):
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)
    type: Literal["function_call"]
    call_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    arguments: str = Field(max_length=4000)


class ProviderUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    total_tokens: int = Field(ge=0, strict=True)


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    status: Literal["completed"]
    output: list[dict] = Field(min_length=1, max_length=32)
    usage: ProviderUsage | None = None

    @field_validator("output")
    @classmethod
    def validate_items(cls, items):
        for item in items:
            kind = item.get("type")
            if kind == "function_call":
                FunctionCall.model_validate(item)
            elif kind == "reasoning":
                if not isinstance(item.get("summary", []), list):
                    raise ValueError("Invalid reasoning item.")
                encrypted = item.get("encrypted_content")
                if encrypted is not None and not isinstance(encrypted, str):
                    raise ValueError("Invalid reasoning item.")
            elif kind == "message":
                if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
                    raise ValueError("Invalid assistant item.")
                for content in item["content"]:
                    if content.get("type") not in {"output_text", "refusal"}:
                        raise ValueError("Unsupported assistant content.")
                    key = "text" if content["type"] == "output_text" else "refusal"
                    if not isinstance(content.get(key), str):
                        raise ValueError("Invalid assistant content.")
            else:
                raise ValueError("Unsupported provider item.")
        calls = [item for item in items if item.get("type") == "function_call"]
        if len(calls) > 1:
            raise ValueError("Parallel tool calls are not accepted.")
        return items
