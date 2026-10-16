"""One-way proposal state transitions; booking snapshots never change."""

from datetime import timedelta
from typing import Literal

ProposalStatus = Literal["PENDING", "CONFIRMED", "CONFLICTED", "EXPIRED", "SUPERSEDED"]
PROPOSAL_TTL = timedelta(minutes=10)
TERMINAL_STATES = frozenset({"CONFIRMED", "CONFLICTED", "EXPIRED", "SUPERSEDED"})


def transition(current: str, target: str) -> ProposalStatus:
    if current != "PENDING" or target not in TERMINAL_STATES:
        raise ValueError("Proposal terminal states cannot be changed or reverted.")
    return target
