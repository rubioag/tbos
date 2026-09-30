from datetime import datetime, timezone

from tbos.ce2_prediction.determinism import assert_deterministic
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.ce2_prediction.matchup_model import MatchupModel
from tbos.inf1_config.taxonomy import Surface

from tests.ce2_prediction.factories import env, make_bundle, make_match_context, make_profile

AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _record(date_str: str, surface: str = "HARD", result: str = "WIN", opponent_id: str = "p2") -> dict:
    return {"opponent_id": opponent_id, "date": date_str, "surface": surface, "result": result}


def test_matchup_model_uses_elo_only_when_no_h2h_instead_of_abstaining() -> None:
    """Real behavior change: Elo carries a real signal even with zero
    prior meetings, so the model no longer abstains unconditionally on
    empty H2H. Default bundle gives both players equal Elo (1500), so
    the Elo-only estimate must be exactly 0.5 (a coin flip prior, not a
    fabricated lean either way).
    """
    output = MatchupModel().estimate(make_bundle())
    assert output.abstained is False
    assert output.estimate["blend_source"] == "elo_only"
    assert output.estimate["h2h_win_rate_player_a"] == 0.5


def test_matchup_model_elo_only_reflects_real_rating_gap() -> None:
    stronger = make_profile(
        "p1", elo_rating=env(1700.0), elo_rating_by_surface=env({"HARD": 1700.0}),
    )
    output = MatchupModel().estimate(make_bundle(player_a_profile=stronger))
    assert output.abstained is False
    assert output.estimate["h2h_win_rate_player_a"] > 0.5


def test_matchup_model_produces_estimate_with_h2h_history() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01")])
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert output.abstained is False
    assert output.estimate["h2h_sample_size"] == 1.0


def test_matchup_model_estimate_never_contains_probability_or_p_win_key() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01")])
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert "p_win" not in output.estimate
    assert "probability" not in output.estimate


def test_matchup_model_is_deterministic() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01"), _record("2024-01-01", result="LOSS")])
    assert_deterministic(MatchupModel(), make_bundle(player_a_profile=profile))


def test_matchup_model_ignores_h2h_records_against_other_opponents() -> None:
    """No RELEVANT H2H (records exist but against a different opponent)
    is the same situation as zero H2H — falls back to Elo-only, doesn't
    abstain, since Elo is unaffected by which opponent the stale H2H
    records mention.
    """
    profile = make_profile("p1", h2h_records=[_record("2025-06-01", opponent_id="someone_else")])
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert output.abstained is False
    assert output.estimate["blend_source"] == "elo_only"


def test_matchup_model_all_wins_gives_high_raw_h2h_but_blended_pulls_toward_elo() -> None:
    profile = make_profile(
        "p1", h2h_records=[_record("2025-06-01", result="WIN"), _record("2025-01-01", result="WIN")],
    )
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    raw_h2h = output.estimate["raw_h2h_win_rate_player_a"]
    blended = output.estimate["h2h_win_rate_player_a"]
    assert raw_h2h > 0.9
    # Equal default Elo (0.5) blended in — final estimate must sit
    # strictly between the pure-H2H signal and the Elo prior, not equal
    # either one outright.
    assert 0.5 < blended < raw_h2h


def test_matchup_model_all_losses_gives_low_raw_h2h_but_blended_pulls_toward_elo() -> None:
    profile = make_profile(
        "p1", h2h_records=[_record("2025-06-01", result="LOSS"), _record("2025-01-01", result="LOSS")],
    )
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    raw_h2h = output.estimate["raw_h2h_win_rate_player_a"]
    blended = output.estimate["h2h_win_rate_player_a"]
    assert raw_h2h < 0.1
    assert raw_h2h < blended < 0.5


