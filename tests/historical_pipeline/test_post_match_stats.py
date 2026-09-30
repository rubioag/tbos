from datetime import UTC, datetime

import pytest

from tbos.historical_pipeline.outcome_tracking import (
    PredictionOutcomeRecord,
    PredictionOutcomeStore,
)
from tbos.historical_pipeline.post_match_stats import (
    PlayerMatchStats,
    PostMatchStatsMismatchError,
    PostMatchStatsStore,
    record_post_match_stats,
)

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def _player_stats(**overrides) -> PlayerMatchStats:
    base = dict(
        aces=4, double_faults=1, first_serve_pct=65.0, second_serve_in_pct=94.0,
        first_serve_points_won_pct=68.0, second_serve_points_won_pct=47.0,
        service_games_played=9, break_points_saved=1, break_points_faced=4,
        return_points_won_vs_first_pct=18.0, return_points_won_vs_second_pct=21.0,
        break_points_converted=0, total_points_won=38, service_points_won=29,
        return_points_won=9, longest_point_streak=5, total_games_won=6,
        service_games_won=6, longest_game_run=1,
    )
    base.update(overrides)
    return PlayerMatchStats(**base)


def _outcome_record(match_id: str = "m1") -> PredictionOutcomeRecord:
    return PredictionOutcomeRecord(
        match_id=match_id, player_a_id="p1", player_b_id="p2",
        predicted_probability_player_a=0.46, fully_abstained=False,
        participating_model_ids=["serve_model"], decision="NO BET (market unavailable)",
        has_market=False, actual_winner_id="p2", actual_score="6-4, 6-2", recorded_at=NOW,
    )


def test_record_requires_existing_prediction(tmp_path) -> None:
    stats_store = PostMatchStatsStore(tmp_path / "stats.jsonl")
    outcomes = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    with pytest.raises(PostMatchStatsMismatchError):
        record_post_match_stats(
            stats_store, outcomes, match_id="ghost",
            player_a_stats=_player_stats(), player_b_stats=_player_stats(),
            tiebreaks=None, recorded_at=NOW,
        )
    assert stats_store.all() == []


def test_record_succeeds_when_prediction_exists(tmp_path) -> None:
    stats_store = PostMatchStatsStore(tmp_path / "stats.jsonl")
    outcomes = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    outcomes.append(_outcome_record())

    record = record_post_match_stats(
        stats_store, outcomes, match_id="m1",
        player_a_stats=_player_stats(aces=4), player_b_stats=_player_stats(aces=0),
        tiebreaks=None, recorded_at=NOW,
    )
    assert record.player_a_stats.aces == 4
    assert record.player_b_stats.aces == 0
    assert stats_store.get("m1") is not None


def test_append_is_idempotent(tmp_path) -> None:
    stats_store = PostMatchStatsStore(tmp_path / "stats.jsonl")
    outcomes = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    outcomes.append(_outcome_record())

    record_post_match_stats(
        stats_store, outcomes, match_id="m1",
        player_a_stats=_player_stats(aces=4), player_b_stats=_player_stats(aces=0),
        tiebreaks=None, recorded_at=NOW,
    )
    record_post_match_stats(
        stats_store, outcomes, match_id="m1",
        player_a_stats=_player_stats(aces=999), player_b_stats=_player_stats(aces=0),
        tiebreaks=None, recorded_at=NOW,
    )
    assert stats_store.get("m1").player_a_stats.aces == 4  # first write wins


def test_reload_from_disk(tmp_path) -> None:
    path = tmp_path / "stats.jsonl"
    stats_store = PostMatchStatsStore(path)
    outcomes = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    outcomes.append(_outcome_record())
    record_post_match_stats(
        stats_store, outcomes, match_id="m1",
        player_a_stats=_player_stats(), player_b_stats=_player_stats(),
        tiebreaks="7-6(4)", recorded_at=NOW,
    )

    reloaded = PostMatchStatsStore(path)
    assert reloaded.get("m1").tiebreaks == "7-6(4)"


def test_partial_stats_missing_fields_stay_none(tmp_path) -> None:
    """Real incident: a match's stat sheet lacked second_serve_in_pct,
    break_points_saved/faced, and streak fields. Must record what's
    real, never fabricate the rest.
    """
    stats_store = PostMatchStatsStore(tmp_path / "stats.jsonl")
    outcomes = PredictionOutcomeStore(tmp_path / "outcomes.jsonl")
    outcomes.append(_outcome_record())

    partial = PlayerMatchStats(
        aces=12, double_faults=3, first_serve_pct=55.0,
        first_serve_points_won_pct=78.0, second_serve_points_won_pct=57.0,
        return_points_won_vs_first_pct=25.0, return_points_won_vs_second_pct=63.0,
        break_points_converted=3, total_points_won=97, service_points_won=61,
        return_points_won=36, total_games_won=16, service_games_won=13,
    )
    record = record_post_match_stats(
        stats_store, outcomes, match_id="m1",
        player_a_stats=partial, player_b_stats=partial, tiebreaks=None, recorded_at=NOW,
    )
    assert record.player_a_stats.aces == 12
    assert record.player_a_stats.second_serve_in_pct is None
    assert record.player_a_stats.break_points_saved is None
    assert record.player_a_stats.longest_point_streak is None
