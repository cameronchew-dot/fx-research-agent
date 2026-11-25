import unittest

from fx_research_agent.exit_management_research import (
    _paired_sign_p_value,
    _simulate_policy,
)


def candle(open_, high, low, close):
    return {"open": open_, "high": high, "low": low, "close": close}


class ExitManagementResearchTests(unittest.TestCase):
    def test_break_even_activates_on_next_candle(self):
        rows = [
            candle(100.0, 101.2, 99.5, 101.0),
            candle(101.0, 101.1, 99.9, 100.1),
        ]
        result = _simulate_policy(
            rows,
            direction="LONG",
            entry=100.0,
            risk_distance=1.0,
            spread_r=0.0,
            policy="BREAK_EVEN_AFTER_1R",
        )
        self.assertEqual(result["net_r"], 0.0)
        self.assertEqual(result["exit_reason"], "BREAK_EVEN")

    def test_activation_bar_uses_conservative_stop_first(self):
        rows = [candle(100.0, 101.2, 98.9, 100.5)]
        result = _simulate_policy(
            rows,
            direction="LONG",
            entry=100.0,
            risk_distance=1.0,
            spread_r=0.2,
            policy="PARTIAL_1R_BE_RUNNER_2R",
        )
        self.assertEqual(result["net_r"], -1.0)
        self.assertFalse(result["partial_taken"])

    def test_partial_runner_accounts_for_extra_fill_cost(self):
        rows = [candle(100.0, 101.2, 99.5, 101.0), candle(101.0, 102.1, 100.8, 102.0)]
        result = _simulate_policy(
            rows,
            direction="LONG",
            entry=100.0,
            risk_distance=1.0,
            spread_r=0.2,
            policy="PARTIAL_1R_RUNNER_2R",
        )
        self.assertAlmostEqual(result["net_r"], 1.45)
        self.assertAlmostEqual(result["extra_partial_cost_r"], 0.05)

    def test_paired_sign_test_ignores_ties(self):
        self.assertEqual(_paired_sign_p_value([1.0, 1.0, -1.0, 0.0]), 1.0)


if __name__ == "__main__":
    unittest.main()
