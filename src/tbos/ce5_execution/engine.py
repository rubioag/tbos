"""CE.5 — pipeline entry point. A DEFER/PASS plan is simply never
executed — returns None, distinct from a CancellationRecord (which
represents a BET_NOW attempt that failed to fill).
"""

from __future__ import annotations

from datetime import datetime

from tbos.ce4_decision.schemas import ActionPlan
from tbos.ce5_execution.execution import execute_action_plan
from tbos.ce5_execution.optimizer import BookQuote
from tbos.ce5_execution.schemas import CancellationRecord, ExecutionRecord
from tbos.inf1_config.taxonomy import ActionType


def run_execution(
    plan: ActionPlan, *, target_odds: float, quotes: list[BookQuote], as_of: datetime
) -> ExecutionRecord | CancellationRecord | None:
    if plan.action_type != ActionType.BET_NOW:
        return None
    return execute_action_plan(plan, target_odds=target_odds, quotes=quotes, as_of=as_of)
