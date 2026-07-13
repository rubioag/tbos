"""INF.2 repository — the only code path allowed to append events or read
the ledger. All reads either return raw ordered Event rows or a replayed
BetRecord/BankrollState view; nothing here ever mutates a row.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from tbos.inf1_config.taxonomy import EventType
from tbos.inf2_ledger.models import Event
from tbos.inf2_ledger.replay import BankrollState, BetRecord, compute_bankroll_state, replay_bet


def append_event(
    session: Session, *, bet_id: uuid.UUID, event_type: EventType, payload: BaseModel
) -> Event:
    row = Event(
        bet_id=bet_id,
        event_type=event_type.value,
        payload=payload.model_dump(mode="json"),
    )
    session.add(row)
    session.flush()
    return row


def get_events_for_bet(session: Session, bet_id: uuid.UUID) -> list[Event]:
    stmt = select(Event).where(Event.bet_id == bet_id).order_by(Event.id.asc())
    return list(session.execute(stmt).scalars().all())


def get_timeline(
    session: Session, *, since_id: int = 0, limit: int = 1000
) -> list[Event]:
    """Global, cross-bet, causally-ordered event stream (spec §D)."""
    stmt = select(Event).where(Event.id > since_id).order_by(Event.id.asc()).limit(limit)
    return list(session.execute(stmt).scalars().all())


def list_bet_ids(session: Session) -> list[uuid.UUID]:
    stmt = select(Event.bet_id).distinct()
    return list(session.execute(stmt).scalars().all())


def get_bet_record(session: Session, bet_id: uuid.UUID) -> BetRecord | None:
    events = get_events_for_bet(session, bet_id)
    if not events:
        return None
    return replay_bet(events)


def get_bankroll_state(session: Session, *, total_capital: float) -> BankrollState:
    records = [
        record
        for bet_id in list_bet_ids(session)
        if (record := get_bet_record(session, bet_id)) is not None
    ]
    return compute_bankroll_state(records, total_capital=total_capital)
