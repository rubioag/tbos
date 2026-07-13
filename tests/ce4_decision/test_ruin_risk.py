from tbos.ce4_decision.ruin_risk import simulate_ruin_risk


def test_zero_stake_never_ruins() -> None:
    result = simulate_ruin_risk(
        stake_fraction=0.0, probability=0.5, offered_odds=2.0, max_ruin_probability=0.01,
        simulated_paths=200, rng_seed=42,
    )
    assert result.ruin_probability == 0.0
    assert result.passed is True


def test_reproducible_given_fixed_seed() -> None:
    a = simulate_ruin_risk(stake_fraction=0.1, probability=0.5, offered_odds=1.9, max_ruin_probability=0.05, simulated_paths=300, rng_seed=7)
    b = simulate_ruin_risk(stake_fraction=0.1, probability=0.5, offered_odds=1.9, max_ruin_probability=0.05, simulated_paths=300, rng_seed=7)
    assert a.ruin_probability == b.ruin_probability


def test_aggressive_stake_with_negative_edge_has_high_ruin_probability() -> None:
    result = simulate_ruin_risk(
        stake_fraction=0.9, probability=0.3, offered_odds=1.5, max_ruin_probability=0.01,
        simulated_paths=300, horizon_bets=50, rng_seed=1,
    )
    assert result.ruin_probability > 0.5
    assert result.passed is False


def test_conservative_stake_with_positive_edge_has_low_ruin_probability() -> None:
    result = simulate_ruin_risk(
        stake_fraction=0.01, probability=0.6, offered_odds=2.0, max_ruin_probability=0.05,
        simulated_paths=500, horizon_bets=50, rng_seed=1,
    )
    assert result.ruin_probability < 0.05
    assert result.passed is True


def test_higher_stake_fraction_increases_ruin_probability() -> None:
    low = simulate_ruin_risk(stake_fraction=0.05, probability=0.5, offered_odds=1.9, max_ruin_probability=0.5, simulated_paths=300, rng_seed=3)
    high = simulate_ruin_risk(stake_fraction=0.5, probability=0.5, offered_odds=1.9, max_ruin_probability=0.5, simulated_paths=300, rng_seed=3)
    assert high.ruin_probability >= low.ruin_probability
