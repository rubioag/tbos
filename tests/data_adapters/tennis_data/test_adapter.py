from datetime import UTC, date, datetime

import pytest

from tbos.data_adapters.contracts import (
    EntityNotFoundError,
    RawPlayerStateRecord,
    SourceMetadata,
    StatsSourceAdapter,
)
from tbos.data_adapters.player_resolution.resolver import PlayerNameResolver
from tbos.data_adapters.player_resolution.store import PlayerNameMappingStore
from tbos.data_adapters.tennis_data.adapter import TennisDataPlayerStateAdapter
from tbos.data_adapters.tennis_data.models import TennisDataMatchRow
from tests.data_adapters.player_resolution.fixtures import real_player_matches

NOW = datetime(2026, 7, 15, tzinfo=UTC)
DJOKOVIC_ID = "104925"


def _base_metadata() -> SourceMetadata:
    return SourceMetadata(
        source_id="sackmann_local_dataset", collected_at=NOW, parser_version="sackmann-csv-v1",
        source_priority_rank=1, source_trust_score=0.85,
    )


def _base_state(player_id: str = DJOKOVIC_ID) -> RawPlayerStateRecord:
    return RawPlayerStateRecord(
        player_id=player_id, injury_flags=[], matches_last_14d=0, sets_played_last_14d=0,
        travel_distance_km=0.0, timezone_shift_hours=0.0, deviation_from_baseline=0.03,
        days_since_last_match=650, metadata=_base_metadata(),
    )


class FakeBaseAdapter(StatsSourceAdapter):
    source_id = "fake_base"

    def __init__(self, states: dict[str, RawPlayerStateRecord]) -> None:
        self._states = states

    def fetch_player_profile(self, player_id: str):
        raise EntityNotFoundError("not used in these tests")

    def fetch_match_context(self, match_id: str):
        raise EntityNotFoundError("not used in these tests")

    def fetch_player_state(self, player_id: str) -> RawPlayerStateRecord:
        record = self._states.get(player_id)
        if record is None:
            raise EntityNotFoundError(f"no base state for {player_id!r}")
        return record


def _resolver(tmp_path) -> PlayerNameResolver:
    store = PlayerNameMappingStore(tmp_path / "mappings.jsonl")
    return PlayerNameResolver(real_player_matches(), store)


def _row(match_date, winner, loser, *, wsets=2, lsets=0, comment="Completed") -> TennisDataMatchRow:
    return TennisDataMatchRow(
        match_date=match_date, winner_name=winner, loser_name=loser,
        winner_sets=wsets, loser_sets=lsets, comment=comment,
    )


def test_fetch_player_profile_always_abstains(tmp_path) -> None:
    base = FakeBaseAdapter({DJOKOVIC_ID: _base_state()})
    adapter = TennisDataPlayerStateAdapter(base, [], _resolver(tmp_path))
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_player_profile(DJOKOVIC_ID)


def test_fetch_match_context_always_abstains(tmp_path) -> None:
    base = FakeBaseAdapter({DJOKOVIC_ID: _base_state()})
    adapter = TennisDataPlayerStateAdapter(base, [], _resolver(tmp_path))
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_match_context("m1")


def test_no_tennis_data_rows_falls_back_to_base_unchanged(tmp_path) -> None:
    base_state = _base_state()
    base = FakeBaseAdapter({DJOKOVIC_ID: base_state})
    adapter = TennisDataPlayerStateAdapter(base, [], _resolver(tmp_path))

    result = adapter.fetch_player_state(DJOKOVIC_ID)
    assert result == base_state  # untouched, including deviation_from_baseline


def test_base_adapter_missing_player_propagates(tmp_path) -> None:
    base = FakeBaseAdapter({})
    rows = [_row(date(2026, 7, 1), "Djokovic N.", "Alcaraz C.")]
    adapter = TennisDataPlayerStateAdapter(base, rows, _resolver(tmp_path))
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_player_state(DJOKOVIC_ID)


