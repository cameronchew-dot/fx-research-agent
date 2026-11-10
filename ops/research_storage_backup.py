#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "fx_research_agent.sqlite3"
DEFAULT_BACKUP_DIR = ROOT / "archives" / "vps_runtime_backups"


def backup_database(
    db_path: Path,
    backup_dir: Path,
    *,
    retain: int = 3,
    now: datetime | None = None,
) -> dict[str, object]:
    if retain < 1:
        raise ValueError("retain must be at least 1")
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"fx_research_agent_{timestamp}.sqlite3"
    temporary = destination.with_suffix(".sqlite3.tmp")
    temporary.unlink(missing_ok=True)

    try:
        with sqlite3.connect(db_path) as source, sqlite3.connect(temporary) as target:
            source.backup(target)
        with sqlite3.connect(temporary) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"backup integrity check failed: {integrity}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)

    backups = sorted(backup_dir.glob("fx_research_agent_*.sqlite3"), reverse=True)
    for stale in backups[retain:]:
        stale.unlink()
    retained = sorted(backup_dir.glob("fx_research_agent_*.sqlite3"), reverse=True)
    return {
        "schema": "FX_RESEARCH_STORAGE_BACKUP_V1",
        "status": "PASS",
        "source": str(db_path),
        "backup": str(destination),
        "integrity": "ok",
        "retain": retain,
        "retained_backup_count": len(retained),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verified FX research SQLite backup")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--retain", type=int, default=3)
    args = parser.parse_args()
    print(
        json.dumps(
            backup_database(args.db, args.backup_dir, retain=args.retain),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
