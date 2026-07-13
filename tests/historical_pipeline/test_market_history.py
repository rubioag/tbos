from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.historical_pipeline import market_history
from tbos.inf1_config.taxonomy import InstrumentType

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _seed(session: Session, match_id: str = "match_1") -> None:
    for i, odds in enumerate([1.90, 1.85, 1.80]):
        market_history.append_tick(
            session,
            match_id=match_id,
            instrument_type=InstrumentType.MONEYLINE,
            book_id="book_a",
            odds=odds,
            tick_timestamp=T0 + timedelta(hours=i),
        )
    session.commit()


def test_get_timeline_returns_all_ticks_in_order(session: Session) -> None:
    _seed(session)
    timeline = market_history.get_timeline(
        session, match_id="match_1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a"
    )
    assert [t.odds for t in timeline] == [1.90, 1.85, 1.80]


def test_get_odds_as_of_returns_latest_tick_not_after_as_of(session: Session) -> None:
    _seed(session)
    tick = market_history.get_odds_as_of(
        session,
        match_id="match_1",
        instrument_type=InstrumentType.MONEYLINE,
        book_id="book_a",
        as_of=T0 + timedelta(hours=1, minutes=30),
    )
    assert tick.odds == 1.85  # the hour=1 tick, not the hour=2 one


def test_get_odds_as_of_before_any_tick_returns_none(session: Session) -> None:
    _seed(session)
    tick = market_history.get_odds_as_of(
        session,
        match_id="match_1",
        instrument_type=InstrumentType.MONEYLINE,
        book_id="book_a",
        as_of=T0 - timedelta(hours=1),
    )
    assert tick is None


def test_get_odds_as_of_never_returns_a_future_tick(session: Session) -> None:
    _seed(session)
    tick = market_history.get_odds_as_of(
        session,
        match_id="match_1",
        instrument_type=InstrumentType.MONEYLINE,
        book_id="book_a",
        as_of=T0,  # exactly the first tick's timestamp
    )
    assert tick.odds == 1.90


def test_get_closing_odds_is_the_last_recorded_tick(session: Session) -> None:
    _seed(session)
    closing = market_history.get_closing_odds(
        session, match_id="match_1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a"
    )
    assert closing.odds == 1.80


def test_ticks_scoped_per_match_instrument_and_book(session: Session) -> None:
    _seed(session, match_id="match_1")
    market_history.append_tick(
        session,
        match_id="match_2",
        instrument_type=InstrumentType.MONEYLINE,
        book_id="book_a",
        odds=2.50,
        tick_timestamp=T0,
    )
    session.commit()

    timeline_match_2 = market_history.get_timeline(
        session, match_id="match_2", instrument_type=InstrumentType.MONEYLINE, book_id="book_a"
    )
    assert len(timeline_match_2) == 1
    assert timeline_match_2[0].odds == 2.50
