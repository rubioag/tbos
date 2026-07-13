"""CE.4 — ActionPlan: the economic intent CE.5 will later execute
unchanged (Execution Intent Principle — instrument, direction, and stake
fixed here, CE.5 may only optimize *how*, never *what*).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from tbos.ce4_decision.bias import BiasChecklistResult
from tbos.ce4_decision.capital import CapitalAllocation
from tbos.ce4_decision.decision import DominantReason
from tbos.ce4_decision.ruin_risk import RuinRiskResult
from tbos.ce4_decision.stake import StakeResult
from tbos.inf1_config.taxonomy import ActionType, InstrumentType


class ActionPlan(BaseModel):
    action_plan_id: uuid.UUID
    edge_id: uuid.UUID
    match_id: str
    instrument_type: InstrumentType
    book_id: str

    action_type: ActionType
    stake_result: StakeResult
    capital_allocation: CapitalAllocation
    dominant_reason: DominantReason

    bias_checklist_result: BiasChecklistResult
    ruin_risk_result: RuinRiskResult

    ce4_engine_version: str
    computed_at: datetime
