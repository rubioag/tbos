"""Historical Data Pipeline §C — Market History Store.

Full odds timeline per (match, instrument, book), append-only ticks —
distinct from CE.1's MarketSnapshot which is a single point-in-time
publication. `get_odds_as_of` is what makes backtesting possible: given
a decision timestamp, find the odds that were actually live then.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Uuid, event, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from tbos.common import forbid_mutation
from tbos.db import Base
from tbos.inf1_config.taxonomy import InstrumentType


class MarketHistoryTick(Base):
    __tablename__ = "market_history_ticks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tick_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), unique=True, default=uuid.uuid4)
    match_id: Mapped[str] = mapped_column(String(255), index=True)
    instrument_type: Mapped[str] = mapped_column(String(20), index=True)
    book_id: Mapped[str] = mapped_column(String(100), index=True)
    odds: Mapped[float] = mapped_column(Float)
    tick_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


event.listen(MarketHistoryTick, "before_update", forbid_mutation)
event.listen(MarketHistoryTick, "before_delete", forbid_mutation)


def append_tick(
    session: Session,
    *,
    match_id: str,
    instrument_type: InstrumentType,
    book_id: str,
    odds: float,
    tick_timestamp: datetime,
) -> MarketHistoryTick:
    row = MarketHistoryTick(
        match_id=match_id,
        instrument_type=instrument_type.value,
        book_id=book_id,
        odds=odds,
        tick_timestamp=tick_timestamp,
    )
    session.add(row)
    session.flush()
    return row


def get_timeline(
    session: Session, *, match_id: str, instrument_type: InstrumentType, book_id: str
) -> list[MarketHistoryTick]:
    stmt = (
        select(MarketHistoryTick)
        .where(
            MarketHistoryTick.match_id == match_id,
            MarketHistoryTick.instrument_type == instrument_type.value,
            MarketHistoryTick.book_id == book_id,
        )
        .order_by(MarketHistoryTick.tick_timestamp.asc())
    )
    return list(session.execute(stmt).scalars().all())


def get_odds_as_of(
    session: Session, *, match_id: str, instrument_type: InstrumentType, book_id: str, as_of: datetime
) -> MarketHistoryTick | None:
    """The odds that were actually live at `as_of` — never a tick recorded
    after it (same anti-lookahead discipline as reconstruction.py).
    """
    stmt = (
        select(MarketHistoryTick)
        .where(
            MarketHistoryTick.match_id == match_id,
            MarketHistoryTick.instrument_type == instrument_type.value,
            MarketHistoryTick.book_id == book_id,
            MarketHistoryTick.tick_timestamp <= as_of,
        )
        .order_by(MarketHistoryTick.tick_timestamp.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_closing_odds(
    session: Session, *, match_id: str, instrument_type: InstrumentType, book_id: str
) -> MarketHistoryTick | None:
    """Last recorded tick for this match/instrument/book — the closing
    reference. Policy-driven per-instrument closing-time selection (live
    vs pre-match) is deferred to CE.6's wiring; this returns the raw last tick.
    """
    stmt = (
        select(MarketHistoryTick)
        .where(
            MarketHistoryTick.match_id == match_id,
            MarketHistoryTick.instrument_type == instrument_type.value,
            MarketHistoryTick.book_id == book_id,
        )
        .order_by(MarketHistoryTick.tick_timestamp.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()