def test_matchup_model_more_recent_meeting_weighted_more_heavily() -> None:
    """A recent win + an old loss should tilt the weighted win rate above
    a naive 50/50 average — recency matters, per spec.
    """
    profile = make_profile(
        "p1",
        h2h_records=[
            _record("2025-12-01", result="WIN"),  # recent, near AS_OF via bundle default (2026-01-01)
            _record("2015-01-01", result="LOSS"),  # ancient
        ],
    )
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert output.estimate["h2h_win_rate_player_a"] > 0.5


def test_matchup_model_surface_mismatch_discounts_weight() -> None:
    same_surface = make_profile("p1", h2h_records=[_record("2025-06-01", surface="HARD", result="WIN")])
    diff_surface = make_profile("p1", h2h_records=[_record("2025-06-01", surface="CLAY", result="WIN")])

    out_same = MatchupModel().estimate(make_bundle(player_a_profile=same_surface, match_context=make_match_context(Surface.HARD)))
    out_diff = MatchupModel().estimate(make_bundle(player_a_profile=diff_surface, match_context=make_match_context(Surface.HARD)))

    assert out_diff.estimate["effective_weight"] < out_same.estimate["effective_weight"]


def test_matchup_model_small_sample_has_high_uncertainty() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01")])
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert output.own_uncertainty >= 0.3


def test_matchup_model_larger_sample_has_lower_uncertainty_than_single_meeting() -> None:
    single = make_profile("p1", h2h_records=[_record("2025-06-01")])
    many = make_profile(
        "p1",
        h2h_records=[_record(f"202{i}-01-01") for i in range(5)],
    )
    out_single = MatchupModel().estimate(make_bundle(player_a_profile=single))
    out_many = MatchupModel().estimate(make_bundle(player_a_profile=many))
    assert out_many.own_uncertainty < out_single.own_uncertainty


def test_matchup_model_abstains_when_match_context_missing() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01")])
    bundle = ModelInputBundle(
        match_id="m", player_a_id="p1", player_b_id="p2", as_of=AS_OF, player_a_profile=profile
    )
    output = MatchupModel().estimate(bundle)
    assert output.abstained is True


def test_matchup_model_never_uses_market_data() -> None:
    profile = make_profile("p1", h2h_records=[_record("2025-06-01")])
    assert MatchupModel().estimate(make_bundle(player_a_profile=profile)).market_data_used is False


def test_matchup_model_uses_surface_elo_when_both_players_have_it() -> None:
    profile_a = make_profile(
        "p1", elo_rating=env(1500.0), elo_rating_by_surface=env({"CLAY": 1700.0}),
    )
    profile_b = make_profile(
        "p2", elo_rating=env(1500.0), elo_rating_by_surface=env({"CLAY": 1500.0}),
    )
    output = MatchupModel().estimate(
        make_bundle(
            player_a_profile=profile_a, player_b_profile=profile_b,
            match_context=make_match_context(Surface.CLAY),
        )
    )
    assert output.estimate["elo_source"] == "surface"
    assert output.estimate["h2h_win_rate_player_a"] > 0.5


def test_matchup_model_falls_back_to_overall_elo_when_surface_elo_missing_for_one_player() -> None:
    profile_a = make_profile(
        "p1", elo_rating=env(1700.0), elo_rating_by_surface=env({"HARD": 1700.0}),
    )
    # player_b has no CLAY entry (surface debut) — must fall back to overall for BOTH.
    profile_b = make_profile(
        "p2", elo_rating=env(1500.0), elo_rating_by_surface=env({"HARD": 1500.0}),
    )
    output = MatchupModel().estimate(
        make_bundle(
            player_a_profile=profile_a, player_b_profile=profile_b,
            match_context=make_match_context(Surface.CLAY),
        )
    )
    assert output.estimate["elo_source"] == "overall"


def test_matchup_model_abstains_when_elo_rating_missing() -> None:
    from tests.ce2_prediction.factories import missing_env

    profile = make_profile("p1", elo_rating=missing_env())
    output = MatchupModel().estimate(make_bundle(player_a_profile=profile))
    assert output.abstained is True
    assert "elo_rating" in output.abstain_reason
