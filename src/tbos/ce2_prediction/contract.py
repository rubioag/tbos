"""CE.2.1 — Common Model Contract output schema (frozen spec §2, §3, §10).

Every Model, regardless of domain, emits exactly this shape. `estimate` is
deliberately a plain dict here — each domain (Serve, Return, Surface, ...)
defines and validates its own internal structure via its own Pydantic
model, but the Common Model Contract itself is domain-agnostic and must
not assume any particular estimate shape.

Non-responsibilities enforced by this schema's structure alone (§3):
- No field here can ever hold a probability or p_win contribution — the
  domain-to-probability translation belongs exclusively to the Ensemble
  Aggregator (CE.2.5), never to a Model.
- `market_data_used` exists so any market-derived feature a Model
  consumes is auditable — never a silent backdoor around Probability-First.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ContributionLineageEntry(BaseModel):
    field_used: str
    ce1_snapshot_id: uuid.UUID | None
    weight: float = Field(ge=0.0, le=1.0)


class ModelOutput(BaseModel):
    domain: str
    model_id: str
    model_version: str

    estimate: dict = Field(default_factory=dict)
    own_uncertainty: float = Field(ge=0.0)
    own_evidence_quality: float = Field(ge=0.0, le=1.0)

    abstained: bool
    abstain_reason: str | None = None

    contribution_lineage: list[ContributionLineageEntry] = Field(default_factory=list)
    market_data_used: bool = False

    computed_at: datetime


def abstain(*, domain: str, model_id: str, model_version: str, reason: str, computed_at: datetime) -> ModelOutput:
    """The only sanctioned way to produce a ModelOutput when required
    evidence is unusable — never fabricate an estimate instead (§3, §9).
    """
    return ModelOutput(
        domain=domain,
        model_id=model_id,
        model_version=model_version,
        estimate={},
        own_uncertainty=1.0,
        own_evidence_quality=0.0,
        abstained=True,
        abstain_reason=reason,
        computed_at=computed_at,
    )
