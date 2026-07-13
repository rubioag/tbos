import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tbos.ce1_data import repository as ce1_repository
from tbos.data_adapters import ingestion
from tbos.data_adapters.contracts import (
    RawMatchContextRecord,
    RawOddsQuote,
    RawPlayerStateRecord,
    RawPlayerStatsRecord,
    SourceMetadata,
)
from tbos.data_adapters.reference_adapters import InMemoryOddsAdapter, InMemoryStatsAdapter
from tbos.inf1_config.schemas import DataIngestionConfig
from tbos.inf1_config.taxonomy import InstrumentType

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CONFIG = DataIngestionConfig()
CONFIG_VERSION_ID = uuid.uuid4()


def _metadata() -> SourceMetadata:
    return SourceMetadata(source_id="ref", collected_at=NOW, parser_version="1.0.0", source_priority_rank=1, source_trust_score=0.9)


def _profile(player_id: str, ranking: int = 5) -> RawPlayerStatsRecord:
    return RawPlayerStatsRecord(
        player_id=player_id, ranking=ranking, first_serve_pct_by_surface={"HARD": 0.62},
        service_points_won_pct_by_surface={"HARD": 0.65}, aces_per_match_by_surface={"HARD": 8.0},
        hold_rate_by_surface={"HARD": 0.8}, return_points_won_pct_by_surface={"HARD": 0.35},
        break_points_converted_pct_by_surface={"HARD": 0.38}, style_tags=["baseline"], career_stage="PEAK",
        h2h_records=[], metadata=_metadata(),
    )


def _state(player_id: str) -> RawPlayerStateRecord:
    return RawPlayerStateRecord(
        player_id=player_id, injury_flags=[], matches_last_14d=3, sets_played_last_14d=7,
        travel_distance_km=100.0, timezone_shift_hours=1.0, deviation_from_baseline=0.0,
        days_since_last_match=4, metadata=_metadata(),
    )


def _context(match_id: str) -> RawMatchContextRecord:
    return RawMatchContextRecord(
        match_id=match_id, tournament_id="t1", round="QF", surface="HARD", indoor_outdoor="OUTDOOR",
        weather_temp_c=24.0, weather_wind_kph=5.0, weather_humidity_pct=40.0, altitude_m=50.0,
        scheduled_start=NOW, best_of="BO3", metadata=_metadata(),
    )


def test_ingest_player_profile_publishes_snapshot(session: Session) -> None:
    adapter = InMemoryStatsAdapter(profiles={"p1": _profile("p1")})
    snapshot = ingestion.ingest_player_profile(session, adapter, "p1", config=CONFIG, config_version_id=CONFIG_VERSION_ID, now=NOW)
    session.commit()

    assert snapshot is not None
    fetched = ce1_repository.get_snapshot(session, snapshot.snapshot_id)
    assert fetched.fields["ranking"]["value"] == 5
    assert fetched.fields["ranking"]["taxonomy_tag"] == "FACT"
    assert fetched.fields["ranking"]["provenance"]["source_id"] == "ref"


def test_ingest_player_profile_unknown_player_returns_none(session: Session) -> None:
    adapter = InMemoryStatsAdapter()
    result = ingestion.ingest_player_profile(session, adapter, "ghost", config=CONFIG, config_version_id=CONFIG_VERSION_ID, now=NOW)
    assert result is None


def test_ingest_player_profile_source_unavailable_returns_none(session: Session) -> None:
    adapter = InMemoryStatsAdapter(unavailable=True)
    result = ingestion.ingest_player_profile(session, adapter, "p1", config=CONFIG, config_version_id=CONFIG_VERSION_ID, now=NOW)
    assert result is None


def test_ingest_player_profile_invalid_ranking_marked_invalid(session: Session) -> None:
    adapter = InMemoryStatsAdapter(profiles={"p1": _profile("p1", ranking=-5)})
    snapshot = ingestion.ingest_player_profile(session, adapter, "p1", config=CONFIG, config_version_id=CONFIG_VERSION_ID, now=NOW)
    session.commit()
    assert snapshot.fields["ranking"]["validity"] == "INVALID"
    assert snapshot.fields["ranking"]["value"] is None  # rejected value never published as valid


def test_ingest_player_state_publishes_snapshot(session: Session) -> None:
    adapter = InMemoryStatsAdapter(states={"p1": _state("p1")})
    snapshot = ingestion.ingest_player_state(session, adapter, "p1", config=CONFIG, config_version_id=CONFIG_VERSION_ID, now=NOW)
    session.commit()
    assert snapshot is not None
    assert snapshot.fields["matches_last_14d"]["value"] == 3


def test_ingest_match_context_publishes_snapshot_with_surface_enum_coercion(session: Session) -> None:
    adapter = InMemoryStatsAdapter(contexts={"m1": _context("m1")})
    snapshot = ingestion.ingest_match_context(session, adapter, "m1", config=CONFIG, config_version_id=CONFIG_VERSION_ID, now=NOW)
    session.commit()
    assert snapshot is not None
    assert snapshot.fields["surface"]["value"] == "HARD"


def test_ingest_odds_publishes_one_snapshot_per_quote(session: Session) -> None:
    quotes = [
        RawOddsQuote(match_id="m1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a", odds=1.9, captured_at=NOW, metadata=_metadata()),
        RawOddsQuote(match_id="m1", instrument_type=InstrumentType.MONEYLINE, book_id="book_b", odds=2.0, captured_at=NOW, metadata=_metadata()),
    ]
    adapter = InMemoryOddsAdapter(quotes=quotes)
    snapshots = ingestion.ingest_odds(session, adapter, "m1", InstrumentType.MONEYLINE, config=CONFIG, config_version_id=CONFIG_VERSION_ID, now=NOW)
    session.commit()
    assert len(snapshots) == 2


def test_ingest_odds_no_quotes_returns_empty_list(session: Session) -> None:
    adapter = InMemoryOddsAdapter()
    result = ingestion.ingest_odds(session, adapter, "ghost", InstrumentType.MONEYLINE, config=CONFIG, config_version_id=CONFIG_VERSION_ID, now=NOW)
    assert result == []


def test_ingest_odds_computes_implied_probability(session: Session) -> None:
    quotes = [RawOddsQuote(match_id="m1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a", odds=2.0, captured_at=NOW, metadata=_metadata())]
    adapter = InMemoryOddsAdapter(quotes=quotes)
    [snapshot] = ingestion.ingest_odds(session, adapter, "m1", InstrumentType.MONEYLINE, config=CONFIG, config_version_id=CONFIG_VERSION_ID, now=NOW)
    session.commit()
    assert snapshot.fields["implied_probability"]["value"] == 0.5
