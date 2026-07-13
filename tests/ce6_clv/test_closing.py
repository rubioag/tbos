from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.schemas import MatchContext
from tbos.ce6_clv.closing import capture_closing_snapshot, determine_closing_reference
from tbos.historical_pipeline import market_history
from tbos.inf1_config.taxonomy import (
    BestOf,
    FieldAvailability,
    FieldValidity,
    InformationReliability,
    InstrumentType,
    Surface,
)

MATCH_START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _env(value: object) -> FieldEnvelope:
    return FieldEnvelope(value=value, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID, taxonomy_tag=InformationReliability.FACT)


def _match_context() -> MatchContext:
    return MatchContext(
        match_id=_env("match_1"), tournament_id=_env("t1"), round=_env("QF"), surface=_env(Surface.HARD),
        indoor_outdoor=_env("OUTDOOR"), weather_temp_c=_env(24.0), weather_wind_kph=_env(5.0),
        weather_humidity_pct=_env(40.0), altitude_m=_env(50.0), scheduled_start=_env(MATCH_START), best_of=_env(BestOf.BO3),
    )


def test_determine_closing_reference_uses_match_start_for_moneyline() -> None:
    ref = determine_closing_reference(InstrumentType.MONEYLINE, _match_context(), closing_time_policy={"MONEYLINE": "match_start"})
    assert ref == MATCH_START


def test_determine_closing_reference_falls_back_to_match_start_for_unconfigured_policy() -> None:
    ref = determine_closing_reference(InstrumentType.LIVE, _match_context(), closing_time_policy={})
    assert ref == MATCH_START


def test_capture_closing_snapshot_returns_latest_tick_before_reference(session: Session) -> None:
    market_history.append_tick(session, match_id="match_1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a", odds=1.90, tick_timestamp=MATCH_START - timedelta(hours=2))
    market_history.append_tick(session, match_id="match_1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a", odds=1.85, tick_timestamp=MATCH_START - timedelta(minutes=5))
    market_history.append_tick(session, match_id="match_1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a", odds=1.80, tick_timestamp=MATCH_START + timedelta(minutes=10))
    session.commit()

    tick = capture_closing_snapshot(session, match_id="match_1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a", closing_reference=MATCH_START)
    assert tick is not None
    assert tick.odds == 1.85  # last tick at/before match_start, not the post-start one


def test_capture_closing_snapshot_returns_none_when_no_ticks_exist(session: Session) -> None:
    tick = capture_closing_snapshot(session, match_id="ghost_match", instrument_type=InstrumentType.MONEYLINE, book_id="book_a", closing_reference=MATCH_START)
    assert tick is None
