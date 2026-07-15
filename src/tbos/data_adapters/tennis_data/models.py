"""Raw row shape for tennis-data.co.uk's ATP/WTA xlsx exports. Only the
columns TennisDataPlayerStateAdapter actually uses are modeled — this
source supplies recent match activity, not serve/return statistics, so
there is no attempt to mirror the full sheet (odds columns, rankings,
per-set game counts).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class TennisDataMatchRow(BaseModel):
    match_date: date
    winner_name: str  # tennis-data.co.uk format: "Surname I." (e.g. "Tiafoe F.")
    loser_name: str
    winner_sets: int | None
    loser_sets: int | None
    comment: str | None  # "Completed" | "Retired" | "Walkover" | other/unknown
