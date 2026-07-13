import pytest

from tbos.ce3_edge.sensitivity import run_sensitivity_analysis


def test_positive_perturbation_increases_ev() -> None:
    result = run_sensitivity_analysis(0.5, 2.0)
    up = next(p for p in result.perturbations if p.delta_probability > 0)
    down = next(p for p in result.perturbations if p.delta_probability < 0)
    assert up.resulting_ev > down.resulting_ev


def test_perturbation_magnitude_matches_delta_parameter() -> None:
    result = run_sensitivity_analysis(0.5, 2.0, delta=0.02)
    assert {abs(p.delta_probability) for p in result.perturbations} == {0.02}


def test_two_perturbations_produced_by_default() -> None:
    result = run_sensitivity_analysis(0.5, 2.0)
    assert len(result.perturbations) == 2


def test_clamped_at_upper_probability_bound() -> None:
    result = run_sensitivity_analysis(0.995, 2.0, delta=0.01)
    up = next(p for p in result.perturbations if p.delta_probability > 0)
    assert up.resulting_ev == pytest.approx(1.0 * 2.0 - 1.0)  # clamped to p=1.0


def test_probability_estimate_is_the_named_driver() -> None:
    result = run_sensitivity_analysis(0.5, 2.0)
    assert "probability_estimate" in result.dominant_assumption_drivers
