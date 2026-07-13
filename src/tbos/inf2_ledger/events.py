"""INF.2 — event payload schemas (spec §B).

Each payload is exactly what its corresponding Engine writes at the moment
it happens; nothing here is ever recomputed or reinterpreted later. The
event, once appended, is the permanent record of what that Engine believed
and did at that instant (Full Versioning + No Hidden Influence).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from tbos.inf1_config.taxonomy import ActionType, EdgeSourceCategory, InstrumentType, OutcomeResult


class VersionStamp(BaseModel):
    ce2_engine_version: str
    ce3_engine_version: str
    ce4_engine_version: str
    model_versions: dict[str, str] = Field(default_factory=dict)
    config_version_id: uuid.UUID


class DominantReason(BaseModel):
    code: str
    justification: str


class CapitalAllocation(BaseModel):
    deployed: float
    reserved_system_wide: float
    reasoning: str


class AdjustmentLogEntry(BaseModel):
    source: str  # KnowledgeBase | EdgeAttribution | Portfolio
    entry_id: str
    magnitude: float
    reason: str


class ActionPlanSummary(BaseModel):
    action_type: ActionType
    instruments: list[dict] = Field(default_factory=list)
    stake: float
    execution_priority: int = 0
    expiration_conditions: dict = Field(default_factory=dict)
    preconditions: list[dict] = Field(default_factory=list)


class DecisionRecordedPayload(BaseModel):
    action_plan: ActionPlanSummary
    dominant_reason: DominantReason
    capital_allocation: CapitalAllocation
    ce1_snapshot_refs: list[uuid.UUID] = Field(default_factory=list)
    ce2_probability_ref: uuid.UUID | None = None
    ce3_opportunity_description_ref: uuid.UUID | None = None
    adjustment_log: list[AdjustmentLogEntry] = Field(default_factory=list)
    version_stamp: VersionStamp


class OddsSplit(BaseModel):
    book_id: str
    odds: float
    stake_portion: float


class ExecutionRecordedPayload(BaseModel):
    actual_instrument_type: InstrumentType
    actual_odds_per_split: list[OddsSplit]
    actual_stake_total: float
    execution_timestamp: datetime
    execution_quality_slippage: float
    ce5_engine_version: str


class CancellationRecordedPayload(BaseModel):
    reason: str
    conditions_unmet: list[str] = Field(default_factory=list)
    cancellation_timestamp: datetime
    ce5_engine_version: str


class CLVRecordedPayload(BaseModel):
    placed_odds: float
    closing_odds: float
    clv_value: float
    vig_adjustment_method: str
    edge_source_category: EdgeSourceCategory
    ce6_engine_version: str


class OutcomeRecordedPayload(BaseModel):
    result: OutcomeResult
    settled_at: datetime
    source: str


class CorrectionRecordedPayload(BaseModel):
    corrects_event_id: uuid.UUID
    reason: str
    replacement_event_id: uuid.UUID | None = None


EVENT_PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "DECISION_RECORDED": DecisionRecordedPayload,
    "EXECUTION_RECORDED": ExecutionRecordedPayload,
    "CANCELLATION_RECORDED": CancellationRecordedPayload,
    "CLV_RECORDED": CLVRecordedPayload,
    "OUTCOME_RECORDED": OutcomeRecordedPayload,
    "CORRECTION_RECORDED": CorrectionRecordedPayload,
}
