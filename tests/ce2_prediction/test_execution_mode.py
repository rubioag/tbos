from datetime import datetime, timezone

from tbos.ce2_prediction.contract import ModelOutput, abstain
from tbos.ce2_prediction.form_fatigue_model import FormFatigueModel
from tbos.ce2_prediction.matchup_model import MatchupModel
from tbos.ce2_prediction.return_model import ReturnModel
from tbos.ce2_prediction.serve_model import ServeModel
from tbos.ce2_prediction.surface_model import SurfaceModel
from tbos.inf1_config.taxonomy import ExecutionMode

from tests.ce2_prediction.factories import make_bundle

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_model_output_defaults_to_live() -> None:
    output = ModelOutput(
        domain="serve", model_id="serve_model", model_version="1.0.0", estimate={},
        own_uncertainty=0.1, own_evidence_quality=0.9, abstained=False, computed_at=NOW,
    )
    assert output.execution_mode == ExecutionMode.LIVE


def test_abstain_defaults_to_live() -> None:
    output = abstain(domain="serve", model_id="serve_model", model_version="1.0.0", reason="x", computed_at=NOW)
    assert output.execution_mode == ExecutionMode.LIVE


def test_all_five_base_models_produce_live_output_by_default() -> None:
    """Regression guard: adding execution_mode to the contract must not
    change any existing Model's default behavior.
    """
    bundle = make_bundle(include_states=True)
    for model in (ServeModel(), ReturnModel(), SurfaceModel(), FormFatigueModel(), MatchupModel()):
        output = model.estimate(bundle)
        assert output.execution_mode == ExecutionMode.LIVE
