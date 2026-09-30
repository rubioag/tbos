import pytest

from tbos.data_adapters.contracts import EntityNotFoundError
from tbos.data_adapters.sackmann.adapter import SackmannStatsAdapter
from tests.data_adapters.sackmann.fixtures import all_matches


def test_fetch_player_profile_returns_record_with_surfaces() -> None:
    adapter = SackmannStatsAdapter(all_matches())
    profile = adapter.fetch_player_profile("p1")
    assert profile.player_id == "p1"
    assert "HARD" in profile.first_serve_pct_by_surface
    assert "CLAY" in profile.first_serve_pct_by_surface


def test_fetch_player_profile_includes_h2h() -> None:
    adapter = SackmannStatsAdapter(all_matches())
    profile = adapter.fetch_player_profile("p1")
    opponents = {r["opponent_id"] for r in profile.h2h_records}
    assert "p2" in opponents and "p3" in opponents


def test_fetch_player_profile_style_tags_from_hand() -> None:
    adapter = SackmannStatsAdapter(all_matches())
    profile = adapter.fetch_player_profile("p1")
    assert "right-handed" in profile.style_tags


def test_fetch_player_profile_includes_elo_rating() -> None:
    """Real Elo math, not a placeholder: the fixture set gives p1 a 2-2
    record (beats p2 on Hard, loses to p3 on Hard, beats p2 on Clay,
    loses to p4 on Hard), so overall/surface ratings must be populated
    and must actually differ from the untouched 1500 default and from
    each other (proving both scopes are tracked independently).
    """
    from tbos.data_adapters.sackmann.elo import DEFAULT_RATING

    adapter = SackmannStatsAdapter(all_matches())
    profile = adapter.fetch_player_profile("p1")
    assert profile.elo_rating != DEFAULT_RATING
    assert "HARD" in profile.elo_rating_by_surface
    assert "CLAY" in profile.elo_rating_by_surface
    assert profile.elo_rating_by_surface["HARD"] != profile.elo_rating_by_surface["CLAY"]


def test_elo_ratings_can_be_precomputed_and_shared_across_adapters() -> None:
    """The `elo_ratings` constructor param lets a caller build once
    (e.g. per-process, from full history) and reuse across adapter
    instances — verifies the injected instance is actually used, not
    silently recomputed.
    """
    from tbos.data_adapters.sackmann.elo import EloRatings

    matches = all_matches()
    shared = EloRatings.from_matches(matches)
    adapter = SackmannStatsAdapter(matches, elo_ratings=shared)
    profile = adapter.fetch_player_profile("p1")
    assert profile.elo_rating == shared.get_overall("p1")


def test_fetch_player_profile_unknown_player_raises() -> None:
    adapter = SackmannStatsAdapter(all_matches())
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_player_profile("ghost")


def test_fetch_player_state_returns_record() -> None:
    adapter = SackmannStatsAdapter(all_matches())
    state = adapter.fetch_player_state("p1")
    assert state.player_id == "p1"
    assert state.travel_distance_km == 0.0  # honestly not derivable, documented
    assert state.timezone_shift_hours == 0.0


def test_fetch_player_state_unknown_player_raises() -> None:
    adapter = SackmannStatsAdapter(all_matches())
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_player_state("ghost")


def test_fetch_match_context_always_raises() -> None:
    adapter = SackmannStatsAdapter(all_matches())
    with pytest.raises(EntityNotFoundError):
        adapter.fetch_match_context("any_match_id")


def test_metadata_source_id_is_stable() -> None:
    adapter = SackmannStatsAdapter(all_matches())
    profile = adapter.fetch_player_profile("p1")
    assert profile.metadata.source_id == "sackmann_local_dataset"
