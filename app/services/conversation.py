"""Durable turn identity and fenced short transactions; never owns provider network I/O."""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.context import ContextLimit, protocol_items, serialized_chars
from app.agent.protocol import MAX_CONTEXT_CHARS, MAX_TOOL_CALLS, ProtocolFailure
from app.core.errors import ApiError
from app.db.models import ChatSession, ChatTurn, ConversationItem
from app.domain.scheduling import as_utc
from app.services.intent import INTENT_ORIGIN, INTERNAL_INTENT_ITEMS


@dataclass(frozen=True)
class Lease:
    session_id: UUID
    turn_id: UUID
    fence: int
    trace_id: UUID


@dataclass(frozen=True)
class Completed:
    body: dict


def message_fingerprint(message):
    return hashlib.sha256(
        json.dumps(
            {"message": message}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


class ConversationStore:
    def __init__(self, engine, clock, lease_seconds):
        self.engine, self.clock, self.lease_seconds = engine, clock, lease_seconds

    @contextmanager
    def transaction(self):
        # M3's unchanged service can commit/rollback its Session savepoint.
        # The outer transaction still owns proposal + source identity + journal.
        with self.engine.connect() as connection, connection.begin():
            with Session(
                bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
            ) as db:
                yield db
                db.commit()

    def claim(self, session_id, client_message_id, message, trace_id):
        fingerprint = message_fingerprint(message)
        with self.transaction() as db:
            session = db.scalar(
                select(ChatSession).where(ChatSession.id == session_id).with_for_update()
            )
            now = as_utc(self.clock())
            if session is None or session.expires_at <= now:
                raise ApiError(401, "UNAUTHORIZED", "A valid session bearer is required.")
            turn = db.scalar(
                select(ChatTurn).where(
                    ChatTurn.session_id == session_id,
                    ChatTurn.client_message_id == client_message_id,
                )
            )
            if turn is not None:
                if turn.request_hash != fingerprint:
                    raise ApiError(
                        409, "MESSAGE_ID_REUSED", "The message ID belongs to different content."
                    )
                if turn.status == "COMPLETED":
                    body = db.scalar(
                        select(ConversationItem.payload).where(
                            ConversationItem.turn_id == turn.id,
                            ConversationItem.item_type == "chat_result",
                        )
                    )
                    if body is None:
                        raise ApiError(
                            503, "SERVICE_UNAVAILABLE", "Completed turn state is unavailable.", True
                        )
                    return Completed(body)
            if (
                session.active_turn_id is not None
                and session.lease_expires_at is not None
                and session.lease_expires_at > now
            ):
                raise ApiError(
                    409, "TURN_IN_PROGRESS", "A turn is already in progress for this session."
                )
            if session.active_turn_id is not None and session.active_turn_id != (
                turn.id if turn else None
            ):
                old = db.get(ChatTurn, session.active_turn_id)
                if old is not None and old.status == "IN_PROGRESS":
                    old.status = "FAILED"
            if turn is None:
                latest = db.scalar(
                    select(func.max(ChatTurn.created_at)).where(ChatTurn.session_id == session_id)
                )
                created = max(now, latest + timedelta(microseconds=1)) if latest else now
                turn = ChatTurn(
                    session_id=session_id,
                    client_message_id=client_message_id,
                    request_hash=fingerprint,
                    status="IN_PROGRESS",
                    trace_id=trace_id,
                    created_at=created,
                )
                db.add(turn)
                db.flush()
                db.add(
                    ConversationItem(
                        session_id=session_id,
                        turn_id=turn.id,
                        sequence=0,
                        item_type="user_message",
                        created_at=now,
                        payload={"role": "user", "content": message},
                    )
                )
                # Only first creation under this implementation establishes
                # origin. Never stamp a reclaimed legacy turn as newly ordered.
                db.add(
                    ConversationItem(
                        session_id=session_id,
                        turn_id=turn.id,
                        sequence=1,
                        item_type=INTENT_ORIGIN,
                        created_at=now,
                        payload={"ordering_version": 1},
                    )
                )
            else:
                turn.status = "IN_PROGRESS"
                turn.completed_at = None
            session.active_turn_id = turn.id
            session.lease_fence += 1
            session.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            result = Lease(session_id, turn.id, session.lease_fence, turn.trace_id)
        return result

    def guard(self, db, lease, *, renew=True):
        with db.no_autoflush:
            session = db.scalar(
                select(ChatSession)
                .where(ChatSession.id == lease.session_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        now = as_utc(self.clock())
        if (
            session is None
            or session.expires_at <= now
            or session.active_turn_id != lease.turn_id
            or session.lease_fence != lease.fence
            or session.lease_expires_at is None
            or session.lease_expires_at <= now
        ):
            raise ApiError(
                409, "TURN_IN_PROGRESS", "The turn lease is no longer owned; retry its message ID."
            )
        if renew:
            session.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
        return session

    def rows(self, db, lease):
        return db.scalars(
            select(ConversationItem)
            .where(
                ConversationItem.session_id == lease.session_id,
                ConversationItem.turn_id == lease.turn_id,
            )
            .order_by(ConversationItem.sequence)
        ).all()

    def append(self, db, lease, kind, payload, call_id=None):
        self.guard(db, lease, renew=False)
        last = db.scalar(
            select(func.max(ConversationItem.sequence)).where(
                ConversationItem.turn_id == lease.turn_id
            )
        )
        db.add(
            ConversationItem(
                session_id=lease.session_id,
                turn_id=lease.turn_id,
                sequence=(last + 1 if last is not None else 0),
                item_type=kind,
                payload=payload,
                call_id=call_id,
                created_at=as_utc(self.clock()),
            )
        )
        db.flush()

    def persist_response(self, lease, response):
        with self.transaction() as db:
            self.guard(db, lease)
            rows = self.rows(db, lease)
            previous_calls = {row.call_id for row in rows if row.item_type == "function_call"}
            calls = [item for item in response.output if item["type"] == "function_call"]
            if len(previous_calls) + len(calls) > MAX_TOOL_CALLS:
                raise ApiError(422, "TOOL_LIMIT_REACHED", "The five-tool turn limit was reached.")
            if any(item["call_id"] in previous_calls for item in calls):
                raise ProtocolFailure("Provider call identity was repeated.")
            current = [
                row.payload
                for row in rows
                if row.item_type not in {"chat_result", *INTERNAL_INTENT_ITEMS}
            ]
            if serialized_chars([*current, *response.output]) > MAX_CONTEXT_CHARS:
                raise ContextLimit("The current turn would exceed the context bound.")
            for item in response.output:
                self.append(
                    db,
                    lease,
                    item["type"],
                    item,
                    item.get("call_id") if item["type"] == "function_call" else None,
                )
            self.guard(db, lease)

    def fail(self, lease):
        # A stale owner may not mark a turn failed or clear another owner's lease.
        with self.transaction() as db:
            session = self.guard(db, lease, renew=False)
            turn = db.get(ChatTurn, lease.turn_id)
            turn.status = "FAILED"
            session.active_turn_id = None
            session.lease_expires_at = None

    def complete(self, db, lease, body):
        session = self.guard(db, lease)
        protocol_items(self.rows(db, lease))
        turn = db.get(ChatTurn, lease.turn_id)
        turn.status = "COMPLETED"
        turn.assistant_message = body["assistant_message"]
        turn.completed_at = as_utc(self.clock())
        self.append(db, lease, "chat_result", body)
        session.active_turn_id = None
        session.lease_expires_at = None
