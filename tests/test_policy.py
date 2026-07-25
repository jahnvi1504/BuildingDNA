from ecoloop.policy import MacroPolicy, PolicyMode, policy_score


def test_declining_score_moves_policy_toward_comfort() -> None:
    policy = MacroPolicy()

    policy.complete_episode(3.0)
    policy.complete_episode(2.0)
    mode, reason = policy.complete_episode(1.0)

    assert mode == PolicyMode.COMFORT_PRIORITY
    assert "stepped toward comfort" in reason


def test_improving_score_allows_more_aggressive_policy() -> None:
    policy = MacroPolicy()

    policy.complete_episode(1.0)
    policy.complete_episode(2.0)
    mode, reason = policy.complete_episode(3.0)

    assert mode == PolicyMode.ENERGY_SAVER
    assert "more aggressive" in reason


def test_policy_score_uses_fixed_documented_weights() -> None:
    assert policy_score(10.0, 20.0, 30.0) == 17.5
