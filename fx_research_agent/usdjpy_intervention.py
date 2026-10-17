from __future__ import annotations

import csv
import gzip
import math
import statistics
from pathlib import Path
from typing import Any


def load_spot(path: Path) -> tuple[list[str], dict[str, float]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    dates = [row["date"] for row in rows]
    return dates, {row["date"]: float(row["usd_jpy"]) for row in rows}


def load_events(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [{**row, "policy_direction_usdjpy": int(row["policy_direction_usdjpy"]), "amount_100m_yen": float(row["amount_100m_yen"])} for row in csv.DictReader(handle)]


def build_episodes(dates: list[str], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    position = {date: index for index, date in enumerate(dates)}
    usable = [event for event in events if event["date"] in position]
    episodes: list[dict[str, Any]] = []
    for event in usable:
        direction = event["policy_direction_usdjpy"]
        if not episodes or episodes[-1]["direction"] != direction or position[event["date"]] - episodes[-1]["last_index"] > 5:
            episodes.append({"start_date": event["date"], "end_date": event["date"], "direction": direction, "first_index": position[event["date"]], "last_index": position[event["date"]], "event_count": 1, "amount_100m_yen": event["amount_100m_yen"]})
        else:
            episodes[-1]["end_date"] = event["date"]
            episodes[-1]["last_index"] = position[event["date"]]
            episodes[-1]["event_count"] += 1
            episodes[-1]["amount_100m_yen"] += event["amount_100m_yen"]
    return episodes


def _episode_return(episode: dict[str, Any], dates: list[str], prices: dict[str, float], cost_bps: float, shift: int = 0, intervention_dates: set[str] | None = None) -> dict[str, Any] | None:
    first = episode["first_index"] + shift
    last = episode["last_index"] + shift
    entry, exit_ = first - 1, last + 5
    if entry < 0 or exit_ >= len(dates):
        return None
    if shift and intervention_dates and any(dates[index] in intervention_dates for index in range(first, exit_ + 1)):
        return None
    gross = episode["direction"] * math.log(prices[dates[exit_]] / prices[dates[entry]])
    return {"episode_start": episode["start_date"], "episode_end": episode["end_date"], "direction": episode["direction"], "event_count": episode["event_count"], "amount_100m_yen": episode["amount_100m_yen"], "entry_date": dates[entry], "exit_date": dates[exit_], "gross_policy_aligned_return": gross, "cost_return": cost_bps / 10000, "net_policy_aligned_return": gross - cost_bps / 10000}


def rows_for(episodes: list[dict[str, Any]], dates: list[str], prices: dict[str, float], cost_bps: float, control: str = "PRIMARY", intervention_dates: set[str] | None = None) -> list[dict[str, Any]]:
    result = []
    for episode in episodes:
        selected = episode if control != "OPPOSITE" else {**episode, "direction": -episode["direction"]}
        shift = 60 if control == "SHIFT60" else 120 if control == "SHIFT120" else 0
        row = _episode_return(selected, dates, prices, cost_bps, shift, intervention_dates)
        if row:
            result.append(row)
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [row["net_policy_aligned_return"] for row in rows]
    return {"episode_count": len(values), "average_net_policy_aligned_return": statistics.fmean(values) if values else None, "median_net_policy_aligned_return": statistics.median(values) if values else None, "positive_rate": sum(value > 0 for value in values) / len(values) if values else None}


def evaluate(spot_path: Path, event_path: Path, cost_bps: float = 5.0) -> dict[str, Any]:
    dates, prices = load_spot(spot_path)
    events = load_events(event_path)
    episodes = build_episodes(dates, events)
    intervention_dates = {event["date"] for event in events}
    primary = rows_for(episodes, dates, prices, cost_bps, intervention_dates=intervention_dates)
    first, second = int(len(primary) * 0.6), int(len(primary) * 0.8)
    partitions = {"development": primary[:first], "chronological_oos": primary[first:second], "dated_confirmation": primary[second:]}
    controls = {name.lower(): rows_for(episodes, dates, prices, cost_bps, name, intervention_dates) for name in ("OPPOSITE", "SHIFT60", "SHIFT120")}
    dated = summarize(partitions["dated_confirmation"])
    dated_starts = {row["episode_start"] for row in partitions["dated_confirmation"]}
    control_dated = {name: summarize([row for row in rows if row["episode_start"] in dated_starts]) for name, rows in controls.items()}
    edges = {name: (dated["average_net_policy_aligned_return"] - summary["average_net_policy_aligned_return"] if summary["average_net_policy_aligned_return"] is not None else None) for name, summary in control_dated.items()}
    return {"schema": "FX_USDJPY_MOF_INTERVENTION_EPISODE_RESULT_V1", "study": "POLICY_ALIGNED_RETURN_PRE_EPISODE_TO_FIVE_DAYS_POST_EPISODE", "publication_constraint": "RETROSPECTIVE_NON_ACTIONABLE_EVENT_LABELS", "cost_model": {"hypothetical_round_trip_bps": cost_bps}, "official_event_count": len(events), "independent_episode_count": len(episodes), "complete_episode_count": len(primary), "window_start": primary[0]["episode_start"] if primary else None, "window_end": primary[-1]["exit_date"] if primary else None, "partitions": {name: summarize(rows) for name, rows in partitions.items()}, "controls_dated_confirmation": control_dated, "dated_control_edge": edges, "rows": primary}
