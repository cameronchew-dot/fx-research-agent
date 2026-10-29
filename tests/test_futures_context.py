import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fx_research_agent.futures_context import futures_context_status, load_contract
from fx_research_agent.storage import initialize


class FuturesContextTests(unittest.TestCase):
    def test_unconfigured_contract_is_inert(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": "CME_FX_CONTEXT_CONTRACT_V1",
                        "products": [{"canonical_product": "6E", "spot_instrument": "EUR_USD"}],
                        "authority": {"context_only": True, "execution_authority": False}
                    }
                ),
                encoding="utf-8"
            )
            connection = sqlite3.connect(":memory:")
            connection.row_factory = sqlite3.Row
            initialize(connection)
            loaded = load_contract(path)
            status = futures_context_status(connection, path)
        self.assertEqual(loaded["schema"], "CME_FX_CONTEXT_CONTRACT_V1")
        self.assertEqual(status["context_status"], "UNCONFIGURED")
        self.assertFalse(status["automatic_signal_or_execution_authority"])


if __name__ == "__main__":
    unittest.main()
