"""Paper Trading Protocol §E — Approval Gate. Criteria are computed
objectively; the decision itself always requires a human reviewer_id,
never automatic, matching the pattern already locked at IL.2/Model
Registry — even a run that passes every criterion still needs a human to
say APPROVE_LIVE.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from tbos.inf1_config.taxonomy import ApprovalDecision
from tbos.paper_trading import repository
from tbos.paper_trading.schemas import ApprovalCriteria, ApprovalRecord, PaperTradingKPISnapshot

DEFAULT_MIN_SAMPLE_SIZE = 200
DEFAULT_MIN_CLV_SAMPLE_FOR_SIGNIFICANCE = 50
DEFAULT_MIN_COVERAGE_RATE = 0.3
DEFAULT_MAX_COVERAGE_RATE = 1.0


class ApprovalRequiresHumanReviewer(RuntimeError):
    pass


def evaluate_approval_criteria(
    kpis: PaperTradingKPISnapshot,
    *,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    min_clv_sample_for_significance: int = DEFAULT_MIN_CLV_SAMPLE_FOR_SIGNIFICANCE,
    min_coverage_rate: float = DEFAULT_MIN_COVERAGE_RATE,
    max_coverage_rate: float = DEFAULT_MAX_COVERAGE_RATE,
) -> ApprovalCriteria:
    min_sample_size_met = kpis.sample_size >= min_sample_size

    clv_significantly_positive = (
        kpis.clv_mean is not None
        and kpis.clv_mean > 0
        and kpis.clv_sample_size >= min_clv_sample_for_significance
    )

    zero_structural_errors = kpis.structural_errors_count == 0

    coverage_within_expected_range = min_coverage_rate <= kpis.coverage_rate <= max_coverage_rate

    return ApprovalCriteria(
        min_sample_size_met=min_sample_size_met,
        clv_significantly_positive=clv_significantly_positive,
        zero_structural_errors=zero_structural_errors,
        coverage_within_expected_range=coverage_within_expected_range,
    )


def record_decision(
    session,
    run_id: uuid.UUID,
    criteria: ApprovalCriteria,
    *,
    decision: ApprovalDecision,
    human_reviewer_id: str | None,
    notes: str,
    as_of: datetime,
) -> ApprovalRecord:
    if not human_reviewer_id:
        raise ApprovalRequiresHumanReviewer(
            "Paper Trading approval decisions always require a human reviewer_id — "
            "never automatic, regardless of how many criteria are met"
        )

    record = ApprovalRecord(
        run_id=run_id, criteria=criteria, decision=decision, human_reviewer_id=human_reviewer_id,
        notes=notes, decided_at=as_of,
    )
    repository.record_approval(session, record)
    return record
