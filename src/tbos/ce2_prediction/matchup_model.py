"""CE.2.4 — Matchup Model.

Estimates expected_matchup_interaction: the H2H empirical signal between
these two specific players, weighted by recency and surface similarity —
never treated as a stable trend from raw win/loss counting (the same
narrative-overfitting trap already guarded against for "momentum" in
Form/Fatigue Model). No style-tag interaction score is computed yet: v1
has no validated data for lefty/two-hander-style clash effects, and
fabricating one from nothing would violate Evidence Quality honesty —
style_tags stay descriptive-only (optional_fields) until that evidence exists.

H2H is inherently pairwise, not per-player — unlike Serve/Return/Surface/
Form, this Model's estimate is a single shared object, not a player_a/
player_b split.
"""

from __future__ import annotations

from datetime import date, datetime

from tbos.ce2_prediction.base import Model
from tbos.ce2_prediction.contract import ContributionLineageEntry, ModelOutput, abstain
from tbos.ce2_prediction.input_bundle import ModelInputBundle, check_required_fields

RECENCY_HALF_LIFE_DAYS = 730.0  # 2 years — v1 placeholder, tune once INF.3 has real calibration data
SURFACE_MISMATCH_DISCOUNT = 0.4  # a meeting on a different surface still carries some signal, just less


def _recency_weight(record_date: date, as_of: datetime) -> float:
    age_days = max(0.0, (as_of.date() - record_date).days)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def _matchup_component(
    h2h_records: list[dict], opponent_id: str, current_surface: str, as_of: datetime
) -> dict[str, float] | None:
    relevant = [r for r in h2h_records if r.get("opponent_id") == opponent_id]
    if not relevant:
        return None

    weighted_wins = 0.0
    total_weight = 0.0
    for record in relevant:
        record_date = date.fromisoformat(record["date"])
        weight = _recency_weight(record_date, as_of)
        if record.get("surface") != current_surface:
            weight *= SURFACE_MISMATCH_DISCOUNT
        total_weight += weight
        if record.get("result") == "WIN":
            weighted_wins += weight

    win_rate = weighted_wins / total_weight if total_weight > 0 else 0.5

    return {
        "h2h_sample_size": float(len(relevant)),
        "h2h_win_rate_player_a": win_rate,
        "effective_weight": total_weight,
    }


class MatchupModel(Model):
    domain = "matchup"
    model_id = "matchup_model"
    version = "1.0.0"
    required_fields: list[str] = [
        "player_a_profile.h2h_records",
        "match_context.surface",
    ]
    optional_fields: list[str] = ["player_a_profile.style_tags", "player_b_profile.style_tags"]

    def estimate(self, bundle: ModelInputBundle) -> ModelOutput:
        now = bundle.as_of
        ok, missing = check_required_fields(bundle, self.required_fields)
        if not ok:
            return abstain(
                domain=self.domain, model_id=self.model_id, model_version=self.version,
                reason=f"missing/unusable required fields: {missing}", computed_at=now,
            )

        assert bundle.player_a_profile is not None
        surface_key = str(bundle.match_context.surface.value)

        component = _matchup_component(
            bundle.player_a_profile.h2h_records.value, bundle.player_b_id, surface_key, now
        )
        if component is None:
            return abstain(
                domain=self.domain, model_id=self.model_id, model_version=self.version,
                reason="no prior head-to-head meetings between these players", computed_at=now,
            )

        lineage = [
            ContributionLineageEntry(
                field_used="player_a_profile.h2h_records",
                ce1_snapshot_id=bundle.snapshot_refs.get("player_a_profile"), weight=1.0,
            ),
        ]

        # Small samples are the norm for H2H (often 1-3 meetings) — high
        # uncertainty is honest default behavior, not a special case.
        sample_size = component["h2h_sample_size"]
        uncertainty = max(0.3, 1.0 - min(sample_size, 10.0) / 10.0)
        evidence_quality = min(0.6, 0.15 + 0.1 * sample_size)

        return ModelOutput(
            domain=self.domain, model_id=self.model_id, model_version=self.version,
            estimate=component,
            own_uncertainty=uncertainty,
            own_evidence_quality=evidence_quality,
            abstained=False,
            contribution_lineage=lineage,
            market_data_used=False,
            computed_at=now,
        )
