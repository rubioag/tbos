"""CE.2.4 — Matchup Model.

Estimates expected_matchup_interaction: a blend of the H2H empirical
signal between these two specific players (weighted by recency and
surface similarity — never treated as a stable trend from raw win/loss
counting, the same narrative-overfitting trap already guarded against
for "momentum" in Form/Fatigue Model) and each player's Elo rating
(overall, or surface-specific when both players have one).

Elo added 2026-07: literature grounding is `elo.py`'s module docstring
(Bunker et al. 2024: 65.87% accuracy on 133,138 ATP matches from a
"well-tuned Elo baseline"; Sackmann's Davis Cup comparison: Elo 72% vs
official ranking 60%). One practitioner source states raw H2H is a minor
predictor (~10% of a typical composite score) once Elo/ranking/surface
are accounted for — this is the reason Elo augments H2H here rather than
replacing it: H2H is real, pairwise, hard-to-fabricate evidence when it
exists, but it is frequently absent (most professional pairings have
zero or one prior meeting), and Elo is a real signal even then. Before
this change, zero H2H meant an unconditional abstention regardless of
how much Elo history existed for both players — that is no longer
correct once Elo is wired in, so the model now only abstains when a
required field is genuinely missing, not merely when H2H is empty.

Blend weight for H2H uses the SAME `own_evidence_quality` formula this
model already computes for H2H alone (min(0.6, 0.15 + 0.1*sample_size))
as the H2H blend fraction, with the remainder going to Elo — reusing an
existing, already-documented v1 heuristic rather than introducing a new
unvalidated constant. Whether this specific blend improves the ensemble
is exactly what the backtest this change ships alongside is for; nothing
here is asserted as proven, only as evidence-grounded and measurable.

H2H is inherently pairwise, not per-player — unlike Serve/Return/Surface/
Form, this Model's estimate is a single shared object, not a player_a/
player_b split. Elo, by contrast, is per-player, so it's read from both
`player_a_profile` and `player_b_profile`.
"""

from __future__ import annotations

from datetime import date, datetime

from tbos.ce2_prediction.base import Model
from tbos.ce2_prediction.contract import ContributionLineageEntry, ModelOutput, abstain
from tbos.ce2_prediction.input_bundle import ModelInputBundle, check_required_fields

RECENCY_HALF_LIFE_DAYS = 730.0  # 2 years — v1 placeholder, tune once INF.3 has real calibration data
SURFACE_MISMATCH_DISCOUNT = 0.4  # a meeting on a different surface still carries some signal, just less
ELO_ONLY_UNCERTAINTY = 0.5  # no pairwise evidence, only a prior — less confident than any H2H
# Below a single H2H meeting's quality (0.15 + 0.1*1 = 0.25) — a prior, not observed evidence.
ELO_ONLY_EVIDENCE_QUALITY = 0.2


