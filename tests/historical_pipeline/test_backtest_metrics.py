import math

from tbos.historical_pipeline.backtest import (
    MatchPrediction,
    accuracy,
    brier_score,
    coverage,
    expected_calibration_error,
    log_loss,
    mcnemar_test,
)


def _pred(
    match_id: str, prob: float | None, actual: int, abstained: bool = False,
) -> MatchPrediction:
    return MatchPrediction(
        match_id=match_id, predicted_probability_player_a=prob, actual_outcome_player_a=actual,
        fully_abstained=abstained, participating_model_ids=["serve_model"] if not abstained else [],
    )


def test_coverage_counts_non_abstained_fraction() -> None:
    preds = [_pred("m1", 0.6, 1), _pred("m2", None, 0, abstained=True)]
    assert coverage(preds) == 0.5


def test_coverage_empty_list_is_zero_not_crash() -> None:
    assert coverage([]) == 0.0


def test_accuracy_perfect_predictions() -> None:
    preds = [_pred("m1", 0.9, 1), _pred("m2", 0.1, 0)]
    assert accuracy(preds) == 1.0


def test_accuracy_all_wrong() -> None:
    preds = [_pred("m1", 0.9, 0), _pred("m2", 0.1, 1)]
    assert accuracy(preds) == 0.0


def test_accuracy_ignores_abstained_matches() -> None:
    preds = [_pred("m1", 0.9, 1), _pred("m2", None, 0, abstained=True)]
    assert accuracy(preds) == 1.0


def test_accuracy_none_when_all_abstained() -> None:
    assert accuracy([_pred("m1", None, 1, abstained=True)]) is None


def test_log_loss_confident_correct_prediction_near_zero() -> None:
    preds = [_pred("m1", 0.999, 1)]
    assert log_loss(preds) < 0.01


def test_log_loss_confident_wrong_prediction_is_large() -> None:
    preds = [_pred("m1", 0.001, 1)]
    assert log_loss(preds) > 5.0


def test_log_loss_matches_hand_computed_value() -> None:
    preds = [_pred("m1", 0.7, 1), _pred("m2", 0.3, 0)]
    expected = -(math.log(0.7) + math.log(0.7)) / 2.0  # both are "correct-direction" 0.7 confidence
    assert abs(log_loss(preds) - expected) < 1e-9


def test_brier_score_perfect_prediction_is_zero() -> None:
    assert brier_score([_pred("m1", 1.0, 1)]) == 0.0


def test_brier_score_matches_hand_computed_value() -> None:
    preds = [_pred("m1", 0.8, 1), _pred("m2", 0.2, 0)]
    expected = ((0.8 - 1) ** 2 + (0.2 - 0) ** 2) / 2.0
    assert abs(brier_score(preds) - expected) < 1e-9


def test_ece_perfectly_calibrated_bucket_is_zero() -> None:
    # 10 predictions all at 0.7, 7 of 10 actually win -> mean_pred == mean_actual == 0.7.
    preds = [_pred(f"m{i}", 0.7, 1 if i < 7 else 0) for i in range(10)]
    assert expected_calibration_error(preds, num_bins=10) < 1e-9


def test_ece_miscalibrated_bucket_is_positive() -> None:
    # All predict 0.9 confidence but only half actually win -> should be badly miscalibrated.
    preds = [_pred(f"m{i}", 0.9, 1 if i < 5 else 0) for i in range(10)]
    assert expected_calibration_error(preds, num_bins=10) > 0.3


def test_mcnemar_identical_predictions_have_no_discordant_pairs() -> None:
    baseline = [_pred("m1", 0.9, 1), _pred("m2", 0.1, 0)]
    treatment = [_pred("m1", 0.9, 1), _pred("m2", 0.1, 0)]
    result = mcnemar_test(baseline, treatment)
    assert result["n_discordant"] == 0
    assert result["p_value"] == 1.0


def test_mcnemar_only_pairs_matches_present_and_non_abstained_in_both() -> None:
    baseline = [_pred("m1", 0.9, 1), _pred("m2", None, 0, abstained=True)]
    treatment = [_pred("m1", 0.9, 1), _pred("m2", 0.9, 0)]
    result = mcnemar_test(baseline, treatment)
    # m2 abstained in baseline -> excluded from the paired comparison.
    assert result["n_paired"] == 1


def test_mcnemar_treatment_strictly_better_gives_low_p_value_with_enough_discordant_pairs() -> None:
    baseline = [_pred(f"m{i}", 0.1, 1) for i in range(30)]  # all wrong
    treatment = [_pred(f"m{i}", 0.9, 1) for i in range(30)]  # all correct
    result = mcnemar_test(baseline, treatment)
    assert result["n_discordant"] == 30
    assert result["p_value"] < 0.05
    assert result["reliable_approximation"] is True
