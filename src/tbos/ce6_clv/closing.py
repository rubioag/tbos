"""CE.6 — Closing Snapshot capture, per closing_time_policy (INF.1
CLVConfig, already locked). Reuses the Historical Data Pipeline's
MarketHistoryTick storage — odds-timeline persistence is a single
concern regardless of whether the tick is later read for backtesting or
live CLV, so there is no reason to duplicate it.

v1 policy support: only "match_start" resolves to a real reference
timestamp (via MatchContext.scheduled_start). Any other configured
policy string falls back to match_start too, documented rather than
silently mishandled — live in-play closing-point policies need CE.5's
live monitoring loop, which doesn't exist yet.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from tbos.ce1_data.schemas import MatchContext
from tbos.historical_pipeline import market_history
from tbos.historical_pipeline.market_history import MarketHistoryTick
from tbos.inf1_config.taxonomy import InstrumentType


def determine_closing_reference(
    instrument_type: InstrumentType, match_context: MatchContext, *, closing_time_policy: dict[str, str]
) -> datetime:
    policy = closing_time_policy.get(instrument_type.value, "match_start")
    if policy != "match_start":
        pass  # documented fallback — see module docstring
    return match_context.scheduled_start.value


def capture_closing_snapshot(
    session: Session, *, match_id: str, instrument_type: InstrumentType, book_id: str, closing_reference: datetime
) -> MarketHistoryTick | None:
    """Returns None (never fabricated) when no tick exists at or before
    the closing reference — e.g. the market was voided or never quoted.
    """
    return market_history.get_odds_as_of(
        session, match_id=match_id, instrument_type=instrument_type, book_id=book_id, as_of=closing_reference,
    )
