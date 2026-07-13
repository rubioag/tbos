import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from tbos.inf1_config.taxonomy import ApprovalDecision
from tbos.paper_trading import repository
from tbos.paper_trading.approval import ApprovalRequiresHumanReviewer, evaluate_approval_criteria, record_decision
from tbos.paper_trading.schemas import PaperTradingKPISnapshot

RUN_ID = uuid.uuid4()
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _kpis(**overrides) -> PaperTradingKPISnapshot:
    defaults = dict(
        run_id=RUN_ID, evaluated_at=NOW, sample_size=250, coverage_rate=0.6, abstention_rate=0.4,
        action_type_distribution={"BET_NOW": 0.6}, structural_errors_count=0, clv_sample_size=100,
        clv_mean=0.02, clv_positive_rate=0.6, calibration_brier_score=None, roi_directional=None,
        max_drawdown_simulated=None,
    )
    defaults.update(overrides)
    return PaperTradingKPISnapshot(**defaults)


def test_all_criteria_met_when_kpis_are_strong() -> None:
    criteria = evaluate_approval_criteria(_kpis())
    assert criteria.all_met is True


def test_sample_size_below_minimum_fails_that_criterion() -> None:
    criteria = evaluate_approval_criteria(_kpis(sample_size=10))
    assert criteria.min_sample_size_met is False
    assert criteria.all_met is False


def test_negative_clv_fails_significance_criterion() -> None:
    criteria = evaluate_approval_criteria(_kpis(clv_mean=-0.01))
    assert criteria.clv_significantly_positive is False


def test_thin_clv_sample_fails_significance_even_if_positive() -> None:
    criteria = evaluate_approval_criteria(_kpis(clv_mean=0.05, clv_sample_size=5))
    assert criteria.clv_significantly_positive is False


def test_structural_errors_fail_that_criterion() -> None:
    criteria = evaluate_approval_criteria(_kpis(structural_errors_count=1))
    assert criteria.zero_structural_errors is False
    assert criteria.all_met is False


def test_coverage_outside_range_fails_that_criterion() -> None:
    criteria = evaluate_approval_criteria(_kpis(coverage_rate=0.01))
    assert criteria.coverage_within_expected_range is False


def test_record_decision_requires_human_reviewer(session: Session) -> None:
    criteria = evaluate_approval_criteria(_kpis())
    with pytest.raises(ApprovalRequiresHumanReviewer):
        record_decision(session, RUN_ID, criteria, decision=ApprovalDecision.APPROVE_LIVE, human_reviewer_id=None, notes="x", as_of=NOW)
    with pytest.raises(ApprovalRequiresHumanReviewer):
        record_decision(session, RUN_ID, criteria, decision=ApprovalDecision.APPROVE_LIVE, human_reviewer_id="", notes="x", as_of=NOW)


def test_record_decision_persists_with_reviewer(session: Session) -> None:
    criteria = evaluate_approval_criteria(_kpis())
    record_decision(session, RUN_ID, criteria, decision=ApprovalDecision.APPROVE_LIVE, human_reviewer_id="alice", notes="looks good", as_of=NOW)
    session.commit()

    rows = repository.list_approvals_for_run(session, RUN_ID)
    assert len(rows) == 1
    assert rows[0].payload["human_reviewer_id"] == "alice"


def test_reject_decision_also_requires_reviewer(session: Session) -> None:
    criteria = evaluate_approval_criteria(_kpis(structural_errors_count=1))
    with pytest.raises(ApprovalRequiresHumanReviewer):
        record_decision(session, RUN_ID, criteria, decision=ApprovalDecision.REJECT, human_reviewer_id=None, notes="x", as_of=NOW)
