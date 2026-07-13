"""Pydantic v2 schemas for INF.1 Config Registry and Model Registry.

A ConfigVersionBundle is the full, immutable snapshot of every threshold and
policy value used by any Engine or Model at a point in time. Publishing a
new bundle always creates a new `config_version_id` — nothing is ever
patched in place (Configuration Independence Principle).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt

from tbos.inf1_config.taxonomy import ModelLifecycleStatus, ValidationStatus


class BankrollConfig(BaseModel):
    total_capital: PositiveFloat
    currency: str = "USD"


class RiskConfig(BaseModel):
    aggressiveness_threshold: float = Field(ge=0.0, le=1.0)
    ruin_risk_max_probability: float = Field(ge=0.0, le=1.0, default=0.01)
    fractional_kelly_multiplier: float = Field(gt=0.0, le=1.0, default=0.25)


class FreshnessThresholds(BaseModel):
    """Max acceptable age, in seconds, before a field is flagged STALE."""

    player_static_seconds: PositiveInt = 7 * 24 * 3600
    player_state_seconds: PositiveInt = 24 * 3600
    match_context_seconds: PositiveInt = 24 * 3600
    market_odds_seconds: PositiveInt = 60


class DataIngestionConfig(BaseModel):
    freshness_thresholds: FreshnessThresholds = Field(default_factory=FreshnessThresholds)
    source_priority: dict[str, list[str]] = Field(default_factory=dict)
    validation_ranges: dict[str, tuple[float, float]] = Field(default_factory=dict)
    polling_cadence_seconds: dict[str, int] = Field(default_factory=dict)


class EnsembleConfig(BaseModel):
    quorum_minimum_absolute: PositiveInt = 2
    quorum_comfortable: PositiveInt = 4
    evidence_quality_floor: float = Field(ge=0.0, le=1.0, default=0.3)
    evidence_quality_comfortable: float = Field(ge=0.0, le=1.0, default=0.6)
    uncertainty_ceiling_degraded: float = Field(ge=0.0, le=1.0, default=0.35)
    disagreement_malfunction_threshold: float = Field(gt=0.0, default=5.0)


class CLVConfig(BaseModel):
    vig_adjustment_method: str = "proportional"
    closing_time_policy: dict[str, str] = Field(default_factory=dict)


class ConfigVersionBundle(BaseModel):
    """The full versioned snapshot. Immutable once persisted."""

    bankroll: BankrollConfig
    risk: RiskConfig
    data_ingestion: DataIngestionConfig = Field(default_factory=DataIngestionConfig)
    ensemble: EnsembleConfig = Field(default_factory=EnsembleConfig)
    clv: CLVConfig = Field(default_factory=CLVConfig)
    behavioral_bias_checklist_version: str | None = None
    taxonomy_version: str = "1.0.0"


class ConfigVersionRead(BaseModel):
    config_version_id: UUID
    created_at: datetime
    approved_by: str
    bundle: ConfigVersionBundle

    model_config = {"from_attributes": True}


class ModelRegistryEntryCreate(BaseModel):
    model_id: str
    domain: str
    version: str
    owner: str
    required_fields: list[str]
    optional_fields: list[str] = Field(default_factory=list)


class ModelRegistryEntryRead(BaseModel):
    model_id: str
    domain: str
    version: str
    owner: str
    required_fields: list[str]
    optional_fields: list[str]
    output_schema_compliance: bool
    validation_status: ValidationStatus
    lifecycle_status: ModelLifecycleStatus
    created_at: datetime

    model_config = {"from_attributes": True}
