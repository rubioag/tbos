"""CE.4 — Decision Engine pipeline.

    EdgeDescription -> Stake Sizing -> Capital Allocation
    -> Behavioral Bias Checklist -> Ruin-Risk Check -> Action Selection
    -> ActionPlan

Consumes CE.3's EdgeDescription only — never re-derives probability or EV,
never touches CE.1/CE.2 data directly (Decision Neutrality boundary
already established at CE.3; CE.4 respects the same one-directional flow).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from tbos.ce3_edge.schemas import EdgeDescription
from tbos.ce4_decision.bias import run_bias_checklist
from tbos.ce4_decision.capital import allocate_capital
from tbos.ce4_decision.decision import select_action
from tbos.ce4_decision.ruin_risk import simulate_ruin_risk
from tbos.ce4_decision.schemas import ActionPlan
from tbos.ce4_decision.stake import compute_stake
from tbos.inf1_config.schemas import RiskConfig
from tbos.inf1_config.taxonomy import ActionType

CE4_ENGINE_VERSION = "1.0.0"


def build_action_plan(
    edge: EdgeDescription,
    *,
    bankroll_total: float,
    current_deployed: float,
    risk_config: RiskConfig,
    as_of: datetime,
    rng_seed: int | None = None,
) -> ActionPlan:
    stake_result = compute_stake(
        bankroll_total=bankroll_total,
        probability=edge.probability_used,
        offered_odds=edge.offered_odds,
        robustness_score=edge.edge_robustness.score,
        uncertainty=edge.probability_uncertainty,
        fractional_kelly_multiplier=risk_config.fractional_kelly_multiplier,
    )

    capital_allocation = allocate_capital(
        bankroll_total=bankroll_total, current_deployed=current_deployed, proposed_stake=stake_result.stake_amount,
    )

    bias_result = run_bias_checklist(
        adjusted_stake_fraction=stake_result.adjusted_fraction, robustness_score=edge.edge_robustness.score,
    )

    ruin_result = simulate_ruin_risk(
        stake_fraction=stake_result.adjusted_fraction,
        probability=edge.probability_used,
        offered_odds=edge.offered_odds,
        max_ruin_probability=risk_config.ruin_risk_max_probability,
        rng_seed=rng_seed,
    )

    action_type, dominant_reason = select_action(
        edge, stake_result, bias_result, ruin_result, aggressiveness_threshold=risk_config.aggressiveness_threshold,
    )

    # A non-BET_NOW action commits zero capital regardless of what Stake
    # Sizing computed — the stake/capital math still runs (for audit and
    # dominant_reason context) but never gets deployed.
    if action_type != ActionType.BET_NOW:
        capital_allocation = allocate_capital(bankroll_total=bankroll_total, current_deployed=current_deployed, proposed_stake=0.0)

    return ActionPlan(
        action_plan_id=uuid.uuid4(),
        edge_id=edge.edge_id,
        match_id=edge.match_id,
        instrument_type=edge.instrument_type,
        book_id=edge.book_id,
        action_type=action_type,
        stake_result=stake_result,
        capital_allocation=capital_allocation,
        dominant_reason=dominant_reason,
        bias_checklist_result=bias_result,
        ruin_risk_result=ruin_result,
        ce4_engine_version=CE4_ENGINE_VERSION,
        computed_at=as_of,
    )
