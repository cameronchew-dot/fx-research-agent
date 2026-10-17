import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.campaigns import load_campaign
from fx_research_agent.usdjpy_intervention import build_episodes, evaluate, load_spot


class UsdJpyInterventionTests(unittest.TestCase):
    def test_campaign_is_retrospective_and_inert(self):
        campaign = load_campaign(Path("config/campaigns/usdjpy_mof_intervention_episode_v1.json"))
        self.assertFalse(campaign["review_gates"]["direct_strategy_or_lifecycle_eligibility"])
        self.assertFalse(campaign["authority"]["order_authority"])
        self.assertFalse(campaign["exact_specification"]["parameter_sweeps_allowed"])

    def test_five_quiet_trading_days_rearm_episode(self):
        dates = [f"2020-01-{day:02d}" for day in range(1, 21)]
        events = [{"date": "2020-01-02", "policy_direction_usdjpy": 1, "amount_100m_yen": 1}, {"date": "2020-01-07", "policy_direction_usdjpy": 1, "amount_100m_yen": 2}, {"date": "2020-01-13", "policy_direction_usdjpy": 1, "amount_100m_yen": 3}, {"date": "2020-01-14", "policy_direction_usdjpy": -1, "amount_100m_yen": 4}]
        episodes = build_episodes(dates, events)
        self.assertEqual(len(episodes), 3)
        self.assertEqual(episodes[0]["event_count"], 2)

    def test_pipeline_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spot, events = root / "spot.gz", root / "events.gz"
            with gzip.open(spot, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["date", "usd_jpy"]); writer.writeheader()
                for day in range(400):
                    writer.writerow({"date": f"{2020 + day // 336:04d}-{(day // 28) % 12 + 1:02d}-{day % 28 + 1:02d}", "usd_jpy": 100 + day * .01})
            with gzip.open(events, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["date", "policy_direction_usdjpy", "amount_100m_yen"]); writer.writeheader()
                for day in range(10, 370, 10):
                    writer.writerow({"date": f"{2020 + day // 336:04d}-{(day // 28) % 12 + 1:02d}-{day % 28 + 1:02d}", "policy_direction_usdjpy": 1 if day % 20 else -1, "amount_100m_yen": 100})
            first, second = evaluate(spot, events), evaluate(spot, events)
        self.assertEqual(first, second)
        self.assertGreater(first["complete_episode_count"], 20)

    def test_non_finite_spot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spot.gz"
            with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["date", "usd_jpy"]); writer.writeheader()
                writer.writerow({"date": "2020-01-01", "usd_jpy": "nan"})
            with self.assertRaisesRegex(ValueError, "non-finite"):
                load_spot(path)

    def test_registry_records_locked_rejection(self):
        registry = json.loads(Path("config/genesis_hypotheses.json").read_text(encoding="utf-8"))
        states = {row["hypothesis_id"]: row["state"] for row in registry["hypotheses"]}
        self.assertEqual(states["HYP_USDJPY_MOF_INTERVENTION_EPISODE_V1"], "REJECTED")


if __name__ == "__main__":
    unittest.main()
