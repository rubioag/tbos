"""Overall + surface-specific Elo ratings, computed entirely from
Sackmann's own match history already loaded by TBOS — no new external
data source.

Standard fixed-K Elo (K=32), the same baseline formula the published
literature this feature is grounded in describes: a "well-tuned Elo
baseline" reached 65.87% accuracy on 133,138 ATP matches (Bunker et al.
2024), and Sackmann's own Davis Cup comparison found Elo at 72% vs
official ranking at 60%. Deliberately the simplest version of Elo (no
K decay, no margin-of-victory adjustment) — the cited research shows
this baseline is hard to beat even with much more complex ML, so v1
stays here rather than guessing at more elaborate tuning unproven for
TBOS's own data.

Built once per process from full history (`from_matches`), then updated
incrementally as new results become known during a run (`record_match`)
— never persisted to a database, never recomputed from scratch mid-run.
Deterministically reconstructible from Sackmann history at any time,
which is why no persistence layer is needed: restart the process, call
`from_matches` again, get the same ratings back.
"""

from __future__ import annotations

from tbos.data_adapters.sackmann.models import SURFACE_MAP, MatchRow

DEFAULT_RATING = 1500.0
K_FACTOR = 32.0


def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def _update_pair(rating_winner: float, rating_loser: float) -> tuple[float, float]:
    expected_winner = _expected_score(rating_winner, rating_loser)
    new_winner = rating_winner + K_FACTOR * (1.0 - expected_winner)
    new_loser = rating_loser + K_FACTOR * (0.0 - (1.0 - expected_winner))
    return new_winner, new_loser


class EloRatings:
    """`overall` is one rating per player_id across all surfaces combined.
    `by_surface` is a separate rating per (surface, player_id) — a player
    unrated on a given surface starts at DEFAULT_RATING the same as a
    brand-new player overall.
    """

    def __init__(self) -> None:
        self._overall: dict[str, float] = {}
        self._by_surface: dict[str, dict[str, float]] = {}

    @classmethod
    def from_matches(cls, matches: list[MatchRow]) -> EloRatings:
        ratings = cls()
        for match in sorted(matches, key=lambda m: m.tourney_date):
            ratings.record_match(match.winner_id, match.loser_id, match.surface)
        return ratings

    def record_match(self, winner_id: str, loser_id: str, raw_surface: str | None) -> None:
        overall_winner = self._overall.get(winner_id, DEFAULT_RATING)
        overall_loser = self._overall.get(loser_id, DEFAULT_RATING)
        new_overall_winner, new_overall_loser = _update_pair(overall_winner, overall_loser)
        self._overall[winner_id] = new_overall_winner
        self._overall[loser_id] = new_overall_loser

        surface = SURFACE_MAP.get(raw_surface or "")
        if surface is None:
            return
        surface_ratings = self._by_surface.setdefault(surface, {})
        surface_winner = surface_ratings.get(winner_id, DEFAULT_RATING)
        surface_loser = surface_ratings.get(loser_id, DEFAULT_RATING)
        new_surface_winner, new_surface_loser = _update_pair(surface_winner, surface_loser)
        surface_ratings[winner_id] = new_surface_winner
        surface_ratings[loser_id] = new_surface_loser

    def get_overall(self, player_id: str) -> float:
        return self._overall.get(player_id, DEFAULT_RATING)

    def get_by_surface(self, player_id: str) -> dict[str, float]:
        return {
            surface: ratings[player_id]
            for surface, ratings in self._by_surface.items()
            if player_id in ratings
        }
