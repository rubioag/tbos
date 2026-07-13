"""CE.5 — ExecutionRecord / CancellationRecord.

`execution_quality_slippage` is computed only against the ActionPlan's own
target odds (Execution Fidelity Principle) — this schema has no field
that could reference outcome, ROI, or CLV; contaminating execution
quality with result-based hindsight is structurally impossible here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from tbos.ce5_execution.optimizer import ExecutionSplit
from tbos.inf1_config.taxonomy import CancellationReason, InstrumentType


class ExecutionRecord(BaseModel):
    action_plan_id: uuid.UUID
    instrument_type: InstrumentType
    splits: list[ExecutionSplit]
    actual_stake_total: float
    target_stake: float
    target_odds: float
    average_odds: float
    execution_quality_slippage: float
    execution_timestamp: datetime
    ce5_engine_version: str


class CancellationRecord(BaseModel):
    action_plan_id: uuid.UUID
    reason: CancellationReason
    conditions_unmet: list[str]
    cancellation_timestamp: datetime
    ce5_engine_version: str
