#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fx_research_agent.cme_forward_context import build_pack, write_pack


DEFAULT_BUILDS = {
    "6E": "B4E29C6EA1D8FC3D4AA7",
    "6J": "EC7B572F0FADDCE3ADA3",
    "6A": "26875F02A6C758377359",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export causal CME context for a forward-only receiving agent"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "exports" / "cme_forward_context" / "latest.json",
    )
    parser.add_argument("--product", action="append", choices=tuple(DEFAULT_BUILDS))
    args = parser.parse_args()
    products = args.product or list(DEFAULT_BUILDS)
    payload = build_pack(
        ROOT,
        builds={product: DEFAULT_BUILDS[product] for product in products},
    )
    write_pack(args.output, payload)
    print(json.dumps({
        "status": "EXPORTED",
        "output": str(args.output),
        "snapshot_count": len(payload["snapshots"]),
        "latest_available_at_utc": max(
            item["available_at_utc"] for item in payload["snapshots"]
        ),
        "execution_authority": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
