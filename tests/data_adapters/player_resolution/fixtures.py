"""Minimal synthetic MatchRow set carrying real player names/ids that
were verified against TBOS's actual downloaded Sackmann data (see the
Wayback download investigation) — not invented. Only the fields the
resolver reads (winner/loser id+name) matter; everything else is filled
with harmless placeholders.
"""

from __future__ import annotations

from datetime import date

from tbos.data_adapters.sackmann.models import MatchRow


def _match(winner_id: str, winner_name: str, loser_id: str, loser_name: str) -> MatchRow:
    return MatchRow(
        tourney_date=date(2024, 1, 1), surface="Hard", tourney_level="A", round="F",
        best_of=3, score="6-4 6-3",
        winner_id=winner_id, winner_name=winner_name, winner_hand=None,
        winner_age=None, winner_rank=None,
        loser_id=loser_id, loser_name=loser_name, loser_hand=None,
        loser_age=None, loser_rank=None,
        w_ace=None, w_df=None, w_svpt=None, w_1stIn=None, w_1stWon=None, w_2ndWon=None,
        w_SvGms=None, w_bpSaved=None, w_bpFaced=None,
        l_ace=None, l_df=None, l_svpt=None, l_1stIn=None, l_1stWon=None, l_2ndWon=None,
        l_SvGms=None, l_bpSaved=None, l_bpFaced=None,
    )


def real_player_matches() -> list[MatchRow]:
    # player_id values confirmed against the real downloaded ATP dataset.
    return [
        _match("104925", "Novak Djokovic", "207989", "Carlos Alcaraz"),
        _match("216347", "Iga Swiatek", "221103", "Coco Gauff"),
        _match("200000", "Felix Auger Aliassime", "122298", "Botic Van De Zandschulp"),
    ]


def ambiguous_name_matches() -> list[MatchRow]:
    # Two distinct real-world-plausible players sharing an identical
    # normalized name — must never be silently resolved to either.
    return [
        _match("p_a", "John Smith", "999", "Someone Else"),
        _match("p_b", "John Smith", "998", "Another Person"),
    ]
