from __future__ import annotations

import gzip
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .campaign_reviews import latest_campaign_review
from .market_data import resolve_payload_path, validate_manifest
from .storage import canonical_json


SOURCE = "FORWARD_SEALED_MARKET_DATA"


def _parse_utc(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_payload(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def load_market_rows(connection, inbox_dir: Path, instrument: str) -> dict[str, Any]:
    candles: dict[str, dict[str, Any]] = {}
    spreads: dict[str, dict[str, Any]] = {}
    manifest_ids: list[str] = []
    for row in connection.execute(
        "SELECT payload_json FROM market_data_manifests WHERE usable_for_testing=1 ORDER BY registered_at_utc, manifest_id"
    ).fetchall():
        registered = json.loads(row["payload_json"])
        if registered.get("instrument") != instrument:
            continue
        classes = set(registered.get("data_classes") or [])
        if not classes.intersection({"COMPLETED_CANDLES", "HISTORICAL_COMPLETED_CANDLES"}):
            continue
        manifest_path = inbox_dir / f"{registered['manifest_id']}.manifest.json"
        if not manifest_path.is_file():
            matches = list(inbox_dir.glob(f"*{registered['manifest_id']}*.manifest.json"))
            if len(matches) != 1:
                raise ValueError(f"immutable market manifest unavailable: {registered['manifest_id']}")
            manifest_path = matches[0]
        manifest = validate_manifest(manifest_path)
        if manifest != registered:
            raise ValueError(f"registered market manifest differs from inbox copy: {manifest['manifest_id']}")
        payload = _load_payload(resolve_payload_path(manifest_path, manifest))
        manifest_ids.append(str(manifest["manifest_id"]))
        for candle in payload.get("completed_candles") or []:
            if candle.get("instrument") != instrument or candle.get("granularity") != "M15":
                continue
            key = str(candle.get("candle_time_utc") or "")
            if not key:
                continue
            core = {name: candle.get(name) for name in ("instrument", "granularity", "candle_time_utc", "candle_end_time_utc", "open", "high", "low", "close", "volume")}
            existing = candles.get(key)
            if existing is not None and canonical_json(existing) != canonical_json(core):
                raise ValueError(f"conflicting immutable M15 candle rewrite: {key}")
            candles[key] = core
        for sample in payload.get("spread_samples") or []:
            if sample.get("instrument") != instrument:
                continue
            key = str(sample.get("sample_time_utc") or "")
            if not key or not isinstance(sample.get("spread_pips"), (int, float)):
                continue
            existing = spreads.get(key)
            if existing is not None and canonical_json(existing) != canonical_json(sample):
                raise ValueError(f"conflicting immutable spread rewrite: {key}")
            spreads[key] = sample
    return {
        "manifest_ids": sorted(set(manifest_ids)),
        "candles": list(candles.values()),
        "spreads": list(spreads.values()),
    }


def _atr14(candles: list[dict[str, Any]], index: int) -> float | None:
    if index < 13:
        return None
    ranges = []
    for offset in range(index - 13, index + 1):
        row = candles[offset]
        previous_close = float(candles[offset - 1]["close"]) if offset else float(row["open"])
        ranges.append(max(float(row["high"]) - float(row["low"]), abs(float(row["high"]) - previous_close), abs(float(row["low"]) - previous_close)))
    return statistics.fmean(ranges)


def _latest_spread(spreads: list[dict[str, Any]], decision_time: datetime) -> float | None:
    lower = decision_time - timedelta(minutes=15)
    eligible = []
    for row in spreads:
        stamp = _parse_utc(row["sample_time_utc"])
        if not lower < stamp <= decision_time:
            continue
        if row.get("tradeable") in (0, False) or str(row.get("pricing_status") or "OK") != "OK":
            continue
        eligible.append((stamp, float(row["spread_pips"])))
    return max(eligible, default=(None, None), key=lambda item: item[0])[1]


def _outcome(
    candles: list[dict[str, Any]],
    entry_index: int,
    direction: str,
    stop_distance: float,
    target_r: float,
    horizon: int,
    spread_pips: float,
    pip_size: float,
) -> dict[str, Any] | None:
    final_index = entry_index + horizon - 1
    if entry_index >= len(candles) or final_index >= len(candles):
        return None
    for index in range(entry_index, final_index):
        if _parse_utc(candles[index + 1]["candle_time_utc"]) - _parse_utc(candles[index]["candle_time_utc"]) != timedelta(minutes=15):
            return None
    entry = float(candles[entry_index]["open"])
    sign = 1.0 if direction == "LONG" else -1.0
    stop = entry - sign * stop_distance
    target = entry + sign * target_r * stop_distance
    exit_price = float(candles[final_index]["close"])
    exit_reason = "HORIZON"
    gross_r: float | None = None
    mfe = -math.inf
    mae = math.inf
    exit_index = final_index
    for index in range(entry_index, final_index + 1):
        row = candles[index]
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        favorable = (high - entry) / stop_distance if direction == "LONG" else (entry - low) / stop_distance
        adverse = (low - entry) / stop_distance if direction == "LONG" else (entry - high) / stop_distance
        mfe = max(mfe, favorable)
        mae = min(mae, adverse)
        stop_gap = open_ <= stop if direction == "LONG" else open_ >= stop
        target_gap = open_ >= target if direction == "LONG" else open_ <= target
        stop_touch = low <= stop if direction == "LONG" else high >= stop
        target_touch = high >= target if direction == "LONG" else low <= target
        if stop_gap:
            exit_price, gross_r, exit_reason, exit_index = open_, (open_ - entry) * sign / stop_distance, "STOP_GAP", index
            break
        if target_gap:
            exit_price, gross_r, exit_reason, exit_index = target, target_r, "TARGET_GAP_CONSERVATIVE", index
            break
        if stop_touch:
            exit_price, gross_r, exit_reason, exit_index = stop, -1.0, "STOP", index
            break
        if target_touch:
            exit_price, gross_r, exit_reason, exit_index = target, target_r, "TARGET", index
            break
    if gross_r is None:
        gross_r = (exit_price - entry) * sign / stop_distance
    cost_r = spread_pips / (stop_distance / pip_size)
    return {
        "entry_time_utc": str(candles[entry_index]["candle_time_utc"]),
        "exit_time_utc": str(candles[exit_index].get("candle_end_time_utc") or candles[exit_index]["candle_time_utc"]),
        "direction": direction,
        "entry": round(entry, 8),
        "stop": round(stop, 8),
        "target": round(target, 8),
        "exit_price": round(exit_price, 8),
        "exit_reason": exit_reason,
        "gross_r": round(gross_r, 8),
        "cost_r": round(cost_r, 8),
        "net_r": round(gross_r - cost_r, 8),
        "mfe_r": round(mfe, 8),
        "mae_r": round(mae, 8),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_r"]) for row in rows]
    return {
        "priced_episode_count": len(values),
        "positive_net_r_count": sum(value > 0 for value in values),
        "positive_net_r_rate": round(sum(value > 0 for value in values) / len(values), 6) if values else None,
        "average_net_r": round(statistics.fmean(values), 6) if values else None,
        "median_net_r": round(statistics.median(values), 6) if values else None,
        "minimum_net_r": round(min(values), 6) if values else None,
        "maximum_net_r": round(max(values), 6) if values else None,
        "calendar_month_count": len({str(row["decision_time_utc"])[:7] for row in rows}),
        "small_sample": len(values) < 40,
    }


def evaluate_rows(
    candles: list[dict[str, Any]],
    spreads: list[dict[str, Any]],
    campaign: dict[str, Any],
    *,
    approval_time_utc: str,
    evaluated_at_utc: str,
) -> dict[str, Any]:
    specification = campaign["exact_specification"]
    population = campaign["population"]
    pip_size = float(population["instrument_pip_size"])
    london = ZoneInfo(population["timezone"])
    approval_time = _parse_utc(approval_time_utc)
    evaluated_at = _parse_utc(evaluated_at_utc)
    ordered = sorted(
        [row for row in candles if _parse_utc(row.get("candle_end_time_utc") or row["candle_time_utc"]) <= evaluated_at],
        key=lambda row: row["candle_time_utc"],
    )
    index_by_start = {_parse_utc(row["candle_time_utc"]): index for index, row in enumerate(ordered)}
    days: dict[Any, list[tuple[int, dict[str, Any], datetime, datetime]]] = defaultdict(list)
    for index, row in enumerate(ordered):
        start = _parse_utc(row["candle_time_utc"]).astimezone(london)
        end = _parse_utc(row.get("candle_end_time_utc") or row["candle_time_utc"]).astimezone(london)
        days[start.date()].append((index, row, start, end))
    baseline_ranges: list[tuple[Any, float]] = []
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    exclusions: dict[str, int] = defaultdict(int)
    for local_date in sorted(days):
        if local_date.weekday() >= 5:
            continue
        day_rows = days[local_date]
        range_rows = [item for item in day_rows if item[2].time() >= datetime.min.time() and item[3].hour <= 7 and (item[3].hour < 7 or item[3].minute == 0)]
        if len(range_rows) != int(specification["required_completed_range_bars"]):
            exclusions["INCOMPLETE_RANGE_WINDOW"] += 1
            continue
        range_high = max(float(item[1]["high"]) for item in range_rows)
        range_low = min(float(item[1]["low"]) for item in range_rows)
        range_size = range_high - range_low
        prior = [value for day, value in baseline_ranges if day < local_date][-int(specification["compression_baseline_completed_london_days"]):]
        baseline_ranges.append((local_date, range_size))
        if len(prior) < int(specification["compression_baseline_completed_london_days"]):
            continue
        ratio = range_size / statistics.median(prior) if statistics.median(prior) > 0 else math.inf
        decision_rows = [item for item in day_rows if (item[3].hour > 7 or (item[3].hour == 7 and item[3].minute > 0)) and (item[3].hour < 10 or (item[3].hour == 10 and item[3].minute == 0))]
        trigger = None
        for index, row, _, end_local in decision_rows:
            atr = _atr14(ordered, index)
            if atr is None:
                continue
            pad = max(float(specification["breakout_pad_pips_minimum"]) * pip_size, float(specification["breakout_pad_atr14_fraction"]) * atr)
            close = float(row["close"])
            if close > range_high + pad:
                trigger = (index, row, end_local, "LONG")
                break
            if close < range_low - pad:
                trigger = (index, row, end_local, "SHORT")
                break
        if trigger is None:
            continue
        signal_index, signal, _, direction = trigger
        decision_time = _parse_utc(signal.get("candle_end_time_utc") or signal["candle_time_utc"])
        if decision_time <= approval_time:
            exclusions["PREAPPROVAL_TRIGGER"] += 1
            continue
        spread_pips = _latest_spread(spreads, decision_time)
        if spread_pips is None:
            exclusions["NO_TIMESTAMP_VALID_SPREAD"] += 1
            continue
        entry_time = decision_time
        entry_index = index_by_start.get(entry_time)
        if entry_index is None:
            exclusions["NO_CONTIGUOUS_NEXT_M15_OPEN"] += 1
            continue
        entry = float(ordered[entry_index]["open"])
        midpoint = (range_high + range_low) / 2.0
        midpoint_distance = abs(entry - midpoint)
        stop_distance = max(float(specification["minimum_stop_pips"]) * pip_size, midpoint_distance)
        common = {
            "target_r": float(specification["target_r"]),
            "horizon": int(specification["maximum_horizon_m15_bars"]),
            "spread_pips": spread_pips,
            "pip_size": pip_size,
        }
        primary = _outcome(ordered, entry_index, direction, stop_distance, **common)
        if primary is None:
            exclusions["UNRESOLVED_TREATMENT_HORIZON"] += 1
            continue
        event = {
            "episode_id": f"{campaign['campaign_id']}:{local_date.isoformat()}",
            "decision_time_utc": _iso(decision_time),
            "london_trading_date": local_date.isoformat(),
            "range_ratio": round(ratio, 8),
            "range_high": round(range_high, 8),
            "range_low": round(range_low, 8),
            "observed_spread_pips": round(spread_pips, 6),
        }
        if ratio <= float(specification["compression_ratio_maximum"]):
            opposite_direction = "SHORT" if direction == "LONG" else "LONG"
            opposite = _outcome(ordered, entry_index, opposite_direction, stop_distance, **common)
            delayed = _outcome(ordered, entry_index + 1, direction, stop_distance, **common)
            if opposite is None or delayed is None:
                exclusions["UNRESOLVED_PAIRED_CONTROL_HORIZON"] += 1
                continue
            records["TREATMENT"].append({**event, **primary})
            records["OPPOSITE_DIRECTION_SAME_EVENT"].append({**event, **opposite})
            records["ONE_COMPLETED_M15_SHIFT_SAME_DIRECTION"].append({**event, **delayed})
        else:
            records["UNCOMPRESSED_RANGE_COMPLEMENT"].append({**event, **primary})
    summaries = {cohort: _summary(records.get(cohort, [])) for cohort in (
        "TREATMENT", "OPPOSITE_DIRECTION_SAME_EVENT", "ONE_COMPLETED_M15_SHIFT_SAME_DIRECTION", "UNCOMPRESSED_RANGE_COMPLEMENT"
    )}
    treatment_average = summaries["TREATMENT"]["average_net_r"]
    lifts = {
        cohort: (round(treatment_average - summary["average_net_r"], 6) if treatment_average is not None and summary["average_net_r"] is not None else None)
        for cohort, summary in summaries.items() if cohort != "TREATMENT"
    }
    minimum = int(campaign["review_gates"]["minimum_resolved_independent_treatment_episodes"])
    gates_met = (
        summaries["TREATMENT"]["priced_episode_count"] >= minimum
        and treatment_average is not None and treatment_average > 0
        and summaries["TREATMENT"]["median_net_r"] is not None and summaries["TREATMENT"]["median_net_r"] >= 0
        and all(value is not None and value > 0 for value in lifts.values())
    )
    return {
        "records": dict(records),
        "summaries": summaries,
        "average_net_r_lift_over_controls": lifts,
        "exclusions": dict(sorted(exclusions.items())),
        "sample_gates_met": gates_met,
        "review_status": "READY_FOR_HUMAN_REVIEW" if gates_met else "ACCRUING_NO_CONCLUSION",
    }


def build_market_evaluation(
    connection,
    campaign: dict[str, Any],
    experiment: dict[str, Any],
    market_inbox_dir: Path,
    *,
    evaluated_at_utc: str,
) -> dict[str, Any]:
    market = load_market_rows(connection, market_inbox_dir, campaign["instrument"])
    result = evaluate_rows(
        market["candles"],
        market["spreads"],
        campaign,
        approval_time_utc=str(experiment["approved_at_utc"]),
        evaluated_at_utc=evaluated_at_utc,
    )
    report = {
        "outcome_source": SOURCE,
        "treatment": result["summaries"]["TREATMENT"],
        "controls": {key: value for key, value in result["summaries"].items() if key != "TREATMENT"},
        "average_net_r_lift_over_controls": result["average_net_r_lift_over_controls"],
        "exclusions": result["exclusions"],
        "sample_gates_met": result["sample_gates_met"],
        "result_interpretation": result["review_status"],
    }
    review = latest_campaign_review(connection, campaign["campaign_id"])
    return {
        "schema": "FX_RESEARCH_EXPERIMENT_EVALUATION_V1",
        "campaign_id": campaign["campaign_id"],
        "experiment_id": experiment["experiment_id"],
        "campaign_payload_hash": experiment["campaign_payload_hash"],
        "predeclared_at_utc": experiment["approved_at_utc"],
        "evaluated_at_utc": evaluated_at_utc,
        "evidence_cutoff_utc": evaluated_at_utc,
        "confirmatory_cutover_policy": "NEW_CAMPAIGN_REQUIRED_AFTER_DEVELOPMENT_REVIEW",
        "campaign_review": review,
        "confirmatory_cutover_at_utc": None,
        "legacy_preapproval_evidence_excluded": True,
        "evidence_manifest_ids": [],
        "market_data_manifest_ids": market["manifest_ids"],
        "eligible_candidate_count_before_episode_deduplication": (
            result["summaries"]["TREATMENT"]["priced_episode_count"]
            + result["summaries"]["UNCOMPRESSED_RANGE_COMPLEMENT"]["priced_episode_count"]
        ),
        "unique_episode_id_count": (
            result["summaries"]["TREATMENT"]["priced_episode_count"]
            + result["summaries"]["UNCOMPRESSED_RANGE_COMPLEMENT"]["priced_episode_count"]
        ),
        "independent_episode_count": result["summaries"]["TREATMENT"]["priced_episode_count"],
        "independence_policy": campaign["independence_unit"]["unit"],
        "outcome_sources_pooled": False,
        "source_reports": [report],
        "confirmatory_independent_episode_count": 0,
        "confirmatory_source_reports": [],
        "review_status": result["review_status"],
        "automatic_promotion_allowed": False,
        "downstream_authority": "NONE",
    }
