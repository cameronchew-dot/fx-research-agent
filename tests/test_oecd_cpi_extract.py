import csv
import io
import tempfile
import unittest
from pathlib import Path

from ops.oecd_cpi_extract import AREA_BY_CURRENCY, normalize


def blob(area, frequency="M"):
    stream = io.StringIO()
    fields = ["REF_AREA", "FREQ", "METHODOLOGY", "MEASURE", "UNIT_MEASURE", "EXPENDITURE", "ADJUSTMENT", "TRANSFORMATION", "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS", "BASE_PER"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerow({"REF_AREA": area, "FREQ": frequency, "METHODOLOGY": "N", "MEASURE": "CPI", "UNIT_MEASURE": "IX", "EXPENDITURE": "_T", "ADJUSTMENT": "N", "TRANSFORMATION": "_Z", "TIME_PERIOD": "2020-Q1" if frequency == "Q" else "2020-01", "OBS_VALUE": "100", "OBS_STATUS": "A", "BASE_PER": "2015"})
    return stream.getvalue().encode()


class OecdCpiExtractTests(unittest.TestCase):
    def test_normalizes_all_locked_areas(self):
        blobs = {area: blob(area, "Q" if area in {"AUS", "NZL"} else "M") for area in set(AREA_BY_CURRENCY.values())}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = normalize(blobs, root / "cpi.csv.gz", root / "summary.json")
        self.assertEqual(summary["row_count"], 10)
        self.assertEqual(summary["information_lag_months"], 2)


if __name__ == "__main__":
    unittest.main()
