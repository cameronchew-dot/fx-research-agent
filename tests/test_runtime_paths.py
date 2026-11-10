import unittest
from pathlib import Path

from ops.research_supervisor import sibling_repo_root


class RuntimePathTests(unittest.TestCase):
    def test_sibling_repository_path_uses_runtime_root(self):
        runtime_root = Path("/srv/fx-runtime")

        self.assertEqual(
            sibling_repo_root("eur_bot", runtime_root=runtime_root),
            runtime_root / "eur_bot",
        )
        self.assertEqual(
            sibling_repo_root("eur_agent", runtime_root=runtime_root),
            runtime_root / "eur_agent",
        )


if __name__ == "__main__":
    unittest.main()
