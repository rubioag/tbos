from tbos.ce4_decision.bias import run_bias_checklist


def test_normal_stake_and_robust_edge_passes() -> None:
    result = run_bias_checklist(adjusted_stake_fraction=0.02, robustness_score=0.9)
    assert result.passed is True
    assert all(not f.triggered for f in result.flags)


def test_oversized_stake_triggers_overconfidence_flag() -> None:
    result = run_bias_checklist(adjusted_stake_fraction=0.25, robustness_score=0.9)
    assert result.passed is False
    flag = next(f for f in result.flags if f.bias_type == "overconfidence_oversized_stake")
    assert flag.triggered is True


def test_fragile_robustness_with_nonzero_stake_triggers_flag() -> None:
    result = run_bias_checklist(adjusted_stake_fraction=0.02, robustness_score=0.1)
    flag = next(f for f in result.flags if f.bias_type == "fragile_edge_pursuit")
    assert flag.triggered is True
    assert result.passed is False


def test_fragile_robustness_with_zero_stake_does_not_trigger() -> None:
    """A zero stake means nothing is actually being committed — flagging
    it as bias pursuit would be a false positive.
    """
    result = run_bias_checklist(adjusted_stake_fraction=0.0, robustness_score=0.1)
    flag = next(f for f in result.flags if f.bias_type == "fragile_edge_pursuit")
    assert flag.triggered is False


def test_evidence_strings_reference_actual_values() -> None:
    result = run_bias_checklist(adjusted_stake_fraction=0.25, robustness_score=0.9)
    flag = next(f for f in result.flags if f.bias_type == "overconfidence_oversized_stake")
    assert "0.25" in flag.evidence
