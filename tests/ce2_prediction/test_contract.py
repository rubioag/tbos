from datetime import datetime, timezone

from tbos.ce2_prediction.contract import ModelOutput, abstain

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_model_output_round_trips_through_json() -> None:
    output = ModelOutput(
        domain="serve",
        model_id="serve_model",
        model_version="1.0.0",
        estimate={"hold_probability": 0.72},
        own_uncertainty=0.15,
        own_evidence_quality=0.8,
        abstained=False,
        computed_at=NOW,
    )
    restored = ModelOutput.model_validate_json(output.model_dump_json())
    assert restored == output


def test_abstain_produces_conservative_output() -> None:
    output = abstain(domain="serve", model_id="serve_model", model_version="1.0.0", reason="missing data", computed_at=NOW)
    assert output.abstained is True
    assert output.abstain_reason == "missing data"
    assert output.estimate == {}
    assert output.own_uncertainty == 1.0
    assert output.own_evidence_quality == 0.0


def test_estimate_is_domain_agnostic_dict_never_a_probability_field() -> None:
    """Structural guard: ModelOutput has no `p_win` / `probability` field
    anywhere — the Common Model Contract forbids a Model from ever
    producing one (Ensemble Aggregator's exclusive job).
    """
    assert "p_win" not in ModelOutput.model_fields
    assert "probability" not in ModelOutput.model_fields
