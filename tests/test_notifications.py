import tempfile
import unittest
import unittest.mock
from pathlib import Path

from fx_research_agent.notifications import (
    notification_status,
    notify_gate_crossings,
    notify_ingest_failures,
    notify_once,
    notify_proposals_for_review,
)
from fx_research_agent.storage import connect, insert_immutable


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.connection = connect(Path(self.temporary.name) / "research.sqlite3")
        self.messages = []

    def tearDown(self):
        self.connection.close()
        self.temporary.cleanup()

    def transport(self, _url, message):
        self.messages.append(message)

    def test_notify_once_deduplicates_only_after_success(self):
        first = notify_once(
            self.connection,
            event_type="SAMPLE_GATE_REACHED",
            subject_id="CAMPAIGN_1",
            message="ready",
            webhook_url="https://example.invalid/webhook",
            transport=self.transport,
            sent_at_utc="2026-10-13T00:00:00Z",
        )
        second = notify_once(
            self.connection,
            event_type="SAMPLE_GATE_REACHED",
            subject_id="CAMPAIGN_1",
            message="ready",
            webhook_url="https://example.invalid/webhook",
            transport=self.transport,
        )
        self.assertEqual(first["status"], "SENT")
        self.assertEqual(second["status"], "ALREADY_SENT")
        self.assertEqual(self.messages, ["ready"])

    def test_delivery_failure_does_not_record_receipt(self):
        def fail(_url, _message):
            raise RuntimeError("offline")

        result = notify_once(
            self.connection,
            event_type="INGEST_FAILED",
            subject_id="manifest",
            message="failed",
            webhook_url="https://example.invalid/webhook",
            transport=fail,
        )
        self.assertEqual(result["status"], "DELIVERY_FAILED")
        self.assertEqual(notification_status(self.connection)["sent_count"], 0)

    def test_only_gate_crossing_notifies(self):
        result = {
            "campaigns": [
                {"campaign_id": "C1", "sample_gate_crossed_now": False, "independent_episode_count": 29},
                {"campaign_id": "C2", "sample_gate_crossed_now": True, "independent_episode_count": 30},
            ]
        }
        with unittest.mock.patch.dict("os.environ", {"FX_RESEARCH_DISCORD_WEBHOOK_URL": "test"}):
            with unittest.mock.patch("fx_research_agent.notifications._discord_transport", self.transport):
                notices = notify_gate_crossings(self.connection, result)
        self.assertEqual(len(notices), 1)
        self.assertIn("C2", self.messages[0])

    def test_ingest_failure_and_new_proposal_are_low_noise(self):
        with unittest.mock.patch.dict("os.environ", {"FX_RESEARCH_DISCORD_WEBHOOK_URL": "test"}):
            with unittest.mock.patch("fx_research_agent.notifications._discord_transport", self.transport):
                ingest = notify_ingest_failures(
                    self.connection,
                    "MARKET_DATA",
                    {"rejected": [{"manifest": "/tmp/bad.json", "error": "bad hash"}]},
                )
                insert_immutable(
                    self.connection,
                    "hypotheses",
                    "hypothesis_id",
                    "H1",
                    {"hypothesis_id": "H1", "mechanism_class": "LIQUIDITY", "statement": "test"},
                    {
                        "source_repo": "test",
                        "source_commit": "test",
                        "source_path": "test",
                        "imported_at_utc": "2026-10-13T00:00:00Z",
                    },
                )
                proposal = notify_proposals_for_review(
                    self.connection,
                    {"results": [{"status": "ACCEPTED_PROPOSED", "hypothesis_id": "H1"}]},
                )
        self.assertEqual(ingest[0]["status"], "SENT")
        self.assertEqual(proposal[0]["status"], "SENT")
        self.assertEqual(len(self.messages), 2)


if __name__ == "__main__":
    unittest.main()
