import csv
import gzip
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "bis_xru_extract.py"
SPEC = importlib.util.spec_from_file_location("bis_xru_extract", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BisExtractTests(unittest.TestCase):
    def test_extracts_exact_series_and_marks_spot_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            headers = [
                "FREQ:Frequency", "REF_AREA:Reference area", "CURRENCY:Currency",
                "COLLECTION:Collection", "TIME_PERIOD:Time period or range",
                "OBS_VALUE:Observation Value", "AVAILABILITY:Availability",
            ]
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                for (area, currency), _ in MODULE.SERIES.items():
                    writer.writerow({
                        headers[0]: "M: Monthly", headers[1]: f"{area}: Area",
                        headers[2]: f"{currency}: Currency", headers[3]: "E: End of period",
                        headers[4]: "2020-01", headers[5]: "2.0", headers[6]: "A: All users",
                    })
                writer.writerow({
                    headers[0]: "D: Daily", headers[1]: "GB: Area",
                    headers[2]: "GBP: Currency", headers[3]: "A: Average",
                    headers[4]: "2020-01-01", headers[5]: "9", headers[6]: "A: All users",
                })
            archive = root / "source.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.write(source, arcname="source.csv")
            output = root / "spot.csv.gz"
            summary = MODULE.extract(archive, output, root / "summary.json")
            with gzip.open(output, "rt", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 9)
        self.assertEqual(summary["common_month_count"], 1)
        self.assertEqual(rows[0]["data_scope"], "SPOT_ONLY_NOT_EXCESS_RETURN")
        self.assertAlmostEqual(float(rows[0]["normalized_usd_per_foreign_currency"]), 0.5)
        self.assertFalse(summary["campaign_4_financing_requirement_satisfied"])


if __name__ == "__main__":
    unittest.main()
