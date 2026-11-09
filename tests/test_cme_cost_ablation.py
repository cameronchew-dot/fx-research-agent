import tempfile
import unittest
from pathlib import Path

from fx_research_agent.cme_cost_ablation import build_report, write_report


ROOT = Path(__file__).resolve().parents[1]


class CmeCostAblationTests(unittest.TestCase):
    def test_existing_locked_result_does_not_support_live_cme_purchase(self):
        report = build_report(
            root=ROOT,
            contract_path=ROOT / "config/cme_live_data_cost_ablation_v1.json",
        )
        self.assertEqual(report["status"], "NO_EVIDENCE_TO_PURCHASE_LIVE_CME")
        self.assertFalse(report["live_cme_purchase_supported"])
        self.assertEqual(report["validation_rows_inspected"], 0)
        self.assertEqual(len(report["populations"]), 4)
        self.assertTrue(all(row["average_net_r"] < 0 for row in report["populations"]))
        self.assertFalse(report["paper_or_live_authority"])

    def test_report_writer_is_deterministic_except_generation_time(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "report.json"
            report = write_report(
                root=ROOT,
                contract_path=ROOT / "config/cme_live_data_cost_ablation_v1.json",
                output_path=output,
            )
            self.assertTrue(output.exists())
            self.assertEqual(report["recommendation"].split(";")[0], "DO_NOT_BUY_LIVE_CME")


if __name__ == "__main__":
    unittest.main()
