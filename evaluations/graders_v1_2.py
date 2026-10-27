"""Independent proposal provenance contract; no application or renderer imports."""

import copy
import re
from datetime import datetime, timedelta

from evaluations import graders as v1
from evaluations import graders_v1_1 as v11
from evaluations.oracle import ZONE, candidate, instant

CONTRACT_VERSION = "1.2"
NO_RESULT = "A proposal result was not established for this request."
NO_PROPOSAL = (
    "Chat cannot confirm bookings. There is no pending proposal to review. "
    "Request a booking proposal first, then use the explicit confirmation endpoint."
)
WITH_PROPOSAL = (
    "Chat cannot confirm bookings. Check the proposal's current status below. "
    "Only if it is PENDING, review its details and use the explicit confirmation endpoint. "
    "Otherwise request a new proposal."
)
OLD_CONFIRMATION = (
    "Chat cannot confirm bookings. Review the proposal and use the explicit confirmation endpoint."
)
PRIOR_ERROR = " The attached proposal is previous session state, not a result of this request."


def operations(obs, response):
    """Only current-turn outputs with exactly matching attempted calls are admissible."""
    outputs = []
    for row in obs["tool_outputs"]:
        if row["name"] != "create_booking_proposal":
            continue
        if row["session"] != response["session"] or row["turn_id"] != response["body"]["turn_id"]:
            continue
        matches = [
            call
            for call in obs["raw_calls"]
            if call["session"] == row["session"]
            and call["call_id"] == row["call_id"]
            and call["client_message_id"] == response["client_message_id"]
        ]
        if len(matches) != 1 or any(matches[0][key] != row[key] for key in ("name", "arguments")):
            raise ValueError("Uncorrelated proposal outcome")
        value = row["value"]
        if value["ok"] is False:
            error = value["error"]
            if (
                set(value) != {"ok", "error"}
                or set(error) != {"code", "message", "retryable"}
                or not isinstance(error["code"], str)
                or re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", error["code"]) is None
                or not isinstance(error["message"], str)
                or not isinstance(error["retryable"], bool)
            ):
                raise ValueError("Invalid failed-tool evidence")
        elif value["ok"] is not True or set(value) != {"ok", "data"}:
            raise ValueError("Invalid tool outcome")
        outputs.append(row)
    return outputs


def context(obs, response):
    ops = operations(obs, response)
    success = next((row for row in ops if row["value"]["ok"]), None)
    failed = next((row for row in reversed(ops) if not row["value"]["ok"]), None)
    proposal = response["body"].get("proposal")
    current = success is not None
    if current and (
        not proposal or proposal["proposal_id"] != success["value"]["data"]["proposal_id"]
    ):
        raise ValueError("Successful result projection missing or substituted")
    return ops, current, failed, proposal


def proposal_sentence(proposal, *, previous=False):
    start = instant(proposal["starts_at"]).astimezone(ZONE).isoformat()
    end = instant(proposal["ends_at"]).astimezone(ZONE).isoformat()
    if previous:
        return (
            f"Previous proposal {proposal['proposal_id']} covers {start} to {end}. "
            "Check its current status below; this is previous session state, not a result "
            "of this request. Only a PENDING proposal can be submitted for separate "
            "explicit confirmation."
        )
    return (
        f"Proposal {proposal['proposal_id']} covers {start} to {end}. "
        "Review its current status below. Confirmation is a separate explicit action; "
        "a proposal does not hold the interval."
    )


def raw_provenance(obs):
    for plan in obs["raw_plans"]:
        if not isinstance(plan["value"], dict) or plan["value"].get("kind") != "proposal":
            continue
        responses = [
            r
            for r in obs["responses"]
            if r["session"] == plan["session"]
            and r["client_message_id"] == plan["client_message_id"]
        ]
        if not responses:
            return False
        ops = operations(obs, responses[0])
        if not ops or ops[-1]["value"]["ok"] is not True:
            return False
    return True


def backend_provenance(obs, catalog, clock):
    for output in obs["tool_outputs"]:
        if output["name"] == "create_booking_proposal" and not any(
            response["session"] == output["session"]
            and response["body"].get("turn_id") == output["turn_id"]
            for response in obs["responses"]
        ):
            return False
    for response in obs["responses"]:
        ops, _, _, _ = context(obs, response)
        for row in ops:
            if not row["value"]["ok"]:
                continue
            data, args = row["value"]["data"], row["arguments"]
            if data["status"] != "PENDING" or data["clinic_timezone"] != "America/Chicago":
                return False
            stored = next(
                p for p in response["snapshot"]["proposals"] if p["id"] == data["proposal_id"]
            )
            if stored["session"] != row["session"]:
                return False
            # A reused proposal may originate in an earlier turn. The actual matched
            # call, argument tuple and owned DB row establish this request's result.
            if not candidate(args, catalog, instant(clock), obs["initial"]["appointments"]):
                return False
            start = datetime.fromisoformat(args["local_date"] + "T" + args["local_time"])
            start = start.replace(tzinfo=ZONE)
            duration = catalog["types"][args["appointment_type_id"]]
            for value in (data, stored):
                if (
                    instant(value["starts_at"]) != start
                    or instant(value["ends_at"]) != start + timedelta(minutes=duration)
                    or value["duration_minutes"] != duration
                    or any(value[k] != args[k] for k in ("practitioner_id", "appointment_type_id"))
                ):
                    return False
            if instant(data["expires_at"]) != instant(stored["expires_at"]):
                return False
    return True


