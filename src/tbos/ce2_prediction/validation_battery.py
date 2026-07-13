"""CE.2.8 — Compatibility battery a Model must pass before it can ever
reach VALIDATED status in the Model Registry (INF.1 §4, already enforced
there — a Model failing this never reaches ACTIVE, structurally). This
module runs the five checks and reports pass/fail per check plus overall.
"""

from __future__ import annotations

import importlib

from pydantic import BaseModel

from tbos.ce1_data.schemas import ENTITY_SCHEMAS
from tbos.ce2_prediction.base import Model
from tbos.ce2_prediction.determinism import NonDeterministicModel, assert_deterministic
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.inf1_config.taxonomy import ExecutionMode

_ENTITY_ATTR_TO_SCHEMA = {
    "player_a_profile": "PlayerProfile", "player_a_state": "PlayerState",
    "player_b_profile": "PlayerProfile", "player_b_state": "PlayerState",
    "match_context": "MatchContext",
}

_OTHER_MODEL_MODULES = {"serve_model", "return_model", "surface_model", "form_fatigue_model", "matchup_model"}


class ValidationTestResult(BaseModel):
    test_name: str
    passed: bool
    detail: str = ""


class ValidationBatteryResult(BaseModel):
    model_id: str
    model_version: str
    tests: list[ValidationTestResult]

    @property
    def overall_pass(self) -> bool:
        return all(t.passed for t in self.tests)


def _check_required_fields_resolve(model_cls: type[Model]) -> ValidationTestResult:
    bad_paths = []
    for path in model_cls.required_fields:
        parts = path.split(".")
        if len(parts) != 2:
            bad_paths.append(path)
            continue
        entity_attr, field_name = parts
        schema_name = _ENTITY_ATTR_TO_SCHEMA.get(entity_attr)
        if schema_name is None:
            bad_paths.append(path)
            continue
        schema = ENTITY_SCHEMAS[schema_name]
        if field_name not in schema.model_fields:
            bad_paths.append(path)
    return ValidationTestResult(
        test_name="required_fields_resolve_against_ce1_schema", passed=not bad_paths,
        detail=f"unresolvable paths: {bad_paths}" if bad_paths else "",
    )


def _check_output_conforms(model_cls: type[Model], bundle: ModelInputBundle) -> ValidationTestResult:
    try:
        output = model_cls().estimate(bundle)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, this is a compatibility probe
        return ValidationTestResult(test_name="output_conforms_common_model_contract", passed=False, detail=str(exc))
    ok = output.model_id == model_cls.model_id and output.domain == model_cls.domain
    return ValidationTestResult(
        test_name="output_conforms_common_model_contract", passed=ok,
        detail="" if ok else f"model_id/domain mismatch: {output.model_id}/{output.domain}",
    )


def _check_determinism(model_cls: type[Model], bundle: ModelInputBundle) -> ValidationTestResult:
    try:
        assert_deterministic(model_cls(), bundle)
    except NonDeterministicModel as exc:
        return ValidationTestResult(test_name="determinism", passed=False, detail=str(exc))
    return ValidationTestResult(test_name="determinism", passed=True)


def _check_independence(model_cls: type[Model]) -> ValidationTestResult:
    module = importlib.import_module(model_cls.__module__)
    source_path = module.__file__
    if source_path is None:
        return ValidationTestResult(test_name="independence", passed=False, detail="no source file found")

    with open(source_path, encoding="utf-8") as f:
        source = f.read()

    own_module_name = model_cls.__module__.rsplit(".", 1)[-1]
    forbidden = _OTHER_MODEL_MODULES - {own_module_name}
    hits = [name for name in forbidden if name in source]
    return ValidationTestResult(
        test_name="independence", passed=not hits,
        detail=f"references other Model module(s): {hits}" if hits else "",
    )


def _check_abstention_correctness(model_cls: type[Model], as_of) -> ValidationTestResult:
    empty_bundle = ModelInputBundle(match_id="__validation_probe__", player_a_id="a", player_b_id="b", as_of=as_of)
    output = model_cls().estimate(empty_bundle)
    ok = output.abstained is True
    return ValidationTestResult(
        test_name="abstention_correctness", passed=ok,
        detail="" if ok else "Model did not abstain on an entirely empty bundle",
    )


def run_validation_battery(model_cls: type[Model], representative_bundle: ModelInputBundle) -> ValidationBatteryResult:
    tests = [
        _check_required_fields_resolve(model_cls),
        _check_output_conforms(model_cls, representative_bundle),
        _check_determinism(model_cls, representative_bundle),
        _check_independence(model_cls),
        _check_abstention_correctness(model_cls, representative_bundle.as_of),
    ]
    return ValidationBatteryResult(model_id=model_cls.model_id, model_version=model_cls.version, tests=tests)
