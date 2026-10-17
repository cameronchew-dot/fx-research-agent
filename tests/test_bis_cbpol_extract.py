import csv
import tempfile
import unittest
import zipfile
from pathlib import Path

from ops.bis_cbpol_extract import AREA_BY_CURRENCY, extract


class BisPolicyRateExtractTests(unittest.TestCase):
    def test_extracts_locked_monthly_g10_rates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "rates.zip"
            fields = ["FREQ:Frequency", "REF_AREA:Reference area", "TIME_PERIOD:Time period or range", "OBS_VALUE:Observation Value", "OBS_STATUS:Observation Status"]
            csv_path = root / "rates.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for area in AREA_BY_CURRENCY.values():
                    writer.writerow({"FREQ:Frequency": "M: Monthly", "REF_AREA:Reference area": f"{area}: Area", "TIME_PERIOD:Time period or range": "2020-01", "OBS_VALUE:Observation Value": "1.25", "OBS_STATUS:Observation Status": "A: Normal"})
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.write(csv_path, "rates.csv")
            summary = extract(archive, root / "out.csv.gz", root / "summary.json")
        self.assertEqual(summary["row_count"], 10)
        self.assertEqual(summary["common_month_count"], 1)


if __name__ == "__main__":
    unittest.main()
