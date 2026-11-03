"""Purge stored chat content of sessions that expired more than the retention period ago."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.db.models import ChatSession, ChatTurn, ConversationItem

# Satisfies the request_hash CHECK constraint but is not the hash of any message.
PURGED_REQUEST_HASH = "0" * 64


@dataclass(frozen=True)
class PurgeResult:
    eligible_sessions: int
    conversation_items: int
    turn_hashes: int
    assistant_messages: int

    def as_dict(self) -> dict:
        return asdict(self)


def purge_expired_chat(
    db: Session, *, now: datetime, retention_days: int, apply: bool
) -> PurgeResult:
    """Delete conversation items and blank turn text; never sessions, turns or bookings.

    Each turn of a qualifying session keeps its row, but its request hash becomes the
    sentinel and its stored reply (``assistant_message``) becomes NULL.

    Only sessions whose bearer expired before ``now - retention_days`` and that hold no
    live lease qualify. Their bearer is already rejected, so no chat or confirmation
    replay can read the purged state. Locked sessions are skipped, never waited on.
    """
    cutoff = now - timedelta(days=retention_days)
    sessions = list(
        db.scalars(
            select(ChatSession.id)
            .where(
                ChatSession.expires_at < cutoff,
                or_(ChatSession.active_turn_id.is_(None), ChatSession.lease_expires_at < now),
            )
            .with_for_update(skip_locked=True)
        )
    )
    items = db.scalar(
        select(func.count())
        .select_from(ConversationItem)
        .where(ConversationItem.session_id.in_(sessions))
    )
    owned = ChatTurn.session_id.in_(sessions)
    hashed = ChatTurn.request_hash != PURGED_REQUEST_HASH
    replied = ChatTurn.assistant_message.is_not(None)
    turns = db.scalar(select(func.count()).select_from(ChatTurn).where(owned, hashed))
    replies = db.scalar(select(func.count()).select_from(ChatTurn).where(owned, replied))
    if apply and sessions:
        db.execute(delete(ConversationItem).where(ConversationItem.session_id.in_(sessions)))
        db.execute(
            update(ChatTurn)
            .where(owned, or_(hashed, replied))
            .values(request_hash=PURGED_REQUEST_HASH, assistant_message=None)
        )
    return PurgeResult(len(sessions), items, turns, replies)
