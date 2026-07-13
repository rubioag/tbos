"""Structural enforcement of the Measurement Independence Principle
(spec, locked at CE.6 design time): CLVRecord may never carry a field
that references match outcome, win/loss, or ROI.
"""

from tbos.ce6_clv.schemas import CLVRecord


def test_clv_record_has_no_outcome_result_or_roi_field() -> None:
    forbidden = {"outcome", "result", "win_loss", "roi", "profit", "settled"}
    assert forbidden.isdisjoint(CLVRecord.model_fields.keys())


def test_clv_calculation_never_takes_an_outcome_parameter() -> None:
    import inspect

    from tbos.ce6_clv.clv import compute_clv

    params = set(inspect.signature(compute_clv).parameters.keys())
    assert "outcome" not in params
    assert "result" not in params
