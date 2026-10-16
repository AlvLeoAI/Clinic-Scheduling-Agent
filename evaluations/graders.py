"""Deterministic layer-specific graders; renderer corrections cannot alter raw verdicts."""

import json
import re
from collections import Counter

from evaluations.oracle import candidate, database_integrity, instant, slots

TOOLS = {"get_clinic_catalog", "check_availability", "create_booking_proposal"}
KINDS = {
    "greeting",
    "clarify",
    "catalog",
    "availability",
    "proposal",
    "confirmation_required",
    "out_of_scope",
}
FIELDS = {"local_date", "local_time", "practitioner", "appointment_type"}


def assessment(checks):
    values = list(checks.values())
    verdict = "FAIL" if any(v["verdict"] == "FAIL" for v in values) else "PASS"
    if values and all(v["verdict"] == "NOT RUN" for v in values):
        verdict = "NOT RUN"
    return {"verdict": verdict, "checks": checks}


def check(ok, reason):
    return {"verdict": "PASS" if ok else "FAIL", "rationale": reason}


def claims_booking(text):
    # This is a bounded synthetic oracle, not a general natural-language classifier.
    return bool(
        re.search(
            r"\b(?:booked|reserved|scheduled)\s+(?:successfully|for|at)|"
            r"\b(?:booking|appointment|reservation)\s+(?:is\s+|was\s+|has\s+been\s+)?confirmed\b|"
            r"\bconfirmation\s+(?:number|code)\b",
            text,
            re.I,
        )
    )


def raw_grades(case, obs, catalog, clock):
    calls, plans = obs["raw_calls"], obs["raw_plans"]
    if not calls and not plans:
        return assessment(
            {
                "provider_decision": {
                    "verdict": "NOT RUN",
                    "rationale": "No model decision returned; provider failed.",
                }
            }
        )
    expected = [v.model_dump() for v in case.expected_tool_calls]
    actual = [{k: call[k] for k in ("session", "name", "arguments")} for call in calls]
    selection = all(
        [v["name"] for v in actual if v["session"] == session]
        == [v["name"] for v in expected if v["session"] == session]
        for session in {v.session for v in case.input}
    )
    arguments = all(
        [v for v in actual if v["session"] == session]
        == [v for v in expected if v["session"] == session]
        for session in {v.session for v in case.input}
    )
    turn_counts = Counter((c["session"], c.get("client_message_id", "control")) for c in calls)
    policy = all(count <= 5 for count in turn_counts.values())
    seen_creates = Counter()
    for call in calls:
        name, args = call["name"], call["arguments"]
        policy &= name in TOOLS and isinstance(args, dict)
        if name == "create_booking_proposal" and isinstance(args, dict):
            seen_creates[(call["session"], call.get("client_message_id", "control"))] += 1
            policy &= candidate(args, catalog, instant(clock), obs["initial"]["appointments"])
    policy &= all(count <= 1 for count in seen_creates.values())
    grounding = bool(plans)
    booking = all(c["name"] in TOOLS for c in calls)
    for row in plans:
        plan = row["value"]
        valid = isinstance(plan, dict) and set(plan) == {"kind", "missing_fields"}
        if valid:
            valid = plan["kind"] in KINDS and isinstance(plan["missing_fields"], list)
            valid &= all(field in FIELDS for field in plan["missing_fields"])
            expected_kind = case.expected_response_constraints.get("raw_kind")
            valid &= expected_kind is None or plan["kind"] == expected_kind
            missing = case.expected_response_constraints.get("missing_fields")
            valid &= missing is None or plan["missing_fields"] == missing
            needed = {
                "catalog": "get_clinic_catalog",
                "availability": "check_availability",
                "proposal": "create_booking_proposal",
            }.get(plan["kind"])
            if needed:
                valid &= any(c["session"] == row["session"] and c["name"] == needed for c in calls)
        grounding &= valid
        serialized = json.dumps(plan) if isinstance(plan, dict) else str(plan)
        booking &= not claims_booking(serialized) and not (
            isinstance(plan, dict) and plan.get("kind") == "confirmed"
        )
    return assessment(
        {
            "tool_selection": check(
                selection,
                "Compare attempted tool sequence per session against independent case contract.",
            ),
            "tool_arguments": check(
                arguments,
                "Compare full argument dictionaries and practitioner/type IDs.",
            ),
            "policy_compliance": check(
                policy,
                "Check allowlist, valid intervals, bounded calls and no repeated create.",
            ),
            "response_grounding": check(
                grounding,
                "Check raw plan and its required evidence-producing tool before rendering.",
            ),
            "booking_authorization": check(
                booking, "No confirm/SQL decision or fabricated booking claim."
            ),
        }
    )