def _elo_win_probability(elo_a: float, elo_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


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
    version = "1.1.0"
    required_fields: list[str] = [
        "player_a_profile.h2h_records",
        "player_a_profile.elo_rating",
        "player_b_profile.elo_rating",
        "match_context.surface",
    ]
    optional_fields: list[str] = [
        "player_a_profile.style_tags", "player_b_profile.style_tags",
        "player_a_profile.elo_rating_by_surface", "player_b_profile.elo_rating_by_surface",
    ]

    def estimate(self, bundle: ModelInputBundle) -> ModelOutput:
        now = bundle.as_of
        ok, missing = check_required_fields(bundle, self.required_fields)
        if not ok:
            return abstain(
                domain=self.domain, model_id=self.model_id, model_version=self.version,
                reason=f"missing/unusable required fields: {missing}", computed_at=now,
            )

        assert bundle.player_a_profile is not None
        assert bundle.player_b_profile is not None
        surface_key = str(bundle.match_context.surface.value)

        component = _matchup_component(
            bundle.player_a_profile.h2h_records.value, bundle.player_b_id, surface_key, now
        )

        elo_a_by_surface = bundle.player_a_profile.elo_rating_by_surface
        elo_b_by_surface = bundle.player_b_profile.elo_rating_by_surface
        if (
            elo_a_by_surface is not None and elo_a_by_surface.is_usable()
            and surface_key in elo_a_by_surface.value
            and elo_b_by_surface is not None and elo_b_by_surface.is_usable()
            and surface_key in elo_b_by_surface.value
        ):
            elo_a = elo_a_by_surface.value[surface_key]
            elo_b = elo_b_by_surface.value[surface_key]
            elo_source = "surface"
        else:
            elo_a = bundle.player_a_profile.elo_rating.value
            elo_b = bundle.player_b_profile.elo_rating.value
            elo_source = "overall"
        elo_win_rate = _elo_win_probability(elo_a, elo_b)

        lineage = [
            ContributionLineageEntry(
                field_used="player_a_profile.elo_rating",
                ce1_snapshot_id=bundle.snapshot_refs.get("player_a_profile"), weight=1.0,
            ),
            ContributionLineageEntry(
                field_used="player_b_profile.elo_rating",
                ce1_snapshot_id=bundle.snapshot_refs.get("player_b_profile"), weight=1.0,
            ),
        ]

        if component is None:
            # No prior meetings — Elo alone still carries a real signal
            # (see module docstring). Previously this abstained
            # unconditionally; that was correct when H2H was the only
            # signal this model had, and is no longer correct now that
            # Elo is wired in.
            estimate = {
                "h2h_sample_size": 0.0,
                "h2h_win_rate_player_a": elo_win_rate,
                "effective_weight": 0.0,
                "elo_win_rate_player_a": elo_win_rate,
                "elo_source": elo_source,
                "blend_source": "elo_only",
            }
            return ModelOutput(
                domain=self.domain, model_id=self.model_id, model_version=self.version,
                estimate=estimate,
                own_uncertainty=ELO_ONLY_UNCERTAINTY,
                own_evidence_quality=ELO_ONLY_EVIDENCE_QUALITY,
                abstained=False,
                contribution_lineage=lineage,
                market_data_used=False,
                computed_at=now,
            )

        lineage.insert(
            0,
            ContributionLineageEntry(
                field_used="player_a_profile.h2h_records",
                ce1_snapshot_id=bundle.snapshot_refs.get("player_a_profile"), weight=1.0,
            ),
        )

        # Small samples are the norm for H2H (often 1-3 meetings) — high
        # uncertainty is honest default behavior, not a special case.
        sample_size = component["h2h_sample_size"]
        h2h_uncertainty = max(0.3, 1.0 - min(sample_size, 10.0) / 10.0)
        h2h_evidence_quality = min(0.6, 0.15 + 0.1 * sample_size)

        # h2h_evidence_quality doubles as the H2H blend weight — reusing
        # an existing, already-documented v1 heuristic (see module
        # docstring) instead of introducing a new unvalidated constant.
        h2h_weight = h2h_evidence_quality
        blended_win_rate = (
            h2h_weight * component["h2h_win_rate_player_a"] + (1.0 - h2h_weight) * elo_win_rate
        )

        estimate = {
            **component,
            "h2h_win_rate_player_a": blended_win_rate,
            "raw_h2h_win_rate_player_a": component["h2h_win_rate_player_a"],
            "elo_win_rate_player_a": elo_win_rate,
            "elo_source": elo_source,
            "h2h_blend_weight": h2h_weight,
            "blend_source": "h2h_and_elo",
        }

        return ModelOutput(
            domain=self.domain, model_id=self.model_id, model_version=self.version,
            estimate=estimate,
            own_uncertainty=h2h_uncertainty,
            own_evidence_quality=max(h2h_evidence_quality, ELO_ONLY_EVIDENCE_QUALITY),
            abstained=False,
            contribution_lineage=lineage,
            market_data_used=False,
            computed_at=now,
        )
