import random
from datetime import datetime, timezone

from tbos.ce2_prediction.base import Model
from tbos.ce2_prediction.contract import ModelOutput
from tbos.ce2_prediction.determinism import NonDeterministicModel, assert_deterministic
from tbos.ce2_prediction.input_bundle import ModelInputBundle

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _PureToyModel(Model):
    domain = "toy"
    model_id = "pure_toy_model"
    version = "1.0.0"
    required_fields: list[str] = []

    def estimate(self, bundle: ModelInputBundle) -> ModelOutput:
        return ModelOutput(
            domain=self.domain, model_id=self.model_id, model_version=self.version,
            estimate={"value": len(bundle.match_id)},
            own_uncertainty=0.1, own_evidence_quality=0.9, abstained=False, computed_at=NOW,
        )


class _ImpureToyModel(Model):
    domain = "toy"
    model_id = "impure_toy_model"
    version = "1.0.0"
    required_fields: list[str] = []

    def estimate(self, bundle: ModelInputBundle) -> ModelOutput:
        return ModelOutput(
            domain=self.domain, model_id=self.model_id, model_version=self.version,
            estimate={"value": random.random()},
            own_uncertainty=0.1, own_evidence_quality=0.9, abstained=False, computed_at=NOW,
        )


def _bundle() -> ModelInputBundle:
    return ModelInputBundle(match_id="match_1", player_a_id="p1", player_b_id="p2")


def test_pure_model_passes_determinism_check() -> None:
    assert_deterministic(_PureToyModel(), _bundle())


def test_impure_model_fails_determinism_check() -> None:
    try:
        assert_deterministic(_ImpureToyModel(), _bundle())
    except NonDeterministicModel:
        pass
    else:
        raise AssertionError("expected NonDeterministicModel to be raised for a random-valued Model")


def test_model_is_abstract_cannot_be_instantiated_directly() -> None:
    try:
        Model()  # type: ignore[abstract]
    except TypeError:
        pass
    else:
        raise AssertionError("Model() should be uninstantiable — estimate() is abstract")
