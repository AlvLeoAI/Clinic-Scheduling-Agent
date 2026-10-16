"""Deterministic demo command grammar, not natural-language model quality evidence."""

import json
import shlex
from uuid import uuid4

from app.agent.protocol import ProviderResponse


class DemoProvider:
    def __init__(self):
        self.requests = []

    def respond(self, payload):
        self.requests.append(payload)
        last = max(i for i, item in enumerate(payload["input"]) if item.get("role") == "user")
        message = payload["input"][last]["content"]
        current = payload["input"][last + 1 :]
        outputs = [item for item in current if item.get("type") == "function_call_output"]
        try:
            parts = shlex.split(message)
        except ValueError:
            parts = []
        name, args, kind = None, {}, "clarify"
        if parts == ["catalog"]:
            name, kind = "get_clinic_catalog", "catalog"
        elif len(parts) == 4 and parts[0] == "availability":
            name, kind = "check_availability", "availability"
            args = dict(zip(("local_date", "practitioner_id", "appointment_type_id"), parts[1:]))
        elif len(parts) == 5 and parts[0] == "propose":
            name, kind = "create_booking_proposal", "proposal"
            args = dict(
                zip(
                    ("local_date", "local_time", "practitioner_id", "appointment_type_id"),
                    parts[1:],
                )
            )
        if name and not outputs:
            output = {
                "type": "function_call",
                "id": "fc_" + uuid4().hex,
                "call_id": "call_" + uuid4().hex,
                "name": name,
                "arguments": json.dumps(args),
                "status": "completed",
            }
        else:
            if outputs and not json.loads(outputs[-1]["output"]).get("ok"):
                kind = "clarify"
            plan = {
                "kind": kind,
                "missing_fields": ["local_date", "local_time", "practitioner", "appointment_type"]
                if kind == "clarify"
                else [],
            }
            output = {
                "type": "message",
                "id": "msg_" + uuid4().hex,
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(plan), "annotations": []}],
            }
        return ProviderResponse(status="completed", output=[output])
