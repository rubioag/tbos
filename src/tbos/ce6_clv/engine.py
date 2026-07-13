"""CE.6 — pipeline entry point.

    ExecutionRecord -> determine closing reference -> capture closing tick
    -> compute CLV -> CLVRecord

Failure modes, all resulting in None rather than a fabricated record:
- No fills at all on the ExecutionRecord (shouldn't happen given CE.5's
  min-fill-fraction guard, defensive check anyway).
- No closing tick available (market voided, never quoted after placement).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from tbos.ce1_data.schemas import MatchContext
from tbos.ce5_execution.schemas import ExecutionRecord
from tbos.ce6_clv import closing
from tbos.ce6_clv.clv import compute_clv
from tbos.ce6_clv.schemas import CLVRecord
from tbos.inf1_config.taxonomy import EdgeSourceCategory

CE6_ENGINE_VERSION = "1.0.0"


def build_clv_record(
    session: Session,
    execution: ExecutionRecord,
    *,
    match_id: str,
    match_context: MatchContext,
    edge_source_category: EdgeSourceCategory,
    closing_time_policy: dict[str, str],
    vig_adjustment_method: str = "proportional",
    placed_opponent_odds: float | None = None,
    closing_opponent_odds: float | None = None,
) -> CLVRecord | None:
    if not execution.splits:
        return None

    primary_split = max(execution.splits, key=lambda s: s.stake_portion)

    closing_reference = closing.determine_closing_reference(
        execution.instrument_type, match_context, closing_time_policy=closing_time_policy,
    )
    closing_tick = closing.capture_closing_snapshot(
        session, match_id=match_id, instrument_type=execution.instrument_type,
        book_id=primary_split.book_id, closing_reference=closing_reference,
    )
    if closing_tick is None:
        return None

    calc = compute_clv(
        placed_odds=primary_split.odds, closing_odds=closing_tick.odds,
        placed_opponent_odds=placed_opponent_odds, closing_opponent_odds=closing_opponent_odds,
        vig_adjustment_method=vig_adjustment_method,
    )

    return CLVRecord(
        clv_id=uuid.uuid4(),
        action_plan_id=execution.action_plan_id,
        match_id=match_id,
        instrument_type=execution.instrument_type,
        book_id=primary_split.book_id,
        placed_odds=primary_split.odds,
        closing_odds=closing_tick.odds,
        placed_implied_probability=calc.placed_implied_probability,
        closing_implied_probability=calc.closing_implied_probability,
        clv_value=calc.clv_value,
        vig_adjusted=calc.vig_adjusted,
        vig_adjustment_method=vig_adjustment_method,
        edge_source_category=edge_source_category,
        ce6_engine_version=CE6_ENGINE_VERSION,
        computed_at=closing_tick.tick_timestamp,
    )
