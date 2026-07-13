"""CE.2.7 — Evidence Quality Aggregator.

Answers "how strong is the informational foundation", independent of
Probability (CE.2.5) and Uncertainty (CE.2.6). Reuses the same Freshness
metadata Uncertainty reads, but for a different question: Uncertainty asks
"how much could reality have drifted since this was collected", Evidence
Quality asks "does this data still represent reality strongly enough to
trust it" — same input, two distinct semantic roles, computed separately.

Unlike Uncertainty Aggregator, `bundle` is a required parameter here:
four of the six spec-locked sources need it directly, so an optional-bundle
path would mean silently defaulting most of this Engine's output — that's
a worse failure mode than just requiring the same bundle every Model and
Uncertainty already had access to.

Source 6 (IL.1 Research signal quality / taxonomy mix) is deferred — IL.1
doesn't exist yet in the build order. Documented, not faked with a
placeholder computation.
"""

from __future__ import annotations

from pydantic import BaseModel

from tbos.ce1_data.envelope import FieldEnvelope
from tbos.ce1_data.schemas import MatchContext, PlayerProfile, PlayerState
from tbos.ce2_prediction.ensemble import EnsembleOutput
from tbos.ce2_prediction.input_bundle import ModelInputBundle
from tbos.inf1_config.taxonomy import FieldAvailability, FreshnessStatus

W_OWN_EVIDENCE_QUALITY = 0.30
W_AVAILABILITY = 0.20
W_RELIABILITY = 0.20
W_PROVENANCE = 0.10
W_FRESHNESS_VALIDITY = 0.10
W_CONFLICT_PENALTY = 0.30


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


_ENTITY_SLOTS: list[tuple[str, type]] = [
    ("player_a_profile", PlayerProfile),
    ("player_a_state", PlayerState),
    ("player_b_profile", PlayerProfile),
    ("player_b_state", PlayerState),
    ("match_context", MatchContext),
]


def _collect_envelopes(bundle: ModelInputBundle) -> tuple[list[FieldEnvelope], int]:
    """Returns (envelopes from entities that ARE present, count of field
    slots belonging to entities that are entirely absent). An absent
    entity (e.g. player_b_profile never published to CE.1) must count as
    every one of its fields being unavailable — silently skipping it
    would understate missing data instead of reflecting it honestly.
    """
    present_envelopes: list[FieldEnvelope] = []
    missing_entity_field_slots = 0
    for attr_name, schema in _ENTITY_SLOTS:
        entity = getattr(bundle, attr_name)
        if entity is None:
            missing_entity_field_slots += len(schema.model_fields)
            continue
        for field_name in type(entity).model_fields:
            value = getattr(entity, field_name)
            if isinstance(value, FieldEnvelope):
                present_envelopes.append(value)
    return present_envelopes, missing_entity_field_slots


class EvidenceQualityComponents(BaseModel):
    avg_own_evidence_quality: float
    field_availability_rate: float
    source_reliability_avg: float
    provenance_completeness_rate: float
    freshness_validity_rate: float
    conflict_rate: float
    il1_signal_quality: float  # always 0.0 for v1 — IL.1 not built yet, not a real measurement


class EvidenceQualityResult(BaseModel):
    final_evidence_quality: float
    components: EvidenceQualityComponents


def compute_evidence_quality(
    ensemble_output: EnsembleOutput, *, bundle: ModelInputBundle
) -> EvidenceQualityResult:
    if ensemble_output.fully_abstained:
        return EvidenceQualityResult(
            final_evidence_quality=0.0,
            components=EvidenceQualityComponents(
                avg_own_evidence_quality=0.0, field_availability_rate=0.0, source_reliability_avg=0.0,
                provenance_completeness_rate=0.0, freshness_validity_rate=0.0, conflict_rate=0.0,
                il1_signal_quality=0.0,
            ),
        )

    participating = ensemble_output.participating
    avg_own_evidence_quality = sum(c.weight * c.own_evidence_quality for c in participating)

    envelopes, missing_entity_field_slots = _collect_envelopes(bundle)
    total_expected = len(envelopes) + missing_entity_field_slots
    total_present = len(envelopes)

    if total_expected == 0:
        field_availability_rate = 0.0
        source_reliability_avg = 0.0
        provenance_completeness_rate = 0.0
        freshness_validity_rate = 0.0
        conflict_rate = 0.0
    else:
        available_count = sum(1 for e in envelopes if e.availability == FieldAvailability.PRESENT)
        field_availability_rate = available_count / total_expected

        # Missing entities have no fields to inspect for provenance/conflict —
        # those rates are computed only over fields that actually exist.
        provenance_completeness_rate = (
            sum(1 for e in envelopes if e.provenance is not None) / total_present if total_present else 0.0
        )
        conflict_rate = sum(1 for e in envelopes if e.has_conflict) / total_present if total_present else 0.0

        with_reliability = [e for e in envelopes if e.reliability is not None]
        source_reliability_avg = (
            sum(e.reliability.source_trust_score for e in with_reliability) / len(with_reliability)
            if with_reliability else 0.0
        )

        with_freshness = [e for e in envelopes if e.freshness is not None]
        freshness_validity_rate = (
            sum(1 for e in with_freshness if e.freshness.status == FreshnessStatus.FRESH) / len(with_freshness)
            if with_freshness else 0.0
        )

    composite = _clamp01(
        W_OWN_EVIDENCE_QUALITY * avg_own_evidence_quality
        + W_AVAILABILITY * field_availability_rate
        + W_RELIABILITY * source_reliability_avg
        + W_PROVENANCE * provenance_completeness_rate
        + W_FRESHNESS_VALIDITY * freshness_validity_rate
        - W_CONFLICT_PENALTY * conflict_rate
    )

    return EvidenceQualityResult(
        final_evidence_quality=composite,
        components=EvidenceQualityComponents(
            avg_own_evidence_quality=avg_own_evidence_quality,
            field_availability_rate=field_availability_rate,
            source_reliability_avg=source_reliability_avg,
            provenance_completeness_rate=provenance_completeness_rate,
            freshness_validity_rate=freshness_validity_rate,
            conflict_rate=conflict_rate,
            il1_signal_quality=0.0,
        ),
    )
