"""Historical Data Pipeline §D — Backtest Dataset Builder.

A BacktestScenario references snapshot/tick IDs, never copies their
content — same "reference, not embed" discipline as INF.2's decision
events pointing at CE.1 snapshots. CE.2/CE.3/CE.4 don't exist yet in the
build order; this module only assembles the input side of a scenario.
The `snapshot_t -> CE.2 -> CE.3 -> CE.4` simulation itself is wired once
those Engines exist, without needing to change anything here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.historical_pipeline import market_history
from tbos.inf1_config.taxonomy import InstrumentType


class MarketReference(BaseModel):
    instrument_type: InstrumentType
    book_id: str
    tick_id: uuid.UUID
    odds: float


class BacktestScenario(BaseModel):
    scenario_id: uuid.UUID
    match_id: str
    simulated_decision_timestamp: datetime

    player_a_profile_snapshot_id: uuid.UUID | None
    player_a_state_snapshot_id: uuid.UUID | None
    player_b_profile_snapshot_id: uuid.UUID | None
    player_b_state_snapshot_id: uuid.UUID | None
    match_context_snapshot_id: uuid.UUID | None

    market_references: list[MarketReference]


def build_scenario(
    session: Session,
    *,
    match_id: str,
    player_a_id: str,
    player_b_id: str,
    as_of: datetime,
    instruments: list[tuple[InstrumentType, str]],  # [(instrument_type, book_id), ...]
) -> BacktestScenario:
    def _snapshot_id(entity_type: str, entity_id: str) -> uuid.UUID | None:
        snap = ce1_repository.get_snapshot_as_of(session, entity_type, entity_id, as_of)
        return snap.snapshot_id if snap is not None else None

    market_refs: list[MarketReference] = []
    for instrument_type, book_id in instruments:
        tick = market_history.get_odds_as_of(
            session, match_id=match_id, instrument_type=instrument_type, book_id=book_id, as_of=as_of
        )
        if tick is not None:
            market_refs.append(
                MarketReference(
                    instrument_type=instrument_type, book_id=book_id, tick_id=tick.tick_id, odds=tick.odds
                )
            )

    return BacktestScenario(
        scenario_id=uuid.uuid4(),
        match_id=match_id,
        simulated_decision_timestamp=as_of,
        player_a_profile_snapshot_id=_snapshot_id("PlayerProfile", player_a_id),
        player_a_state_snapshot_id=_snapshot_id("PlayerState", player_a_id),
        player_b_profile_snapshot_id=_snapshot_id("PlayerProfile", player_b_id),
        player_b_state_snapshot_id=_snapshot_id("PlayerState", player_b_id),
        match_context_snapshot_id=_snapshot_id("MatchContext", match_id),
        market_references=market_refs,
    )
