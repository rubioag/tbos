import pytest

from tbos.inf3_review.calibration import brier_score, compute_finding_confidence, reliability_curve


def test_brier_score_perfect_predictions_is_zero() -> None:
    assert brier_score([(1.0, True), (0.0, False)]) == 0.0


def test_brier_score_worst_case_is_one() -> None:
    assert brier_score([(0.0, True), (1.0, False)]) == 1.0


def test_brier_score_always_half_baseline() -> None:
    assert brier_score([(0.5, True), (0.5, False)]) == pytest.approx(0.25)


def test_brier_score_empty_raises() -> None:
    with pytest.raises(ValueError):
        brier_score([])


def test_reliability_curve_empty_is_empty() -> None:
    assert reliability_curve([]) == []


def test_reliability_curve_groups_by_bucket_and_reports_observed_frequency() -> None:
    predictions = [
        (0.65, True), (0.68, True), (0.62, False),  # bucket ~0.6-0.7: 2/3 wins
        (0.15, False), (0.12, False),                 # bucket ~0.1-0.2: 0/2 wins
    ]
    curve = reliability_curve(predictions, n_buckets=10)
    buckets = {round(b.predicted_bucket, 2): b for b in curve}
    assert buckets[0.65].count == 3
    assert buckets[0.65].observed_frequency == pytest.approx(2 / 3)
    assert buckets[0.15].count == 2
    assert buckets[0.15].observed_frequency == 0.0


def test_reliability_curve_clamps_p_equal_one_into_last_bucket() -> None:
    curve = reliability_curve([(1.0, True)], n_buckets=10)
    assert len(curve) == 1
    assert curve[0].count == 1


def test_finding_confidence_full_sample_and_all_axes_strong_is_near_one() -> None:
    fc = compute_finding_confidence(
        sample_size=500,
        min_sample_size_for_full_confidence=500,
        version_consistency_score=1.0,
        recency_score=1.0,
        evidence_stability_score=1.0,
    )
    assert fc.composite == pytest.approx(1.0)


def test_finding_confidence_low_sample_size_drags_composite_down() -> None:
    fc = compute_finding_confidence(
        sample_size=5,
        min_sample_size_for_full_confidence=500,
        version_consistency_score=1.0,
        recency_score=1.0,
        evidence_stability_score=1.0,
    )
    assert fc.sample_size_score == pytest.approx(5 / 500)
    # geometric mean of (0.01, 1, 1, 1) = 0.01**0.25 ≈ 0.316 — well below 1.0
    assert fc.composite == pytest.approx(0.01**0.25)
    assert fc.composite < 0.5


def test_finding_confidence_one_weak_axis_still_lowers_composite_even_with_big_sample() -> None:
    """Geometric mean means high statistical significance alone cannot
    mask a single untrustworthy axis (e.g. spans inconsistent versions).
    """
    strong_sample = compute_finding_confidence(
        sample_size=10_000,
        min_sample_size_for_full_confidence=500,
        version_consistency_score=0.1,  # spans many incompatible versions
        recency_score=1.0,
        evidence_stability_score=1.0,
    )
    assert strong_sample.composite < 0.6
