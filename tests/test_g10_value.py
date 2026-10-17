import csv
import gzip
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.g10_value import INSTRUMENT_CURRENCY, evaluate
from fx_research_agent.campaigns import load_campaign


class G10ValueTests(unittest.TestCase):
    def test_locked_campaign_contract_is_valid_and_inert(self):
        campaign = load_campaign(Path("config/campaigns/g10_real_exchange_rate_value_v1.json"))
        self.assertEqual(campaign["exact_specification"]["confirmatory_strategy"], "REAL_VALUE_60M")
        self.assertFalse(campaign["authority"]["order_authority"])

    def test_value_pipeline_is_deterministic_and_uses_complete_months(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spot = root / "spot.csv.gz"
            cpi = root / "cpi.csv.gz"
            with gzip.open(spot, "wt", encoding="utf-8", newline="") as handle:
                fields = ["month", "instrument", "normalized_usd_per_foreign_currency"]
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for index in range(100):
                    month = f"{2010 + index // 12:04d}-{index % 12 + 1:02d}"
                    for offset, (instrument, _) in enumerate(INSTRUMENT_CURRENCY.items()):
                        writer.writerow({"month": month, "instrument": instrument, "normalized_usd_per_foreign_currency": 1 + offset * 0.1 + index * (offset + 1) * 0.0002})
            with gzip.open(cpi, "wt", encoding="utf-8", newline="") as handle:
                fields = ["period", "currency", "cpi_index"]
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for index in range(100):
                    month = f"{2010 + index // 12:04d}-{index % 12 + 1:02d}"
                    for offset, currency in enumerate([*INSTRUMENT_CURRENCY.values(), "USD"]):
                        writer.writerow({"period": month, "currency": currency, "cpi_index": 100 + index * (0.1 + offset * 0.001)})
            first = evaluate(spot, cpi)
            second = evaluate(spot, cpi)
        self.assertEqual(first, second)
        self.assertGreater(first["portfolio_month_count"], 20)
        self.assertEqual(sum(value["month_count"] for value in first["partitions"].values()), first["portfolio_month_count"])


if __name__ == "__main__":
    unittest.main()
