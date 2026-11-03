"""Confirmation state of each proposal card. Pure Python, so it is testable without Streamlit.

A confirm whose response is lost may still have booked. That outcome is UNCERTAIN, not
failed: the card then offers "Check booking status", which resends the confirm with the
same Idempotency-Key. The server answers a known key with the stored outcome before it
looks at the proposal's TTL or status, so the check works after expiry and books once.
"""

from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from ui.client import ApiError, Appointment, Proposal, confirmation_key

# A new key cannot book these; only an uncertain confirm may still be checked.
CLOSED_STATUSES = frozenset({"SUPERSEDED", "EXPIRED"})


class ConfirmState(StrEnum):
    PENDING = "pending"
    CONFIRMING = "confirming"
    UNCERTAIN = "uncertain"
    CONFIRMED = "confirmed"
    FAILED = "failed"


@dataclass
class Flow:
    state: ConfirmState = ConfirmState.PENDING
    appointment: Appointment | None = None
    error: ApiError | None = None


@dataclass(frozen=True)
class Action:
    label: str
    enabled: bool


class ConfirmApi(Protocol):
    def confirm(self, token: str, proposal_id: UUID, idempotency_key: str) -> Appointment: ...


def flow_for(flows: MutableMapping[str, Flow], proposal_id: UUID) -> Flow:
    flow = flows.setdefault(str(proposal_id), Flow())
    if flow.state is ConfirmState.CONFIRMING:
        # The run that sent the request was interrupted before it saw a response.
        flow.state = ConfirmState.UNCERTAIN
    return flow


def confirm(
    api: ConfirmApi,
    token: str,
    proposal: Proposal,
    flows: MutableMapping[str, Flow],
    keys: MutableMapping[str, str],
) -> Flow:
    flow = flows.setdefault(str(proposal.proposal_id), Flow())
    flow.state, flow.error = ConfirmState.CONFIRMING, None
    key = confirmation_key(keys, proposal.proposal_id)
    try:
        flow.appointment = api.confirm(token, proposal.proposal_id, key)
    except ApiError as error:
        # Retryable means the request may have committed: unreachable, timeout or 503.
        flow.error = error
        flow.state = ConfirmState.UNCERTAIN if error.retryable else ConfirmState.FAILED
        return flow
    flow.state = ConfirmState.CONFIRMED
    return flow


def action(proposal: Proposal, flow: Flow, now: datetime) -> Action | None:
    if flow.state in (ConfirmState.CONFIRMING, ConfirmState.UNCERTAIN):
        return Action("Check booking status", enabled=True)
    if flow.state is ConfirmState.PENDING:
        open_ = proposal.status not in CLOSED_STATUSES and proposal.seconds_left(now) > 0
        return Action("Confirm booking", enabled=open_)
    return None
