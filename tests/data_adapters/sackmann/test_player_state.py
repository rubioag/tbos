from datetime import date

from tbos.data_adapters.sackmann.player_state import (
    compute_days_since_last_match,
    compute_deviation_from_baseline,
    compute_matches_last_n_days,
    compute_sets_played_last_n_days,
    count_sets_in_score,
    detect_injury_flags,
)
from tests.data_adapters.sackmann.fixtures import all_matches


def test_count_sets_simple() -> None:
    assert count_sets_in_score("6-4 6-3") == 2


def test_count_sets_with_tiebreak_notation() -> None:
    assert count_sets_in_score("7-6(4) 3-6 6-2") == 3


def test_count_sets_with_retirement_excludes_ret_token() -> None:
    assert count_sets_in_score("6-4 3-2 RET") == 2


def test_count_sets_empty_score() -> None:
    assert count_sets_in_score(None) == 0
    assert count_sets_in_score("") == 0


def test_matches_last_n_days_counts_within_window() -> None:
    # match1 = 2024-01-10; as_of = 2024-01-20, 14-day window -> cutoff 2024-01-06
    count = compute_matches_last_n_days(all_matches(), "p1", as_of=date(2024, 1, 20), days=14)
    assert count == 1


def test_matches_last_n_days_excludes_matches_outside_window() -> None:
    # as_of far enough that no matches fall in the last 14 days
    count = compute_matches_last_n_days(all_matches(), "p1", as_of=date(2024, 6, 1), days=14)
    assert count == 0


def test_sets_played_last_n_days_sums_across_matches() -> None:
    total = compute_sets_played_last_n_days(all_matches(), "p1", as_of=date(2024, 1, 20), days=14)
    assert total == 2  # match1's score "6-4 6-3"


def test_days_since_last_match() -> None:
    days = compute_days_since_last_match(all_matches(), "p1", as_of=date(2024, 1, 20))
    assert days == 10  # match1 on 2024-01-10


def test_days_since_last_match_none_when_no_history() -> None:
    assert compute_days_since_last_match(all_matches(), "ghost", as_of=date(2024, 1, 20)) is None


def test_deviation_from_baseline_is_zero_for_single_match() -> None:
    """With only one match ever, recent == career baseline exactly."""
    from tests.data_adapters.sackmann.fixtures import match1_p1_beats_p2_hard

    deviation = compute_deviation_from_baseline([match1_p1_beats_p2_hard()], "p1", as_of=date(2024, 1, 20))
    assert deviation == 0.0


def test_deviation_from_baseline_none_with_no_history() -> None:
    assert compute_deviation_from_baseline(all_matches(), "ghost", as_of=date(2024, 1, 20)) is None


def test_injury_flag_detected_on_retirement_loss() -> None:
    flags = detect_injury_flags(all_matches(), "p1", as_of=date(2024, 4, 10), lookback_days=30)
    assert len(flags) == 1
    assert flags[0]["severity"] == "MINOR"
    assert flags[0]["source"] == "sackmann_retirement_heuristic"


def test_no_injury_flag_for_the_winner_of_a_retirement_match() -> None:
    """p4 won via p1's retirement — p4 itself did not retire, no flag."""
    flags = detect_injury_flags(all_matches(), "p4", as_of=date(2024, 4, 10), lookback_days=30)
    assert flags == []


def test_injury_flag_respects_lookback_window() -> None:
    flags = detect_injury_flags(all_matches(), "p1", as_of=date(2024, 6, 1), lookback_days=30)
    assert flags == []