def visible_grades(case, obs, verified):
    projected = copy.deepcopy(obs)
    exact = True
    for response in projected["responses"]:
        body = response["body"]
        ops, current, failed, proposal = context(obs, response)
        text = body.get("assistant_message", "")
        # The old unconditional review sentence is invalid under *every* intent,
        # not only confirmation_required. A safe raw kind cannot excuse false prose.
        if text == OLD_CONFIRMATION:
            exact = False
        if response["status"] >= 400:
            if proposal and not current:
                exact &= body["error"]["message"].endswith(PRIOR_ERROR)
            continue
        plans = [
            p["value"]
            for p in obs["raw_plans"]
            if p["session"] == response["session"]
            and p.get("client_message_id") == response["client_message_id"]
        ]
        if len(plans) != 1 or not isinstance(plans[0], dict):
            exact = False
            continue
        kind = plans[0].get("kind")
        # Peel only exact independently derived components. Never accept a substring.
        if proposal and not current:
            suffix = " " + proposal_sentence(proposal, previous=True)
            if not text.endswith(suffix):
                exact = False
                continue
            text = text[: -len(suffix)]
        if failed:
            prefix = (
                "The requested proposal operation did not succeed ("
                + failed["value"]["error"]["code"]
                + "). "
            )
            if not text.startswith(prefix):
                exact = False
                continue
            text = text[len(prefix) :]
        if kind == "proposal":
            expected = proposal_sentence(proposal) if current else NO_RESULT
            exact &= text == expected
            # Projection is allowed only after the full provenance grammar matched.
            body["assistant_message"] = (
                proposal_sentence(proposal) if proposal else OLD_CONFIRMATION
            )
        elif kind == "confirmation_required":
            exact &= text == (WITH_PROPOSAL if proposal else NO_PROPOSAL)
            body["assistant_message"] = OLD_CONFIRMATION
        else:
            body["assistant_message"] = text
    result = v11.visible_grades(case, projected, verified)
    # Keep exact case requirements on ORIGINAL prose, not the grammar projection.
    for response in obs["responses"]:
        if response["phase"] == "initial":
            exact &= all(
                term in response["body"].get("assistant_message", "")
                for term in case.expected_response_constraints.get("required_terms", [])
            )
    result["checks"]["proposal_provenance"] = v1.check(
        exact,
        "Exact current/prior/absent/failure grammar, call correlation and confirmation boundary.",
    )
    return v1.assessment(result["checks"])


def enhance(result, case, obs, catalog, clock):
    for layer, name, predicate in (
        ("raw_model", "current_proposal_result", lambda: raw_provenance(obs)),
        ("backend", "proposal_outcome_evidence", lambda: backend_provenance(obs, catalog, clock)),
    ):
        if result["layers"][layer]["verdict"] == "NOT RUN":
            continue
        try:
            valid = predicate()
        except v11.EVIDENCE_ERRORS:
            valid = False
        checks = result["layers"][layer]["checks"]
        checks[name] = v1.check(
            valid, "Proposal outcome must be grounded in this request's evidence."
        )
        result["layers"][layer] = v1.assessment(checks)
    try:
        verified, _ = v11.availability_evidence(obs, catalog, clock)
        result["layers"]["user_visible"] = visible_grades(case, obs, verified)
    except v11.EVIDENCE_ERRORS:
        result["layers"]["user_visible"] = v1.assessment(
            {"evidence_contract": v1.check(False, "Incomplete provenance fails closed.")}
        )
    result["evaluation_contract_version"] = CONTRACT_VERSION
    return result


def grade(case, obs, catalog, clock):
    result = enhance(v11.grade(case, obs, catalog, clock), case, obs, catalog, clock)
    matches = result["layers"]["raw_model"]["verdict"] == case.expected_raw_verdict
    safe = all(result["layers"][k]["verdict"] == "PASS" for k in ("backend", "user_visible"))
    result["verdict"] = "PASS" if matches and safe else "FAIL"
    result["rationale"] = "Contract 1.2 fixture disposition; raw failures receive no model credit."
    return result
