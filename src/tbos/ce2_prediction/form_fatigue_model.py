"""CE.2.3 — Form/Fatigue Model.

Estimates expected_form_fatigue_adjustment: fatigue load, injury
availability, and recent deviation from baseline — never "momentum"
(corrected per the frozen spec: recent trend is expressed only as
`deviation_from_baseline` with uncertainty, never as a win/loss-streak
narrative). No surface interaction, no cross-player comparison — that
belongs to Surface Model and Matchup Model respectively.
"""

from __future__ import annotations

from tbos.ce1_data.schemas import PlayerState
from tbos.ce2_prediction.base import Model
from tbos.ce2_prediction.contract import ContributionLineageEntry, ModelOutput, abstain
from tbos.ce2_prediction.input_bundle import ModelInputBundle, check_required_fields

FATIGUE_MATCH_WEIGHT = 0.015
FATIGUE_SET_WEIGHT = 0.008
INJURY_SEVERITY_WEIGHTS: dict[str, float] = {
    "MINOR": 0.02,
    "MODERATE": 0.08,
    "SEVERE": 0.20,
}


def _form_fatigue_component(state: PlayerState) -> dict[str, float] | None:
    matches = state.matches_last_14d.value
    sets = state.sets_played_last_14d.value
    deviation = state.deviation_from_baseline.value
    injuries = state.injury_flags.value

    if matches is None or sets is None or deviation is None or injuries is None:
        return None

    fatigue_load = matches * FATIGUE_MATCH_WEIGHT + sets * FATIGUE_SET_WEIGHT
    injury_penalty = sum(INJURY_SEVERITY_WEIGHTS.get(flag.get("severity", ""), 0.0) for flag in injuries)

    return {
        "fatigue_load": fatigue_load,
        "injury_penalty": injury_penalty,
        "form_deviation": deviation,
        "net_adjustment": deviation - fatigue_load - injury_penalty,
    }


class FormFatigueModel(Model):
    domain = "form_fatigue"
    model_id = "form_fatigue_model"
    version = "1.0.0"
    required_fields: list[str] = [
        "player_a_state.injury_flags",
        "player_a_state.matches_last_14d",
        "player_a_state.sets_played_last_14d",
        "player_a_state.deviation_from_baseline",
        "player_b_state.injury_flags",
        "player_b_state.matches_last_14d",
        "player_b_state.sets_played_last_14d",
        "player_b_state.deviation_from_baseline",
    ]
    optional_fields: list[str] = ["player_a_state.days_since_last_match", "player_b_state.days_since_last_match"]

    def estimate(self, bundle: ModelInputBundle) -> ModelOutput:
        now = bundle.as_of
        ok, missing = check_required_fields(bundle, self.required_fields)
        if not ok:
            return abstain(
                domain=self.domain, model_id=self.model_id, model_version=self.version,
                reason=f"missing/unusable required fields: {missing}", computed_at=now,
            )

        assert bundle.player_a_state is not None
        assert bundle.player_b_state is not None

        player_a_component = _form_fatigue_component(bundle.player_a_state)
        player_b_component = _form_fatigue_component(bundle.player_b_state)

        if player_a_component is None or player_b_component is None:
            return abstain(
                domain=self.domain, model_id=self.model_id, model_version=self.version,
                reason="incomplete PlayerState data for one or both players", computed_at=now,
            )

        lineage = [
            ContributionLineageEntry(
                field_used="player_a_state.deviation_from_baseline",
                ce1_snapshot_id=bundle.snapshot_refs.get("player_a_state"), weight=0.5,
            ),
            ContributionLineageEntry(
                field_used="player_b_state.deviation_from_baseline",
                ce1_snapshot_id=bundle.snapshot_refs.get("player_b_state"), weight=0.5,
            ),
        ]

        return ModelOutput(
            domain=self.domain, model_id=self.model_id, model_version=self.version,
            estimate={"player_a": player_a_component, "player_b": player_b_component},
            own_uncertainty=0.4,
            own_evidence_quality=0.65,
            abstained=False,
            contribution_lineage=lineage,
            market_data_used=False,
            computed_at=now,
        )
