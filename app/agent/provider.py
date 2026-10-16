"""Responses REST adapter with an injectable transport; no SDK or live call at startup."""

from typing import Protocol

import httpx

from app.agent.protocol import ProviderFailure, ProviderResponse
from app.core.config import Settings


class ResponsesProvider(Protocol):
    def respond(self, payload: dict) -> ProviderResponse: ...


class HttpResponsesProvider:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def respond(self, payload: dict) -> ProviderResponse:
        key = self.settings.openai_api_key
        if (
            not self.settings.enable_live_openai
            or not self.settings.openai_model
            or key is None
            or not key.get_secret_value()
        ):
            raise ProviderFailure("The agent provider is not enabled/configured.")
        try:
            with httpx.Client(
                timeout=self.settings.provider_timeout_seconds,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = client.post(
                    "https://api.openai.com/v1/responses",
                    json=payload,
                    headers={"Authorization": "Bearer " + key.get_secret_value()},
                )
                response.raise_for_status()
                if len(response.content) > 1_048_576:
                    raise ProviderFailure("Provider output exceeds the transport bound.")
                return ProviderResponse.model_validate(response.json())
        except Exception:
            # Never include HTTP request headers, provider error bodies or exceptions.
            raise ProviderFailure("The provider response could not be established.") from None
