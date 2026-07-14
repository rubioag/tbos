"""Head-to-head record extraction. Output shape matches exactly what
CE.2's Matchup Model already expects (locked contract, unchanged):
`{opponent_id, date, surface, result}` per match, result relative to
`player_id`.
"""

from __future__ import annotations

from datetime import date

from tbos.data_adapters.sackmann.models import SURFACE_MAP, MatchRow


def compute_h2h_records(
    matches: list[MatchRow], player_id: str, *, opponent_id: str | None = None, as_of: date | None = None
) -> list[dict]:
    records: list[dict] = []
    for match in matches:
        if as_of is not None and match.tourney_date > as_of:
            continue
        if match.winner_id == player_id:
            opponent, result = match.loser_id, "WIN"
        elif match.loser_id == player_id:
            opponent, result = match.winner_id, "LOSS"
        else:
            continue
        if opponent_id is not None and opponent != opponent_id:
            continue
        records.append({
            "opponent_id": opponent,
            "date": match.tourney_date.isoformat(),
            "surface": SURFACE_MAP.get(match.surface or "", match.surface or "UNKNOWN"),
            "result": result,
        })
    return records
