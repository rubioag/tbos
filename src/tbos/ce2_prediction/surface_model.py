"""CE.2.3 — Surface Model.

Estimates each player's expected surface_adjustment: how much their level
shifts on this specific surface relative to their own multi-surface
baseline (never translated to p_win). CE.1's PlayerProfile has no direct
"win_rate_by_surface" field, so v1 uses hold_rate + service_points_won
by-surface as the surface-level proxy, compared against the player's own
average across every surface they have data for — deliberately a
self-relative baseline, not an absolute rating, since no cross-player
surface-strength scale exists yet.
"""

from __future__ import annotations

from tbos.ce1_data.schemas import PlayerProfile
from tbos.ce2_prediction.base import Model
from tbos.ce2_prediction.contract import ContributionLineageEntry, ModelOutput, abstain
from tbos.ce2_prediction.input_bundle import ModelInputBundle, check_required_fields
from tbos.ce2_prediction.surface_math import surface_value


def _surface_component(profile: PlayerProfile, surface_key: str) -> dict[str, float] | None:
    hold_by_surface = profile.hold_rate_by_surface.value
    service_by_surface = profile.service_points_won_pct_by_surface.value

    own_surface_hold = surface_value(hold_by_surface, surface_key)
    own_surface_service = surface_value(service_by_surface, surface_key)
    if own_surface_hold is None or own_surface_service is None:
        return None  # no history on this specific surface — surface debut

    surface_level = (own_surface_hold + own_surface_service) / 2

    all_levels = [
        (hold_by_surface[s] + service_by_surface[s]) / 2
        for s in hold_by_surface
        if s in service_by_surface
    ]
    baseline_level = sum(all_levels) / len(all_levels) if all_levels else surface_level

    return {
        "surface_level": surface_level,
        "baseline_level": baseline_level,
        "surface_adjustment": surface_level - baseline_level,
        "surfaces_on_record": float(len(all_levels)),
    }


class SurfaceModel(Model):
    domain = "surface"
    model_id = "surface_model"
    version = "1.0.0"
    required_fields: list[str] = [
        "player_a_profile.hold_rate_by_surface",
        "player_a_profile.service_points_won_pct_by_surface",
        "player_b_profile.hold_rate_by_surface",
        "player_b_profile.service_points_won_pct_by_surface",
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

        surface_key = str(bundle.match_context.surface.value)
        assert bundle.player_a_profile is not None
        assert bundle.player_b_profile is not None

        player_a_component = _surface_component(bundle.player_a_profile, surface_key)
        player_b_component = _surface_component(bundle.player_b_profile, surface_key)

        if player_a_component is None or player_b_component is None:
            return abstain(
                domain=self.domain, model_id=self.model_id, model_version=self.version,
                reason=f"no historical data for surface {surface_key!r} for one or both players (surface debut)",
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

        # Fewer surfaces on record means the self-relative baseline is
        # weaker evidence — reflected as lower own_evidence_quality, never
        # hidden or defaulted away.
        min_surfaces = min(player_a_component["surfaces_on_record"], player_b_component["surfaces_on_record"])
        evidence_quality = 0.4 if min_surfaces <= 1 else 0.75

        return ModelOutput(
            domain=self.domain, model_id=self.model_id, model_version=self.version,
            estimate={"player_a": player_a_component, "player_b": player_b_component},
            own_uncertainty=0.35,
            own_evidence_quality=evidence_quality,
            abstained=False,
            contribution_lineage=lineage,
            market_data_used=False,
            computed_at=now,
        )
