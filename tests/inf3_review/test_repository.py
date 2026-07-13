import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from tbos.inf1_config.taxonomy import (
    DecisionConfidenceTier,
    DecisionQualityClassification,
    FindingStatus,
    MistakeCategory,
    OutcomeResult,
)
from tbos.inf3_review import repository
from tbos.inf3_review.calibration import brier_score, compute_finding_confidence, reliability_curve
from tbos.inf3_review.decision_quality import classify_decision
from tbos.inf3_review.mistake_patterns import MistakeOccurrence, aggregate_mistake_patterns

NOW = datetime.now(timezone.utc)


def test_record_and_read_calibration(session: Session) -> None:
    predictions = [(0.7, True), (0.3, False), (0.6, True)]
    fc = compute_finding_confidence(
        sample_size=3, min_sample_size_for_full_confidence=500,
        version_consistency_score=1.0, recency_score=1.0, evidence_stability_score=1.0,
    )
    row = repository.record_calibration(
        session,
        scope={"model_id": "serve_model", "engine_version": "1.0.0"},
        sample_size=3,
        brier=brier_score(predictions),
        curve=reliability_curve(predictions),
        finding_confidence=fc,
    )
    session.commit()
    assert row.sample_size == 3
    assert row.scope["model_id"] == "serve_model"


def test_record_decision_quality_and_distribution(session: Session) -> None:
    for tier, outcome in [
        (DecisionConfidenceTier.STRONG, OutcomeResult.WIN),
        (DecisionConfidenceTier.STRONG, OutcomeResult.LOSS),
        (DecisionConfidenceTier.WEAK, OutcomeResult.LOSS),
    ]:
        record = classify_decision(bet_id=uuid.uuid4(), confidence_tier=tier, outcome=outcome, evaluated_at=NOW)
        repository.record_decision_quality(session, record)
    session.commit()

    distribution = repository.get_decision_quality_distribution(session)
    assert distribution[DecisionQualityClassification.GOOD_DECISION_GOOD_OUTCOME.value] == 1
    assert distribution[DecisionQualityClassification.GOOD_DECISION_BAD_OUTCOME.value] == 1
    assert distribution[DecisionQualityClassification.BAD_DECISION_BAD_OUTCOME.value] == 1


def test_record_mistake_pattern(session: Session) -> None:
    occurrences = [
        MistakeOccurrence(bet_id=uuid.uuid4(), category=MistakeCategory.MODEL_ERROR, occurred_at=NOW, description="x"),
    ]
    [pattern] = aggregate_mistake_patterns(occurrences, min_sample_size_for_full_confidence=10, now=NOW)
    row = repository.record_mistake_pattern(session, pattern)
    session.commit()
    assert row.recurrence_count == 1
    assert row.category == MistakeCategory.MODEL_ERROR.value


def _submit_finding(session: Session) -> uuid.UUID:
    fc = compute_finding_confidence(
        sample_size=500, min_sample_size_for_full_confidence=500,
        version_consistency_score=1.0, recency_score=1.0, evidence_stability_score=1.0,
    )
    row = repository.submit_candidate_finding(
        session,
        source_type="CalibrationRecord",
        source_id=uuid.uuid4(),
        statement="Serve Model is well-calibrated on hard courts",
        finding_confidence=fc,
        proposed_for="IL2_KnowledgeBase",
    )
    session.commit()
    return row.id


def test_finding_starts_as_candidate(session: Session) -> None:
    finding_id = _submit_finding(session)
    findings = repository.list_findings_by_status(session, FindingStatus.CANDIDATE)
    assert finding_id in [f.id for f in findings]


def test_finding_full_promotion_path_requires_human_reviewer(session: Session) -> None:
    finding_id = _submit_finding(session)

    repository.transition_finding(session, finding_id, FindingStatus.UNDER_REVIEW, notes="queued for review")
    session.commit()

    with pytest.raises(repository.PromotionRequiresHumanReviewer):
        repository.transition_finding(session, finding_id, FindingStatus.PROMOTED, notes="looks good")

    repository.transition_finding(
        session, finding_id, FindingStatus.PROMOTED, notes="approved after review", reviewer_id="alice"
    )
    session.commit()

    promoted = repository.list_findings_by_status(session, FindingStatus.PROMOTED)
    assert finding_id in [f.id for f in promoted]


def test_finding_invalid_transition_rejected(session: Session) -> None:
    finding_id = _submit_finding(session)
    with pytest.raises(repository.InvalidFindingTransition):
        repository.transition_finding(
            session, finding_id, FindingStatus.PROMOTED, notes="skip review", reviewer_id="alice"
        )


def test_finding_terminal_states_have_no_further_transitions(session: Session) -> None:
    finding_id = _submit_finding(session)
    repository.transition_finding(session, finding_id, FindingStatus.REJECTED, notes="not significant")
    session.commit()

    with pytest.raises(repository.InvalidFindingTransition):
        repository.transition_finding(
            session, finding_id, FindingStatus.UNDER_REVIEW, notes="reconsider", reviewer_id="bob"
        )
