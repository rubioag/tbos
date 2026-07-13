import pytest

from tbos.ce3_edge.ev import compute_ev_distribution


def test_expected_ev_matches_standard_formula() -> None:
    dist = compute_ev_distribution(0.6, 0.0, 2.0)
    assert dist.expected == pytest.approx(0.6 * 2.0 - 1.0)


def test_zero_uncertainty_collapses_best_worst_to_expected() -> None:
    dist = compute_ev_distribution(0.6, 0.0, 2.0)
    assert dist.best_case == pytest.approx(dist.expected)
    assert dist.worst_case == pytest.approx(dist.expected)


def test_uncertainty_widens_the_range_around_expected() -> None:
    dist = compute_ev_distribution(0.6, 0.1, 2.0)
    assert dist.worst_case < dist.expected < dist.best_case


def test_confidence_interval_matches_worst_and_best() -> None:
    dist = compute_ev_distribution(0.6, 0.1, 2.0)
    assert dist.confidence_interval == (dist.worst_case, dist.best_case)


def test_probability_clamped_at_bounds_under_large_uncertainty() -> None:
    """probability=0.05 with uncertainty=0.5 would go negative without
    clamping — must never produce a nonsensical p<0 EV calculation.
    """
    dist = compute_ev_distribution(0.05, 0.5, 3.0)
    # worst_case uses clamp01(0.05-0.5)=0.0 -> EV = -1.0 exactly
    assert dist.worst_case == pytest.approx(-1.0)


def test_offered_odds_at_or_below_one_raises() -> None:
    with pytest.raises(ValueError):
        compute_ev_distribution(0.6, 0.1, 1.0)
    with pytest.raises(ValueError):
        compute_ev_distribution(0.6, 0.1, 0.5)


def test_negative_ev_when_offered_odds_below_fair() -> None:
    dist = compute_ev_distribution(0.6, 0.0, 1.5)  # fair odds would be ~1.67
    assert dist.expected < 0
