from datetime import date

from tbos.data_adapters.sackmann.models import MatchRow
from tbos.data_adapters.sackmann.tournament_surface import (
    build_tournament_surface_lookup,
    resolve_league_surface,
)
from tbos.inf1_config.taxonomy import Surface


def _match(tourney_name: str | None, surface: str | None, year: int = 2024) -> MatchRow:
    return MatchRow(
        tourney_date=date(year, 1, 1), tourney_name=tourney_name, surface=surface,
        tourney_level="A", round="F", best_of=3, score="6-4 6-3",
        winner_id="p1", winner_name="Player One", winner_hand=None, winner_age=None, winner_rank=None,
        loser_id="p2", loser_name="Player Two", loser_hand=None, loser_age=None, loser_rank=None,
        w_ace=None, w_df=None, w_svpt=None, w_1stIn=None, w_1stWon=None, w_2ndWon=None,
        w_SvGms=None, w_bpSaved=None, w_bpFaced=None,
        l_ace=None, l_df=None, l_svpt=None, l_1stIn=None, l_1stWon=None, l_2ndWon=None,
        l_SvGms=None, l_bpSaved=None, l_bpFaced=None,
    )


def test_consistent_surface_across_years_is_trusted() -> None:
    # Real evidence: Bastad is Clay in every loaded ATP year, 2003-2024.
    matches = [_match("Bastad", "Clay", 2022), _match("Bastad", "Clay", 2023), _match("Bastad", "Clay", 2024)]
    lookup = build_tournament_surface_lookup(matches)
    assert lookup["bastad"] == Surface.CLAY


def test_inconsistent_surface_across_years_excluded_not_guessed() -> None:
    matches = [_match("Relocated Open", "Hard", 2022), _match("Relocated Open", "Clay", 2023)]
    lookup = build_tournament_surface_lookup(matches)
    assert "relocated open" not in lookup


def test_missing_tourney_name_ignored() -> None:
    matches = [_match(None, "Hard")]
    lookup = build_tournament_surface_lookup(matches)
    assert lookup == {}


def test_missing_surface_ignored() -> None:
    matches = [_match("Some Open", None)]
    lookup = build_tournament_surface_lookup(matches)
    assert lookup == {}


def test_unmapped_surface_string_ignored() -> None:
    matches = [_match("Weird Open", "Astroturf")]
    lookup = build_tournament_surface_lookup(matches)
    assert lookup == {}


def test_surface_change_outside_recency_window_resolves_to_recent_surface() -> None:
    # Real case: the US Open was Grass (1968-1974), Clay (1975), then Hard
    # (1979-2024). A genuine surface change decades ago must not permanently
    # block a tournament whose surface has been stable and verified since.
    matches = [_match("US Open", "Grass", 1970), _match("US Open", "Clay", 1975)]
    matches += [_match("US Open", "Hard", year) for year in range(2015, 2025)]
    lookup = build_tournament_surface_lookup(matches)
    assert lookup["us open"] == Surface.HARD


def test_edition_exactly_outside_window_is_ignored() -> None:
    matches = [_match("Boundary Open", "Grass", 2014)]
    matches += [_match("Boundary Open", "Hard", year) for year in range(2015, 2025)]
    lookup = build_tournament_surface_lookup(matches)
    assert lookup["boundary open"] == Surface.HARD


def test_surface_change_inside_recency_window_still_excluded() -> None:
    # Anti-guessing preserved: a tournament that changed surface recently is
    # genuinely ambiguous for an upcoming match — exclude, never guess.
    matches = [_match("Relocated Open", "Clay", 2020)]
    matches += [_match("Relocated Open", "Hard", year) for year in range(2021, 2025)]
    lookup = build_tournament_surface_lookup(matches)
    assert "relocated open" not in lookup


def test_recency_window_counts_editions_not_rows() -> None:
    # A full draw is many rows per edition; those must not push older editions
    # out of the window — the window is measured in editions, not matches.
    matches = [_match("Big Draw Open", "Clay", 2023) for _ in range(50)]
    matches += [_match("Big Draw Open", "Hard", 2024) for _ in range(50)]
    lookup = build_tournament_surface_lookup(matches)
    assert "big draw open" not in lookup


