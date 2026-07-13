import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.schemas import MatchContext
from tbos.ce5_execution.optimizer import ExecutionSplit
from tbos.ce5_execution.schemas import ExecutionRecord
from tbos.ce6_clv import repository
from tbos.ce6_clv.engine import build_clv_record
from tbos.historical_pipeline import market_history
from tbos.inf1_config.taxonomy import (
    BestOf,
    EdgeSourceCategory,
    FieldAvailability,
    FieldValidity,
    InformationReliability,
    InstrumentType,
    Surface,
)

MATCH_START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
CLOSING_POLICY = {"MONEYLINE": "match_start"}


def _env(value: object) -> FieldEnvelope:
    return FieldEnvelope(value=value, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID, taxonomy_tag=InformationReliability.FACT)


def _match_context() -> MatchContext:
    return MatchContext(
        match_id=_env("match_1"), tournament_id=_env("t1"), round=_env("QF"), surface=_env(Surface.HARD),
        indoor_outdoor=_env("OUTDOOR"), weather_temp_c=_env(24.0), weather_wind_kph=_env(5.0),
        weather_humidity_pct=_env(40.0), altitude_m=_env(50.0), scheduled_start=_env(MATCH_START), best_of=_env(BestOf.BO3),
    )


def _execution(*, odds: float = 1.90, stake: float = 100.0, book_id: str = "book_a") -> ExecutionRecord:
    return ExecutionRecord(
        action_plan_id=uuid.uuid4(), instrument_type=InstrumentType.MONEYLINE,
        splits=[ExecutionSplit(book_id=book_id, odds=odds, stake_portion=stake)],
        actual_stake_total=stake, target_stake=stake, target_odds=odds, average_odds=odds,
        execution_quality_slippage=0.0, execution_timestamp=MATCH_START - timedelta(hours=1), ce5_engine_version="1.0.0",
    )


def test_build_clv_record_with_real_closing_tick(session: Session) -> None:
    market_history.append_tick(session, match_id="match_1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a", odds=1.80, tick_timestamp=MATCH_START - timedelta(minutes=5))
    session.commit()

    execution = _execution(odds=1.90)
    record = build_clv_record(
        session, execution, match_id="match_1", match_context=_match_context(),
        edge_source_category=EdgeSourceCategory.MODEL, closing_time_policy=CLOSING_POLICY,
    )
    assert record is not None
    assert record.placed_odds == 1.90
    assert record.closing_odds == 1.80
    assert record.clv_value > 0  # closing shorter than placed -> we beat the closing line


def test_build_clv_record_returns_none_when_no_closing_tick(session: Session) -> None:
    execution = _execution()
    record = build_clv_record(
        session, execution, match_id="match_1", match_context=_match_context(),
        edge_source_category=EdgeSourceCategory.MODEL, closing_time_policy=CLOSING_POLICY,
    )
    assert record is None


def test_build_clv_record_returns_none_for_empty_execution(session: Session) -> None:
    execution = ExecutionRecord(
        action_plan_id=uuid.uuid4(), instrument_type=InstrumentType.MONEYLINE, splits=[],
        actual_stake_total=0.0, target_stake=100.0, target_odds=1.9, average_odds=0.0,
        execution_quality_slippage=0.0, execution_timestamp=MATCH_START, ce5_engine_version="1.0.0",
    )
    record = build_clv_record(
        session, execution, match_id="match_1", match_context=_match_context(),
        edge_source_category=EdgeSourceCategory.MODEL, closing_time_policy=CLOSING_POLICY,
    )
    assert record is None


def test_multi_book_execution_uses_largest_split_as_reference(session: Session) -> None:
    market_history.append_tick(session, match_id="match_1", instrument_type=InstrumentType.MONEYLINE, book_id="book_big", odds=1.85, tick_timestamp=MATCH_START - timedelta(minutes=5))
    session.commit()

    execution = ExecutionRecord(
        action_plan_id=uuid.uuid4(), instrument_type=InstrumentType.MONEYLINE,
        splits=[
            ExecutionSplit(book_id="book_small", odds=2.00, stake_portion=10.0),
            ExecutionSplit(book_id="book_big", odds=1.90, stake_portion=90.0),
        ],
        actual_stake_total=100.0, target_stake=100.0, target_odds=1.90, average_odds=1.91,
        execution_quality_slippage=0.01, execution_timestamp=MATCH_START - timedelta(hours=1), ce5_engine_version="1.0.0",
    )
    record = build_clv_record(
        session, execution, match_id="match_1", match_context=_match_context(),
        edge_source_category=EdgeSourceCategory.MODEL, closing_time_policy=CLOSING_POLICY,
    )
    assert record is not None
    assert record.book_id == "book_big"
    assert record.placed_odds == 1.90


def test_publish_and_retrieve_clv_record(session: Session) -> None:
    market_history.append_tick(session, match_id="match_1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a", odds=1.80, tick_timestamp=MATCH_START - timedelta(minutes=5))
    session.commit()

    execution = _execution()
    record = build_clv_record(
        session, execution, match_id="match_1", match_context=_match_context(),
        edge_source_category=EdgeSourceCategory.MODEL, closing_time_policy=CLOSING_POLICY,
    )
    repository.publish_clv_record(session, record)
    session.commit()

    fetched = repository.get_clv_record(session, record.clv_id)
    assert fetched is not None
    rows = repository.list_for_match(session, "match_1")
    assert len(rows) == 1
