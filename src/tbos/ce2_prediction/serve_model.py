"""CE.2.2 — Serve Model.

Estimates each player's expected serve-domain performance (hold ability,
service points won, ace propensity) for this match — never translated to
p_win (Common Model Contract §3, and the correction locked into the
frozen spec: "estimate: expected_serve_performance_distribution", not a
"contribución a p_win").

Formula is deliberately simple and fully documented: own serve rate,
discounted by how much the opponent's raw return numbers exceed a tour
baseline. RETURN_BASELINE/ADJUSTMENT_WEIGHT are v1 placeholders — they
belong in INF.1 config once there's real backtested data to tune them
against; hardcoded here only because that data doesn't exist yet.
"""

from __future__ import annotations

from tbos.ce1_data.schemas import PlayerProfile
from tbos.ce2_prediction.base import Model
from tbos.ce2_prediction.contract import ContributionLineageEntry, ModelOutput, abstain
from tbos.ce2_prediction.input_bundle import ModelInputBundle, check_required_fields
from tbos.ce2_prediction.surface_math import clamp01, surface_value

RETURN_BASELINE = 0.35
ADJUSTMENT_WEIGHT = 0.5


def _serve_component(
    server: PlayerProfile, returner: PlayerProfile, surface_key: str
) -> dict[str, float] | None:
    own_hold = surface_value(server.hold_rate_by_surface.value, surface_key)
    own_service_pts = surface_value(server.service_points_won_pct_by_surface.value, surface_key)
    own_aces = surface_value(server.aces_per_match_by_surface.value, surface_key)
    opp_return_pts = surface_value(returner.return_points_won_pct_by_surface.value, surface_key)
    opp_break_conv = surface_value(returner.break_points_converted_pct_by_surface.value, surface_key)

    if None in (own_hold, own_service_pts, own_aces, opp_return_pts, opp_break_conv):
        return None

    hold_adjustment = ADJUSTMENT_WEIGHT * (opp_return_pts - RETURN_BASELINE)
    service_pts_adjustment = ADJUSTMENT_WEIGHT * (opp_break_conv - RETURN_BASELINE)

    return {
        "hold_probability": clamp01(own_hold - hold_adjustment),
        "service_points_won_pct": clamp01(own_service_pts - service_pts_adjustment),
        "ace_propensity": max(0.0, own_aces),
    }


class ServeModel(Model):
    domain = "serve"
    model_id = "serve_model"
    version = "1.0.0"
    required_fields: list[str] = [
        "player_a_profile.hold_rate_by_surface",
        "player_a_profile.service_points_won_pct_by_surface",
        "player_a_profile.aces_per_match_by_surface",
        "player_a_profile.return_points_won_pct_by_surface",
        "player_a_profile.break_points_converted_pct_by_surface",
        "player_b_profile.hold_rate_by_surface",
        "player_b_profile.service_points_won_pct_by_surface",
        "player_b_profile.aces_per_match_by_surface",
        "player_b_profile.return_points_won_pct_by_surface",
        "player_b_profile.break_points_converted_pct_by_surface",
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

        player_a_component = _serve_component(bundle.player_a_profile, bundle.player_b_profile, surface_key)
        player_b_component = _serve_component(bundle.player_b_profile, bundle.player_a_profile, surface_key)

        if player_a_component is None or player_b_component is None:
            return abstain(
                domain=self.domain, model_id=self.model_id, model_version=self.version,
                reason=f"no historical data for surface {surface_key!r} for one or both players",
                computed_at=now,
            )

        lineage = [
            ContributionLineageEntry(
                field_used="player_a_profile.hold_rate_by_surface",
                ce1_snapshot_id=bundle.snapshot_refs.get("player_a_profile"), weight=0.5,
            ),
            ContributionLineageEntry(
                field_used="player_b_profile.hold_rate_by_surface",
                ce1_snapshot_id=bundle.snapshot_refs.get("player_b_profile"), weight=0.5,
            ),
        ]

        return ModelOutput(
            domain=self.domain, model_id=self.model_id, model_version=self.version,
            estimate={"player_a": player_a_component, "player_b": player_b_component},
            own_uncertainty=0.3,  # v1 placeholder — calibrated properly once INF.3 has real samples
            own_evidence_quality=0.7,
            abstained=False,
            contribution_lineage=lineage,
            market_data_used=False,
            computed_at=now,
        )
