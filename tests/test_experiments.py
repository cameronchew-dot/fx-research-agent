import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.campaigns import approve_campaign, register_campaign
from fx_research_agent.evidence import register_manifest
from fx_research_agent.experiments import run_campaign
from fx_research_agent.storage import initialize
from tests.test_campaigns import campaign_payload


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        initialize(self.connection)
        self.connection.execute(
            "INSERT INTO hypotheses VALUES (?,?,?,?,?,?,?)",
            ("HYP_1", "hash", json.dumps({"hypothesis_id": "HYP_1"}), "repo", "commit", "path", "2026-10-13T00:00:00Z"),
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def _campaign(self, root: Path) -> tuple[Path, dict]:
        payload = campaign_payload()
        payload["required_data_classes"] = [
            "FORWARD_FAILED_AUCTION_EPISODES",
            "FORWARD_RULE_BASELINE_OUTCOMES",
        ]
        payload["population"] = {
            "source": "FORWARD",
            "allowed_levels": ["PRIOR_DAY_HIGH"],
            "timeframe": "M15",
            "outcome_horizon_m15_bars": 16,
            "entry_model": "NEXT_M15_OPEN_WITH_DECISION_SPREAD",
            "same_bar_tie_policy": "STOP_FIRST_CONSERVATIVE",
        }
        payload["exact_specification"] = {"objective_room": {"minimum_reward_room_r": 2.0}}
        payload["review_gates"] = {
            "minimum_resolved_independent_treatment_episodes": 1,
            "minimum_resolved_independent_comparator_episodes": 1,
        }
        path = root / "campaign.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path, payload

    def _evidence(self, root: Path) -> Path:
        candidates = []
        contexts = []
        outcomes = []
        rows = [
            ("C1", "E1", "2026-10-13T02:00:00Z", "ALIGNED", 2.5, "FORWARD_ABSTENTION_COUNTERFACTUAL", 1.0),
            ("C2", "E2", "2026-10-13T03:00:00Z", "OPPOSED", 2.5, "FORWARD_ABSTENTION_COUNTERFACTUAL", -1.0),
            ("C3", "E2", "2026-10-13T04:00:00Z", "ALIGNED", 3.0, "FORWARD_ABSTENTION_COUNTERFACTUAL", 5.0),
            ("C4", "E3", "2026-10-13T05:00:00Z", "ALIGNED", 3.0, "FORWARD_SHADOW_ACTION", 0.5),
        ]
        for candidate_id, episode_id, decision_time, alignment, room, source, net_r in rows:
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "episode_id": episode_id,
                    "instrument": "EUR_USD",
                    "mechanism_class": "OBJECTIVE_LEVEL_FAILED_AUCTION",
                    "base_timeframe": "M15",
                    "level_signature": "PRIOR_DAY_HIGH",
                    "decision_time_utc": decision_time,
                }
            )
            contexts.append(
                {
                    "candidate_id": candidate_id,
                    "created_at_utc": decision_time,
                    "as_of_utc": decision_time,
                    "daily_trend": {"status": "READY", "direction_alignment": alignment},
                    "target_room": {"status": "READY", "reward_room_r": room},
                }
            )
            outcomes.append(
                {
                    "outcome_id": f"O_{candidate_id}",
                    "candidate_id": candidate_id,
                    "arm_id": "RULE_BASELINE",
                    "observed_at_utc": "2026-10-13T10:00:00Z",
                    "outcome_source": source,
                    "realized_net_r": net_r,
                    "entry_model": "NEXT_M15_OPEN_WITH_DECISION_SPREAD",
                    "horizon_bars": 16,
                    "same_bar_tie_policy": "STOP_FIRST_CONSERVATIVE",
                }
            )
        payload = {
            "schema": "FX_RESEARCH_EVIDENCE_PAYLOAD_V1",
            "manifest_id": "EVIDENCE_TEST",
            "data_classes": ["FORWARD_FAILED_AUCTION_EPISODES", "FORWARD_RULE_BASELINE_OUTCOMES"],
            "candidate_episode_facts": candidates,
            "trend_location_range_context_facts": contexts,
            "rule_baseline_outcome_facts": outcomes,
        }
        payload_path = root / "EVIDENCE_TEST.payload.json.gz"
        with gzip.open(payload_path, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle)
        manifest = {
            "manifest_id": "EVIDENCE_TEST",
            "schema": "FX_RESEARCH_EVIDENCE_EXPORT_V1",
            "created_at_utc": "2026-10-13T10:00:00Z",
            "source_system": "EUR_AGENT_FORWARD_EVIDENCE",
            "instrument": "EUR_USD",
            "window_start_utc": "2026-10-13T02:00:00Z",
            "window_end_utc": "2026-10-13T10:00:00Z",
            "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
            "payload_path": payload_path.name,
            "freshness_status": "FRESH",
            "gap_status": "COMPLETE",
            "data_classes": payload["data_classes"],
        }
        manifest_path = root / "EVIDENCE_TEST.manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        register_manifest(self.connection, manifest_path)
        return manifest_path

    def test_draft_campaign_cannot_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            register_campaign(self.connection, self._campaign(root)[0])
            self._evidence(root)
            with self.assertRaisesRegex(ValueError, "explicit human approval"):
                run_campaign(self.connection, "CAMPAIGN_1", root)

    def test_approved_run_is_forward_only_episode_deduplicated_and_source_separated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registered = register_campaign(self.connection, self._campaign(root)[0])
            approve_campaign(
                self.connection,
                "CAMPAIGN_1",
                expected_payload_hash=registered["campaign_payload_hash"],
                approved_by="CAMERON",
                reason="Exact specification reviewed",
                approved_at_utc="2026-10-13T01:00:00Z",
            )
            self._evidence(root)
            first = run_campaign(self.connection, "CAMPAIGN_1", root, evaluated_at_utc="2026-10-13T11:00:00Z")
            second = run_campaign(self.connection, "CAMPAIGN_1", root, evaluated_at_utc="2026-10-13T12:00:00Z")

        self.assertTrue(first["inserted"])
        self.assertFalse(second["inserted"])
        self.assertEqual(first["independent_episode_count"], 3)
        self.assertFalse(first["outcome_sources_pooled"])
        reports = {row["outcome_source"]: row for row in first["source_reports"]}
        counterfactual = reports["FORWARD_ABSTENTION_COUNTERFACTUAL"]
        self.assertEqual(counterfactual["treatment"]["independent_episode_count"], 1)
        self.assertEqual(counterfactual["comparator"]["independent_episode_count"], 1)
        self.assertEqual(counterfactual["average_net_r_lift"], 2.0)
        self.assertTrue(counterfactual["sample_gates_met"])
        self.assertEqual(reports["FORWARD_SHADOW_ACTION"]["treatment"]["independent_episode_count"], 1)


if __name__ == "__main__":
    unittest.main()
