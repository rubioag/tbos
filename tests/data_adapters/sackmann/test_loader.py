from pathlib import Path

from tbos.data_adapters.sackmann.loader import SackmannMatchLoader, parse_row

HEADER = (
    "tourney_date,surface,tourney_level,round,best_of,score,"
    "winner_id,winner_name,winner_hand,winner_age,winner_rank,"
    "loser_id,loser_name,loser_hand,loser_age,loser_rank,"
    "w_ace,w_df,w_svpt,w_1stIn,w_1stWon,w_2ndWon,w_SvGms,w_bpSaved,w_bpFaced,"
    "l_ace,l_df,l_svpt,l_1stIn,l_1stWon,l_2ndWon,l_SvGms,l_bpSaved,l_bpFaced\n"
)


def _row(**overrides: str) -> str:
    defaults = dict(
        tourney_date="20240110", surface="Hard", tourney_level="A", round="F", best_of="3", score="6-4 6-3",
        winner_id="p1", winner_name="Player One", winner_hand="R", winner_age="24.5", winner_rank="10",
        loser_id="p2", loser_name="Player Two", loser_hand="L", loser_age="26.1", loser_rank="20",
        w_ace="8", w_df="2", w_svpt="80", w_1stIn="50", w_1stWon="40", w_2ndWon="20", w_SvGms="12", w_bpSaved="3", w_bpFaced="4",
        l_ace="5", l_df="3", l_svpt="75", l_1stIn="45", l_1stWon="30", l_2ndWon="15", l_SvGms="11", l_bpSaved="2", l_bpFaced="5",
    )
    defaults.update(overrides)
    return ",".join(defaults[k] for k in [
        "tourney_date", "surface", "tourney_level", "round", "best_of", "score",
        "winner_id", "winner_name", "winner_hand", "winner_age", "winner_rank",
        "loser_id", "loser_name", "loser_hand", "loser_age", "loser_rank",
        "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_SvGms", "w_bpSaved", "w_bpFaced",
        "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_SvGms", "l_bpSaved", "l_bpFaced",
    ]) + "\n"


def test_parse_row_produces_match_row() -> None:
    fields = HEADER.strip().split(",")
    values = _row().strip().split(",")
    row = dict(zip(fields, values, strict=True))
    match = parse_row(row)
    assert match is not None
    assert match.winner_id == "p1"
    assert match.surface == "Hard"
    assert match.w_svpt == 80


def test_parse_row_rejects_missing_date() -> None:
    fields = HEADER.strip().split(",")
    values = _row(tourney_date="").strip().split(",")
    row = dict(zip(fields, values, strict=True))
    assert parse_row(row) is None


def test_parse_row_rejects_missing_winner_id() -> None:
    fields = HEADER.strip().split(",")
    values = _row(winner_id="").strip().split(",")
    row = dict(zip(fields, values, strict=True))
    assert parse_row(row) is None


def test_parse_row_keeps_row_with_missing_stat_columns() -> None:
    """Missing individual stat fields must not reject the whole row —
    the aggregator decides field by field what it can compute."""
    fields = HEADER.strip().split(",")
    values = _row(w_ace="").strip().split(",")
    row = dict(zip(fields, values, strict=True))
    match = parse_row(row)
    assert match is not None
    assert match.w_ace is None


def test_loader_loads_all_csv_files(tmp_path: Path) -> None:
    (tmp_path / "atp_matches_2024.csv").write_text(HEADER + _row())
    loader = SackmannMatchLoader(tmp_path)
    matches = loader.load_all()
    assert len(matches) == 1
    assert loader.loaded_file_count() == 1


def test_loader_is_incremental_does_not_reparse_known_files(tmp_path: Path) -> None:
    (tmp_path / "atp_matches_2024.csv").write_text(HEADER + _row())
    loader = SackmannMatchLoader(tmp_path)
    loader.load_all()

    (tmp_path / "atp_matches_2025.csv").write_text(HEADER + _row(winner_id="p3", tourney_date="20250101"))
    matches = loader.load_all()

    assert len(matches) == 2
    assert loader.loaded_file_count() == 2


def test_loader_skips_malformed_rows(tmp_path: Path) -> None:
    bad_row = _row(winner_id="")
    (tmp_path / "atp_matches_2024.csv").write_text(HEADER + _row() + bad_row)
    loader = SackmannMatchLoader(tmp_path)
    matches = loader.load_all()
    assert len(matches) == 1
