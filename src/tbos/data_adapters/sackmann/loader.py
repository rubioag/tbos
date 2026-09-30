"""Incremental CSV loader for Sackmann's tennis_atp/tennis_wta match
files. Incremental means file-level: re-calling `load_all()` after new
yearly CSV files appear in `data_dir` (e.g. a new `atp_matches_2027.csv`
after a `git pull` of the upstream repo) only parses the new files —
already-loaded filenames are never re-read.

Malformed rows (missing required identity fields) are skipped, never
fabricated; rows with missing individual stat columns are kept (the
aggregator decides field-by-field what it can compute).
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from tbos.data_adapters.sackmann.models import MatchRow


def _parse_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _parse_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_date(value: str) -> date | None:
    value = value.strip()
    if len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def parse_row(row: dict[str, str]) -> MatchRow | None:
    tourney_date = _parse_date(row.get("tourney_date", ""))
    winner_id = (row.get("winner_id") or "").strip()
    loser_id = (row.get("loser_id") or "").strip()
    if tourney_date is None or not winner_id or not loser_id:
        return None  # cannot identify the match or its date — skip, never guess

    return MatchRow(
        tourney_date=tourney_date,
        tourney_name=(row.get("tourney_name") or "").strip() or None,
        surface=(row.get("surface") or "").strip() or None,
        tourney_level=(row.get("tourney_level") or "").strip() or None,
        round=(row.get("round") or "").strip() or None,
        best_of=_parse_int(row.get("best_of", "")),
        score=(row.get("score") or "").strip() or None,
        winner_id=winner_id,
        winner_name=(row.get("winner_name") or "").strip(),
        winner_hand=(row.get("winner_hand") or "").strip() or None,
        winner_age=_parse_float(row.get("winner_age", "")),
        winner_rank=_parse_int(row.get("winner_rank", "")),
        loser_id=loser_id,
        loser_name=(row.get("loser_name") or "").strip(),
        loser_hand=(row.get("loser_hand") or "").strip() or None,
        loser_age=_parse_float(row.get("loser_age", "")),
        loser_rank=_parse_int(row.get("loser_rank", "")),
        w_ace=_parse_int(row.get("w_ace", "")), w_df=_parse_int(row.get("w_df", "")),
        w_svpt=_parse_int(row.get("w_svpt", "")), w_1stIn=_parse_int(row.get("w_1stIn", "")),
        w_1stWon=_parse_int(row.get("w_1stWon", "")), w_2ndWon=_parse_int(row.get("w_2ndWon", "")),
        w_SvGms=_parse_int(row.get("w_SvGms", "")), w_bpSaved=_parse_int(row.get("w_bpSaved", "")),
        w_bpFaced=_parse_int(row.get("w_bpFaced", "")),
        l_ace=_parse_int(row.get("l_ace", "")), l_df=_parse_int(row.get("l_df", "")),
        l_svpt=_parse_int(row.get("l_svpt", "")), l_1stIn=_parse_int(row.get("l_1stIn", "")),
        l_1stWon=_parse_int(row.get("l_1stWon", "")), l_2ndWon=_parse_int(row.get("l_2ndWon", "")),
        l_SvGms=_parse_int(row.get("l_SvGms", "")), l_bpSaved=_parse_int(row.get("l_bpSaved", "")),
        l_bpFaced=_parse_int(row.get("l_bpFaced", "")),
    )


class SackmannMatchLoader:
    """Points at a local directory containing a cloned/synced copy of
    JeffSackmann/tennis_atp and/or tennis_wta (`*matches*.csv` files).
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._loaded_files: set[str] = set()
        self._matches: list[MatchRow] = []

    def load_all(self) -> list[MatchRow]:
        for path in sorted(self._data_dir.glob("*matches*.csv")):
            if path.name in self._loaded_files:
                continue
            self._matches.extend(self._parse_file(path))
            self._loaded_files.add(path.name)
        return self._matches

    def loaded_file_count(self) -> int:
        return len(self._loaded_files)

    @staticmethod
    def _parse_file(path: Path) -> list[MatchRow]:
        rows: list[MatchRow] = []
        with path.open(newline="", encoding="utf-8") as f:
            for raw_row in csv.DictReader(f):
                parsed = parse_row(raw_row)
                if parsed is not None:
                    rows.append(parsed)
        return rows
