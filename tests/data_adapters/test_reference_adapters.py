from datetime import UTC, datetime

import pytest

from tbos.data_adapters.contracts import (
    EntityNotFoundError,
    RawOddsQuote,
    RawPlayerStatsRecord,
    SourceMetadata,
    SourceUnavailableError,
)
from tbos.data_adapters.reference_adapters import InMemoryOddsAdapter, InMemoryStatsAdapter
from tbos.inf1_config.taxonomy import InstrumentType

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _metadata() -> SourceMetadata:
    return SourceMetadata(source_id="ref", collected_at=NOW, parser_version="1.0.0", source_priority_rank=1, source_trust_score=0.9)


def _profile(player_id: str) -> RawPlayerStatsRecord:
    return RawPlayerStatsRecord(
        player_id=player_id, ranking=5, first_serve_pct_by_surface={"HARD": 0.62},
        service_points_won_pct_by_surface={"HARD": 0.65}, aces_per_match_by_surface={"HARD": 8.0},
        hold_rate_by_surface={"HARD": 0.8}, return_points_won_pct_by_surface={"HARD": 0.35},
        break_points_converted_pct_by_surface={"HARD": 0.38}, style_tags=["baseline"], career_stage="PEAK",
        h2h_records=[], metadata=_metadata(),
    )


def test_stats_adapter_returns_known_profile() -> None:
    adapter = InMemoryStatsAdapter(profiles={"p1": _profile("p1")})
    result = adapter.fetch_player_profile("p1")
    assert result.player_id == "p1"


def test_stats_adapter_unknown_player_raises_entity_not_found() -> None:
    adapter = InMemoryStatsAdapter()
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_player_profile("ghost")


def test_stats_adapter_unavailable_raises_source_unavailable() -> None:
    adapter = InMemoryStatsAdapter(unavailable=True)
    with pytest.raises(SourceUnavailableError):
        adapter.fetch_player_profile("p1")


def test_odds_adapter_returns_matching_quotes() -> None:
    quote = RawOddsQuote(match_id="m1", instrument_type=InstrumentType.MONEYLINE, book_id="book_a", selection="player_a", odds=1.9, captured_at=NOW, metadata=_metadata())
    adapter = InMemoryOddsAdapter(quotes=[quote])
    result = adapter.fetch_odds("m1", InstrumentType.MONEYLINE)
    assert len(result) == 1
    assert result[0].odds == 1.9


def test_odds_adapter_unknown_match_raises() -> None:
    adapter = InMemoryOddsAdapter()
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_odds("ghost_match", InstrumentType.MONEYLINE)


def test_odds_adapter_filters_by_instrument_type() -> None:
    quote = RawOddsQuote(match_id="m1", instrument_type=InstrumentType.HANDICAP, book_id="book_a", selection="player_a", odds=1.9, captured_at=NOW, metadata=_metadata())
    adapter = InMemoryOddsAdapter(quotes=[quote])
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_odds("m1", InstrumentType.MONEYLINE)
