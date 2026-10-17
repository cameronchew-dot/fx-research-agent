import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_research_agent.campaigns import load_campaign
from fx_research_agent.experiments import (
    _candidate_levels_allowed,
    _classify_spread_degradation,
    _classify_touch_degradation,
)


ROOT = Path(__file__).resolve().parents[1]


class CampaignCohortTests(unittest.TestCase):
    def test_new_campaign_specs_are_valid_and_inert(self):
        paths = [
            ROOT
            / "config"
            / "campaigns"
            / "eur_spread_liquidity_degradation_forward_v1.json",
            ROOT
            / "config"
            / "campaigns"
            / "eur_level_touch_degradation_forward_v1.json",
            ROOT
            / "config"
            / "campaigns"
            / "g10_cross_sectional_momentum_v1.json",
        ]
        for path in paths:
            campaign = load_campaign(path)
            self.assertEqual(campaign["state"], "DRAFT")
            self.assertFalse(campaign["authority"]["automatic_approval"])
            self.assertFalse(campaign["authority"]["automatic_execution"])
            self.assertFalse(campaign["authority"]["downstream_activation"])
            self.assertFalse(campaign["authority"]["order_authority"])

    def test_g10_momentum_has_one_confirmatory_strategy(self):
        campaign = load_campaign(
            ROOT / "config" / "campaigns" / "g10_cross_sectional_momentum_v1.json"
        )
        specification = campaign["exact_specification"]
        self.assertEqual(specification["confirmatory_strategy"], "MOM_1_1")
        self.assertEqual(specification["descriptive_only_variants"], ["MOM_6_1", "MOM_12_1"])
        self.assertFalse(specification["descriptive_variants_can_qualify"])
        self.assertFalse(campaign["population"]["spot_only_substitution_allowed"])

    def test_confluent_new_york_level_signature_uses_allowed_level_set(self):
        candidate = {
            "level_signature": "NEW_YORK_SESSION_HIGH,PRIOR_DAY_HIGH"
        }
        self.assertTrue(
            _candidate_levels_allowed(
                candidate,
                ["NY_SESSION_HIGH", "PRIOR_DAY_HIGH"],
            )
        )
        self.assertFalse(
            _candidate_levels_allowed(candidate, ["PRIOR_DAY_HIGH"])
        )

    def test_spread_campaign_uses_only_96_prior_completed_bars(self):
        campaign = json.loads(
            (
                ROOT
                / "config"
                / "campaigns"
                / "eur_spread_liquidity_degradation_forward_v1.json"
            ).read_text()
        )
        decision = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
        bars = {
            (decision - timedelta(minutes=15 * offset))
            .isoformat()
            .replace("+00:00", "Z"): 1.0
            for offset in range(1, 97)
        }
        bars[decision.isoformat().replace("+00:00", "Z")] = 100.0
        candidate = {
            "decision_time_utc": decision.isoformat().replace("+00:00", "Z"),
            "market_facts": {"spread_pips": 1.6},
        }
        result = _classify_spread_degradation(
            {"candidate_id": "C1"}, candidate, campaign, bars
        )
        self.assertEqual(result["cohort"], "TREATMENT")
        self.assertEqual(result["cohort_label"], "HIGH_SPREAD")
        self.assertEqual(result["trailing_spread_median_pips"], 1.0)
        self.assertEqual(result["spread_lookback_bar_count"], 96)
        self.assertIsNone(
            _classify_spread_degradation(
                {"candidate_id": "C1"},
                candidate,
                campaign,
                dict(list(bars.items())[:95]),
            )
        )

    def test_touch_campaign_is_only_first_touch_versus_repeat_touch(self):
        first = _classify_touch_degradation(
            {"candidate_id": "C1"},
            {"objective_levels": [{"touch_index": 1}, {"touch_index": 1}]},
        )
        repeat = _classify_touch_degradation(
            {"candidate_id": "C2"},
            {"objective_levels": [{"touch_index": 1}, {"touch_index": 2}]},
        )
        self.assertEqual(first["cohort_label"], "FIRST_TOUCH")
        self.assertEqual(first["cohort"], "TREATMENT")
        self.assertEqual(repeat["cohort_label"], "REPEAT_TOUCH")
        self.assertEqual(repeat["cohort"], "COMPARATOR")
        self.assertEqual(repeat["maximum_contributing_touch_index"], 2)


if __name__ == "__main__":
    unittest.main()
