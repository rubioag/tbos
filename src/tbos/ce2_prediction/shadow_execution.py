"""CE.2.8 — Shadow Execution Layer.

Runs a VALIDATED (not yet ACTIVE) Model against a snapshot, tags the
result SHADOW, and stores it for INF.3 calibration — never lets it reach
the live Ensemble Aggregator, which structurally rejects any non-LIVE
execution_mode (see ensemble.py).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from tbos.ce2_prediction.base import Model
from tbos.ce2_prediction.contract import ModelOutput
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.ce2_prediction.models import ShadowOutputRow
from tbos.inf1_config.taxonomy import ExecutionMode


def run_shadow(model: Model, bundle: ModelInputBundle) -> ModelOutput:
    """The Model itself is execution-mode-agnostic by design (a pure domain
    estimator) — it always produces a LIVE-tagged output. The Shadow
    Execution Layer, sitting above it, relabels the result SHADOW before
    it's ever persisted or seen by anything else.
    """
    output = model.estimate(bundle)
    return output.model_copy(update={"execution_mode": ExecutionMode.SHADOW})


def store_shadow_output(
    session: Session, *, run_id: uuid.UUID, match_id: str, output: ModelOutput
) -> ShadowOutputRow:
    row = ShadowOutputRow(
        run_id=run_id, model_id=output.model_id, model_version=output.model_version,
        match_id=match_id, output=output.model_dump(mode="json"), execution_mode=output.execution_mode.value,
    )
    session.add(row)
    session.flush()
    return row


def run_and_store_shadow(
    session: Session, model: Model, bundle: ModelInputBundle, *, run_id: uuid.UUID
) -> ShadowOutputRow:
    output = run_shadow(model, bundle)
    return store_shadow_output(session, run_id=run_id, match_id=bundle.match_id, output=output)
