import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.automation import load_policy, refresh_approved_campaigns, register_policy
from fx_research_agent.campaigns import approve_campaign, register_campaign
from fx_research_agent.storage import initialize


class AutomationPolicyTests(unittest.TestCase):
    def _policy(self):
        return {
            "schema": "FX_RESEARCH_AUTONOMY_POLICY_V1",
            "policy_id": "POLICY_1",
            "registered_at_utc": "2026-10-13T00:00:00Z",
            "objective": "Test",
            "campaign_slot_limit": 10,
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

    def test_campaign_limit_above_ten_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            payload = self._policy()
            payload["campaign_slot_limit"] = 11
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "between one and ten"):
                load_policy(path)

    def test_refresh_skips_approved_campaign_when_data_is_not_ready(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        initialize(connection)
        connection.execute(
            "INSERT INTO hypotheses VALUES (?,?,?,?,?,?,?)",
            ("HYP_BLOCKED", "hash", "{}", "repo", "commit", "path", "2026-10-13T00:00:00Z"),
        )
        campaign = {
            "schema": "FX_RESEARCH_CAMPAIGN_V1",
            "campaign_id": "CAMPAIGN_BLOCKED",
            "hypothesis_id": "HYP_BLOCKED",
            "created_at_utc": "2026-10-13T00:00:00Z",
            "state": "DRAFT",
            "title": "Blocked campaign",
            "instrument": "EUR_USD",
            "mechanism_class": "TEST",
            "research_question": "Question",
            "null_hypothesis": "Null",
            "required_data_classes": ["UNAVAILABLE_CLASS"],
            "population": {"source": "TEST"},
            "independence_unit": {"unit": "MONTH"},
            "exact_specification": {"rule": "LOCKED"},
            "controls": [{"control_id": "CONTROL", "definition": "Control"}],
            "metrics": {"primary": "NET_RETURN"},
            "review_gates": {"minimum_n": 30},
            "multiple_comparisons_policy": {"confirmatory_slice_count": 1},
            "stopping_rules": {"no_early_success_declaration": True},
            "authority": {
                "automatic_approval": False,
                "automatic_execution": False,
                "downstream_activation": False,
                "order_authority": False,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path = root / "policy.json"
            policy_path.write_text(json.dumps(self._policy()), encoding="utf-8")
            register_policy(connection, policy_path)
            campaign_path = root / "campaign.json"
            campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
            registered = register_campaign(connection, campaign_path)
            approve_campaign(
                connection,
                "CAMPAIGN_BLOCKED",
                expected_payload_hash=registered["campaign_payload_hash"],
                approved_by="CAMERON",
                reason="Reviewed",
                approved_at_utc="2026-10-13T01:00:00Z",
            )
            result = refresh_approved_campaigns(
                connection,
                root / "evidence",
                market_inbox=root / "market",
                trigger="MANUAL",
                observed_at_utc="2026-10-14T00:00:00Z",
            )
        self.assertEqual(result["campaigns"][0]["review_status"], "BLOCKED_DATA_READINESS")
        self.assertEqual(result["campaigns"][0]["skip_reason"], "CAMPAIGN_DATA_NOT_READY")
        self.assertFalse(result["campaigns"][0]["evaluation_refreshed"])
        connection.close()


if __name__ == "__main__":
    unittest.main()
