"""Derives per-surface serve/return statistics from Sackmann match rows.

Sackmann data records stats only from the serving player's perspective
per match (`w_*` for the winner, `l_*` for the loser). Return stats for a
player are derived from the OPPONENT's serving numbers within the same
match: points the opponent lost while serving are points this player won
while returning. This is the standard, well-known way to derive return
stats from this dataset — not a novel assumption.

Rates are computed by summing raw counts across all matches first, then
dividing once (e.g. total_1stIn / total_svpt) — never by averaging
per-match percentages, which would incorrectly weight low-volume matches
equally with high-volume ones.

hold_rate uses a standard proxy: `breaks_against = bp_faced - bp_saved`
(break points converted against this player while serving), so
`hold_rate = 1 - breaks_against / service_games`. This is an
approximation (a service game could theoretically be lost without a
recorded break point in rare data-entry edge cases) — documented, not
treated as exact.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from pydantic import BaseModel

from tbos.data_adapters.sackmann.models import SURFACE_MAP, MatchRow


class SurfaceStatTotals(BaseModel):
    """Raw summed counts for one player, one surface — the aggregator's
    intermediate state, kept so it can be inspected/tested independently
    of the final rate computation.
    """

    matches: int = 0
    matches_with_ace_data: int = 0
    aces: int = 0
    svpt: int = 0
    first_in: int = 0
    first_won: int = 0
    second_won: int = 0
    service_games: int = 0
    bp_saved: int = 0
    bp_faced: int = 0

    return_pts_played: int = 0
    return_pts_won: int = 0
    return_bp_chances: int = 0
    return_bp_converted: int = 0


def pair_prefixes(match: MatchRow, player_id: str) -> tuple[str, str] | None:
    if match.winner_id == player_id:
        return "w", "l"
    if match.loser_id == player_id:
        return "l", "w"
    return None


def get_stat(match: MatchRow, prefix: str, field: str) -> int | None:
    return getattr(match, f"{prefix}_{field}")


def accumulate_surface_totals(
    matches: list[MatchRow], player_id: str, *, as_of: date | None = None
) -> dict[str, SurfaceStatTotals]:
    totals: dict[str, SurfaceStatTotals] = defaultdict(SurfaceStatTotals)

    for match in matches:
        if as_of is not None and match.tourney_date > as_of:
            continue  # anti-lookahead: never use a match that hadn't happened yet

        prefixes = pair_prefixes(match, player_id)
        if prefixes is None:
            continue
        own, opp = prefixes

        surface = SURFACE_MAP.get(match.surface or "")
        if surface is None:
            continue

        own_svpt, own_1stIn, own_1stWon, own_2ndWon = (
            get_stat(match, own, "svpt"), get_stat(match, own, "1stIn"), get_stat(match, own, "1stWon"), get_stat(match, own, "2ndWon"),
        )
        own_ace, own_SvGms, own_bpSaved, own_bpFaced = (
            get_stat(match, own, "ace"), get_stat(match, own, "SvGms"), get_stat(match, own, "bpSaved"), get_stat(match, own, "bpFaced"),
        )
        opp_svpt, opp_1stWon, opp_2ndWon, opp_bpSaved, opp_bpFaced = (
            get_stat(match, opp, "svpt"), get_stat(match, opp, "1stWon"), get_stat(match, opp, "2ndWon"),
            get_stat(match, opp, "bpSaved"), get_stat(match, opp, "bpFaced"),
        )

        t = totals[surface]
        t.matches += 1

        # Independent metrics degrade independently: a missing ace count
        # must never also discard the (unrelated) serve-percentage fields.
        if None not in (own_svpt, own_1stIn, own_1stWon, own_2ndWon):
            t.svpt += own_svpt
            t.first_in += own_1stIn
            t.first_won += own_1stWon
            t.second_won += own_2ndWon
        if own_ace is not None:
            t.aces += own_ace
            t.matches_with_ace_data += 1
        if None not in (own_SvGms, own_bpSaved, own_bpFaced):
            t.service_games += own_SvGms
            t.bp_saved += own_bpSaved
            t.bp_faced += own_bpFaced

        if None not in (opp_svpt, opp_1stWon, opp_2ndWon):
            t.return_pts_played += opp_svpt
            t.return_pts_won += opp_svpt - (opp_1stWon + opp_2ndWon)
        if None not in (opp_bpSaved, opp_bpFaced):
            t.return_bp_chances += opp_bpFaced
            t.return_bp_converted += opp_bpFaced - opp_bpSaved

    return dict(totals)


def compute_serve_return_by_surface(
    matches: list[MatchRow], player_id: str, *, as_of: date | None = None
) -> dict[str, dict[str, float]]:
    totals = accumulate_surface_totals(matches, player_id, as_of=as_of)
    result: dict[str, dict[str, float]] = {}

    for surface, t in totals.items():
        stats: dict[str, float] = {}
        if t.svpt > 0:
            stats["first_serve_pct"] = t.first_in / t.svpt
            stats["service_points_won_pct"] = (t.first_won + t.second_won) / t.svpt
        if t.matches_with_ace_data > 0:
            stats["aces_per_match"] = t.aces / t.matches_with_ace_data
        if t.service_games > 0:
            stats["hold_rate"] = max(0.0, min(1.0, 1.0 - (t.bp_faced - t.bp_saved) / t.service_games))
        if t.return_pts_played > 0:
            stats["return_points_won_pct"] = t.return_pts_won / t.return_pts_played
        if t.return_bp_chances > 0:
            stats["break_points_converted_pct"] = t.return_bp_converted / t.return_bp_chances

        if stats:
            result[surface] = stats

    return result
