import uuid
from datetime import datetime, timezone

from tbos.ce3_edge.ev import EVDistribution
from tbos.ce3_edge.persistence import EdgePersistence
from tbos.ce3_edge.robustness import RobustnessScore
from tbos.ce3_edge.schemas import EdgeDescription
from tbos.ce3_edge.sensitivity import SensitivityAnalysis
from tbos.ce4_decision.bias import BiasChecklistResult, BiasFlag
from tbos.ce4_decision.decision import select_action
from tbos.ce4_decision.ruin_risk import RuinRiskResult
from tbos.ce4_decision.stake import StakeResult
from tbos.inf1_config.taxonomy import (
    ActionType,
    EdgeLifecycle,
    EdgeSourceCategory,
    InstrumentType,
    PersistenceClass,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _edge(*, expected_ev: float, robustness: float) -> EdgeDescription:
    return EdgeDescription(
        edge_id=uuid.uuid4(), match_id="m", instrument_type=InstrumentType.MONEYLINE, book_id="b",
        probability_used=0.6, probability_uncertainty=0.1, fair_odds=1.67, offered_odds=2.0,
        ev_distribution=EVDistribution(expected=expected_ev, best_case=expected_ev + 0.1, worst_case=expected_ev - 0.1, confidence_interval=(expected_ev - 0.1, expected_ev + 0.1)),
        edge_robustness=RobustnessScore(score=robustness, method="test"),
        edge_persistence=EdgePersistence(estimate_seconds=3600, persistence_class=PersistenceClass.HOURS, based_on="test"),
        sensitivity_analysis=SensitivityAnalysis(perturbations=[], dominant_assumption_drivers=[]),
        edge_lifecycle=EdgeLifecycle.UNKNOWN, edge_source_category=EdgeSourceCategory.MODEL,
        ce3_engine_version="1.0.0", computed_at=NOW,
    )


_PASSING_BIAS = BiasChecklistResult(passed=True, flags=[])
_FAILING_BIAS = BiasChecklistResult(passed=False, flags=[BiasFlag(bias_type="overconfidence_oversized_stake", triggered=True, evidence="x")])
_PASSING_RUIN = RuinRiskResult(ruin_probability=0.001, passed=True, simulated_paths=100)
_FAILING_RUIN = RuinRiskResult(ruin_probability=0.5, passed=False, simulated_paths=100)
_STAKE = StakeResult(raw_kelly_fraction=0.1, adjusted_fraction=0.02, stake_amount=200.0)


def test_non_positive_ev_is_pass() -> None:
    action, reason = select_action(_edge(expected_ev=-0.02, robustness=0.9), _STAKE, _PASSING_BIAS, _PASSING_RUIN, aggressiveness_threshold=0.5)
    assert action == ActionType.PASS
    assert reason.code == "NON_POSITIVE_EV"


def test_zero_ev_is_pass() -> None:
    action, _ = select_action(_edge(expected_ev=0.0, robustness=0.9), _STAKE, _PASSING_BIAS, _PASSING_RUIN, aggressiveness_threshold=0.5)
    assert action == ActionType.PASS


def test_robustness_below_threshold_is_defer() -> None:
    action, reason = select_action(_edge(expected_ev=0.05, robustness=0.3), _STAKE, _PASSING_BIAS, _PASSING_RUIN, aggressiveness_threshold=0.5)
    assert action == ActionType.DEFER
    assert reason.code == "MARGINAL_ROBUSTNESS"


def test_failed_bias_checklist_is_defer() -> None:
    action, reason = select_action(_edge(expected_ev=0.05, robustness=0.9), _STAKE, _FAILING_BIAS, _PASSING_RUIN, aggressiveness_threshold=0.5)
    assert action == ActionType.DEFER
    assert reason.code == "BEHAVIORAL_BIAS_FLAGGED"


def test_failed_ruin_risk_is_pass_not_defer() -> None:
    """Ruin risk is a hard capital-safety gate — rejected outright, never
    just 'wait and see' like a marginal-evidence DEFER.
    """
    action, reason = select_action(_edge(expected_ev=0.05, robustness=0.9), _STAKE, _PASSING_BIAS, _FAILING_RUIN, aggressiveness_threshold=0.5)
    assert action == ActionType.PASS
    assert reason.code == "RUIN_RISK_EXCEEDED"


def test_all_checks_pass_is_bet_now() -> None:
    action, reason = select_action(_edge(expected_ev=0.05, robustness=0.9), _STAKE, _PASSING_BIAS, _PASSING_RUIN, aggressiveness_threshold=0.5)
    assert action == ActionType.BET_NOW
    assert reason.code == "POSITIVE_EV_ROBUST"


def test_rule_priority_ev_checked_before_robustness() -> None:
    """Even with terrible robustness, a non-positive EV must report as
    NON_POSITIVE_EV, not MARGINAL_ROBUSTNESS — EV is checked first.
    """
    action, reason = select_action(_edge(expected_ev=-0.01, robustness=0.0), _STAKE, _PASSING_BIAS, _PASSING_RUIN, aggressiveness_threshold=0.5)
    assert reason.code == "NON_POSITIVE_EV"
