"""Durable mutation fences in the existing journal, serialized by the session lock."""

from sqlalchemy import func, select

from app.core.errors import ApiError
from app.db.models import BookingProposal, ChatTurn, ConversationItem

STALE_INTENT = "stale_intent"
INTENT_ORIGIN = "intent_origin"
INTERNAL_INTENT_ITEMS = {STALE_INTENT, INTENT_ORIGIN}


def supersede_unfinished_intents(db, session_id, proposal_id, source_turn_id, now):
    """Caller holds ChatSession FOR UPDATE until the proposal transaction commits.

    An accepted proposal makes other unfinished mutations obsolete. Completed
    turns and recorded tool results remain replayable. No timestamp comparison,
    lease counter reuse, or provider-visible instruction establishes this order.
    """
    turns = select(ChatTurn.id).where(
        ChatTurn.session_id == session_id, ChatTurn.status != "COMPLETED"
    )
    if source_turn_id is not None:
        turns = turns.where(ChatTurn.id != source_turn_id)
    for turn_id in db.scalars(turns):
        exists = db.scalar(
            select(ConversationItem.id).where(
                ConversationItem.turn_id == turn_id,
                ConversationItem.item_type == STALE_INTENT,
            )
        )
        if exists is not None:
            continue
        last = db.scalar(
            select(func.max(ConversationItem.sequence)).where(ConversationItem.turn_id == turn_id)
        )
        db.add(
            ConversationItem(
                session_id=session_id,
                turn_id=turn_id,
                sequence=last + 1 if last is not None else 0,
                item_type=STALE_INTENT,
                payload={"superseding_proposal_id": str(proposal_id)},
                created_at=now,
            )
        )
    db.flush()


def require_current_intent(db, session_id, rows):
    """Check under the same session lock as the subsequent unexecuted mutation."""
    if any(row.item_type == STALE_INTENT for row in rows):
        raise ApiError(
            409,
            "STALE_INTENT",
            "A newer proposal was accepted. This older request cannot create a proposal. "
            "Send a new message to change details.",
        )
    ordered_origin = any(
        row.item_type == INTENT_ORIGIN and row.payload == {"ordering_version": 1} for row in rows
    )
    if not ordered_origin and db.scalar(
        select(BookingProposal.id).where(BookingProposal.session_id == session_id).limit(1)
    ):
        # Legacy turns have no trustworthy acceptance-order provenance. Even
        # terminal history can represent intervening intent; timestamps and
        # lease reacquisition do not establish a right to replace it. Recorded
        # effects are replayed by the caller before reaching this mutation gate.
        raise ApiError(
            409,
            "STALE_INTENT",
            "This older request's ordering relative to existing proposals cannot be verified. "
            "It cannot create a proposal. Send a new message to choose the current details.",
        )