def test_recent_matches_override_only_the_four_activity_fields(tmp_path) -> None:
    base_state = _base_state()
    base = FakeBaseAdapter({DJOKOVIC_ID: base_state})
    rows = [
        _row(date(2026, 7, 10), "Djokovic N.", "Alcaraz C.", wsets=2, lsets=1),
        _row(date(2026, 7, 5), "Auger-Aliassime F.", "Djokovic N.", wsets=2, lsets=0),
    ]
    adapter = TennisDataPlayerStateAdapter(base, rows, _resolver(tmp_path))

    result = adapter.fetch_player_state(DJOKOVIC_ID)

    assert result.matches_last_14d == 2
    # row1: Djokovic is winner, won 2 sets. row2: Djokovic is loser, won 0 sets.
    assert result.sets_played_last_14d == 2 + 0
    today = datetime.now(UTC).date()
    assert result.days_since_last_match == (today - date(2026, 7, 10)).days
    # untouched fields, taken straight from the base record
    assert result.travel_distance_km == base_state.travel_distance_km
    assert result.timezone_shift_hours == base_state.timezone_shift_hours
    assert result.deviation_from_baseline == base_state.deviation_from_baseline
    assert result.metadata.source_id == "sackmann_plus_tennis_data_co_uk"


def test_retirement_loss_flags_injury(tmp_path) -> None:
    base = FakeBaseAdapter({DJOKOVIC_ID: _base_state()})
    rows = [_row(date(2026, 7, 10), "Alcaraz C.", "Djokovic N.", wsets=2, lsets=0, comment="Retired")]
    adapter = TennisDataPlayerStateAdapter(base, rows, _resolver(tmp_path))

    result = adapter.fetch_player_state(DJOKOVIC_ID)
    assert len(result.injury_flags) == 1
    assert result.injury_flags[0]["source"] == "tennis_data_co_uk_retirement_heuristic"
    assert result.injury_flags[0]["severity"] == "MINOR"


def test_retirement_win_does_not_flag_injury(tmp_path) -> None:
    """Djokovic WON via the opponent's retirement — he isn't the injured one."""
    base = FakeBaseAdapter({DJOKOVIC_ID: _base_state()})
    rows = [_row(date(2026, 7, 10), "Djokovic N.", "Alcaraz C.", comment="Retired")]
    adapter = TennisDataPlayerStateAdapter(base, rows, _resolver(tmp_path))

    result = adapter.fetch_player_state(DJOKOVIC_ID)
    assert result.injury_flags == []


def test_walkover_does_not_flag_injury(tmp_path) -> None:
    """Per explicit scope: only 'Retired' feeds the injury heuristic."""
    base = FakeBaseAdapter({DJOKOVIC_ID: _base_state()})
    rows = [_row(date(2026, 7, 10), "Alcaraz C.", "Djokovic N.", comment="Walkover")]
    adapter = TennisDataPlayerStateAdapter(base, rows, _resolver(tmp_path))

    result = adapter.fetch_player_state(DJOKOVIC_ID)
    assert result.injury_flags == []


def test_old_injury_outside_lookback_window_not_flagged(tmp_path) -> None:
    base = FakeBaseAdapter({DJOKOVIC_ID: _base_state()})
    rows = [_row(date(2026, 1, 1), "Alcaraz C.", "Djokovic N.", comment="Retired")]  # >30d before NOW
    adapter = TennisDataPlayerStateAdapter(base, rows, _resolver(tmp_path))

    result = adapter.fetch_player_state(DJOKOVIC_ID)
    assert result.injury_flags == []


def test_unresolvable_name_row_ignored_not_crashed(tmp_path) -> None:
    base = FakeBaseAdapter({DJOKOVIC_ID: _base_state()})
    rows = [_row(date(2026, 7, 10), "Totally Unknown Player X.", "Also Unknown Y.")]
    adapter = TennisDataPlayerStateAdapter(base, rows, _resolver(tmp_path))

    # Falls back to base since none of these rows attribute to Djokovic.
    result = adapter.fetch_player_state(DJOKOVIC_ID)
    assert result == _base_state()


def test_future_dated_row_ignored(tmp_path) -> None:
    base_state = _base_state()
    base = FakeBaseAdapter({DJOKOVIC_ID: base_state})
    rows = [_row(date(2026, 12, 25), "Djokovic N.", "Alcaraz C.")]  # after NOW
    adapter = TennisDataPlayerStateAdapter(base, rows, _resolver(tmp_path))

    result = adapter.fetch_player_state(DJOKOVIC_ID)
    assert result == base_state