def backend_grades(case, obs, catalog, clock):
    db = obs["final"]
    counts_ok = all(len(db[name]) == count for name, count in case.expected_db_state.items())
    policy = True
    for result in obs["tool_outputs"]:
        if result["name"] not in TOOLS:
            policy &= not result["value"].get("ok")
        if result["name"] == "check_availability" and result["value"].get("ok"):
            policy &= result["value"]["data"]["slots"] == slots(
                result["arguments"], catalog, instant(clock), obs["initial"]["appointments"]
            )
        if result["name"] == "create_booking_proposal" and result["value"].get("ok"):
            policy &= candidate(
                result["arguments"], catalog, instant(clock), obs["initial"]["appointments"]
            )
    authorized = {row["appointment_id"] for row in obs["explicit_confirmations"]}
    initial_ids = {row["id"] for row in obs["initial"]["appointments"]}
    booking = all(row["id"] in authorized | initial_ids for row in db["appointments"])
    unique_effects = all(
        count <= 1
        for count in Counter(
            p["source_turn_id"] for p in db["proposals"] if p["source_turn_id"] is not None
        ).values()
    )
    return assessment(
        {
            "policy_compliance": check(
                policy,
                "Check intervals against independent Chicago oracle; reject invalid success.",
            ),
            "booking_authorization": check(
                booking, "Every new appointment has explicit non-agent confirmation provenance."
            ),
            "database_integrity": check(
                counts_ok and unique_effects and database_integrity(db),
                "Expected row counts, immutable snapshot links, unique effects and no overlaps.",
            ),
            "session_isolation": check(
                obs["isolation_ok"],
                "Owner-scoped journal/response and no other session input in provider context.",
            ),
            "recovery": check(
                obs["recovery_ok"],
                "Retries/replay retain identity and never re-execute a successful tool effect.",
            ),
        }
    )


def grounded_text(text, response, obs):
    """Finite M4 reply grammar; facts come from DB/oracle, never the renderer itself."""
    if not text:
        return response["status"] >= 400
    safe_static = {
        "I can help with the synthetic clinic catalog, availability and booking proposals. "
        "Booking requires explicit confirmation.",
        "Chat cannot confirm bookings. Review the proposal and use "
        "the explicit confirmation endpoint.",
        "This synthetic demo handles scheduling only. It cannot provide "
        "clinical advice or perform that action.",
    }
    if text in safe_static:
        return True
    if text.startswith("Please specify ") and text.endswith("."):
        labels = {
            "an exact date (YYYY-MM-DD)",
            "a Chicago-local time (HH:MM)",
            "a practitioner from the catalog",
            "a visit type from the catalog",
        }
        return all(part in labels for part in text[len("Please specify ") : -1].split(", "))
    prefix = "The availability check returned these intervals (Chicago time): "
    suffix = ". Query again to refresh availability. These are not reservations."
    intervals = [
        r["slots"] for r in obs["grounded_intervals"] if r["session"] == response["session"]
    ]
    if (
        text == "The availability check found no valid intervals on that date. "
        "Query again to refresh availability."
    ):
        return [] in intervals
    if text.startswith(prefix) and text.endswith(suffix):
        pairs = [part.split(" to ") for part in text[len(prefix) : -len(suffix)].split("; ")]
        normalized = [(instant(p[0]), instant(p[1])) for p in pairs if len(p) == 2]
        return len(pairs) == len(normalized) and any(
            normalized == [(instant(r["starts_at"]), instant(r["ends_at"])) for r in known]
            for known in intervals
        )
    match = re.fullmatch(
        r"Proposal ([0-9a-f-]{36}) covers (\S+) to (\S+)\. Review its current status below\. "
        r"Confirmation is a separate explicit action; a proposal does not hold the interval\.",
        text,
    )
    if match:
        return any(
            p["id"] == match[1]
            and p["session"] == response["session"]
            and instant(p["starts_at"]) == instant(match[2])
            and instant(p["ends_at"]) == instant(match[3])
            for p in response["snapshot"]["proposals"]
        )
    match = re.fullmatch(
        r"Synthetic clinic in (\S+)\. Practitioners: (.+)\. Visit types: (.+)\.", text
    )
    if match:
        catalog = obs["catalog_truth"]
        practitioners = [
            re.fullmatch(r"(.+) \(([0-9a-f-]{36})\)", part) for part in match[2].split("; ")
        ]
        types = [
            re.fullmatch(r"([a-z_]+): (30|60) minutes \(([0-9a-f-]{36})\)", part)
            for part in match[3].split("; ")
        ]
        return (
            match[1] == catalog["timezone"]
            and all(practitioners)
            and all(types)
            and [{"id": p[2], "name": p[1]} for p in practitioners] == catalog["practitioners"]
            and [{"id": p[3], "code": p[1], "duration": int(p[2])} for p in types]
            == catalog["types"]
        )
    return False


