"""Arithmetic verified by hand against match1+match2 (HARD, player p1):

svpt=80+68=148, first_in=50+38=88, first_won=40+28=68, second_won=20+14=34
ace=8+4=12, SvGms=12+10=22, bpSaved=3+1=4, bpFaced=4+4=8, matches=2

first_serve_pct           = 88/148          = 0.594594...
service_points_won_pct    = (68+34)/148     = 102/148 = 0.689189...
aces_per_match             = 12/2            = 6.0
hold_rate                  = 1-(8-4)/22      = 0.818182...
return_pts_played=75+70=145, return_pts_won=(75-45)+(70-50)=30+20=50
return_points_won_pct      = 50/145          = 0.344828...
return_bp_chances=5+3=8, return_bp_converted=(5-2)+(3-2)=3+1=4
break_points_converted_pct = 4/8             = 0.5
"""

from datetime import date

import pytest

from tbos.data_adapters.sackmann.aggregator import accumulate_surface_totals, compute_serve_return_by_surface

from tests.data_adapters.sackmann.fixtures import all_matches, match1_p1_beats_p2_hard, match2_p1_loses_to_p3_hard, match3_p1_beats_p2_clay


def test_hard_surface_stats_match_hand_computed_values() -> None:
    matches = [match1_p1_beats_p2_hard(), match2_p1_loses_to_p3_hard()]
    result = compute_serve_return_by_surface(matches, "p1")

    hard = result["HARD"]
    assert hard["first_serve_pct"] == pytest.approx(88 / 148)
    assert hard["service_points_won_pct"] == pytest.approx(102 / 148)
    assert hard["aces_per_match"] == pytest.approx(6.0)
    assert hard["hold_rate"] == pytest.approx(1 - 4 / 22)
    assert hard["return_points_won_pct"] == pytest.approx(50 / 145)
    assert hard["break_points_converted_pct"] == pytest.approx(0.5)


def test_surfaces_are_kept_separate() -> None:
    matches = all_matches()
    result = compute_serve_return_by_surface(matches, "p1")
    assert "HARD" in result
    assert "CLAY" in result
    # clay stats come only from match3, must not be polluted by hard totals
    clay = result["CLAY"]
    assert clay["first_serve_pct"] == pytest.approx(30 / 50)


def test_opponent_perspective_not_included() -> None:
    """p2's stats must not leak into p1's totals even though they share matches."""
    matches = [match1_p1_beats_p2_hard()]
    p1_stats = compute_serve_return_by_surface(matches, "p1")["HARD"]
    p2_stats = compute_serve_return_by_surface(matches, "p2")["HARD"]
    assert p1_stats["first_serve_pct"] != p2_stats["first_serve_pct"]


def test_missing_stat_fields_excluded_from_totals_not_zeroed() -> None:
    match = match1_p1_beats_p2_hard()
    match.w_ace = None
    totals = accumulate_surface_totals([match], "p1")
    assert totals["HARD"].aces == 0
    assert totals["HARD"].matches_with_ace_data == 0
    assert totals["HARD"].svpt == 80  # unrelated field, still summed — a missing ace count must never discard it


def test_aces_per_match_denominator_excludes_matches_missing_ace_data() -> None:
    """Regression guard: aces_per_match must average only over matches
    that actually reported an ace count, not over all matches — otherwise
    a single match with missing ace data silently dilutes the average.
    """
    m1 = match1_p1_beats_p2_hard()  # w_ace=8
    m2 = match2_p1_loses_to_p3_hard()  # l_ace=4
    m2.l_ace = None  # simulate missing ace data for this match

    result = compute_serve_return_by_surface([m1, m2], "p1")
    assert result["HARD"]["aces_per_match"] == pytest.approx(8.0)  # averaged over 1 match, not 2


def test_player_with_no_matches_returns_empty_dict() -> None:
    assert compute_serve_return_by_surface(all_matches(), "ghost_player") == {}


def test_as_of_excludes_future_matches() -> None:
    matches = all_matches()
    as_of = date(2024, 1, 15)  # only match1 (2024-01-10) has happened
    result = compute_serve_return_by_surface(matches, "p1", as_of=as_of)
    assert "CLAY" not in result  # match3 (clay) is in the future relative to as_of
    hard = result["HARD"]
    assert hard["aces_per_match"] == pytest.approx(8.0)  # only match1's ace count


def test_unknown_surface_string_ignored() -> None:
    match = match1_p1_beats_p2_hard()
    match.surface = "Astroturf"  # not in SURFACE_MAP
    result = compute_serve_return_by_surface([match], "p1")
    assert result == {}
