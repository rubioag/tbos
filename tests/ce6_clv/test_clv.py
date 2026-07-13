import pytest

from tbos.ce6_clv.clv import compute_clv, implied_probability, vig_adjusted_probability


def test_implied_probability_basic() -> None:
    assert implied_probability(2.0) == pytest.approx(0.5)
    assert implied_probability(4.0) == pytest.approx(0.25)


def test_implied_probability_rejects_odds_at_or_below_one() -> None:
    with pytest.raises(ValueError):
        implied_probability(1.0)
    with pytest.raises(ValueError):
        implied_probability(0.5)


def test_vig_adjusted_probability_without_opponent_is_raw_and_flagged() -> None:
    result = vig_adjusted_probability(2.0, None)
    assert result.probability == pytest.approx(0.5)
    assert result.vig_adjusted is False


def test_vig_adjusted_probability_with_opponent_normalizes_to_one() -> None:
    # both sides at 1.91 implies 2*0.5236 = 1.047 total (typical vig)
    a = vig_adjusted_probability(1.91, 1.91)
    assert a.probability == pytest.approx(0.5)
    assert a.vig_adjusted is True


def test_vig_adjusted_probability_asymmetric_odds() -> None:
    result = vig_adjusted_probability(1.5, 3.0)  # raw: 0.667 and 0.333, sum=1.0 exactly (no vig here)
    assert result.probability == pytest.approx(2 / 3)


def test_vig_adjusted_probability_unknown_method_raises() -> None:
    with pytest.raises(ValueError):
        vig_adjusted_probability(2.0, 2.0, method="shin")


def test_compute_clv_positive_when_closing_probability_higher() -> None:
    # placed at odds 2.2 (implied 0.4545), closed at 2.0 (implied 0.5) -> market moved our way
    calc = compute_clv(placed_odds=2.2, closing_odds=2.0)
    assert calc.clv_value > 0


def test_compute_clv_negative_when_closing_probability_lower() -> None:
    calc = compute_clv(placed_odds=1.8, closing_odds=2.2)
    assert calc.clv_value < 0


def test_compute_clv_zero_when_odds_unchanged() -> None:
    calc = compute_clv(placed_odds=1.9, closing_odds=1.9)
    assert calc.clv_value == pytest.approx(0.0)


def test_compute_clv_vig_adjusted_flag_requires_both_sides_both_times() -> None:
    with_opponent = compute_clv(placed_odds=1.9, closing_odds=1.85, placed_opponent_odds=1.9, closing_opponent_odds=1.95)
    assert with_opponent.vig_adjusted is True

    missing_one_side = compute_clv(placed_odds=1.9, closing_odds=1.85, placed_opponent_odds=1.9, closing_opponent_odds=None)
    assert missing_one_side.vig_adjusted is False
