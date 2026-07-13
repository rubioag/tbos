import uuid
from datetime import datetime, timezone

from tbos.inf1_config.taxonomy import ActionType, ConfidenceFlag
from tbos.paper_trading.kpis import compute_kpis
from tbos.paper_trading.schemas import PaperTradingBetRecord

RUN_ID = uuid.uuid4()
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _bet(*, confidence=ConfidenceFlag.NORMAL, action=ActionType.BET_NOW, clv=None, error=False) -> PaperTradingBetRecord:
    return PaperTradingBetRecord(
        run_id=RUN_ID, match_id="m", confidence_flag=confidence, action_type=action,
        clv_value=clv, structural_error=error, error_detail=None, recorded_at=NOW,
    )


def test_empty_bets_yields_zeroed_snapshot() -> None:
    kpis = compute_kpis(RUN_ID, [], evaluated_at=NOW)
    assert kpis.sample_size == 0
    assert kpis.clv_mean is None


def test_coverage_and_abstention_rates() -> None:
    bets = [_bet(confidence=ConfidenceFlag.NORMAL), _bet(confidence=ConfidenceFlag.ABSTAINED), _bet(confidence=ConfidenceFlag.DEGRADED), _bet(confidence=ConfidenceFlag.ABSTAINED)]
    kpis = compute_kpis(RUN_ID, bets, evaluated_at=NOW)
    assert kpis.coverage_rate == 0.5
    assert kpis.abstention_rate == 0.5


def test_action_type_distribution_sums_to_one() -> None:
    bets = [_bet(action=ActionType.BET_NOW), _bet(action=ActionType.DEFER), _bet(action=ActionType.PASS), _bet(action=ActionType.BET_NOW)]
    kpis = compute_kpis(RUN_ID, bets, evaluated_at=NOW)
    assert abs(sum(kpis.action_type_distribution.values()) - 1.0) < 1e-9
    assert kpis.action_type_distribution["BET_NOW"] == 0.5


def test_action_type_none_counted_when_abstained_before_ce4() -> None:
    bets = [_bet(confidence=ConfidenceFlag.ABSTAINED, action=None)]
    kpis = compute_kpis(RUN_ID, bets, evaluated_at=NOW)
    assert kpis.action_type_distribution["NONE"] == 1.0


def test_structural_errors_counted() -> None:
    bets = [_bet(error=True), _bet(error=False), _bet(error=True)]
    kpis = compute_kpis(RUN_ID, bets, evaluated_at=NOW)
    assert kpis.structural_errors_count == 2


def test_clv_mean_and_positive_rate() -> None:
    bets = [_bet(clv=0.03), _bet(clv=-0.01), _bet(clv=0.05), _bet(clv=None)]
    kpis = compute_kpis(RUN_ID, bets, evaluated_at=NOW)
    assert kpis.clv_sample_size == 3
    assert abs(kpis.clv_mean - (0.03 - 0.01 + 0.05) / 3) < 1e-9
    assert abs(kpis.clv_positive_rate - 2 / 3) < 1e-9


def test_deferred_metrics_are_none_not_fabricated() -> None:
    kpis = compute_kpis(RUN_ID, [_bet()], evaluated_at=NOW)
    assert kpis.calibration_brier_score is None
    assert kpis.roi_directional is None
    assert kpis.max_drawdown_simulated is None
