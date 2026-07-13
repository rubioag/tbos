import pytest

from tbos.ce4_decision.capital import allocate_capital


def test_full_stake_funded_when_capital_available() -> None:
    result = allocate_capital(bankroll_total=10_000, current_deployed=0, proposed_stake=500)
    assert result.deployed == 500
    assert result.capped is False


def test_reserved_equals_remainder() -> None:
    result = allocate_capital(bankroll_total=10_000, current_deployed=2_000, proposed_stake=500)
    assert result.reserved_system_wide == pytest.approx(10_000 - 2_000 - 500)


def test_stake_capped_when_exceeding_available_capital() -> None:
    result = allocate_capital(bankroll_total=10_000, current_deployed=9_800, proposed_stake=500)
    assert result.deployed == pytest.approx(200)
    assert result.capped is True


def test_zero_available_capital_yields_zero_deployment() -> None:
    result = allocate_capital(bankroll_total=10_000, current_deployed=10_000, proposed_stake=500)
    assert result.deployed == 0.0
    assert result.capped is True


def test_reasoning_is_populated() -> None:
    result = allocate_capital(bankroll_total=10_000, current_deployed=0, proposed_stake=500)
    assert result.reasoning
