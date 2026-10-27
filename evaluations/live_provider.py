"""Metered transport observes raw decisions BEFORE the existing REST adapter validates them."""

import copy
import hashlib
import json
import os
import re
from collections import deque
from time import perf_counter

import httpx
from pydantic import SecretStr

from app.agent.protocol import ProviderFailure, ProviderUsage
from app.agent.provider import HttpResponsesProvider
from app.agent.replies import reply_format
from app.agent.tools import tool_definitions
from evaluations.live_contracts import BudgetStop


class ObservedTransport(httpx.BaseTransport):
    def __init__(self, owner, delegate):
        self.owner, self.delegate = owner, delegate

    def handle_request(self, request):
        owner = self.owner
        payload = json.loads(request.content)
        try:
            reservation = owner.ledger.admit(payload)
        except BudgetStop:
            raise ProviderFailure("Run admission refused.") from None
        owner.requests.append({"session": "A", "payload": copy.deepcopy(payload)})
        evidence = {
            "source": "PROVIDER" if owner.live else "MOCKED",
            "request_number": owner.ledger.requests,
            "request_sha256": hashlib.sha256(request.content).hexdigest(),
            "reservation": reservation,
            "requested_model": payload["model"],
            "actual_model": None,
            "usage": None,
            "outcome": "transport_error",
            "http_status": None,
        }
        owner.events.append(evidence)
        started = perf_counter()
        try:
            response = self.delegate.handle_request(request)
            evidence["http_status"] = response.status_code
            response.read()
            if len(response.content) > 1_048_576:
                evidence["outcome"] = "oversized_response"
                owner.ledger.stop("PROVIDER_OVERSIZED")
                return response
            if response.status_code != 200:
                evidence["outcome"] = "http_error"
                owner.ledger.stop("PROVIDER_HTTP_ERROR")
                return response
            body = response.json()
            evidence["actual_model"] = (
                body.get("model")
                if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", str(body.get("model", "")))
                else None
            )
            owner.capture(body.get("output", []))
            usage = body.get("usage")
            if usage is not None:
                usage = ProviderUsage.model_validate(usage).model_dump()
                if usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
                    raise ValueError("Inconsistent usage.")
            evidence["usage"] = usage
            owner.ledger.record_usage(usage, reservation)
            # Capture even malformed or incomplete model decisions. Never export opaque
            # reasoning, headers, raw provider errors, credentials, or the full wire body.
            evidence["outcome"] = "completed" if body.get("status") == "completed" else "incomplete"
            if evidence["outcome"] != "completed":
                owner.ledger.stop("PROVIDER_INCOMPLETE")
            if evidence["actual_model"] != owner.config.model:
                owner.ledger.stop("MODEL_IDENTITY_UNVERIFIED")
            return response
        except httpx.TimeoutException:
            evidence["outcome"] = "timeout"
            owner.ledger.stop("PROVIDER_TIMEOUT")
            raise
        except Exception:
            owner.ledger.stop("PROVIDER_INVALID_OR_TRANSPORT_ERROR")
            raise ProviderFailure("Provider execution was not established.") from None
        finally:
            evidence["latency_ms"] = round((perf_counter() - started) * 1000, 3)
            if evidence["outcome"] != "completed":
                owner.errors.append({"session": "A", "kind": evidence["outcome"]})


class SmokeProvider:
    def __init__(self, case, settings, config, ledger, *, live=False, transport=None):
        if live and (
            os.environ.get("CLINIC_EVAL_ENABLE_LIVE") != "true"
            or settings.openai_api_key is None
            or not settings.openai_api_key.get_secret_value()
        ):
            raise ValueError("Live execution needs a separate opt-in and local credential.")
        if live and transport is not None:
            raise ValueError("Live mode cannot accept a test transport.")
        self.case, self.config, self.ledger = case, config, ledger
        self.requests, self.events, self.raw_calls, self.raw_plans, self.errors = [], [], [], [], []
        self.message_ids = {}
        self.steps = deque(case.script["A"])
        self.live = live
        # Offline ALWAYS installs MockTransport and discards the real local key.
        delegate = (
            httpx.HTTPTransport(retries=0)
            if live
            else (transport if transport is not None else httpx.MockTransport(self.fixture))
        )
        if not live and not isinstance(delegate, httpx.MockTransport):
            raise ValueError("Offline execution requires httpx.MockTransport.")
        runtime = settings.model_copy(
            update={
                "enable_live_openai": True,
                "openai_api_key": settings.openai_api_key
                if live
                else SecretStr("synthetic-protocol-credential"),
                "openai_model": config.model,
            }
        )
        self.delegate = delegate
        self.adapter = HttpResponsesProvider(runtime, ObservedTransport(self, delegate))

    def close(self):
        self.delegate.close()

    def respond(self, payload):
        if (
            payload.get("store") is not False
            or payload.get("parallel_tool_calls") is not False
            or payload.get("tools") != tool_definitions()
            or payload.get("text") != reply_format()
            or payload.get("tool_choice") not in {"auto", "none"}
        ):
            self.ledger.stop("REQUEST_CONTRACT")
            raise ProviderFailure("Evaluation request violates the reviewed contract.")
        request = copy.deepcopy(payload)
        request.update(
            model=self.config.model,
            reasoning={"effort": self.config.reasoning_effort},
            service_tier="default",
            max_output_tokens=self.config.max_output_tokens,
        )
        try:
            response = self.adapter.respond(request)
        except ProviderFailure:
            self.ledger.stop("PROVIDER_PROTOCOL_ERROR")
            if self.events and self.events[-1]["outcome"] == "completed":
                self.events[-1]["outcome"] = "protocol_error"
                self.errors.append({"session": "A", "kind": "protocol_error"})
            raise
        if self.ledger.stop_reason:
            raise ProviderFailure("Run halted after provider observation.")
        return response

    def capture(self, output):
        for item in output:
            if item.get("type") == "function_call":
                try:
                    args = json.loads(item.get("arguments", ""))
                except (ValueError, TypeError):
                    args = item.get("arguments")
                self.raw_calls.append(
                    {
                        "session": "A",
                        "name": item.get("name"),
                        "arguments": args,
                        "call_id": item.get("call_id"),
                        "client_message_id": "single-smoke-turn",
                    }
                )
            elif item.get("type") == "message":
                for content in item.get("content", []):
                    value = content.get("text", content.get("refusal", ""))
                    try:
                        value = json.loads(value)
                    except (ValueError, TypeError):
                        pass
                    self.raw_plans.append({"session": "A", "value": value})

    def fixture(self, request):
        if not self.steps:
            raise ProviderFailure("Smoke fixture exhausted.")
        step = self.steps.popleft()
        if "tool" in step:
            output = [
                {
                    "type": "function_call",
                    "call_id": f"smoke_{len(self.requests)}",
                    "name": step["tool"],
                    "arguments": json.dumps(step["arguments"]),
                }
            ]
        else:
            output = [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "kind": step["reply"],
                                    "missing_fields": step.get("missing_fields", []),
                                }
                            ),
                        }
                    ],
                }
            ]
        return httpx.Response(
            200,
            json={
                "model": self.config.model,
                "status": "completed",
                "output": output,
                "usage": {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130},
            },
        )
