from datetime import datetime, timezone

# Intentionally imported so this test file's own source contains the
# string "serve_model" — used below to prove the independence checker
# actually inspects source text rather than trivially passing everything.
from tbos.ce2_prediction import serve_model as _serve_model_ref  # noqa: F401
from tbos.ce2_prediction.base import Model
from tbos.ce2_prediction.contract import ModelOutput, abstain
from tbos.ce2_prediction.form_fatigue_model import FormFatigueModel
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.ce2_prediction.matchup_model import MatchupModel
from tbos.ce2_prediction.return_model import ReturnModel
from tbos.ce2_prediction.serve_model import ServeModel
from tbos.ce2_prediction.surface_model import SurfaceModel
from tbos.ce2_prediction.validation_battery import run_validation_battery

from tests.ce2_prediction.factories import make_bundle

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_all_five_base_models_pass_the_full_battery() -> None:
    bundle = make_bundle(include_states=True, match_context=make_bundle().match_context)
    # Matchup needs h2h history to avoid abstaining, but abstention itself
    # doesn't fail output_conforms/determinism/independence — only the
    # dedicated abstention_correctness check cares, and that uses its own
    # deliberately-empty probe bundle, not this one.
    for model_cls in (ServeModel, ReturnModel, SurfaceModel, FormFatigueModel, MatchupModel):
        result = run_validation_battery(model_cls, bundle)
        assert result.overall_pass, [t for t in result.tests if not t.passed]


class _FakeModelWithBogusRequiredField(Model):
    domain = "fake"
    model_id = "fake_bogus_field_model"
    version = "1.0.0"
    required_fields: list[str] = ["player_a_profile.this_field_does_not_exist"]

    def estimate(self, bundle: ModelInputBundle) -> ModelOutput:
        return abstain(domain=self.domain, model_id=self.model_id, model_version=self.version, reason="x", computed_at=bundle.as_of)


def test_bogus_required_field_path_fails_resolution_check() -> None:
    result = run_validation_battery(_FakeModelWithBogusRequiredField, make_bundle())
    test = next(t for t in result.tests if t.test_name == "required_fields_resolve_against_ce1_schema")
    assert test.passed is False
    assert result.overall_pass is False


class _FakeModelWrongIdentity(Model):
    domain = "fake"
    model_id = "fake_wrong_identity_model"
    version = "1.0.0"
    required_fields: list[str] = []

    def estimate(self, bundle: ModelInputBundle) -> ModelOutput:
        return ModelOutput(
            domain="totally_different_domain", model_id="not_my_id", model_version=self.version,
            estimate={}, own_uncertainty=0.1, own_evidence_quality=0.9, abstained=False, computed_at=bundle.as_of,
        )


def test_output_with_mismatched_identity_fails_conformance_check() -> None:
    result = run_validation_battery(_FakeModelWrongIdentity, make_bundle())
    test = next(t for t in result.tests if t.test_name == "output_conforms_common_model_contract")
    assert test.passed is False


class _FakeNonDeterministicModel(Model):
    domain = "fake"
    model_id = "fake_nondeterministic_model"
    version = "1.0.0"
    required_fields: list[str] = []

    def estimate(self, bundle: ModelInputBundle) -> ModelOutput:
        import random

        return ModelOutput(
            domain=self.domain, model_id=self.model_id, model_version=self.version,
            estimate={"value": random.random()}, own_uncertainty=0.1, own_evidence_quality=0.9,
            abstained=False, computed_at=bundle.as_of,
        )


def test_nondeterministic_model_fails_determinism_check() -> None:
    result = run_validation_battery(_FakeNonDeterministicModel, make_bundle())
    test = next(t for t in result.tests if t.test_name == "determinism")
    assert test.passed is False


class _FakeCoupledModel(Model):
    """Its __module__ is this test file, which deliberately imports
    serve_model above — proves the independence checker inspects real
    source text rather than trusting a Model's declared metadata.
    """

    domain = "fake"
    model_id = "fake_coupled_model"
    version = "1.0.0"
    required_fields: list[str] = []

    def estimate(self, bundle: ModelInputBundle) -> ModelOutput:
        return abstain(domain=self.domain, model_id=self.model_id, model_version=self.version, reason="x", computed_at=bundle.as_of)


def test_model_coupled_to_another_models_module_fails_independence_check() -> None:
    result = run_validation_battery(_FakeCoupledModel, make_bundle())
    test = next(t for t in result.tests if t.test_name == "independence")
    assert test.passed is False
    assert "serve_model" in test.detail


class _FakeAlwaysAnswersModel(Model):
    domain = "fake"
    model_id = "fake_never_abstains_model"
    version = "1.0.0"
    required_fields: list[str] = ["player_a_profile.hold_rate_by_surface"]

    def estimate(self, bundle: ModelInputBundle) -> ModelOutput:
        # Fabricates an answer regardless of whether required data exists —
        # exactly the failure mode abstention_correctness must catch.
        return ModelOutput(
            domain=self.domain, model_id=self.model_id, model_version=self.version,
            estimate={"value": 0.5}, own_uncertainty=0.1, own_evidence_quality=0.9,
            abstained=False, computed_at=bundle.as_of,
        )


def test_model_that_never_abstains_fails_abstention_correctness_check() -> None:
    result = run_validation_battery(_FakeAlwaysAnswersModel, make_bundle())
    test = next(t for t in result.tests if t.test_name == "abstention_correctness")
    assert test.passed is False
