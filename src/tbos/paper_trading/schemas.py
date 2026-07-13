"""Paper Trading Protocol v1 — core schemas.

`PaperTradingBetRecord` is intentionally self-contained: rather than
reconstruct history after the fact from CE.4/CE.5/CE.6's separate
storage (they were never wired to write into INF.2's event-sourced Bet
Ledger — a real gap between the frozen spec and what got built), the
Paper Trading orchestrator (engine.py) captures a summary record at the
moment it drives each pipeline cycle. This is the honest v1 approach
given the actual state of the codebase.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from tbos.inf1_config.taxonomy import ActionType, ApprovalDecision, ConfidenceFlag, PaperTradingStatus

PROTOCOL_VERSION = "1.0.0"


class PaperTradingRun(BaseModel):
    run_id: uuid.UUID
    protocol_version: str
    start_date: datetime
    config_version_id_at_start: uuid.UUID
    status: PaperTradingStatus


class PaperTradingBetRecord(BaseModel):
    run_id: uuid.UUID
    match_id: str
    confidence_flag: ConfidenceFlag
    action_type: ActionType | None  # None if CE.2 abstained before CE.4 ever ran
    clv_value: float | None  # None if not computable (no closing tick, DEFER/PASS, etc.)
    structural_error: bool
    error_detail: str | None
    recorded_at: datetime


class PaperTradingKPISnapshot(BaseModel):
    run_id: uuid.UUID
    evaluated_at: datetime
    sample_size: int

    coverage_rate: float          # fraction of cycles that produced a NORMAL/DEGRADED prediction
    abstention_rate: float        # 1 - coverage_rate, kept explicit per spec naming
    action_type_distribution: dict[str, float]
    structural_errors_count: int

    clv_sample_size: int
    clv_mean: float | None
    clv_positive_rate: float | None  # fraction of CLV-bearing bets with clv_value > 0

    # Deferred: calibration (needs settled match outcomes, not wired to
    # Paper Trading yet), ROI, max_drawdown_simulated (needs a bankroll
    # simulation across settled bets) — None rather than fabricated.
    calibration_brier_score: float | None
    roi_directional: float | None
    max_drawdown_simulated: float | None


class ApprovalCriteria(BaseModel):
    min_sample_size_met: bool
    clv_significantly_positive: bool
    zero_structural_errors: bool
    coverage_within_expected_range: bool

    @property
    def all_met(self) -> bool:
        return self.min_sample_size_met and self.clv_significantly_positive and self.zero_structural_errors and self.coverage_within_expected_range


class ApprovalRecord(BaseModel):
    run_id: uuid.UUID
    criteria: ApprovalCriteria
    decision: ApprovalDecision
    human_reviewer_id: str
    notes: str
    decided_at: datetime
