"""Confirmation state of each proposal card. Pure Python, so it is testable without Streamlit.

A confirm whose response is lost may still have booked. That outcome is UNCERTAIN, not
failed: the card then offers "Check booking status", which resends the confirm with the
same Idempotency-Key. The server answers a known key with the stored outcome before it
looks at the proposal's TTL or status, so the check works after expiry and books once.

A newer proposal does not hide an earlier card that was sent: an unresolved one stays
visible with its own key, and the newer proposal cannot be confirmed until it resolves.
The server supersedes only PENDING proposals, so a committed confirm is never undone.

Only three answers prove that a key did not book: PROPOSAL_EXPIRED, PROPOSAL_SUPERSEDED
and SLOT_TAKEN (the server stores them under the key, so a retry returns them again).
Every other error, including 401, 500, unknown codes and malformed bodies, leaves the
outcome unknown.

A confirm is sent only with the bearer of the session that received the proposal. A
button drawn before that bearer was dropped or replaced sends nothing: the new session
does not own the proposal, and its bearer cannot check another session's key.
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
# The only answers that prove this key booked nothing.
NOT_BOOKED_CODES = frozenset({"PROPOSAL_EXPIRED", "PROPOSAL_SUPERSEDED", "SLOT_TAKEN"})


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
    # The bearer that sent the confirm was replaced, so no request can check it now.
    session_lost: bool = False

    @property
    def unverifiable(self) -> bool:
        expired = self.error is not None and self.error.status == 401
        return self.state in UNRESOLVED and (expired or self.session_lost)


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
        flow.error = error
        not_booked = error.code in NOT_BOOKED_CODES
        flow.state = ConfirmState.FAILED if not_booked else ConfirmState.UNCERTAIN
        return flow
    flow.state = ConfirmState.CONFIRMED
    return flow


def send_confirm(
    api: ConfirmApi, state: Mapping, proposal: Proposal, owner: UUID | None
) -> Flow | None:
    """Confirm with the page's bearer if `owner` is its session; None means nothing was sent.

    `state` is the page state: `token` and `session_id` of the live session (no token
    after a 401), `flows` and `confirm_keys`.
    """
    token = state.get("token")
    if token is None or owner is None or owner != state.get("session_id"):
        return None
    return confirm(api, token, proposal, state["flows"], state["confirm_keys"])


def stale_notice(flow: Flow | None) -> str:
    if flow is not None and flow.state in UNRESOLVED:
        return (
            "The session that sent this confirmation has expired, so its status was not "
            "checked. The booking may exist."
        )
    return (
        "This proposal belonged to a session that has expired, so it was not sent and "
        "booked nothing. Ask for a new proposal."
    )


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


def carry_over(
    flows: Mapping[str, Flow], proposals: Mapping[str, Proposal], keys: Mapping[str, str]
) -> tuple[dict[str, Flow], dict[str, Proposal], dict[str, str]]:
    """What a new session keeps from the old one: only its unresolved confirmations.

    Their cards stay visible and keep blocking new confirms, but the old bearer is gone,
    so they can no longer be checked from this page.
    """
    kept = {key: flow for key, flow in flows.items() if flow.state in UNRESOLVED}
    for flow in kept.values():
        flow.session_lost = True
    return (
        kept,
        {key: proposals[key] for key in kept if key in proposals},
        {key: keys[key] for key in kept if key in keys},
    )


def blocked_by_unresolved(flows: Mapping[str, Flow], proposal_id: UUID) -> bool:
    return any(key != str(proposal_id) and f.state in UNRESOLVED for key, f in flows.items())


def action(
    proposal: Proposal, flow: Flow, now: datetime, *, blocked: bool = False
) -> Action | None:
    if flow.state in UNRESOLVED:
        return Action("Check booking status", enabled=not flow.unverifiable)
    if flow.state is ConfirmState.PENDING:
        open_ = proposal.status not in CLOSED_STATUSES and proposal.seconds_left(now) > 0
        return Action("Confirm booking", enabled=open_ and not blocked)
    return None


def uncertain_message(flow: Flow) -> str:
    if flow.unverifiable:
        return (
            "The booking outcome cannot be verified from this page: the session expired. "
            "The booking may exist."
        )
    return (
        "The booking outcome is unknown: the request may have reached the clinic. "
        "Check its status; this cannot book twice."
    )
