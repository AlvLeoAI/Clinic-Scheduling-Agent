"""R2 smoke contracts and versioned, deliberately conservative admission estimates."""

import json
from decimal import Decimal
from typing import Literal

from pydantic import Field

from evaluations.contracts import Case, Contract


class SmokeDataset(Contract):
    version: str
    prompt_version: str
    clock: str
    catalog: dict
    cases: list[Case] = Field(min_length=5, max_length=5)


class RunConfig(Contract):
    model: Literal["gpt-6-luna"] = "gpt-6-luna"
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "none"
    max_requests: int = Field(default=25, ge=1, le=25)
    max_total_tokens: int = Field(default=250_000, ge=1, le=1_000_000)
    max_estimated_usd: Decimal = Field(default=Decimal("1"), gt=0, le=1)
    max_input_tokens: int = Field(default=32_768, ge=1, le=32_768)
    max_output_tokens: int = Field(default=2048, ge=256, le=4096)


PRICING = {
    "version": "gpt-6-luna-standard-2026-10-20-v1",
    "source": "https://developers.openai.com/api/docs/pricing",
    "model_source": "https://developers.openai.com/api/docs/models/gpt-6-luna",
    "verified_date": "2026-10-20",
    "short_context_limit": 272_000,
    "usd_per_million_input": "0.10",
    "usd_per_million_cached_input": "0.01",
    "usd_per_million_cache_write": "0.125",
    "usd_per_million_output": "0.50",
    "admission_input_rate": "0.125",
    "safety_multiplier": "2",
    "assumptions": "Standard tier, short text-only context; all input charged as cache writes, "
    "no cache discount, 2x margin. Estimate is not a provider billing guarantee.",
}


class BudgetStop(Exception):
    pass


class Ledger:
    """One ledger per RUN, never per scenario. Reservations are never refunded."""

    def __init__(self, config: RunConfig):
        self.config = config
        self.requests = self.reserved_tokens = self.actual_tokens = 0
        self.reserved_usd = Decimal("0")
        self.stop_reason = None

    def stop(self, reason):
        self.stop_reason = self.stop_reason or reason

    def admit(self, payload):
        if self.stop_reason:
            raise BudgetStop(self.stop_reason)
        # Full UTF-8 wire bytes plus protocol margin: deliberately larger than the
        # character context proxy. Not a certified model tokenizer/billing bound.
        inputs = len(json.dumps(payload, ensure_ascii=False).encode()) + 4096
        total = inputs + self.config.max_output_tokens
        price = (
            (
                (Decimal(inputs) * Decimal(PRICING["admission_input_rate"]))
                + Decimal(self.config.max_output_tokens)
                * Decimal(PRICING["usd_per_million_output"])
            )
            * Decimal(PRICING["safety_multiplier"])
            / 1_000_000
        )
        reason = None
        if self.requests >= self.config.max_requests:
            reason = "REQUEST_LIMIT"
        elif inputs > self.config.max_input_tokens:
            reason = "INPUT_LIMIT"
        elif self.reserved_tokens + total > self.config.max_total_tokens:
            reason = "TOKEN_LIMIT"
        elif self.reserved_usd + price > self.config.max_estimated_usd:
            reason = "ESTIMATED_SPEND_LIMIT"
        if reason:
            self.stop(reason)
            raise BudgetStop(reason)
        self.requests += 1
        self.reserved_tokens += total
        self.reserved_usd += price
        return {"input_tokens": inputs, "total_tokens": total, "estimated_usd": str(price)}

    def record_usage(self, usage, reservation):
        if usage is None:
            self.stop("USAGE_UNAVAILABLE")
            return
        self.actual_tokens += usage["total_tokens"]
        if (
            usage["input_tokens"] > reservation["input_tokens"]
            or usage["output_tokens"] > self.config.max_output_tokens
            or usage["total_tokens"] > reservation["total_tokens"]
            or self.actual_tokens > self.config.max_total_tokens
        ):
            self.stop("USAGE_EXCEEDS_RESERVATION")

    def report(self):
        return {
            "provider_requests": self.requests,
            "reserved_tokens": self.reserved_tokens,
            "observed_total_tokens": self.actual_tokens,
            "reserved_estimated_usd": str(self.reserved_usd),
            "stop_reason": self.stop_reason,
            "billing_guarantee": False,
        }
