"""Incremental xlsx loader for tennis-data.co.uk's ATP/WTA yearly result
files (e.g. `2026/2026.xlsx`, `2026w/2026.xlsx`). Incremental like
SackmannMatchLoader: re-calling `load_all()` after a new yearly file
appears in `data_dir` only parses the new file.

Rows missing an identifying field (date, winner, or loser) are skipped,
never fabricated. A file whose header doesn't contain the columns this
loader needs is skipped entirely rather than guessing column positions —
tennis-data.co.uk's column set has changed over the years (see the
provider investigation), so silently assuming a fixed layout would be
a real correctness risk on an unexpected sheet.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import openpyxl

from tbos.data_adapters.tennis_data.models import TennisDataMatchRow

REQUIRED_COLUMNS = ("Date", "Winner", "Loser")


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None  # unexpected type (e.g. a string) — skip rather than guess a format


def parse_row(row: dict[str, object]) -> TennisDataMatchRow | None:
    match_date = _to_date(row.get("Date"))
    winner = row.get("Winner")
    loser = row.get("Loser")
    if match_date is None or not winner or not loser:
        return None  # cannot identify the match — skip, never guess

    return TennisDataMatchRow(
        match_date=match_date,
        winner_name=str(winner).strip(),
        loser_name=str(loser).strip(),
        winner_sets=_to_int(row.get("Wsets")),
        loser_sets=_to_int(row.get("Lsets")),
        comment=(str(row["Comment"]).strip() if row.get("Comment") is not None else None),
    )


class TennisDataLoader:
    """Points at a local directory containing downloaded tennis-data.co.uk
    `*.xlsx` files (any mix of ATP/WTA years).
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._loaded_files: set[str] = set()
        self._rows: list[TennisDataMatchRow] = []

    def load_all(self) -> list[TennisDataMatchRow]:
        for path in sorted(self._data_dir.glob("*.xlsx")):
            if path.name in self._loaded_files:
                continue
            self._rows.extend(self._parse_file(path))
            self._loaded_files.add(path.name)
        return self._rows

    def loaded_file_count(self) -> int:
        return len(self._loaded_files)

    @staticmethod
    def _parse_file(path: Path) -> list[TennisDataMatchRow]:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            worksheet = workbook.active
            rows_iter = worksheet.iter_rows(values_only=True)
            header = next(rows_iter, None)
            if header is None:
                return []

            column_index = {name: i for i, name in enumerate(header) if name is not None}
            if any(col not in column_index for col in REQUIRED_COLUMNS):
                return []  # unexpected schema — skip file, don't guess positions

            parsed: list[TennisDataMatchRow] = []
            for raw_row in rows_iter:
                row_dict = {
                    name: (raw_row[i] if i < len(raw_row) else None)
                    for name, i in column_index.items()
                }
                result = parse_row(row_dict)
                if result is not None:
                    parsed.append(result)
            return parsed
        finally:
            workbook.close()
