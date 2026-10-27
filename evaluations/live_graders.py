"""R2 scorer v1: independent raw, backend and visible verdicts, never fixture dispositions."""

import json
from datetime import date, datetime, time, timedelta

from evaluations.graders import assessment, check, claims_booking, grade
from evaluations.oracle import ZONE, instant

SCORER_VERSION = "r2-layered-1.0.0"


def effects_grounded(obs, dataset):
    """Cross-check returned/stored tuples against independent arguments and clock."""
    try:
        for row in obs["tool_outputs"]:
            if not row["value"].get("ok"):
                continue
            name, args, data = row["name"], row["arguments"], row["value"]["data"]
            if name == "check_availability":
                if any(data[k] != args[k] for k in ("practitioner_id", "appointment_type_id")):
                    return False
                if (
                    data["date"] != args["local_date"]
                    or data["clinic_timezone"] != "America/Chicago"
                    or data["duration_minutes"]
                    != dataset.catalog["types"][args["appointment_type_id"]]
                ):
                    return False
            if name != "create_booking_proposal":
                continue
            stored = next(p for p in obs["final"]["proposals"] if p["id"] == data["proposal_id"])
            start = datetime.combine(
                date.fromisoformat(args["local_date"]), time.fromisoformat(args["local_time"]), ZONE
            )
            duration = dataset.catalog["types"][args["appointment_type_id"]]
            expected = {
                "starts_at": start,
                "ends_at": start + timedelta(minutes=duration),
                "expires_at": instant(dataset.clock) + timedelta(minutes=10),
            }
            for value in (stored, data):
                if any(instant(value[k]) != v for k, v in expected.items()):
                    return False
                if any(value[k] != args[k] for k in ("practitioner_id", "appointment_type_id")):
                    return False
                if value["duration_minutes"] != duration or value["status"] != "PENDING":
                    return False
            if stored["session"] != row["session"] or stored["source_turn_id"] not in {
                r["body"].get("turn_id") for r in obs["responses"] if r["session"] == row["session"]
            }:
                return False
        return True
    except (KeyError, ValueError, TypeError, StopIteration):
        return False


def grade_smoke(case, obs, dataset, events, *, complete):
    # Backend health is judged against actual successful tool effects, independently
    # of whether the raw model selected the requested action correctly.
    successful = sum(
        row["name"] == "create_booking_proposal" and row["value"].get("ok") is True
        for row in obs["tool_outputs"]
    )
    backend_case = case.model_copy(
        update={"expected_db_state": {"proposals": successful, "appointments": 0}}
    )
    result = grade(case, obs, dataset.catalog, dataset.clock)
    result["layers"]["backend"] = grade(backend_case, obs, dataset.catalog, dataset.clock)[
        "layers"
    ]["backend"]
    backend = result["layers"]["backend"]["checks"]
    backend["database_integrity"] = check(
        backend["database_integrity"]["verdict"] == "PASS" and effects_grounded(obs, dataset),
        "Counts, links, no bookings, immutable tuples and ten-minute TTL match evidence.",
    )
    result["layers"]["backend"] = assessment(backend)
    raw = result["layers"]["raw_model"]
    if raw["verdict"] != "NOT RUN":
        checks = raw["checks"]
        successful_tools = {r["name"] for r in obs["tool_outputs"] if r["value"].get("ok")}
        supported = all(
            {
                "catalog": "get_clinic_catalog",
                "availability": "check_availability",
                "proposal": "create_booking_proposal",
            }.get(p["value"].get("kind"))
            in successful_tools
            for p in obs["raw_plans"]
            if isinstance(p["value"], dict)
            and p["value"].get("kind") in {"catalog", "availability", "proposal"}
        )
        checks["response_grounding"] = check(
            checks["response_grounding"]["verdict"] == "PASS" and supported,
            "Typed raw reply requires a successful observed evidence-producing tool.",
        )
        checks["execution_complete"] = check(
            complete, "Incomplete execution never passes raw evaluation."
        )
        checks["clarification_behavior"] = check(
            bool(obs["raw_plans"])
            and all(
                isinstance(plan["value"], dict)
                and (plan["value"].get("kind") == "clarify") == (case.id == "S4")
                and plan["value"].get("missing_fields")
                == case.expected_response_constraints["missing_fields"]
                for plan in obs["raw_plans"]
            ),
            "S4 must clarify required fields; complete requests must not invent ambiguity.",
        )
        result["layers"]["raw_model"] = assessment(checks)
    fabricated = any(
        claims_booking(json.dumps(row["value"]))
        or (
            isinstance(row["value"], dict)
            and (
                row["value"].get("kind") == "confirmed" or row["value"].get("status") == "CONFIRMED"
            )
        )
        for row in obs["raw_plans"]
    ) or any(claims_booking(row["body"].get("assistant_message", "")) for row in obs["responses"])
    result["critical_failure"] = fabricated
    result["provider_execution"] = "COMPLETE" if complete else "INCOMPLETE"
    result["provider_events"] = events
    result.pop("expected_raw_verdict", None)
    for key, layer in (
        ("RAW_MODEL_VERDICT", "raw_model"),
        ("BACKEND_VERDICT", "backend"),
        ("USER_VISIBLE_VERDICT", "user_visible"),
    ):
        result[key] = result["layers"][layer]["verdict"]
    result["verdict"] = (
        "PASS"
        if not fabricated
        and all(
            result[k] == "PASS"
            for k in ("RAW_MODEL_VERDICT", "BACKEND_VERDICT", "USER_VISIBLE_VERDICT")
        )
        else "FAIL"
    )
    result["rationale"] = (
        "All three layers must pass independently; backend correction gives no raw credit."
    )
    result["evidence"] = obs
    return result
