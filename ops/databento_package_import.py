#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fx_research_agent.databento_package import import_package


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify and import an immutable Databento CME FX package")
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=ROOT / "data" / "external" / "databento")
    args = parser.parse_args()
    print(json.dumps(import_package(args.source_dir, args.output_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
