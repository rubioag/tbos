"""Hand-verified synthetic match set, reused across aggregator/h2h/
player_state/adapter tests. Expected aggregate values are computed and
documented in test_aggregator.py's module docstring-style comments.
"""

from __future__ import annotations

from datetime import date

from tbos.data_adapters.sackmann.models import MatchRow


def match1_p1_beats_p2_hard() -> MatchRow:
    return MatchRow(
        tourney_date=date(2024, 1, 10), surface="Hard", tourney_level="A", round="F", best_of=3, score="6-4 6-3",
        winner_id="p1", winner_name="Player One", winner_hand="R", winner_age=24.5, winner_rank=10,
        loser_id="p2", loser_name="Player Two", loser_hand="L", loser_age=26.1, loser_rank=20,
        w_ace=8, w_df=2, w_svpt=80, w_1stIn=50, w_1stWon=40, w_2ndWon=20, w_SvGms=12, w_bpSaved=3, w_bpFaced=4,
        l_ace=5, l_df=3, l_svpt=75, l_1stIn=45, l_1stWon=30, l_2ndWon=15, l_SvGms=11, l_bpSaved=2, l_bpFaced=5,
    )


def match2_p1_loses_to_p3_hard() -> MatchRow:
    return MatchRow(
        tourney_date=date(2024, 2, 15), surface="Hard", tourney_level="A", round="QF", best_of=3, score="7-6(4) 3-6 6-2",
        winner_id="p3", winner_name="Player Three", winner_hand="R", winner_age=28.0, winner_rank=5,
        loser_id="p1", loser_name="Player One", loser_hand="R", loser_age=24.6, loser_rank=10,
        w_ace=6, w_df=1, w_svpt=70, w_1stIn=40, w_1stWon=32, w_2ndWon=18, w_SvGms=10, w_bpSaved=2, w_bpFaced=3,
        l_ace=4, l_df=2, l_svpt=68, l_1stIn=38, l_1stWon=28, l_2ndWon=14, l_SvGms=10, l_bpSaved=1, l_bpFaced=4,
    )


def match3_p1_beats_p2_clay() -> MatchRow:
    return MatchRow(
        tourney_date=date(2024, 3, 1), surface="Clay", tourney_level="A", round="R16", best_of=3, score="6-2 6-3",
        winner_id="p1", winner_name="Player One", winner_hand="R", winner_age=24.7, winner_rank=9,
        loser_id="p2", loser_name="Player Two", loser_hand="L", loser_age=26.2, loser_rank=21,
        w_ace=3, w_df=1, w_svpt=50, w_1stIn=30, w_1stWon=25, w_2ndWon=10, w_SvGms=8, w_bpSaved=2, w_bpFaced=2,
        l_ace=2, l_df=2, l_svpt=48, l_1stIn=28, l_1stWon=20, l_2ndWon=9, l_SvGms=8, l_bpSaved=1, l_bpFaced=3,
    )


def match4_p1_loses_to_p4_retirement() -> MatchRow:
    return MatchRow(
        tourney_date=date(2024, 4, 5), surface="Hard", tourney_level="A", round="R32", best_of=3, score="6-4 3-2 RET",
        winner_id="p4", winner_name="Player Four", winner_hand="R", winner_age=22.0, winner_rank=15,
        loser_id="p1", loser_name="Player One", loser_hand="R", loser_age=24.8, loser_rank=10,
        w_ace=4, w_df=1, w_svpt=45, w_1stIn=28, w_1stWon=22, w_2ndWon=10, w_SvGms=7, w_bpSaved=1, w_bpFaced=2,
        l_ace=3, l_df=1, l_svpt=40, l_1stIn=24, l_1stWon=18, l_2ndWon=8, l_SvGms=6, l_bpSaved=1, l_bpFaced=3,
    )


def all_matches() -> list[MatchRow]:
    return [
        match1_p1_beats_p2_hard(),
        match2_p1_loses_to_p3_hard(),
        match3_p1_beats_p2_clay(),
        match4_p1_loses_to_p4_retirement(),
    ]
