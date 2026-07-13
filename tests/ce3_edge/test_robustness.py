import pytest

from tbos.ce3_edge.ev import EVDistribution
from tbos.ce3_edge.robustness import compute_robustness


def _dist(worst: float, best: float) -> EVDistribution:
    return EVDistribution(expected=(worst + best) / 2, worst_case=worst, best_case=best, confidence_interval=(worst, best))


def test_entirely_positive_range_is_fully_robust() -> None:
    assert compute_robustness(_dist(0.05, 0.20)).score == 1.0


def test_entirely_negative_range_has_zero_robustness() -> None:
    assert compute_robustness(_dist(-0.20, -0.05)).score == 0.0


def test_range_straddling_zero_is_partial() -> None:
    result = compute_robustness(_dist(-0.10, 0.30))
    # fraction of range that's positive: 0.30 / (0.30 - (-0.10)) = 0.75
    assert result.score == pytest.approx(0.75)


def test_same_expected_ev_can_have_very_different_robustness() -> None:
    """The core motivating property: +4% EV narrow-uncertainty vs +4% EV
    wide-uncertainty must not be treated as the same opportunity.
    """
    narrow = _dist(0.02, 0.06)   # both worst and best positive -> fully robust
    wide = _dist(-0.10, 0.18)    # same expected (0.04), but straddles zero
    assert compute_robustness(narrow).score > compute_robustness(wide).score


def test_boundary_at_exactly_zero_worst_case_is_fully_robust() -> None:
    assert compute_robustness(_dist(0.0, 0.10)).score == 1.0
