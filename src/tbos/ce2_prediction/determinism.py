"""CE.2.1 — reusable determinism assertion (Common Model Contract §10).
Every concrete Model's own test suite (CE.2.2+) is expected to call this
at least once against a representative bundle.
"""

from __future__ import annotations

from tbos.ce2_prediction.base import Model
from tbos.ce2_prediction.input_bundle import ModelInputBundle


class NonDeterministicModel(AssertionError):
    pass


def assert_deterministic(model: Model, bundle: ModelInputBundle, *, runs: int = 5) -> None:
    outputs = [model.estimate(bundle) for _ in range(runs)]
    first = outputs[0]
    for i, other in enumerate(outputs[1:], start=2):
        if other != first:
            raise NonDeterministicModel(
                f"{model.model_id} v{model.version} produced a different output on run {i} "
                f"than run 1 for the same bundle — violates Common Model Contract §10"
            )
