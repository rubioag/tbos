import pytest

from tbos.ce4_decision.stake import compute_stake, kelly_fraction


def test_kelly_fraction_positive_when_edge_exists() -> None:
    # fair odds for p=0.6 is 1.667; offered 2.0 is better than fair -> positive edge
    assert kelly_fraction(0.6, 2.0) > 0


def test_kelly_fraction_zero_when_odds_exactly_fair() -> None:
    assert kelly_fraction(0.5, 2.0) == pytest.approx(0.0, abs=1e-9)


def test_kelly_fraction_clamped_at_zero_when_no_edge() -> None:
    assert kelly_fraction(0.4, 2.0) == 0.0


def test_stake_scales_with_fractional_kelly_multiplier() -> None:
    full = compute_stake(bankroll_total=10_000, probability=0.6, offered_odds=2.0, robustness_score=1.0, uncertainty=0.0, fractional_kelly_multiplier=1.0)
    quarter = compute_stake(bankroll_total=10_000, probability=0.6, offered_odds=2.0, robustness_score=1.0, uncertainty=0.0, fractional_kelly_multiplier=0.25)
    assert quarter.stake_amount == pytest.approx(full.stake_amount * 0.25)


def test_lower_robustness_reduces_stake() -> None:
    robust = compute_stake(bankroll_total=10_000, probability=0.6, offered_odds=2.0, robustness_score=1.0, uncertainty=0.0, fractional_kelly_multiplier=0.25)
    fragile = compute_stake(bankroll_total=10_000, probability=0.6, offered_odds=2.0, robustness_score=0.3, uncertainty=0.0, fractional_kelly_multiplier=0.25)
    assert fragile.stake_amount < robust.stake_amount


def test_higher_uncertainty_reduces_stake() -> None:
    certain = compute_stake(bankroll_total=10_000, probability=0.6, offered_odds=2.0, robustness_score=1.0, uncertainty=0.0, fractional_kelly_multiplier=0.25)
    uncertain = compute_stake(bankroll_total=10_000, probability=0.6, offered_odds=2.0, robustness_score=1.0, uncertainty=0.5, fractional_kelly_multiplier=0.25)
    assert uncertain.stake_amount < certain.stake_amount


def test_maximum_uncertainty_yields_zero_stake() -> None:
    result = compute_stake(bankroll_total=10_000, probability=0.6, offered_odds=2.0, robustness_score=1.0, uncertainty=1.0, fractional_kelly_multiplier=0.25)
    assert result.stake_amount == pytest.approx(0.0)


def test_zero_robustness_yields_zero_stake() -> None:
    result = compute_stake(bankroll_total=10_000, probability=0.6, offered_odds=2.0, robustness_score=0.0, uncertainty=0.0, fractional_kelly_multiplier=0.25)
    assert result.stake_amount == 0.0


def test_no_edge_yields_zero_stake_regardless_of_confidence() -> None:
    result = compute_stake(bankroll_total=10_000, probability=0.4, offered_odds=2.0, robustness_score=1.0, uncertainty=0.0, fractional_kelly_multiplier=1.0)
    assert result.stake_amount == 0.0
