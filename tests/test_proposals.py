import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.automation import register_policy
from fx_research_agent.proposals import build_blind_input, run_proposal_cycle
from fx_research_agent.storage import initialize
from tests.test_automation import AutomationPolicyTests


def proposal(statement="Quote-pressure reversal after objective-level failure"):
    return {
        "title": "Quote pressure reversal",
        "statement": statement,
        "mechanism_class": "MICROSTRUCTURE_CONFIRMATION",
        "instrument": "EUR_USD",
        "hypothesis_type": "CONTEXT_FILTER",
        "classification": "CONTEXT",
        "causal_rationale": "Absorption may distinguish rejection from continuation.",
        "data_requirements": ["OANDA_QUOTE_PRESSURE_PROXY"],
        "expected_frequency": "ONE_PER_ELIGIBLE_EPISODE",
        "population": {
            "inclusion_rule": "Failed-auction episodes",
            "exclusion_rule": "Missing pressure",
            "timeframe": "M15",
            "decision_time_rule": "Completed candle only",
        },
        "exact_specification": [
            {"field": "pressure_z", "operator": ">=", "value": "1.5"},
            {"field": "lookback_minutes", "operator": "=", "value": "5"},
        ],
        "controls": [{
            "control_id": "NO_PRESSURE",
            "definition": "Complement",
            "post_selection_mutation_allowed": False,
        }],
        "primary_metric": "AVERAGE_NET_R_LIFT",
        "independence_unit": "LEVEL_EPISODE",
        "overlap_notes": "Conditions existing triggers.",
        "falsification_condition": "No positive lift after costs at the sample gate.",
        "estimated_sample_gate": 30,
    }


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        initialize(self.connection)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(AutomationPolicyTests()._policy()), encoding="utf-8")
            register_policy(self.connection, path)
        hypothesis = {
            "hypothesis_id": "HYP_EXISTING",
            "state": "REJECTED",
            "statement": "M5 confirmation improves failed auction timing",
        }
        self.connection.execute(
            "INSERT INTO hypotheses VALUES (?,?,?,?,?,?,?)",
            ("HYP_EXISTING", "hash", json.dumps(hypothesis), "repo", "commit", "path", "2026-10-13T00:00:00Z"),
        )
        manifest = {"data_classes": ["OANDA_QUOTE_PRESSURE_PROXY"], "instrument": "EUR_USD"}
        self.connection.execute(
            "INSERT INTO market_data_manifests VALUES (?,?,?,?,?)",
            ("M1", "hash", json.dumps(manifest), "2026-10-13T00:00:00Z", 1),
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def _provider(self, output):
        def provider(policy, packet):
            self.assertNotIn("findings", packet)
            self.assertNotIn("realized_net_r", json.dumps(packet).lower())
            return output, {"provider_request_id": "REQ1", "input_tokens": 100, "output_tokens": 50}
        return provider

    def test_accepted_machine_proposal_stops_at_proposed(self):
        result = run_proposal_cycle(
            self.connection,
            provider=self._provider({"proposals": [proposal()]}),
            created_at_utc="2026-10-13T10:00:00Z",
        )
        self.assertEqual(result["results"][0]["status"], "ACCEPTED_PROPOSED")
        row = self.connection.execute(
            "SELECT payload_json FROM hypotheses WHERE hypothesis_id=?",
            (result["results"][0]["hypothesis_id"],),
        ).fetchone()
        self.assertEqual(json.loads(row["payload_json"])["state"], "PROPOSED")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) AS n FROM research_campaigns").fetchone()["n"], 0)

    def test_duplicate_and_missing_data_do_not_enter_registry(self):
        duplicate = proposal("M5 confirmation improves failed auction timing")
        unavailable = proposal("Macro surprise divergence improves failed auctions")
        unavailable["data_requirements"] = ["UNAVAILABLE_MACRO_SERIES"]
        result = run_proposal_cycle(
            self.connection,
            provider=self._provider({"proposals": [duplicate, unavailable]}),
            created_at_utc="2026-10-13T11:00:00Z",
        )
        self.assertEqual([item["status"] for item in result["results"]], ["REJECTED_DUPLICATE", "BLOCKED_DATA"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) AS n FROM hypotheses").fetchone()["n"], 1)

    def test_blind_input_excludes_findings_even_when_findings_exist(self):
        self.connection.execute(
            "INSERT INTO findings VALUES (?,?,?,?,?)",
            ("F1", "RUN1", "hash", json.dumps({"realized_net_r": 99}), "2026-10-13T00:00:00Z"),
        )
        packet = build_blind_input(self.connection)
        serialized = json.dumps(packet).lower()
        self.assertNotIn("realized_net_r", serialized)
        self.assertNotIn("finding_id", serialized)


if __name__ == "__main__":
    unittest.main()
