from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .campaigns import campaign_state
from .evidence import load_validated_package


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _family(event: dict[str, Any]) -> str:
    for key in ("mechanism_id", "candidate_family", "family_id", "setup_id", "candidate_type"):
        if event.get(key):
            return str(event[key])
    return "UNCLASSIFIED"


def _time(event: dict[str, Any]) -> str:
    for key in ("decision_time_utc", "observed_at_utc", "event_time_utc", "candidate_time_utc"):
        if event.get(key):
            return str(event[key])
    return ""


def _identity(event: dict[str, Any], instrument: str) -> str:
    for key in ("event_id", "candidate_id", "episode_id"):
        if event.get(key):
            return f"{instrument}:{event[key]}"
    return f"{instrument}:{_family(event)}:{_time(event)}"


def _metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    dated = [(event, _parse_utc(event["decision_time_utc"])) for event in events]
    dated = [(event, stamp) for event, stamp in dated if stamp is not None]
    if not dated:
        return {
            "event_count": 0,
            "observed_week_count": 0,
            "mean_events_per_week": 0.0,
            "median_events_per_week": 0.0,
            "idle_week_rate": None,
            "busiest_week_event_count": 0,
        }
    first = min(stamp for _, stamp in dated)
    last = max(stamp for _, stamp in dated)
    first_monday = first.date() - timedelta(days=first.weekday())
    last_monday = last.date() - timedelta(days=last.weekday())
    week_count = ((last_monday - first_monday).days // 7) + 1
    counts = [0 for _ in range(week_count)]
    for _, stamp in dated:
        monday = stamp.date() - timedelta(days=stamp.weekday())
        counts[(monday - first_monday).days // 7] += 1
    return {
        "event_count": len(dated),
        "observed_week_count": week_count,
        "mean_events_per_week": round(statistics.fmean(counts), 4),
        "median_events_per_week": round(float(statistics.median(counts)), 4),
        "idle_week_rate": round(sum(value == 0 for value in counts) / len(counts), 4),
        "busiest_week_event_count": max(counts),
        "window_start_utc": first.isoformat().replace("+00:00", "Z"),
        "window_end_utc": last.isoformat().replace("+00:00", "Z"),
    }


def build_portfolio_opportunity_report(connection, evidence_inbox_dir: Path) -> dict[str, Any]:
    events_by_id: dict[str, dict[str, Any]] = {}
    resolved_ids: set[str] = set()
    manifest_ids: list[str] = []
    for row in connection.execute(
        "SELECT payload_json FROM evidence_manifests WHERE usable_for_testing=1 ORDER BY manifest_id"
    ).fetchall():
        registered = json.loads(row["payload_json"])
        manifest_path = evidence_inbox_dir / f"{registered['manifest_id']}.manifest.json"
        if not manifest_path.is_file():
            matches = list(evidence_inbox_dir.glob(f"*{registered['manifest_id']}*.manifest.json"))
            if len(matches) != 1:
                continue
            manifest_path = matches[0]
        manifest, payload = load_validated_package(manifest_path)
        if manifest != registered:
            raise ValueError(f"registered evidence manifest differs from inbox copy: {manifest['manifest_id']}")
        manifest_ids.append(str(manifest["manifest_id"]))
        instrument = str(manifest.get("instrument") or "UNKNOWN")
        for key in ("candidate_episode_facts", "strategy_shadow_event_facts"):
            for event in payload.get(key, []):
                if not isinstance(event, dict):
                    continue
                decision_time = _time(event)
                if not decision_time:
                    continue
                event_id = _identity(event, instrument)
                normalized = {
                    "event_id": event_id,
                    "instrument": instrument,
                    "family": _family(event),
                    "decision_time_utc": decision_time,
                    "day_utc": decision_time[:10],
                }
                existing = events_by_id.get(event_id)
                if existing is not None and existing != normalized:
                    raise ValueError(f"conflicting immutable opportunity event: {event_id}")
                events_by_id[event_id] = normalized
        for key in ("rule_baseline_outcome_facts", "strategy_shadow_outcome_facts"):
            for outcome in payload.get(key, []):
                if not isinstance(outcome, dict):
                    continue
                reference = outcome.get("candidate_id") or outcome.get("event_id")
                if reference:
                    resolved_ids.add(f"{instrument}:{reference}")

    events = sorted(events_by_id.values(), key=lambda value: (value["decision_time_utc"], value["event_id"]))
    by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_pair[event["instrument"]].append(event)
        by_family[f"{event['instrument']}:{event['family']}"].append(event)

    family_days = {key: {event["day_utc"] for event in values} for key, values in by_family.items()}
    overlaps = []
    families = sorted(family_days)
    for index, left in enumerate(families):
        for right in families[index + 1 :]:
            intersection = family_days[left] & family_days[right]
            union = family_days[left] | family_days[right]
            if not intersection:
                continue
            overlaps.append(
                {
                    "left": left,
                    "right": right,
                    "shared_trigger_day_count": len(intersection),
                    "jaccard_trigger_day_overlap": round(len(intersection) / len(union), 4),
                }
            )
    overlaps.sort(key=lambda value: (-value["jaccard_trigger_day_overlap"], value["left"], value["right"]))

    campaigns = []
    for row in connection.execute(
        "SELECT campaign_id, payload_json FROM research_campaigns ORDER BY campaign_id"
    ).fetchall():
        campaign = json.loads(row["payload_json"])
        campaigns.append(
            {
                "campaign_id": row["campaign_id"],
                "instrument": campaign.get("instrument"),
                "mechanism_class": campaign.get("mechanism_class"),
                "state": campaign_state(connection, row["campaign_id"]),
            }
        )
    overall = _metrics(events)
    return {
        "schema": "FX_RESEARCH_PORTFOLIO_OPPORTUNITY_REPORT_V1",
        "report_scope": "RESEARCH_EVIDENCE_ONLY_NOT_EXECUTION_ELIGIBILITY",
        "interpretation": "RAW_FORWARD_CANDIDATE_CADENCE_NOT_VALIDATED_EDGE_OR_TRADE_FREQUENCY",
        "evidence_manifest_ids": manifest_ids,
        "overall": overall,
        "target": {
            "qualified_opportunities_per_week_min": 2.0,
            "qualified_opportunities_per_week_max": 3.0,
            "qualified_cadence_status": "NOT_MEASURABLE_FROM_RAW_CANDIDATES",
            "target_is_not_a_trade_quota": True,
        },
        "by_instrument": {key: _metrics(value) for key, value in sorted(by_pair.items())},
        "by_family": {key: _metrics(value) for key, value in sorted(by_family.items())},
        "resolved_event_count": sum(event["event_id"] in resolved_ids for event in events),
        "top_trigger_day_overlaps": overlaps[:50],
        "campaigns": campaigns,
        "automatic_promotion_allowed": False,
        "execution_authority": False,
    }