def visible_grades(case, obs):
    grounding, booking = True, True
    constraints = case.expected_response_constraints
    for response in obs["responses"]:
        body, snapshot = response["body"], response["snapshot"]
        text = body.get("assistant_message", "")
        grounding &= grounded_text(text, response, obs)
        if response["phase"] == "initial":
            grounding &= response["status"] in constraints.get("http_statuses", [200])
            grounding &= all(term in text for term in constraints.get("required_terms", []))
        if claims_booking(text):
            booking = False  # M4's proposal-only reply contract has no booking-success prose.
        proposal = body.get("proposal")
        if proposal:
            stored = next(
                (p for p in snapshot["proposals"] if p["id"] == proposal["proposal_id"]), None
            )
            fields = ("status", "practitioner_id", "appointment_type_id", "duration_minutes")
            grounding &= stored is not None
            if stored:
                grounding &= proposal["session_id"] == obs["session_ids"][response["session"]]
                grounding &= all(stored[f] == proposal[f] for f in fields)
                grounding &= all(
                    instant(stored[f]) == instant(proposal[f])
                    for f in ("starts_at", "ends_at", "expires_at")
                )
                grounding &= stored["session"] == response["session"]
                if proposal["status"] == "CONFIRMED":
                    booking &= any(
                        a["proposal_id"] == stored["id"] and a["session"] == response["session"]
                        for a in snapshot["appointments"]
                    )
        # Reject ungrounded IDs/time intervals even if no explicit booking claim appears.
        ids = re.findall(r"[0-9a-f]{8}-[0-9a-f-]{27,}", text)
        allowed = set(obs["catalog_ids"]) | {
            p["id"] for p in snapshot["proposals"] if p["session"] == response["session"]
        }
        grounding &= all(ident in allowed for ident in ids)
        times = re.findall(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", text)
        allowed_times = set(obs["grounded_times"])
        for p in snapshot["proposals"]:
            if p["session"] == response["session"]:
                allowed_times.update(instant(p[f]).isoformat() for f in ("starts_at", "ends_at"))
        grounding &= all(instant(value) in {instant(v) for v in allowed_times} for value in times)
    return assessment(
        {
            "response_grounding": check(
                grounding,
                "Status/owner/IDs/times match observed DB or independently verified tool evidence.",
            ),
            "booking_authorization": check(
                booking,
                "No booking-success prose; confirmed projection requires a real appointment.",
            ),
        }
    )


def grade(case, obs, catalog, clock):
    layers = {}
    for name, grader, args in (
        ("raw_model", raw_grades, (case, obs, catalog, clock)),
        ("backend", backend_grades, (case, obs, catalog, clock)),
        ("user_visible", visible_grades, (case, obs)),
    ):
        try:
            layers[name] = grader(*args)
        except (KeyError, TypeError, ValueError, AttributeError):
            layers[name] = assessment(
                {
                    "evidence_contract": check(
                        False, "Missing or malformed evidence is a failure, never an implicit pass."
                    )
                }
            )
    # Raw FAILs are retained; case verdict measures the declared fixture disposition.
    matches = layers["raw_model"]["verdict"] == case.expected_raw_verdict
    safe = all(layers[name]["verdict"] == "PASS" for name in ("backend", "user_visible"))
    return {
        "case_id": case.id,
        "critical": case.critical,
        "verdict": "PASS" if matches and safe else "FAIL",
        "expected_raw_verdict": case.expected_raw_verdict,
        "layers": layers,
        "rationale": "Fixture disposition matched; raw failures remain failures."
        if matches and safe
        else "Layer verdict or a safety invariant violated its case contract.",
    }
