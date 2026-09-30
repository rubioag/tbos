"""Walk-forward backtest: measures the incremental value of a CE.2 change
by replaying real historical Sackmann matches in chronological order and
comparing predicted outcome probability against the real result — for
two variants of the pipeline (baseline vs. a change under test) on the
exact same matches, so any metric delta is attributable to that one
change alone.

Strict anti-lookahead by construction: every per-match, per-player input
(serve/return stats, H2H, Elo rating, recent form) is computed using only
matches strictly before the evaluated match's date — the same `as_of`
discipline `compute_serve_return_by_surface`/`compute_h2h_records`/the
`player_state` helpers already support, called directly here (bypassing
`SackmannStatsAdapter`, which is documented as "live only" and does not
take an `as_of`). No CE.1/database persistence involved — this is a pure
in-memory ModelInputBundle construction, reusing the real, unmodified
CE.2 Model classes and Ensemble Aggregator so the models under test are
byte-for-byte the same code that runs in production.

Match surface is read directly from the match's own recorded surface
field, not derived from any lookup — this is not lookahead: which
surface a tournament is played on is public knowledge before the match
starts in real life, unlike the match's own outcome statistics.

Known, documented limitation: no historical bookmaker odds are available
locally in this environment (tennis-data.co.uk's odds columns are not
currently parsed, and no archive files are downloaded — see
tests/data_adapters/tennis_data). Betting ROI/Yield/bet-count cannot be
computed from real market data and are reported as unavailable, never
estimated or invented.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, date, datetime

from pydantic import BaseModel

from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.schemas import MatchContext, PlayerProfile, PlayerState
from tbos.ce2_prediction.contract import ContributionLineageEntry, ModelOutput, abstain
from tbos.ce2_prediction.ensemble import combine_models
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.ce2_prediction.matchup_model import MatchupModel, _matchup_component
from tbos.ce2_prediction.registry_bootstrap import BASE_MODEL_CLASSES
from tbos.data_adapters.sackmann.adapter import _career_stage_from_age, _most_recent_match
from tbos.data_adapters.sackmann.aggregator import compute_serve_return_by_surface
from tbos.data_adapters.sackmann.elo import EloRatings
from tbos.data_adapters.sackmann.h2h import compute_h2h_records
from tbos.data_adapters.sackmann.models import SURFACE_MAP, MatchRow
from tbos.data_adapters.sackmann.player_state import (
    compute_days_since_last_match,
    compute_deviation_from_baseline,
    compute_matches_last_n_days,
    compute_sets_played_last_n_days,
    detect_injury_flags,
)
from tbos.inf1_config.taxonomy import (
    BestOf,
    FieldAvailability,
    FieldValidity,
    InformationReliability,
    Surface,
)

_MATCHUP_BASELINE_VERSION = "1.0.0-backtest-reconstruction"


def _env(value: object) -> FieldEnvelope:
    return FieldEnvelope(
        value=value, availability=FieldAvailability.PRESENT, validity=FieldValidity.VALID,
        taxonomy_tag=InformationReliability.FACT,
    )


def _build_profile(
    matches: list[MatchRow], player_id: str, *, as_of_date: date, elo_ratings: EloRatings,
) -> PlayerProfile | None:
    by_surface = compute_serve_return_by_surface(matches, player_id, as_of=as_of_date)
    if not by_surface:
        return None

    recent = _most_recent_match(matches, player_id, as_of=as_of_date)
    assert recent is not None
    if recent.winner_id == player_id:
        hand, age, ranking = recent.winner_hand, recent.winner_age, recent.winner_rank
    else:
        hand, age, ranking = recent.loser_hand, recent.loser_age, recent.loser_rank

    style_tags = []
    if hand == "L":
        style_tags.append("left-handed")
    elif hand == "R":
        style_tags.append("right-handed")

    def _field(key: str) -> dict[str, float]:
        return {surface: stats[key] for surface, stats in by_surface.items() if key in stats}

    return PlayerProfile(
        player_id=_env(player_id),
        ranking=_env(ranking if ranking is not None else 9999),
        first_serve_pct_by_surface=_env(_field("first_serve_pct")),
        service_points_won_pct_by_surface=_env(_field("service_points_won_pct")),
        aces_per_match_by_surface=_env(_field("aces_per_match")),
        hold_rate_by_surface=_env(_field("hold_rate")),
        return_points_won_pct_by_surface=_env(_field("return_points_won_pct")),
        break_points_converted_pct_by_surface=_env(_field("break_points_converted_pct")),
        style_tags=_env(style_tags),
        career_stage=_env(_career_stage_from_age(age)),
        h2h_records=_env(compute_h2h_records(matches, player_id, as_of=as_of_date)),
        elo_rating=_env(elo_ratings.get_overall(player_id)),
        elo_rating_by_surface=_env(elo_ratings.get_by_surface(player_id)),
    )


def _build_state(
    matches: list[MatchRow], player_id: str, *, as_of_date: date,
) -> PlayerState | None:
    if _most_recent_match(matches, player_id, as_of=as_of_date) is None:
        return None
    deviation = compute_deviation_from_baseline(matches, player_id, as_of=as_of_date)
    days_since = compute_days_since_last_match(matches, player_id, as_of=as_of_date)
    matches_14d = compute_matches_last_n_days(matches, player_id, as_of=as_of_date, days=14)
    sets_14d = compute_sets_played_last_n_days(matches, player_id, as_of=as_of_date, days=14)
    return PlayerState(
        player_id=_env(player_id),
        injury_flags=_env(detect_injury_flags(matches, player_id, as_of=as_of_date)),
        matches_last_14d=_env(matches_14d),
        sets_played_last_14d=_env(sets_14d),
        travel_distance_km=_env(0.0),
        timezone_shift_hours=_env(0.0),
        deviation_from_baseline=_env(deviation if deviation is not None else 0.0),
        days_since_last_match=_env(days_since if days_since is not None else 0),
    )


def _build_match_context(
    match: MatchRow, match_id: str, as_of_datetime: datetime,
) -> MatchContext | None:
    surface = SURFACE_MAP.get(match.surface or "")
    if surface is None:
        return None

    return MatchContext(
        match_id=_env(match_id), tournament_id=_env(match.tourney_name or "unknown"),
        round=_env(match.round or "unknown"),
        surface=_env(Surface(surface)), indoor_outdoor=_env("unknown"),
        weather_temp_c=_env(0.0), weather_wind_kph=_env(0.0),
        weather_humidity_pct=_env(0.0), altitude_m=_env(0.0),
        scheduled_start=_env(as_of_datetime), best_of=_env(BestOf.BO3),
    )


def _baseline_matchup_estimate(bundle: ModelInputBundle) -> ModelOutput:
    """Exact reconstruction of matchup_model's pre-Elo (v1.0.0) logic —
    H2H only, unconditional abstention on zero relevant meetings. Lives
    here (backtest-only) rather than as a toggle in the production
    MatchupModel, since it's a one-time ablation comparison, not a
    permanent code path.
    """
    now = bundle.as_of
    if bundle.player_a_profile is None or bundle.match_context is None:
        return abstain(
            domain="matchup", model_id="matchup_model", model_version=_MATCHUP_BASELINE_VERSION,
            reason="missing required fields", computed_at=now,
        )
    surface_key = str(bundle.match_context.surface.value)
    component = _matchup_component(
        bundle.player_a_profile.h2h_records.value, bundle.player_b_id, surface_key, now,
    )
    if component is None:
        return abstain(
            domain="matchup", model_id="matchup_model", model_version=_MATCHUP_BASELINE_VERSION,
            reason="no prior head-to-head meetings between these players", computed_at=now,
        )
    sample_size = component["h2h_sample_size"]
    uncertainty = max(0.3, 1.0 - min(sample_size, 10.0) / 10.0)
    evidence_quality = min(0.6, 0.15 + 0.1 * sample_size)
    return ModelOutput(
        domain="matchup", model_id="matchup_model", model_version=_MATCHUP_BASELINE_VERSION,
        estimate=component, own_uncertainty=uncertainty, own_evidence_quality=evidence_quality,
        abstained=False, contribution_lineage=[
            ContributionLineageEntry(
                field_used="player_a_profile.h2h_records",
                ce1_snapshot_id=bundle.snapshot_refs.get("player_a_profile"), weight=1.0,
            ),
        ], market_data_used=False, computed_at=now,
    )


class MatchPrediction(BaseModel):
    match_id: str
    predicted_probability_player_a: float | None
    actual_outcome_player_a: int
    fully_abstained: bool
    participating_model_ids: list[str]


def build_bundle_for_match(
    history: list[MatchRow], match: MatchRow, *, elo_ratings: EloRatings,
) -> tuple[ModelInputBundle, int]:
    """`history` must already exclude `match` and everything at/after its
    date — the caller (run_walk_forward_backtest) enforces this via
    chronological iteration order, not this function.
    """
    winner_id, loser_id = match.winner_id, match.loser_id
    player_a_id, player_b_id = sorted((winner_id, loser_id))
    actual_outcome = 1 if player_a_id == winner_id else 0

    as_of_date = match.tourney_date
    as_of_datetime = datetime.combine(as_of_date, datetime.min.time(), tzinfo=UTC)

    profile_a = _build_profile(history, player_a_id, as_of_date=as_of_date, elo_ratings=elo_ratings)
    profile_b = _build_profile(history, player_b_id, as_of_date=as_of_date, elo_ratings=elo_ratings)
    state_a = _build_state(history, player_a_id, as_of_date=as_of_date)
    state_b = _build_state(history, player_b_id, as_of_date=as_of_date)
    match_id = f"{match.tourney_name}-{match.tourney_date.isoformat()}-{winner_id}-{loser_id}"
    match_context = _build_match_context(match, match_id, as_of_datetime)

    return ModelInputBundle(
        match_id=match_id, player_a_id=player_a_id, player_b_id=player_b_id, as_of=as_of_datetime,
        player_a_profile=profile_a, player_b_profile=profile_b,
        player_a_state=state_a, player_b_state=state_b, match_context=match_context,
    ), actual_outcome


def run_walk_forward_backtest(
    all_matches: list[MatchRow], test_matches: list[MatchRow], *,
    matchup_estimator: Callable[[ModelInputBundle], ModelOutput] | None = None,
) -> list[MatchPrediction]:
    """`matchup_estimator` overrides only MatchupModel's contribution
    (pass `_baseline_matchup_estimate` for the pre-Elo comparison run);
    None uses the real, current `MatchupModel().estimate`. All other 4
    Models are always the real, unmodified classes — the single-variable
    discipline the whole experiment depends on.
    """
    test_matches_sorted = sorted(test_matches, key=lambda m: m.tourney_date)
    history_sorted = sorted(all_matches, key=lambda m: m.tourney_date)

    elo_ratings = EloRatings()
    history_idx = 0
    other_models = [cls() for cls in BASE_MODEL_CLASSES if cls is not MatchupModel]
    matchup_model = MatchupModel()

    results: list[MatchPrediction] = []
    for match in test_matches_sorted:
        # Advance the running Elo state (and the visible history slice)
        # up to, but not including, this match's own date.
        while (
            history_idx < len(history_sorted)
            and history_sorted[history_idx].tourney_date < match.tourney_date
        ):
            m = history_sorted[history_idx]
            elo_ratings.record_match(m.winner_id, m.loser_id, m.surface)
            history_idx += 1
        visible_history = history_sorted[:history_idx]

        bundle, actual_outcome = build_bundle_for_match(
            visible_history, match, elo_ratings=elo_ratings,
        )

        outputs = [model.estimate(bundle) for model in other_models]
        if matchup_estimator is not None:
            outputs.append(matchup_estimator(bundle))
        else:
            outputs.append(matchup_model.estimate(bundle))

        ensemble = combine_models(bundle.match_id, outputs)
        results.append(
            MatchPrediction(
                match_id=bundle.match_id,
                predicted_probability_player_a=ensemble.probability_player_a,
                actual_outcome_player_a=actual_outcome,
                fully_abstained=ensemble.fully_abstained,
                participating_model_ids=[c.model_id for c in ensemble.participating],
            )
        )

        # This match itself now becomes part of history for subsequent
        # (later-dated) test matches.
        elo_ratings.record_match(match.winner_id, match.loser_id, match.surface)

    return results


# --- Metrics -----------------------------------------------------------

_EPS = 1e-12


def coverage(predictions: list[MatchPrediction]) -> float:
    if not predictions:
        return 0.0
    return sum(1 for p in predictions if not p.fully_abstained) / len(predictions)


def _covered(predictions: list[MatchPrediction]) -> list[MatchPrediction]:
    return [
        p for p in predictions
        if not p.fully_abstained and p.predicted_probability_player_a is not None
    ]


def accuracy(predictions: list[MatchPrediction]) -> float | None:
    covered = _covered(predictions)
    if not covered:
        return None
    correct = sum(
        1 for p in covered
        if (p.predicted_probability_player_a >= 0.5) == bool(p.actual_outcome_player_a)
    )
    return correct / len(covered)


def log_loss(predictions: list[MatchPrediction]) -> float | None:
    covered = _covered(predictions)
    if not covered:
        return None
    total = 0.0
    for p in covered:
        prob = min(max(p.predicted_probability_player_a, _EPS), 1.0 - _EPS)
        y = p.actual_outcome_player_a
        total += -(y * math.log(prob) + (1 - y) * math.log(1 - prob))
    return total / len(covered)


def brier_score(predictions: list[MatchPrediction]) -> float | None:
    covered = _covered(predictions)
    if not covered:
        return None
    squared_errors = (
        (p.predicted_probability_player_a - p.actual_outcome_player_a) ** 2 for p in covered
    )
    return sum(squared_errors) / len(covered)


def expected_calibration_error(
    predictions: list[MatchPrediction], *, num_bins: int = 10,
) -> float | None:
    covered = _covered(predictions)
    if not covered:
        return None
    bins: list[list[MatchPrediction]] = [[] for _ in range(num_bins)]
    for p in covered:
        idx = min(int(p.predicted_probability_player_a * num_bins), num_bins - 1)
        bins[idx].append(p)
    total = len(covered)
    ece = 0.0
    for bucket in bins:
        if not bucket:
            continue
        mean_pred = sum(p.predicted_probability_player_a for p in bucket) / len(bucket)
        mean_actual = sum(p.actual_outcome_player_a for p in bucket) / len(bucket)
        ece += (len(bucket) / total) * abs(mean_pred - mean_actual)
    return ece


class BacktestReport(BaseModel):
    label: str
    sample_size: int
    coverage: float
    accuracy: float | None
    log_loss: float | None
    brier_score: float | None
    ece: float | None


def summarize(label: str, predictions: list[MatchPrediction]) -> BacktestReport:
    return BacktestReport(
        label=label, sample_size=len(predictions), coverage=coverage(predictions),
        accuracy=accuracy(predictions), log_loss=log_loss(predictions),
        brier_score=brier_score(predictions), ece=expected_calibration_error(predictions),
    )


# --- Statistical significance ------------------------------------------

def mcnemar_test(
    baseline: list[MatchPrediction], treatment: list[MatchPrediction],
) -> dict[str, float | int | None]:
    """Paired test on accuracy, restricted to matches where BOTH variants
    produced a prediction (fair comparison — a match either variant
    abstained on can't inform "which is more accurate"). Uses the
    continuity-corrected chi-square approximation (standard for McNemar's
    test); exact binomial would be more precise for very small
    discordant-pair counts, flagged in the result if n_discordant < 25
    (where the chi-square approximation is unreliable).
    """
    by_id_b = {p.match_id: p for p in baseline}
    by_id_t = {p.match_id: p for p in treatment}
    shared_ids = set(by_id_b) & set(by_id_t)

    b_correct_t_wrong = 0
    b_wrong_t_correct = 0
    n_paired = 0
    for match_id in shared_ids:
        pb, pt = by_id_b[match_id], by_id_t[match_id]
        if pb.fully_abstained or pt.fully_abstained:
            continue
        n_paired += 1
        b_correct = (pb.predicted_probability_player_a >= 0.5) == bool(pb.actual_outcome_player_a)
        t_correct = (pt.predicted_probability_player_a >= 0.5) == bool(pt.actual_outcome_player_a)
        if b_correct and not t_correct:
            b_correct_t_wrong += 1
        elif not b_correct and t_correct:
            b_wrong_t_correct += 1

    n_discordant = b_correct_t_wrong + b_wrong_t_correct
    if n_discordant == 0:
        return {
            "n_paired": n_paired, "n_discordant": 0, "chi_square": 0.0, "p_value": 1.0,
            "reliable_approximation": n_discordant >= 25,
        }

    chi_square = (abs(b_correct_t_wrong - b_wrong_t_correct) - 1) ** 2 / n_discordant
    # Survival function of chi-square(1 df): P(X>x) = erfc(sqrt(x/2)) — X = Z^2 for
    # standard normal Z, so P(X>x) = P(|Z|>sqrt(x)) = 2*(1-Phi(sqrt(x))) = erfc(sqrt(x/2)).
    p_value = math.erfc(math.sqrt(chi_square / 2.0))
    return {
        "n_paired": n_paired, "n_discordant": n_discordant,
        "chi_square": chi_square, "p_value": p_value,
        "reliable_approximation": n_discordant >= 25,
    }
