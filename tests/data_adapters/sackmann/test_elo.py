from datetime import date

from tbos.data_adapters.sackmann.elo import DEFAULT_RATING, EloRatings
from tbos.data_adapters.sackmann.models import MatchRow


def _match(
    tourney_date: date, winner_id: str, loser_id: str, surface: str | None = "Hard",
) -> MatchRow:
    return MatchRow(
        tourney_date=tourney_date, tourney_name="Test Event", surface=surface,
        tourney_level="A", round="F", best_of=3, score="6-4 6-3",
        winner_id=winner_id, winner_name="Winner", winner_hand=None, winner_age=None, winner_rank=None,
        loser_id=loser_id, loser_name="Loser", loser_hand=None, loser_age=None, loser_rank=None,
        w_ace=None, w_df=None, w_svpt=None, w_1stIn=None, w_1stWon=None, w_2ndWon=None,
        w_SvGms=None, w_bpSaved=None, w_bpFaced=None,
        l_ace=None, l_df=None, l_svpt=None, l_1stIn=None, l_1stWon=None, l_2ndWon=None,
        l_SvGms=None, l_bpSaved=None, l_bpFaced=None,
    )


def test_unrated_player_starts_at_default_rating() -> None:
    ratings = EloRatings()
    assert ratings.get_overall("nobody") == DEFAULT_RATING


def test_winner_gains_loser_loses_equal_ratings() -> None:
    ratings = EloRatings()
    ratings.record_match("p1", "p2", "Hard")
    assert ratings.get_overall("p1") > DEFAULT_RATING
    assert ratings.get_overall("p2") < DEFAULT_RATING
    # Equal pre-match ratings: expected score 0.5 each, K=32 symmetric.
    assert ratings.get_overall("p1") - DEFAULT_RATING == DEFAULT_RATING - ratings.get_overall("p2")


def test_upset_win_gains_more_than_expected_win() -> None:
    """A lower-rated player beating a much higher-rated one should gain
    more rating points than a win between two equally-rated players —
    the core Elo property (surprising results move ratings further).
    """
    equal_ratings = EloRatings()
    equal_ratings.record_match("p1", "p2", "Hard")
    equal_gain = equal_ratings.get_overall("p1") - DEFAULT_RATING

    upset_ratings = EloRatings()
    # Build a rating gap: p3 beats many opponents to get well above 1500,
    # p4 stays unrated at 1500, then p4 (underdog) beats p3 (favorite).
    for i in range(10):
        upset_ratings.record_match("p3", f"filler{i}", "Hard")
    upset_ratings.record_match("p4", "p3", "Hard")
    upset_gain = upset_ratings.get_overall("p4") - DEFAULT_RATING

    assert upset_gain > equal_gain


def test_from_matches_processes_chronologically_not_file_order() -> None:
    """Feeding matches out of chronological order must produce the same
    result as feeding them in order — from_matches sorts by tourney_date.
    """
    early = _match(date(2020, 1, 1), "p1", "p2")
    late = _match(date(2021, 1, 1), "p2", "p1")

    forward = EloRatings.from_matches([early, late])
    reversed_input = EloRatings.from_matches([late, early])

    assert forward.get_overall("p1") == reversed_input.get_overall("p1")
    assert forward.get_overall("p2") == reversed_input.get_overall("p2")


def test_surface_rating_tracked_independently_of_overall() -> None:
    ratings = EloRatings()
    ratings.record_match("p1", "p2", "Clay")
    assert ratings.get_by_surface("p1") == {"CLAY": ratings.get_overall("p1")}
    # No Hard-court match recorded for these players yet.
    assert "HARD" not in ratings.get_by_surface("p1")


def test_unmapped_surface_string_updates_overall_but_not_by_surface() -> None:
    ratings = EloRatings()
    ratings.record_match("p1", "p2", "Astroturf")
    assert ratings.get_overall("p1") > DEFAULT_RATING
    assert ratings.get_by_surface("p1") == {}


def test_missing_surface_updates_overall_but_not_by_surface() -> None:
    ratings = EloRatings()
    ratings.record_match("p1", "p2", None)
    assert ratings.get_overall("p1") > DEFAULT_RATING
    assert ratings.get_by_surface("p1") == {}
