import pytest

from app.domain.proposals import PROPOSAL_TTL, TERMINAL_STATES, transition


@pytest.mark.parametrize("target", sorted(TERMINAL_STATES))
def test_pending_can_enter_each_approved_terminal_state(target):
    assert transition("PENDING", target) == target


@pytest.mark.parametrize("current", sorted(TERMINAL_STATES))
@pytest.mark.parametrize("target", ["PENDING", *sorted(TERMINAL_STATES)])
def test_terminal_state_cannot_change_or_revert(current, target):
    with pytest.raises(ValueError):
        transition(current, target)


def test_pending_cannot_renew_itself_or_enter_unknown_state():
    for target in ["PENDING", "INVALID"]:
        with pytest.raises(ValueError):
            transition("PENDING", target)
    assert PROPOSAL_TTL.total_seconds() == 600
