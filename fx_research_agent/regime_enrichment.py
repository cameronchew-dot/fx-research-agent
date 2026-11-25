from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .evidence import load_validated_package
from .market_data import resolve_payload_path, validate_manifest
from .storage import canonical_json


MODEL_CONTRACT = {
    "schema": "FX_CAUSAL_REGIME_REPLAY_CONTRACT_V1",
    "markov": {
        "granularity": "M15",
        "maximum_observations": 500,
        "direction_lookback_bars": 4,
        "range_lookback_bars": 20,
    },
    "hmm": {
        "granularity": "M15",
        "maximum_observations": 500,
        "minimum_observations": 96,
        "state_count": 4,
        "rolling_baseline_bars": 32,
        "implementation": "DETERMINISTIC_KMEANS_TRANSITION_VITERBI_BASELINE_V1",
    },
    "garch": {
        "granularity": "H1",
        "maximum_observations": 500,
        "minimum_closes": 60,
        "alpha": 0.05,
        "beta": 0.94,
    },
    "candle_cutoff": "CANDLE_END_TIME_LE_DECISION_TIME",
    "historical_result_authority": "EXPLORATORY_ONLY_NOT_FORWARD_CONFIRMATION",
}

PIP_SIZE_BY_INSTRUMENT = {
    "EUR_USD": 0.0001,
    "GBP_USD": 0.0001,
    "AUD_USD": 0.0001,
    "USD_JPY": 0.01,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _load_payload(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_path(inbox_dir: Path, manifest_id: str) -> Path:
    direct = inbox_dir / f"{manifest_id}.manifest.json"
    if direct.is_file():
        return direct
    matches = list(inbox_dir.glob(f"*{manifest_id}*.manifest.json"))
    if len(matches) != 1:
        raise ValueError(f"immutable manifest unavailable: {manifest_id}")
    return matches[0]


def _evidence_events(connection, evidence_inbox: Path) -> list[dict[str, str]]:
    events: dict[tuple[str, str], dict[str, str]] = {}
    for row in connection.execute(
        "SELECT payload_json FROM evidence_manifests "
        "WHERE usable_for_testing=1 ORDER BY registered_at_utc, manifest_id"
    ).fetchall():
        manifest = json.loads(row["payload_json"])
        manifest_path = _manifest_path(evidence_inbox, str(manifest["manifest_id"]))
        registered, payload = load_validated_package(manifest_path)
        if registered != manifest:
            raise ValueError(
                f"registered evidence manifest differs from inbox copy: {manifest['manifest_id']}"
            )
        for population, records, identifier in (
            (
                "ORIGINAL_FAILED_AUCTION_CANDIDATE",
                payload.get("candidate_episode_facts") or [],
                "candidate_id",
            ),
            (
                "STRATEGY_SHADOW_EVENT",
                payload.get("strategy_shadow_event_facts") or [],
                "event_id",
            ),
        ):
            for record in records:
                source_id = str(record.get(identifier) or "")
                decision = str(record.get("decision_time_utc") or "")
                instrument = str(record.get("instrument") or "")
                if not source_id or not decision or not instrument:
                    continue
                key = (population, source_id)
                normalized = {
                    "source_population": population,
                    "source_id": source_id,
                    "instrument": instrument,
                    "decision_time_utc": decision,
                }
                existing = events.get(key)
                if existing is not None and canonical_json(existing) != canonical_json(
                    normalized
                ):
                    raise ValueError(f"conflicting immutable signal rewrite: {key}")
                events[key] = normalized
    return sorted(
        events.values(),
        key=lambda row: (
            row["decision_time_utc"],
            row["source_population"],
            row["source_id"],
        ),
    )


def _load_candles(
    connection,
    market_inbox: Path,
    instruments: set[str],
    earliest_decision: datetime,
    latest_decision: datetime,
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, Any]]:
    lookback_start = earliest_decision - timedelta(days=35)
    candles: dict[tuple[str, str, str], dict[str, Any]] = {}
    sources: dict[str, dict[str, Any]] = {}
    for row in connection.execute(
        "SELECT payload_json FROM market_data_manifests "
        "WHERE usable_for_testing=1 ORDER BY registered_at_utc, manifest_id"
    ).fetchall():
        registered = json.loads(row["payload_json"])
        instrument = str(registered.get("instrument") or "")
        if instrument not in instruments:
            continue
        classes = set(registered.get("data_classes") or [])
        if not classes.intersection(
            {"COMPLETED_CANDLES", "HISTORICAL_COMPLETED_CANDLES"}
        ):
            continue
        window_start = parse_utc(str(registered["window_start_utc"]))
        window_end = parse_utc(str(registered["window_end_utc"]))
        if window_start > latest_decision or window_end < lookback_start:
            continue
        manifest_id = str(registered["manifest_id"])
        manifest_path = _manifest_path(market_inbox, manifest_id)
        manifest = validate_manifest(manifest_path)
        if manifest != registered:
            raise ValueError(
                f"registered market manifest differs from inbox copy: {manifest_id}"
            )
        payload = _load_payload(resolve_payload_path(manifest_path, manifest))
        sources[manifest_id] = {
            "manifest_id": manifest_id,
            "payload_sha256": str(manifest["payload_sha256"]),
            "instrument": instrument,
            "window_start_utc": str(manifest["window_start_utc"]),
            "window_end_utc": str(manifest["window_end_utc"]),
        }
        for candle in payload.get("completed_candles") or []:
            granularity = str(candle.get("granularity") or "")
            if candle.get("instrument") != instrument or granularity not in {
                "M15",
                "H1",
            }:
                continue
            end_time = str(
                candle.get("candle_end_time_utc")
                or candle.get("end_time_utc")
                or ""
            )
            if not end_time:
                continue
            end = parse_utc(end_time)
            if end < lookback_start or end > latest_decision:
                continue
            core = {
                "instrument": instrument,
                "granularity": granularity,
                "end_time_utc": end_time,
                "open": candle.get("open"),
                "high": candle.get("high"),
                "low": candle.get("low"),
                "close": candle.get("close"),
                "volume": candle.get("volume"),
            }
            key = (instrument, granularity, end_time)
            existing = candles.get(key)
            if existing is not None and canonical_json(existing) != canonical_json(core):
                raise ValueError(f"conflicting immutable completed candle: {key}")
            candles[key] = core
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for instrument in instruments:
        for granularity in ("M15", "H1"):
            grouped[(instrument, granularity)] = sorted(
                [
                    candle
                    for (source_instrument, source_granularity, _), candle in candles.items()
                    if source_instrument == instrument
                    and source_granularity == granularity
                ],
                key=lambda item: item["end_time_utc"],
            )
    source_rows = [sources[key] for key in sorted(sources)]
    return grouped, {
        "manifest_count": len(source_rows),
        "manifests": source_rows,
        "source_manifest_set_sha256": hashlib.sha256(
            canonical_json(source_rows).encode("utf-8")
        ).hexdigest(),
        "lookback_start_utc": lookback_start.isoformat().replace("+00:00", "Z"),
        "latest_decision_utc": latest_decision.isoformat().replace("+00:00", "Z"),
    }


def _session_bucket(value: datetime) -> str:
    hour = value.astimezone(timezone.utc).hour
    if 0 <= hour < 7:
        return "ASIA"
    if 7 <= hour < 12:
        return "LONDON"
    if 12 <= hour < 16:
        return "LONDON_NY_OVERLAP"
    if 16 <= hour < 21:
        return "NY_AFTERNOON"
    return "ROLLOVER_LATE"


def _markov(rows: list[dict[str, Any]], pip_size: float) -> dict[str, Any]:
    states: list[str] = []
    for index in range(20, len(rows)):
        current = rows[index]
        previous = rows[index - 4]
        delta = (float(current["close"]) - float(previous["close"])) / pip_size
        direction = "UP" if delta >= 2.0 else "DOWN" if delta <= -2.0 else "FLAT"
        ranges = [
            (float(row["high"]) - float(row["low"])) / pip_size
            for row in rows[index - 20 : index]
        ]
        baseline = statistics.fmean(ranges)
        current_range = (
            float(current["high"]) - float(current["low"])
        ) / pip_size
        ratio = current_range / baseline if baseline > 0 else 1.0
        volatility = (
            "EXPANDING"
            if ratio >= 1.25
            else "COMPRESSED"
            if ratio <= 0.75
            else "NORMAL"
        )
        states.append(
            f"{_session_bucket(parse_utc(current['end_time_utc']))}|"
            f"{direction}|{volatility}"
        )
    if not states:
        return {"status": "UNAVAILABLE", "state_id": None, "observation_count": 0}
    current = states[-1]
    outgoing = [right for left, right in zip(states, states[1:]) if left == current]
    persistence = (
        sum(value == current for value in outgoing) / len(outgoing)
        if outgoing
        else None
    )
    return {
        "status": "READY_HISTORICAL_CAUSAL",
        "state_id": current,
        "observation_count": len(states),
        "source_state_transition_count": len(outgoing),
        "persistence_probability": (
            round(persistence, 4) if persistence is not None else None
        ),
    }


def _hmm_feature_rows(
    rows: list[dict[str, Any]], pip_size: float, rolling_window: int = 32
) -> list[dict[str, Any]]:
    closes: list[float] = []
    ranges: list[float] = []
    volumes: list[float] = []
    features: list[dict[str, Any]] = []
    for row in rows:
        close = float(row["close"])
        candle_range = (float(row["high"]) - float(row["low"])) / pip_size
        volume = float(row.get("volume") or 0.0)
        baseline_range = (
            statistics.median(ranges[-rolling_window:]) if ranges else candle_range
        )
        baseline_volume = (
            statistics.median(volumes[-rolling_window:]) if volumes else volume
        )
        delta = 0.0 if not closes else (close - closes[-1]) / pip_size
        range_ratio = candle_range / baseline_range if baseline_range > 0 else 1.0
        volume_ratio = volume / baseline_volume if baseline_volume > 0 else 1.0
        features.append(
            {
                "vector": [delta, range_ratio, volume_ratio],
                "raw": {
                    "delta_pips": delta,
                    "range_ratio": range_ratio,
                    "volume_ratio": volume_ratio,
                },
            }
        )
        closes.append(close)
        ranges.append(candle_range)
        volumes.append(volume)
    return features


def _squared_distance(left: list[float], right: list[float]) -> float:
    return sum((a - b) ** 2 for a, b in zip(left, right))


def _hmm_sequence(
    vectors: list[list[float]], state_count: int = 4
) -> tuple[list[int], list[int]]:
    dimensions = len(vectors[0])
    means = [
        statistics.fmean(row[index] for row in vectors)
        for index in range(dimensions)
    ]
    stds = []
    for index in range(dimensions):
        variance = statistics.fmean(
            (row[index] - means[index]) ** 2 for row in vectors
        )
        stds.append(math.sqrt(variance) or 1.0)
    scaled = [
        [(row[index] - means[index]) / stds[index] for index in range(dimensions)]
        for row in vectors
    ]
    states = min(max(2, state_count), len(scaled))
    centroids = [
        scaled[int((len(scaled) - 1) * index / max(1, states - 1))][:]
        for index in range(states)
    ]
    assignments = [0] * len(scaled)
    for _ in range(20):
        changed = False
        for index, vector in enumerate(scaled):
            selected = min(
                range(states),
                key=lambda state: _squared_distance(vector, centroids[state]),
            )
            changed = changed or selected != assignments[index]
            assignments[index] = selected
        grouped = [[] for _ in range(states)]
        for assignment, vector in zip(assignments, scaled):
            grouped[assignment].append(vector)
        for state, group in enumerate(grouped):
            if group:
                centroids[state] = [
                    statistics.fmean(row[index] for row in group)
                    for index in range(dimensions)
                ]
        if not changed:
            break
    transitions = [[1.0 for _ in range(states)] for _ in range(states)]
    for left, right in zip(assignments, assignments[1:]):
        transitions[left][right] += 1.0
    transitions = [[value / sum(row) for value in row] for row in transitions]
    variances = []
    for state in range(states):
        distances = [
            _squared_distance(vector, centroids[state])
            for vector, assignment in zip(scaled, assignments)
            if assignment == state
        ]
        variances.append(
            max(statistics.fmean(distances) if distances else 1.0, 0.05)
        )
    scores = [
        -math.log(states)
        - _squared_distance(scaled[0], centroids[state]) / (2.0 * variances[state])
        for state in range(states)
    ]
    paths = [[state] for state in range(states)]
    for vector in scaled[1:]:
        next_scores: list[float] = []
        next_paths: list[list[int]] = []
        for state in range(states):
            emission = -_squared_distance(vector, centroids[state]) / (
                2.0 * variances[state]
            )
            options = [
                (
                    scores[previous]
                    + math.log(max(transitions[previous][state], 1e-9))
                    + emission,
                    paths[previous] + [state],
                )
                for previous in range(states)
            ]
            best_score, best_path = max(options, key=lambda item: item[0])
            next_scores.append(best_score)
            next_paths.append(best_path)
        scores, paths = next_scores, next_paths
    return max(zip(scores, paths), key=lambda item: item[0])[1], assignments


def _hmm(rows: list[dict[str, Any]], pip_size: float) -> dict[str, Any]:
    features = _hmm_feature_rows(rows, pip_size)
    if len(features) < 96:
        return {
            "status": "UNAVAILABLE",
            "state_id": None,
            "observation_count": len(features),
        }
    hidden, assignments = _hmm_sequence([row["vector"] for row in features])
    current_state = hidden[-1]
    grouped = [
        row["raw"]
        for row, assignment in zip(features, assignments)
        if assignment == current_state
    ]
    delta = statistics.fmean(row["delta_pips"] for row in grouped)
    range_ratio = statistics.fmean(row["range_ratio"] for row in grouped)
    volume_ratio = statistics.fmean(row["volume_ratio"] for row in grouped)
    direction = "UP" if delta > 0.35 else "DOWN" if delta < -0.35 else "FLAT"
    volatility = (
        "EXPANDING"
        if range_ratio >= 1.25
        else "COMPRESSED"
        if range_ratio <= 0.8
        else "NORMAL"
    )
    participation = (
        "HIGHVOL"
        if volume_ratio >= 1.25
        else "THINVOL"
        if volume_ratio <= 0.8
        else "NORMALVOL"
    )
    return {
        "status": "READY_HISTORICAL_CAUSAL_RESEARCH_ONLY",
        "state_id": f"HMM_{direction}_{volatility}_{participation}",
        "hidden_state": current_state,
        "observation_count": len(features),
    }


def _garch(rows: list[dict[str, Any]], pip_size: float) -> dict[str, Any]:
    closes = [float(row["close"]) for row in rows if float(row["close"]) > 0]
    if len(closes) < 60:
        return {
            "status": "UNAVAILABLE",
            "volatility_state": None,
            "observation_count": len(closes),
        }
    returns = [
        100.0 * math.log(right / left) for left, right in zip(closes, closes[1:])
    ]
    initial = statistics.fmean(value * value for value in returns[:50])
    alpha, beta = 0.05, 0.94
    omega = max(initial * (1.0 - alpha - beta), 1e-10)
    variance = max(initial, 1e-10)
    forecasts = []
    for value in returns:
        variance = max(omega + alpha * value * value + beta * variance, 1e-10)
        forecasts.append(math.sqrt(variance))
    latest = forecasts[-1]
    percentile = sum(value <= latest for value in forecasts) / len(forecasts)
    state = (
        "LOW"
        if percentile < 0.25
        else "NORMAL"
        if percentile < 0.75
        else "HIGH"
        if percentile < 0.9
        else "EXTREME"
    )
    return {
        "status": "READY_HISTORICAL_CAUSAL",
        "volatility_state": state,
        "forecast_sigma_pips": round(closes[-1] * latest / 100.0 / pip_size, 3),
        "volatility_percentile": round(percentile, 4),
        "observation_count": len(returns),
    }


def _history_as_of(
    rows: list[dict[str, Any]], ends: list[datetime], decision: datetime
) -> list[dict[str, Any]]:
    index = bisect.bisect_right(ends, decision)
    return rows[max(0, index - 500) : index]


def build_regime_enrichment(
    connection,
    evidence_inbox: Path,
    market_inbox: Path,
) -> dict[str, Any]:
    events = _evidence_events(connection, evidence_inbox)
    generated = utc_now()
    contract_hash = hashlib.sha256(
        canonical_json(MODEL_CONTRACT).encode("utf-8")
    ).hexdigest()
    if not events:
        return {
            "schema": "FX_SIGNAL_REGIME_ENRICHMENT_V1",
            "generated_at_utc": generated,
            "model_contract": MODEL_CONTRACT,
            "model_contract_sha256": contract_hash,
            "rows": [],
            "row_count": 0,
            "authority": "EXPLORATORY_HISTORICAL_CAUSAL_ONLY",
        }
    decisions = [parse_utc(row["decision_time_utc"]) for row in events]
    instruments = {row["instrument"] for row in events}
    candles, sources = _load_candles(
        connection,
        market_inbox,
        instruments,
        min(decisions),
        max(decisions),
    )
    timelines = {
        key: [parse_utc(row["end_time_utc"]) for row in values]
        for key, values in candles.items()
    }
    rows = []
    status_counts: dict[str, int] = defaultdict(int)
    for event in events:
        instrument = event["instrument"]
        decision = parse_utc(event["decision_time_utc"])
        pip_size = PIP_SIZE_BY_INSTRUMENT.get(instrument)
        if pip_size is None:
            status_counts["UNSUPPORTED_INSTRUMENT"] += 1
            rows.append(
                {
                    **event,
                    "status": "UNSUPPORTED_INSTRUMENT",
                    "model_contract_sha256": contract_hash,
                }
            )
            continue
        m15 = _history_as_of(
            candles.get((instrument, "M15"), []),
            timelines.get((instrument, "M15"), []),
            decision,
        )
        h1 = _history_as_of(
            candles.get((instrument, "H1"), []),
            timelines.get((instrument, "H1"), []),
            decision,
        )
        if any(parse_utc(row["end_time_utc"]) > decision for row in m15 + h1):
            raise ValueError("future candle leaked into historical regime replay")
        markov = _markov(m15, pip_size)
        hmm = _hmm(m15, pip_size)
        garch = _garch(h1, pip_size)
        ready_count = sum(
            value.get("status", "").startswith("READY")
            for value in (markov, hmm, garch)
        )
        status = "READY" if ready_count == 3 else "PARTIAL" if ready_count else "UNAVAILABLE"
        status_counts[status] += 1
        rows.append(
            {
                **event,
                "status": status,
                "derived_at_utc": generated,
                "historical_causal_not_forward": True,
                "model_contract_sha256": contract_hash,
                "source_manifest_set_sha256": sources[
                    "source_manifest_set_sha256"
                ],
                "latest_m15_candle_end_utc": (
                    m15[-1]["end_time_utc"] if m15 else None
                ),
                "latest_h1_candle_end_utc": h1[-1]["end_time_utc"] if h1 else None,
                "markov": markov,
                "hmm": hmm,
                "garch": garch,
            }
        )
    artifact_core = {
        "model_contract_sha256": contract_hash,
        "source_manifest_set_sha256": sources["source_manifest_set_sha256"],
        "rows": rows,
    }
    return {
        "schema": "FX_SIGNAL_REGIME_ENRICHMENT_V1",
        "artifact_id": "REGIME_ENRICHMENT_"
        + hashlib.sha256(canonical_json(artifact_core).encode("utf-8")).hexdigest()[:20],
        "generated_at_utc": generated,
        "model_contract": MODEL_CONTRACT,
        "model_contract_sha256": contract_hash,
        "market_lineage": sources,
        "row_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "rows": rows,
        "authority": {
            "historical_causal_reconstruction": True,
            "forward_confirmation": False,
            "automatic_campaign_creation": False,
            "automatic_policy_changes": False,
            "automatic_execution_changes": False,
            "order_authority": False,
        },
    }