def test_recency_window_is_relative_to_each_tournaments_own_last_edition() -> None:
    # A discontinued tournament still resolves from its own final editions —
    # the window must not be anchored to the dataset's global latest year.
    matches = [_match("Discontinued Open", "Carpet", year) for year in range(1970, 1980)]
    lookup = build_tournament_surface_lookup(matches)
    assert lookup["discontinued open"] == Surface.CARPET


def test_conflicting_surfaces_within_a_single_edition_excluded() -> None:
    matches = [_match("Ambiguous Open", "Hard", 2024), _match("Ambiguous Open", "Clay", 2024)]
    lookup = build_tournament_surface_lookup(matches)
    assert "ambiguous open" not in lookup


def test_resolve_league_surface_strips_tour_prefix_and_location() -> None:
    lookup = {"bastad": Surface.CLAY}
    assert resolve_league_surface("ATP - Bastad, Sweden", lookup) == Surface.CLAY


def test_resolve_league_surface_challenger_prefix() -> None:
    lookup = {"cordenons": Surface.CLAY}
    assert resolve_league_surface("Challenger - Cordenons, Italy", lookup) == Surface.CLAY


def test_resolve_league_surface_no_dash_prefix() -> None:
    lookup = {"wimbledon": Surface.GRASS}
    assert resolve_league_surface("Wimbledon", lookup) == Surface.GRASS


def test_resolve_league_surface_unknown_tournament_returns_none() -> None:
    lookup = {"bastad": Surface.CLAY}
    assert resolve_league_surface("WTA - Iasi, Romania", lookup) is None


def test_resolve_league_surface_case_and_whitespace_insensitive() -> None:
    lookup = {"athens": Surface.CLAY}
    assert resolve_league_surface("WTA -   ATHENS  , Greece", lookup) == Surface.CLAY


def test_punctuation_differences_do_not_block_a_match() -> None:
    # Real case: Sackmann stores "Winston-Salem", odds-api.io sends
    # "ATP - Winston Salem, USA". Same tournament, one hyphen apart.
    matches = [_match("Winston-Salem", "Hard", year) for year in range(2015, 2025)]
    lookup = build_tournament_surface_lookup(matches)
    assert resolve_league_surface("ATP - Winston Salem, USA", lookup) == Surface.HARD


def test_punctuation_normalisation_is_symmetric() -> None:
    # The reverse spelling must work too — neither side is privileged.
    matches = [_match("Winston Salem", "Hard", year) for year in range(2015, 2025)]
    lookup = build_tournament_surface_lookup(matches)
    assert resolve_league_surface("ATP - Winston-Salem, USA", lookup) == Surface.HARD


def test_numeric_edition_suffix_falls_back_to_the_base_tournament() -> None:
    # A second edition in the same year ("Kingston 2") is the same event on
    # the same surface; Sackmann only ever names the base tournament.
    matches = [_match("Kingston", "Hard", year) for year in range(2015, 2025)]
    lookup = build_tournament_surface_lookup(matches)
    assert resolve_league_surface("Challenger - Kingston 2, Jamaica", lookup) == Surface.HARD


def test_numeric_suffix_never_overrides_an_exact_match() -> None:
    # If the numbered name exists in its own right, it wins — the suffix
    # fallback is a last resort, never a substitution.
    matches = [_match("Kingston", "Hard", y) for y in range(2015, 2025)]
    matches += [_match("Kingston 2", "Clay", y) for y in range(2015, 2025)]
    lookup = build_tournament_surface_lookup(matches)
    assert resolve_league_surface("Challenger - Kingston 2, Jamaica", lookup) == Surface.CLAY


def test_punctuation_collision_between_real_tournaments_is_excluded_not_guessed() -> None:
    # If collapsing punctuation merges two genuinely different tournaments
    # that play on different surfaces, the anti-guessing rule must still
    # exclude the merged name rather than pick one.
    matches = [_match("Saint-Malo", "Clay", y) for y in range(2015, 2025)]
    matches += [_match("Saint Malo", "Hard", y) for y in range(2015, 2025)]
    lookup = build_tournament_surface_lookup(matches)
    assert "saint malo" not in lookup
