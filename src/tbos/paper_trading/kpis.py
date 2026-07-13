"""Paper Trading KPI computation — pure function over the bets recorded
during a run. Calibration/ROI/drawdown are left None (never fabricated):
they need settled match outcomes and a bankroll simulation across
settled bets, neither of which Paper Trading has a live data feed for yet.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from tbos.inf1_config.taxonomy import ConfidenceFlag
from tbos.paper_trading.schemas import PaperTradingBetRecord, PaperTradingKPISnapshot


def compute_kpis(run_id: uuid.UUID, bets: list[PaperTradingBetRecord], *, evaluated_at: datetime) -> PaperTradingKPISnapshot:
    sample_size = len(bets)

    if sample_size == 0:
        return PaperTradingKPISnapshot(
            run_id=run_id, evaluated_at=evaluated_at, sample_size=0,
            coverage_rate=0.0, abstention_rate=0.0, action_type_distribution={},
            structural_errors_count=0, clv_sample_size=0, clv_mean=None, clv_positive_rate=None,
            calibration_brier_score=None, roi_directional=None, max_drawdown_simulated=None,
        )

    covered = [b for b in bets if b.confidence_flag != ConfidenceFlag.ABSTAINED]
    coverage_rate = len(covered) / sample_size
    abstention_rate = 1.0 - coverage_rate

    action_counts: dict[str, int] = {}
    for b in bets:
        key = b.action_type.value if b.action_type is not None else "NONE"
        action_counts[key] = action_counts.get(key, 0) + 1
    action_type_distribution = {k: v / sample_size for k, v in action_counts.items()}

    structural_errors_count = sum(1 for b in bets if b.structural_error)

    clv_values = [b.clv_value for b in bets if b.clv_value is not None]
    clv_sample_size = len(clv_values)
    clv_mean = sum(clv_values) / clv_sample_size if clv_sample_size else None
    clv_positive_rate = (sum(1 for v in clv_values if v > 0) / clv_sample_size) if clv_sample_size else None

    return PaperTradingKPISnapshot(
        run_id=run_id, evaluated_at=evaluated_at, sample_size=sample_size,
        coverage_rate=coverage_rate, abstention_rate=abstention_rate,
        action_type_distribution=action_type_distribution, structural_errors_count=structural_errors_count,
        clv_sample_size=clv_sample_size, clv_mean=clv_mean, clv_positive_rate=clv_positive_rate,
        calibration_brier_score=None, roi_directional=None, max_drawdown_simulated=None,
    )
