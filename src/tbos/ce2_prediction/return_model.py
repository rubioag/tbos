"""CE.2.2 — Return Model.

Estimates each player's expected return-domain performance (return points
won, break conversion rate) — domain-only, never translated to p_win
(mirrors the correction locked for Serve Model). Independent of Serve
Model: reads only raw CE.1 fields, never Serve Model's output.
"""

from __future__ import annotations

from tbos.ce1_data.schemas import PlayerProfile
from tbos.ce2_prediction.base import Model
from tbos.ce2_prediction.contract import ContributionLineageEntry, ModelOutput, abstain
from tbos.ce2_prediction.input_bundle import ModelInputBundle, check_required_fields
from tbos.ce2_prediction.surface_math import clamp01, surface_value

SERVE_BASELINE = 0.60
ADJUSTMENT_WEIGHT = 0.5


def _return_component(
    returner: PlayerProfile, server: PlayerProfile, surface_key: str
) -> dict[str, float] | None:
    own_return_pts = surface_value(returner.return_points_won_pct_by_surface.value, surface_key)
    own_break_conv = surface_value(returner.break_points_converted_pct_by_surface.value, surface_key)
    opp_first_serve = surface_value(server.first_serve_pct_by_surface.value, surface_key)
    opp_service_pts = surface_value(server.service_points_won_pct_by_surface.value, surface_key)

    if None in (own_return_pts, own_break_conv, opp_first_serve, opp_service_pts):
        return None

    return_adjustment = ADJUSTMENT_WEIGHT * (opp_service_pts - SERVE_BASELINE)
    break_adjustment = ADJUSTMENT_WEIGHT * (opp_first_serve - SERVE_BASELINE)

    return {
        "return_points_won_pct": clamp01(own_return_pts - return_adjustment),
        "break_conversion_rate": clamp01(own_break_conv - break_adjustment),
    }


class ReturnModel(Model):
    domain = "return"
    model_id = "return_model"
    version = "1.0.0"
    required_fields: list[str] = [
        "player_a_profile.return_points_won_pct_by_surface",
        "player_a_profile.break_points_converted_pct_by_surface",
        "player_a_profile.first_serve_pct_by_surface",
        "player_a_profile.service_points_won_pct_by_surface",
        "player_b_profile.return_points_won_pct_by_surface",
        "player_b_profile.break_points_converted_pct_by_surface",
        "player_b_profile.first_serve_pct_by_surface",
        "player_b_profile.service_points_won_pct_by_surface",
        "match_context.surface",
    ]
    optional_fields: list[str] = ["player_a_state.injury_flags", "player_b_state.injury_flags"]

    def estimate(self, bundle: ModelInputBundle) -> ModelOutput:
        now = bundle.as_of
        ok, missing = check_required_fields(bundle, self.required_fields)
        if not ok:
            return abstain(
                domain=self.domain, model_id=self.model_id, model_version=self.version,
                reason=f"missing/unusable required fields: {missing}", computed_at=now,
            )

        surface_key = str(bundle.match_context.surface.value)
        assert bundle.player_a_profile is not None
        assert bundle.player_b_profile is not None

        player_a_component = _return_component(bundle.player_a_profile, bundle.player_b_profile, surface_key)
        player_b_component = _return_component(bundle.player_b_profile, bundle.player_a_profile, surface_key)

        if player_a_component is None or player_b_component is None:
            return abstain(
                domain=self.domain, model_id=self.model_id, model_version=self.version,
                reason=f"no historical data for surface {surface_key!r} for one or both players",
                computed_at=now,
            )

        lineage = [
            ContributionLineageEntry(
                field_used="player_a_profile.return_points_won_pct_by_surface",
                ce1_snapshot_id=bundle.snapshot_refs.get("player_a_profile"), weight=0.5,
            ),
            ContributionLineageEntry(
                field_used="player_b_profile.return_points_won_pct_by_surface",
                ce1_snapshot_id=bundle.snapshot_refs.get("player_b_profile"), weight=0.5,
            ),
        ]

        return ModelOutput(
            domain=self.domain, model_id=self.model_id, model_version=self.version,
            estimate={"player_a": player_a_component, "player_b": player_b_component},
            own_uncertainty=0.3,
            own_evidence_quality=0.7,
            abstained=False,
            contribution_lineage=lineage,
            market_data_used=False,
            computed_at=now,
        )
