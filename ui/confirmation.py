"""Confirmation state of each proposal card. Pure Python, so it is testable without Streamlit.

A confirm whose response is lost may still have booked. That outcome is UNCERTAIN, not
failed: the card then offers "Check booking status", which resends the confirm with the
same Idempotency-Key. The server answers a known key with the stored outcome before it
looks at the proposal's TTL or status, so the check works after expiry and books once.

A newer proposal does not hide an earlier card that was sent: an unresolved one stays
visible with its own key, and the newer proposal cannot be confirmed until it resolves.
The server supersedes only PENDING proposals, so a committed confirm is never undone.
"""

from collections.abc import Mapping, MutableMapping
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


# The request may have committed and nobody has seen the outcome yet.
UNRESOLVED = frozenset({ConfirmState.CONFIRMING, ConfirmState.UNCERTAIN})


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


def cards(
    proposals: Mapping[str, Proposal], flows: MutableMapping[str, Flow], latest: UUID
) -> list[Proposal]:
    """Cards to show, oldest first: every earlier proposal that was sent, then the latest.

    An earlier proposal that was never sent was superseded and is dropped; one that was
    sent keeps its card (and its button, while unresolved) whatever came after it.
    """
    shown = [
        proposal
        for key, proposal in proposals.items()
        if key != str(latest)
        and flow_for(flows, proposal.proposal_id).state is not ConfirmState.PENDING
    ]
    return shown + [proposals[str(latest)]]


def blocked_by_unresolved(flows: Mapping[str, Flow], proposal_id: UUID) -> bool:
    return any(key != str(proposal_id) and f.state in UNRESOLVED for key, f in flows.items())


def action(
    proposal: Proposal, flow: Flow, now: datetime, *, blocked: bool = False
) -> Action | None:
    if flow.state in UNRESOLVED:
        return Action("Check booking status", enabled=True)
    if flow.state is ConfirmState.PENDING:
        open_ = proposal.status not in CLOSED_STATUSES and proposal.seconds_left(now) > 0
        return Action("Confirm booking", enabled=open_ and not blocked)
    return None
