import pytest

from tbos.ce3_edge.fair_odds import fair_odds_from_probability


def test_fifty_fifty_gives_even_money_fair_odds() -> None:
    assert fair_odds_from_probability(0.5) == pytest.approx(2.0)


def test_high_probability_gives_low_fair_odds() -> None:
    assert fair_odds_from_probability(0.8) == pytest.approx(1.25)


def test_low_probability_gives_high_fair_odds() -> None:
    assert fair_odds_from_probability(0.1) == pytest.approx(10.0)


def test_probability_zero_raises() -> None:
    with pytest.raises(ValueError):
        fair_odds_from_probability(0.0)


def test_probability_one_raises() -> None:
    with pytest.raises(ValueError):
        fair_odds_from_probability(1.0)


def test_probability_out_of_range_raises() -> None:
    with pytest.raises(ValueError):
        fair_odds_from_probability(1.5)
