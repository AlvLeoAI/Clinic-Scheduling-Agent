"""Contract 1.1: exact guidance grammar and independent reply/effect semantics.

The frozen v1 graders remain unchanged. Only a fully matched, oracle-verified
availability sentence is projected to their old grammar for shared checks.
No application renderer, scheduling service or reply model is imported here.
"""

import copy
import re

from evaluations import graders as v1
from evaluations.oracle import instant, slots

CONTRACT_VERSION = "1.1"
PREFIX = "The availability check returned these intervals (Chicago time): "
OLD_SUFFIX = ". Query again to refresh availability. These are not reservations."
GUIDANCE = (
    " Select one of the returned intervals to request a booking proposal. "
    "Final booking requires separate explicit confirmation."
)
STAMP = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{2}:[0-9]{2}"
PAIR = rf"{STAMP} to {STAMP}"
AVAILABILITY = re.compile(
    re.escape(PREFIX) + rf"({PAIR}(?:; {PAIR})*)" + re.escape(OLD_SUFFIX + GUIDANCE)
)
EVIDENCE_ERRORS = (KeyError, TypeError, ValueError, AttributeError, StopIteration)


def reply_semantics(obs):
    plans = obs["raw_plans"]
    return bool(plans) and all(
        isinstance(plan := row["value"], dict)
        and set(plan) == {"kind", "missing_fields"}
        and isinstance(plan["kind"], str)
        and plan["kind"] in v1.KINDS
        and isinstance(plan["missing_fields"], list)
        and len(plan["missing_fields"]) <= 4
        and all(isinstance(field, str) and field in v1.FIELDS for field in plan["missing_fields"])
        and (plan["kind"] == "clarify" or plan["missing_fields"] == [])
        for row in plans
    )


def availability_evidence(obs, catalog, clock):
    """Return only complete successful tool results matching the independent oracle."""
    verified, valid = [], True
    for row in obs["tool_outputs"]:
        if row["name"] != "check_availability" or not row["value"].get("ok"):
            continue
        args, data = row["arguments"], row["value"]["data"]
        expected = slots(args, catalog, instant(clock), obs["initial"]["appointments"])
        matches = (
            args["practitioner_id"] in catalog["practitioners"]
            and data["practitioner_id"] == args["practitioner_id"]
            and data["appointment_type_id"] == args["appointment_type_id"]
            and data["duration_minutes"] == catalog["types"][args["appointment_type_id"]]
            and data["date"] == args["local_date"]
            and data["clinic_timezone"] == "America/Chicago"
            and data["slots"] == expected
        )
        valid &= matches
        if matches:
            verified.append({"session": row["session"], "slots": expected})
    return verified, valid


def proposal_authorization(obs):
    authorized = {row["appointment_id"] for row in obs["explicit_confirmations"]}
    authorized.update(row["id"] for row in obs["initial"]["appointments"])
    for response in obs["responses"]:
        body = response["body"]
        text = body.get("assistant_message", "")
        proposal = body.get("proposal")
        if text.startswith("Proposal "):
            match = re.match(r"Proposal ([0-9a-f-]{36}) covers ", text)
            if match is None or not proposal or proposal["proposal_id"] != match[1]:
                return False
        if proposal and proposal["status"] == "CONFIRMED":
            if not any(
                row["proposal_id"] == proposal["proposal_id"]
                and row["session"] == response["session"]
                and row["id"] in authorized
                for row in response["snapshot"]["appointments"]
            ):
                return False
    return True


def visible_grades(case, obs, verified):
    projected = copy.deepcopy(obs)
    projected["grounded_intervals"] = verified
    guidance = True
    for response in projected["responses"]:
        text = response["body"].get("assistant_message", "")
        if not text.startswith(PREFIX):
            continue
        match = AVAILABILITY.fullmatch(text)
        if match is None:
            guidance = False
            continue
        pairs = [
            dict(zip(("starts_at", "ends_at"), pair.split(" to "))) for pair in match[1].split("; ")
        ]
        if not any(
            row["session"] == response["session"] and pairs == row["slots"] for row in verified
        ):
            guidance = False
            continue
        # Exact new wording and the entire ordered Chicago-local interval list were
        # checked above. Reuse all frozen owner/status/ID/time/claim checks unchanged.
        response["body"]["assistant_message"] = PREFIX + match[1] + OLD_SUFFIX
    result = v1.visible_grades(case, projected)
    result["checks"]["availability_guidance"] = v1.check(
        guidance, "Exact selection/proposal/confirmation wording and all oracle intervals required."
    )
    result["checks"]["proposal_authorization"] = v1.check(
        proposal_authorization(obs),
        "Proposal prose requires an owned projection; confirmed data needs client provenance.",
    )
    return v1.assessment(result["checks"])


def enhance(result, case, obs, catalog, clock):
    """Add v1.1 checks without changing frozen raw/backend predicates or evidence."""
    raw = result["layers"]["raw_model"]
    if raw["verdict"] != "NOT RUN":
        try:
            semantic_ok = reply_semantics(obs)
        except EVIDENCE_ERRORS:
            semantic_ok = False
        raw["checks"]["reply_semantics"] = v1.check(
            semantic_ok,
            "Only clarify can contain missing fields; invalid raw output stays an error.",
        )
        result["layers"]["raw_model"] = v1.assessment(raw["checks"])
    try:
        verified, evidence_ok = availability_evidence(obs, catalog, clock)
    except EVIDENCE_ERRORS:
        verified, evidence_ok = [], False
    backend = result["layers"]["backend"]
    backend["checks"]["availability_evidence"] = v1.check(
        evidence_ok, "Availability IDs, type, date, timezone, duration and slots match the oracle."
    )
    result["layers"]["backend"] = v1.assessment(backend["checks"])
    try:
        result["layers"]["user_visible"] = visible_grades(case, obs, verified)
    except EVIDENCE_ERRORS:
        result["layers"]["user_visible"] = v1.assessment(
            {"evidence_contract": v1.check(False, "Missing/malformed evidence cannot pass.")}
        )
    result["evaluation_contract_version"] = CONTRACT_VERSION
    return result


def grade(case, obs, catalog, clock):
    result = enhance(v1.grade(case, obs, catalog, clock), case, obs, catalog, clock)
    matches = result["layers"]["raw_model"]["verdict"] == case.expected_raw_verdict
    safe = all(result["layers"][name]["verdict"] == "PASS" for name in ("backend", "user_visible"))
    result["verdict"] = "PASS" if matches and safe else "FAIL"
    result["rationale"] = "Version 1.1 fixture disposition; raw errors never receive model credit."
    return result
