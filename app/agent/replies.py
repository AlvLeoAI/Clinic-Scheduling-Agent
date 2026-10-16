"""The model selects a reply plan; generated prose never becomes a booking fact."""

from typing import Literal

from pydantic import Field
from sqlalchemy import select

from app.agent.tools import (
    AvailabilityArguments,
    CatalogArguments,
    execute_tool,
    validate_arguments,
)
from app.db.models import Appointment, BookingProposal
from app.schemas.booking import ProposalResponse
from app.schemas.foundation import Contract
from app.services.booking import BookingService


class ReplyPlan(Contract):
    kind: Literal[
        "greeting",
        "clarify",
        "catalog",
        "availability",
        "proposal",
        "confirmation_required",
        "out_of_scope",
    ]
    missing_fields: list[
        Literal["local_date", "local_time", "practitioner", "appointment_type"]
    ] = Field(max_length=4)


def reply_format():
    return {
        "format": {
            "type": "json_schema",
            "name": "scheduling_reply",
            "strict": True,
            "schema": ReplyPlan.model_json_schema(),
        }
    }


def proposal_view(db, session_id, trace_id, clock, *, proposal_id=None):
    if proposal_id is None:
        proposal_id = db.scalar(
            select(BookingProposal.id)
            .where(
                BookingProposal.session_id == session_id,
                BookingProposal.status == "PENDING",
            )
            .limit(1)
        )
    if proposal_id is None:
        return None
    result = BookingService(db, clock).get_proposal(session_id, proposal_id, trace_id)
    snapshot = ProposalResponse.model_validate(result.body)
    if snapshot.status == "CONFIRMED":
        committed = db.scalar(
            select(Appointment.id).where(
                Appointment.session_id == session_id,
                Appointment.proposal_id == snapshot.proposal_id,
            )
        )
        if committed is None:
            raise ValueError("Confirmed proposal has no verified appointment.")
    return snapshot


def render_reply(plan, db, session_id, turn_id, trace_id, clock, rows, proposal):
    if plan.kind == "confirmation_required":
        return (
            "Chat cannot confirm bookings. Review the proposal and use "
            "the explicit confirmation endpoint."
        )
    if plan.kind == "out_of_scope":
        return (
            "This synthetic demo handles scheduling only. It cannot provide "
            "clinical advice or perform that action."
        )
    if plan.kind == "proposal" and proposal is not None:
        # The wording remains true on replay after status changes. Status is a
        # fresh DB projection, while the stored message and immutable tuple stay stable.
        return (
            f"Proposal {proposal.proposal_id} covers {proposal.starts_at.isoformat()} to "
            f"{proposal.ends_at.isoformat()}. Review its current status below. "
            "Confirmation is a separate explicit action; a proposal does not hold the interval."
        )
    if plan.kind == "catalog":
        result = execute_tool(
            "get_clinic_catalog", CatalogArguments(), db, session_id, turn_id, trace_id, clock
        )
        if result["ok"]:
            data = result["data"]
            clinicians = "; ".join(
                f"{row['display_name']} ({row['id']})" for row in data["practitioners"]
            )
            types = "; ".join(
                f"{row['code']}: {row['duration_minutes']} minutes ({row['id']})"
                for row in data["appointment_types"]
            )
            return (
                f"Synthetic clinic in {data['clinic']['timezone']}. "
                f"Practitioners: {clinicians}. Visit types: {types}."
            )
    if plan.kind == "availability":
        for row in reversed(rows):
            if row.item_type == "function_call" and row.payload["name"] == "check_availability":
                args, error = validate_arguments("check_availability", row.payload["arguments"])
                if error is None and isinstance(args, AvailabilityArguments):
                    result = execute_tool(
                        "check_availability", args, db, session_id, turn_id, trace_id, clock
                    )
                    if result["ok"]:
                        slots = result["data"]["slots"]
                        if not slots:
                            return (
                                "The availability check found no valid intervals on that date. "
                                "Query again to refresh availability."
                            )
                        intervals = "; ".join(
                            f"{slot['starts_at']} to {slot['ends_at']}" for slot in slots
                        )
                        return (
                            "The availability check returned these intervals (Chicago time): "
                            + intervals
                            + ". Query again to refresh availability. These are not reservations."
                        )
    if plan.kind == "greeting":
        return (
            "I can help with the synthetic clinic catalog, availability and "
            "booking proposals. Booking requires explicit confirmation."
        )
    labels = {
        "local_date": "an exact date (YYYY-MM-DD)",
        "local_time": "a Chicago-local time (HH:MM)",
        "practitioner": "a practitioner from the catalog",
        "appointment_type": "a visit type from the catalog",
    }
    wanted = plan.missing_fields or ["local_date", "practitioner", "appointment_type"]
    return "Please specify " + ", ".join(labels[name] for name in dict.fromkeys(wanted)) + "."
