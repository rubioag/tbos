"""Post-match statistics — real, observed in-match numbers (aces, serve
%, break points, etc.) recorded AFTER a match for evaluation/calibration
research only. Never fed back into the prediction that already ran for
that match (the prediction is immutable, already recorded in
PredictionOutcomeStore, and post-match stats cannot have influenced it
without look-ahead bias by definition — they didn't exist yet).

Same append-only JSONL discipline as every other store in this package.
Linked to (never merged into) the existing PredictionOutcomeRecord for
the same match_id — a separate file, a separate record type, joined only
at read/report time by match_id.

`player_a`/`player_b` here follow the exact same identity as the
already-recorded PredictionOutcomeRecord for that match_id (whichever
side TBOS labeled player_a at prediction time) — validated against it at
save time so post-match stats can never silently attach to the wrong
match or the wrong side.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from tbos.historical_pipeline.outcome_tracking import PredictionOutcomeStore


class PostMatchStatsMismatchError(ValueError):
    """Raised when the match_id has no recorded prediction, or the
    supplied stats don't reference the players already on record.
    """


class PlayerMatchStats(BaseModel):
    """Every field optional (default None) — real post-match stat
    sheets vary in completeness by source, and a missing field must be
    recorded as absent, never fabricated to satisfy a required schema.
    """

    aces: int | None = None
    double_faults: int | None = None
    first_serve_pct: float | None = None
    second_serve_in_pct: float | None = None
    first_serve_points_won_pct: float | None = None
    second_serve_points_won_pct: float | None = None
    service_games_played: int | None = None
    break_points_saved: int | None = None
    break_points_faced: int | None = None
    return_points_won_vs_first_pct: float | None = None
    return_points_won_vs_second_pct: float | None = None
    break_points_converted: int | None = None
    total_points_won: int | None = None
    service_points_won: int | None = None
    return_points_won: int | None = None
    longest_point_streak: int | None = None
    total_games_won: int | None = None
    service_games_won: int | None = None
    longest_game_run: int | None = None


class PostMatchStatsRecord(BaseModel):
    match_id: str
    player_a_stats: PlayerMatchStats
    player_b_stats: PlayerMatchStats
    tiebreaks: str | None
    recorded_at: datetime


class PostMatchStatsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, PostMatchStatsRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = PostMatchStatsRecord.model_validate_json(line)
                if record.match_id not in self._index:
                    self._index[record.match_id] = record

    def get(self, match_id: str) -> PostMatchStatsRecord | None:
        return self._index.get(match_id)

    def all(self) -> list[PostMatchStatsRecord]:
        return list(self._index.values())

    def append(self, record: PostMatchStatsRecord) -> None:
        if record.match_id in self._index:
            return  # already recorded — append-only, never duplicate/overwrite
        with self._path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")
        self._index[record.match_id] = record


def record_post_match_stats(
    stats_store: PostMatchStatsStore, outcome_store: PredictionOutcomeStore, *,
    match_id: str, player_a_stats: PlayerMatchStats, player_b_stats: PlayerMatchStats,
    tiebreaks: str | None, recorded_at: datetime,
) -> PostMatchStatsRecord:
    """Requires a prediction to already exist for this match_id — post-
    match stats research is only meaningful relative to a real, already-
    recorded prediction. Raises `PostMatchStatsMismatchError` and saves
    nothing if no such prediction exists.
    """
    outcome = outcome_store.get(match_id)
    if outcome is None:
        raise PostMatchStatsMismatchError(
            f"no recorded prediction for match_id={match_id!r} — record the prediction first"
        )

    record = PostMatchStatsRecord(
        match_id=match_id, player_a_stats=player_a_stats, player_b_stats=player_b_stats,
        tiebreaks=tiebreaks, recorded_at=recorded_at,
    )
    stats_store.append(record)
    return record
