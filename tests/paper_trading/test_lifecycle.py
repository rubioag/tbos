import pytest

from tbos.inf1_config.taxonomy import PaperTradingStatus
from tbos.paper_trading.lifecycle import InvalidRunTransition, validate_transition


def test_active_can_transition_to_passed() -> None:
    validate_transition(PaperTradingStatus.ACTIVE, PaperTradingStatus.PASSED)


def test_active_can_transition_to_failed() -> None:
    validate_transition(PaperTradingStatus.ACTIVE, PaperTradingStatus.FAILED)


def test_active_can_transition_to_aborted() -> None:
    validate_transition(PaperTradingStatus.ACTIVE, PaperTradingStatus.ABORTED)


def test_terminal_states_have_no_further_transitions() -> None:
    for terminal in (PaperTradingStatus.PASSED, PaperTradingStatus.FAILED, PaperTradingStatus.ABORTED):
        with pytest.raises(InvalidRunTransition):
            validate_transition(terminal, PaperTradingStatus.ACTIVE)
