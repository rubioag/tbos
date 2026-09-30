"""Raw row shape for Jeff Sackmann's tennis_atp/tennis_wta CSV match
files (github.com/JeffSackmann). Column names match the dataset exactly;
this is the only place that needs to change if the upstream schema drifts.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class MatchRow(BaseModel):
    tourney_date: date
    tourney_name: str | None
    surface: str | None
    tourney_level: str | None
    round: str | None
    best_of: int | None
    score: str | None

    winner_id: str
    winner_name: str
    winner_hand: str | None
    winner_age: float | None
    winner_rank: int | None

    loser_id: str
    loser_name: str
    loser_hand: str | None
    loser_age: float | None
    loser_rank: int | None

    w_ace: int | None
    w_df: int | None
    w_svpt: int | None
    w_1stIn: int | None
    w_1stWon: int | None
    w_2ndWon: int | None
    w_SvGms: int | None
    w_bpSaved: int | None
    w_bpFaced: int | None

    l_ace: int | None
    l_df: int | None
    l_svpt: int | None
    l_1stIn: int | None
    l_1stWon: int | None
    l_2ndWon: int | None
    l_SvGms: int | None
    l_bpSaved: int | None
    l_bpFaced: int | None


SURFACE_MAP: dict[str, str] = {"Hard": "HARD", "Clay": "CLAY", "Grass": "GRASS", "Carpet": "CARPET"}
