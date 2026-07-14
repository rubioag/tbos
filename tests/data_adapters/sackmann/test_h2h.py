from datetime import date

from tbos.data_adapters.sackmann.h2h import compute_h2h_records

from tests.data_adapters.sackmann.fixtures import all_matches


def test_h2h_includes_win_and_loss_relative_to_player() -> None:
    records = compute_h2h_records(all_matches(), "p1")
    by_opponent = {}
    for r in records:
        by_opponent.setdefault(r["opponent_id"], []).append(r)

    assert len(by_opponent["p2"]) == 2  # match1 (win) + match3 (win)
    assert all(r["result"] == "WIN" for r in by_opponent["p2"])

    assert len(by_opponent["p3"]) == 1
    assert by_opponent["p3"][0]["result"] == "LOSS"


def test_h2h_filtered_to_single_opponent() -> None:
    records = compute_h2h_records(all_matches(), "p1", opponent_id="p3")
    assert len(records) == 1
    assert records[0]["opponent_id"] == "p3"


def test_h2h_surface_and_date_populated() -> None:
    records = compute_h2h_records(all_matches(), "p1", opponent_id="p2")
    assert records[0]["surface"] in ("HARD", "CLAY")
    assert records[0]["date"] == "2024-01-10"


def test_h2h_respects_as_of() -> None:
    records = compute_h2h_records(all_matches(), "p1", opponent_id="p2", as_of=date(2024, 1, 15))
    assert len(records) == 1  # only match1, match3 is in the future


def test_h2h_no_matches_against_unknown_opponent() -> None:
    assert compute_h2h_records(all_matches(), "p1", opponent_id="nobody") == []
