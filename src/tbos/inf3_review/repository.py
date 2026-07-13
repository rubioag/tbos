"""INF.3 repository. Persists Calibration/DecisionQuality/MistakePattern
records (all append-only) and manages the CandidateFinding review gate —
promotion to PROMOTED always requires a human reviewer_id, never automatic
regardless of how strong finding_confidence is.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from tbos.inf1_config.taxonomy import FindingStatus
from tbos.inf3_review.calibration import FindingConfidence, ReliabilityBucket
from tbos.inf3_review.decision_quality import DecisionQualityRecord
from tbos.inf3_review.mistake_patterns import MistakePatternRecord
from tbos.inf3_review.models import (
    CalibrationRecordRow,
    CandidateFindingRow,
    DecisionQualityRecordRow,
    FindingReviewEvent,
    MistakePatternRecordRow,
)

_ALLOWED_TRANSITIONS: dict[FindingStatus, set[FindingStatus]] = {
    FindingStatus.CANDIDATE: {FindingStatus.UNDER_REVIEW, FindingStatus.REJECTED},
    FindingStatus.UNDER_REVIEW: {FindingStatus.PROMOTED, FindingStatus.REJECTED},
    FindingStatus.PROMOTED: set(),
    FindingStatus.REJECTED: set(),
}


class InvalidFindingTransition(RuntimeError):
    pass


class PromotionRequiresHumanReviewer(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def record_calibration(
    session: Session,
    *,
    scope: dict,
    sample_size: int,
    brier: float,
    curve: list[ReliabilityBucket],
    finding_confidence: FindingConfidence,
) -> CalibrationRecordRow:
    row = CalibrationRecordRow(
        scope=scope,
        sample_size=sample_size,
        brier_score=brier,
        reliability_curve=[b.model_dump(mode="json") for b in curve],
        finding_confidence=finding_confidence.model_dump(mode="json"),
    )
    session.add(row)
    session.flush()
    return row


# ---------------------------------------------------------------------------
# Decision Quality
# ---------------------------------------------------------------------------


def record_decision_quality(session: Session, record: DecisionQualityRecord) -> DecisionQualityRecordRow:
    row = DecisionQualityRecordRow(
        bet_id=record.bet_id,
        classification=record.classification.value,
        confidence_tier=record.confidence_tier.value,
        outcome=record.outcome.value,
        classification_rules_version=record.classification_rules_version,
        evaluated_at=record.evaluated_at,
    )
    session.add(row)
    session.flush()
    return row


def get_decision_quality_distribution(session: Session) -> dict[str, int]:
    rows = session.execute(select(DecisionQualityRecordRow)).scalars().all()
    distribution: dict[str, int] = {}
    for row in rows:
        distribution[row.classification] = distribution.get(row.classification, 0) + 1
    return distribution


# ---------------------------------------------------------------------------
# Mistake Patterns
# ---------------------------------------------------------------------------


def record_mistake_pattern(session: Session, record: MistakePatternRecord) -> MistakePatternRecordRow:
    row = MistakePatternRecordRow(
        category=record.category.value,
        time_window_start=record.time_window_start,
        time_window_end=record.time_window_end,
        occurrences=[str(bet_id) for bet_id in record.occurrences],
        recurrence_count=record.recurrence_count,
        finding_confidence=record.finding_confidence.model_dump(mode="json"),
    )
    session.add(row)
    session.flush()
    return row


# ---------------------------------------------------------------------------
# Candidate Findings + Human Review Gate
# ---------------------------------------------------------------------------


def submit_candidate_finding(
    session: Session,
    *,
    source_type: str,
    source_id: uuid.UUID,
    statement: str,
    finding_confidence: FindingConfidence,
    proposed_for: str,
) -> CandidateFindingRow:
    row = CandidateFindingRow(
        source_type=source_type,
        source_id=source_id,
        statement=statement,
        finding_confidence=finding_confidence.model_dump(mode="json"),
        proposed_for=proposed_for,
        status=FindingStatus.CANDIDATE.value,
    )
    session.add(row)
    session.flush()
    return row


def transition_finding(
    session: Session,
    finding_id: uuid.UUID,
    to_status: FindingStatus,
    *,
    notes: str,
    reviewer_id: str | None = None,
) -> CandidateFindingRow:
    finding = session.get(CandidateFindingRow, finding_id)
    if finding is None:
        raise ValueError(f"unknown finding {finding_id}")

    current = FindingStatus(finding.status)
    if to_status not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidFindingTransition(f"{current} -> {to_status} is not a valid transition")

    if to_status == FindingStatus.PROMOTED and not reviewer_id:
        raise PromotionRequiresHumanReviewer(
            "promotion to PROMOTED always requires a human reviewer_id — never automatic, "
            "regardless of finding_confidence"
        )

    session.add(
        FindingReviewEvent(
            finding_id=finding.id,
            from_status=current.value,
            to_status=to_status.value,
            reviewer_id=reviewer_id,
            notes=notes,
        )
    )
    finding.status = to_status.value
    session.flush()
    return finding


def list_findings_by_status(session: Session, status: FindingStatus) -> list[CandidateFindingRow]:
    stmt = select(CandidateFindingRow).where(CandidateFindingRow.status == status.value)
    return list(session.execute(stmt).scalars().all())
