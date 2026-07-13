"""CE.5 — Execution. Fills an ActionPlan's exact instrument/direction/
target stake against available book liquidity, or cancels — never
substitutes a different instrument (Execution Intent Principle,
structurally enforced: `instrument_type` is copied straight from the
plan, there is no code path that could set it independently).
"""

from __future__ import annotations

from datetime import datetime

from tbos.ce4_decision.schemas import ActionPlan
from tbos.ce5_execution.cancellation import liquidity_insufficient_cancellation
from tbos.ce5_execution.optimizer import BookQuote, optimize_execution
from tbos.ce5_execution.schemas import CancellationRecord, ExecutionRecord
from tbos.inf1_config.taxonomy import ActionType

CE5_ENGINE_VERSION = "1.0.0"
DEFAULT_MIN_FILL_FRACTION = 0.5


class NotABetNowPlan(ValueError):
    """Raised if execution is attempted on a plan that never committed
    capital — DEFER/PASS plans have nothing for CE.5 to execute.
    """


def execute_action_plan(
    plan: ActionPlan,
    *,
    target_odds: float,
    quotes: list[BookQuote],
    as_of: datetime,
    min_fill_fraction: float = DEFAULT_MIN_FILL_FRACTION,
) -> ExecutionRecord | CancellationRecord:
    if plan.action_type != ActionType.BET_NOW:
        raise NotABetNowPlan(f"cannot execute a plan with action_type={plan.action_type}")

    target_stake = plan.stake_result.stake_amount
    splits = optimize_execution(target_stake, quotes)
    filled = sum(s.stake_portion for s in splits)

    if target_stake > 0 and filled < target_stake * min_fill_fraction:
        return liquidity_insufficient_cancellation(
            plan.action_plan_id, target_stake=target_stake, filled_stake=filled, as_of=as_of,
        )

    average_odds = sum(s.odds * s.stake_portion for s in splits) / filled if filled > 0 else 0.0
    slippage = average_odds - target_odds

    return ExecutionRecord(
        action_plan_id=plan.action_plan_id,
        instrument_type=plan.instrument_type,  # always copied from the plan, never chosen independently
        splits=splits,
        actual_stake_total=filled,
        target_stake=target_stake,
        target_odds=target_odds,
        average_odds=average_odds,
        execution_quality_slippage=slippage,
        execution_timestamp=as_of,
        ce5_engine_version=CE5_ENGINE_VERSION,
    )
