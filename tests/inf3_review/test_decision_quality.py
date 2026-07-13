import uuid
from datetime import datetime, timezone

from tbos.inf1_config.taxonomy import DecisionConfidenceTier, DecisionQualityClassification, OutcomeResult
from tbos.inf3_review.decision_quality import classify_decision

BET_ID = uuid.uuid4()
NOW = datetime.now(timezone.utc)


def test_strong_confidence_win_is_good_decision_good_outcome() -> None:
    record = classify_decision(
        bet_id=BET_ID, confidence_tier=DecisionConfidenceTier.STRONG, outcome=OutcomeResult.WIN, evaluated_at=NOW
    )
    assert record.classification == DecisionQualityClassification.GOOD_DECISION_GOOD_OUTCOME


def test_strong_confidence_loss_is_good_decision_bad_outcome() -> None:
    """The whole point of this classification: a well-reasoned bet that
    loses is NOT the same failure mode as a poorly-reasoned bet that loses.
    """
    record = classify_decision(
        bet_id=BET_ID, confidence_tier=DecisionConfidenceTier.STRONG, outcome=OutcomeResult.LOSS, evaluated_at=NOW
    )
    assert record.classification == DecisionQualityClassification.GOOD_DECISION_BAD_OUTCOME


def test_weak_confidence_win_is_bad_decision_good_outcome() -> None:
    """Getting lucky on a bad bet must never be scored as validation."""
    record = classify_decision(
        bet_id=BET_ID, confidence_tier=DecisionConfidenceTier.WEAK, outcome=OutcomeResult.WIN, evaluated_at=NOW
    )
    assert record.classification == DecisionQualityClassification.BAD_DECISION_GOOD_OUTCOME


def test_weak_confidence_loss_is_bad_decision_bad_outcome() -> None:
    record = classify_decision(
        bet_id=BET_ID, confidence_tier=DecisionConfidenceTier.WEAK, outcome=OutcomeResult.LOSS, evaluated_at=NOW
    )
    assert record.classification == DecisionQualityClassification.BAD_DECISION_BAD_OUTCOME


def test_marginal_confidence_is_always_ambiguous_regardless_of_outcome() -> None:
    for outcome in (OutcomeResult.WIN, OutcomeResult.LOSS):
        record = classify_decision(
            bet_id=BET_ID, confidence_tier=DecisionConfidenceTier.MARGINAL, outcome=outcome, evaluated_at=NOW
        )
        assert record.classification == DecisionQualityClassification.AMBIGUOUS


def test_void_and_push_outcomes_are_always_ambiguous_regardless_of_confidence() -> None:
    for outcome in (OutcomeResult.VOID, OutcomeResult.PUSH):
        for tier in (DecisionConfidenceTier.STRONG, DecisionConfidenceTier.WEAK):
            record = classify_decision(bet_id=BET_ID, confidence_tier=tier, outcome=outcome, evaluated_at=NOW)
            assert record.classification == DecisionQualityClassification.AMBIGUOUS
