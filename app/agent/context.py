"""Select complete turn bundles; never split a call/output pair or reasoning item."""

import json

from sqlalchemy import select

from app.agent.protocol import MAX_COMPLETED_TURNS, MAX_CONTEXT_CHARS
from app.db.models import ChatTurn, ConversationItem


class ContextLimit(ValueError):
    pass


def serialized_chars(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def protocol_items(rows):
    allowed = {"user_message", "message", "reasoning", "function_call", "function_call_output"}
    items = [row.payload for row in rows if row.item_type in allowed]
    calls = [item["call_id"] for item in items if item.get("type") == "function_call"]
    outputs = [item["call_id"] for item in items if item.get("type") == "function_call_output"]
    if sorted(calls) != sorted(outputs) or len(set(calls)) != len(calls):
        raise ValueError("Incomplete or inconsistent persisted tool context.")
    return items


def selected_context(db, session_id, current_turn_id, *, overhead_chars=0):
    previous = list(
        db.scalars(
            select(ChatTurn.id)
            .where(
                ChatTurn.session_id == session_id,
                ChatTurn.status == "COMPLETED",
                ChatTurn.id != current_turn_id,
            )
            .order_by(ChatTurn.created_at.desc(), ChatTurn.id.desc())
            .limit(MAX_COMPLETED_TURNS)
        )
    )
    previous.reverse()
    bundles = []
    for turn_id in [*previous, current_turn_id]:
        rows = db.scalars(
            select(ConversationItem)
            .where(
                ConversationItem.session_id == session_id,
                ConversationItem.turn_id == turn_id,
            )
            .order_by(ConversationItem.sequence)
        ).all()
        bundles.append(protocol_items(rows))
    while True:
        items = [item for bundle in bundles for item in bundle]
        if serialized_chars(items) + overhead_chars <= MAX_CONTEXT_CHARS:
            return items
        if len(bundles) == 1:
            raise ContextLimit("The current turn cannot fit without truncating required context.")
        bundles.pop(0)
