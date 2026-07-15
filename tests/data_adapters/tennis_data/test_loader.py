from datetime import date

import openpyxl

from tbos.data_adapters.tennis_data.loader import TennisDataLoader, parse_row


def _write_xlsx(path, header, rows) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_parse_row_valid() -> None:
    row = parse_row({
        "Date": date(2026, 7, 10), "Winner": "Tiafoe F.", "Loser": "Nadal R.",
        "Wsets": 2, "Lsets": 0, "Comment": "Completed",
    })
    assert row is not None
    assert row.match_date == date(2026, 7, 10)
    assert row.winner_name == "Tiafoe F."
    assert row.winner_sets == 2
    assert row.comment == "Completed"


def test_parse_row_missing_date_skipped() -> None:
    assert parse_row({"Date": None, "Winner": "Tiafoe F.", "Loser": "Nadal R."}) is None


def test_parse_row_missing_winner_skipped() -> None:
    assert parse_row({"Date": date(2026, 1, 1), "Winner": None, "Loser": "Nadal R."}) is None


def test_parse_row_non_date_type_skipped() -> None:
    assert parse_row({"Date": "2026-01-01", "Winner": "A", "Loser": "B"}) is None


def test_load_all_parses_real_shaped_file(tmp_path) -> None:
    header = ["ATP", "Location", "Tournament", "Date", "Series", "Court", "Surface",
              "Round", "Best of", "Winner", "Loser", "WRank", "LRank", "WPts", "LPts",
              "W1", "L1", "W2", "L2", "Wsets", "Lsets", "Comment"]
    rows = [
        [1, "Brisbane", "Brisbane International", date(2026, 1, 4), "ATP250", "Outdoor",
         "Hard", "1st Round", 3, "Tiafoe F.", "Vukic A.", 30, 87, 1485, 693,
         6, 2, 6, 2, 2, 0, "Completed"],
        [2, "Brisbane", "Brisbane International", date(2026, 1, 5), "ATP250", "Outdoor",
         "Hard", "2nd Round", 3, "Djokovic N.", "Tiafoe F.", 1, 30, 9000, 1485,
         6, 3, None, None, 1, 0, "Retired"],
    ]
    path = tmp_path / "2026.xlsx"
    _write_xlsx(path, header, rows)

    loader = TennisDataLoader(tmp_path)
    parsed = loader.load_all()

    assert len(parsed) == 2
    assert parsed[0].winner_name == "Tiafoe F."
    assert parsed[1].comment == "Retired"
    assert loader.loaded_file_count() == 1


def test_load_all_incremental_skips_already_loaded_file(tmp_path) -> None:
    header = ["Date", "Winner", "Loser", "Wsets", "Lsets", "Comment"]
    _write_xlsx(tmp_path / "a.xlsx", header, [[date(2026, 1, 1), "A B.", "C D.", 2, 0, "Completed"]])

    loader = TennisDataLoader(tmp_path)
    first = loader.load_all()
    assert len(first) == 1

    second = loader.load_all()
    assert len(second) == 1  # not duplicated
    assert loader.loaded_file_count() == 1


def test_load_all_new_file_added_incrementally(tmp_path) -> None:
    header = ["Date", "Winner", "Loser", "Wsets", "Lsets", "Comment"]
    _write_xlsx(tmp_path / "a.xlsx", header, [[date(2026, 1, 1), "A B.", "C D.", 2, 0, "Completed"]])
    loader = TennisDataLoader(tmp_path)
    loader.load_all()

    _write_xlsx(tmp_path / "b.xlsx", header, [[date(2026, 2, 1), "E F.", "G H.", 2, 1, "Completed"]])
    result = loader.load_all()
    assert len(result) == 2
    assert loader.loaded_file_count() == 2


def test_unexpected_schema_file_skipped_entirely(tmp_path) -> None:
    _write_xlsx(tmp_path / "weird.xlsx", ["Foo", "Bar"], [["x", "y"]])
    loader = TennisDataLoader(tmp_path)
    assert loader.load_all() == []
