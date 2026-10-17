import csv
import gzip
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.campaigns import load_campaign
from fx_research_agent.g10_policy_stance import evaluate
from fx_research_agent.g10_value import INSTRUMENT_CURRENCY


class G10PolicyStanceTests(unittest.TestCase):
    def test_campaign_contract_is_one_inert_specification(self):
        campaign = load_campaign(Path("config/campaigns/g10_real_policy_stance_shift_v1.json"))
        self.assertEqual(campaign["exact_specification"]["minimum_absolute_stance_shift_percentage_points"], 0.25)
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_pipeline_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spot, policy, cpi = root / "spot.gz", root / "policy.gz", root / "cpi.gz"
            with gzip.open(spot, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["month", "instrument", "normalized_usd_per_foreign_currency"]); writer.writeheader()
                for index in range(100):
                    month = f"{2010 + index // 12:04d}-{index % 12 + 1:02d}"
                    for offset, instrument in enumerate(INSTRUMENT_CURRENCY):
                        writer.writerow({"month": month, "instrument": instrument, "normalized_usd_per_foreign_currency": 1 + offset * .1 + index * (offset + 1) * .001})
            with gzip.open(policy, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["month", "currency", "policy_rate_percent"]); writer.writeheader()
                for index in range(100):
                    month = f"{2010 + index // 12:04d}-{index % 12 + 1:02d}"
                    for offset, currency in enumerate([*INSTRUMENT_CURRENCY.values(), "USD"]):
                        slope = 0 if currency == "USD" else (offset + 1) * .02
                        writer.writerow({"month": month, "currency": currency, "policy_rate_percent": offset * .1 + index * slope})
            with gzip.open(cpi, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["period", "currency", "cpi_index"]); writer.writeheader()
                for index in range(100):
                    month = f"{2010 + index // 12:04d}-{index % 12 + 1:02d}"
                    for currency in [*INSTRUMENT_CURRENCY.values(), "USD"]:
                        writer.writerow({"period": month, "currency": currency, "cpi_index": 100 + index * .2})
            first = evaluate(spot, policy, cpi)
            second = evaluate(spot, policy, cpi)
        self.assertEqual(first, second)
        self.assertGreater(first["active_month_count"], 20)


if __name__ == "__main__":
    unittest.main()
