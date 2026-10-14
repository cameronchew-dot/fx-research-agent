import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.automation import load_policy, register_policy
from fx_research_agent.storage import initialize


class AutomationPolicyTests(unittest.TestCase):
    def _policy(self):
        return {
            "schema": "FX_RESEARCH_AUTONOMY_POLICY_V1",
            "policy_id": "POLICY_1",
            "registered_at_utc": "2026-10-13T00:00:00Z",
            "objective": "Test",
            "campaign_slot_limit": 3,
            "daily_evaluation_local_hour": 17,
            "daily_evaluation_local_minute": 0,
            "threshold_refresh_enabled": True,
            "proposal_cadence": "WEEKLY_MARKET_CLOSED",
            "weekly_proposal_local_weekday": 7,
            "weekly_proposal_local_hour": 10,
            "weekly_proposal_local_minute": 0,
            "maximum_proposals_per_cycle": 3,
            "maximum_pending_machine_proposals": 3,
            "provider": "ANTHROPIC",
            "model": "claude-sonnet-5-5",
            "endpoint": "https://api.anthropic.com/v1/messages",
            "prompt_version": "TEST",
            "temperature": 0.2,
            "seed": 1,
            "maximum_output_tokens": 1000,
            "duplicate_statement_jaccard_threshold": 0.65,
            "maximum_active_campaigns_per_mechanism_class": 1,
            "proposal_input_policy": {
                "include_findings": False,
                "include_net_r": False,
                "include_hidden_holdouts": False,
            },
            "authority": {
                "automatic_hypothesis_proposal": True,
                "automatic_campaign_creation": False,
                "automatic_campaign_approval": False,
                "automatic_policy_change": False,
                "automatic_downstream_export": False,
                "order_authority": False,
            },
        }

    def test_anthropic_policy_registers_without_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(self._policy()), encoding="utf-8")
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            result = register_policy(connection, path)
        self.assertEqual(result["provider"], "ANTHROPIC")
        self.assertFalse(result["automatic_approval"])
        self.assertFalse(result["order_authority"])

    def test_local_provider_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            payload = self._policy()
            payload["provider"] = "OLLAMA_LOCAL"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Anthropic"):
                load_policy(path)


if __name__ == "__main__":
    unittest.main()
