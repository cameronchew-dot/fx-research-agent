import json
import unittest
from pathlib import Path

from fx_research_agent.batches import load_batch
from fx_research_agent.campaigns import load_campaign


class TurnOfMonthFixCampaignTests(unittest.TestCase):
    def test_campaign_is_locked_to_existing_forward_emitter(self):
        campaign = load_campaign(
            Path("config/campaigns/eur_turn_of_month_london_fix_fade_v1.json")
        )
        population = campaign["population"]
        specification = campaign["exact_specification"]

        self.assertEqual(population["mechanism_id"], "TURN_OF_MONTH_REBALANCE_FADE")
        self.assertEqual(
            population["setup_id"], "TURN_OF_MONTH_LONDON_FIX_STRETCH_FADE_V1"
        )
        self.assertEqual(population["entry_model"], "NEXT_M15_OPEN_WITH_DECISION_SPREAD")
        self.assertEqual(population["target_r"], 1.5)
        self.assertEqual(population["outcome_horizon_m15_bars"], 16)
        self.assertEqual(specification["timezone"], "Europe/London")
        self.assertEqual(
            specification["eligible_days"],
            "FIRST_TWO_AND_LAST_TWO_WEEKDAYS_OF_LOCAL_MONTH",
        )
        self.assertEqual(specification["confirmation_start_local"], "16:15")
        self.assertEqual(specification["confirmation_end_local"], "17:00")
        self.assertEqual(specification["minimum_stretch_pips"], 8.0)
        self.assertFalse(campaign["authority"]["automatic_approval"])
        self.assertFalse(campaign["authority"]["automatic_execution"])
        self.assertFalse(campaign["authority"]["downstream_activation"])
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_hypothesis_is_present_in_genesis_registry(self):
        registry = json.loads(
            Path("config/genesis_hypotheses.json").read_text(encoding="utf-8")
        )
        hypothesis = next(
            item
            for item in registry["hypotheses"]
            if item["hypothesis_id"] == "HYP_EUR_TURN_OF_MONTH_LONDON_FIX_FADE_V1"
        )

        self.assertEqual(hypothesis["classification"], "STRATEGY")
        self.assertEqual(hypothesis["priority"], 23)
        self.assertEqual(hypothesis["state"], "PROPOSED")

    def test_campaign_has_a_single_hypothesis_confirmatory_batch(self):
        batch = load_batch(
            Path("config/batches/eur_time_anchored_forward_v1.json")
        )

        self.assertEqual(batch["maximum_active_campaigns"], 1)
        self.assertEqual(
            batch["campaign_ids"],
            ["CAMPAIGN_EUR_TURN_OF_MONTH_LONDON_FIX_FADE_V1"],
        )
        self.assertEqual(batch["multiplicity_policy"]["hypothesis_budget"], 1)
        self.assertFalse(batch["authority"]["automatic_campaign_addition"])
        self.assertFalse(batch["authority"]["automatic_promotion"])


if __name__ == "__main__":
    unittest.main()
