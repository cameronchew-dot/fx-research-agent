from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


PACK_SCHEMA = "FX_RESEARCH_CME_FORWARD_CONTEXT_PACK_V1"
SNAPSHOT_SCHEMA = "EUR_AGENT_CME_CONTEXT_SNAPSHOT_V1"
PRODUCTS = {
    "6E": "EUR_USD",
    "6J": "USD_JPY",
    "6A": "AUD_USD",
}


def _utc(value: Any) -> str:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _hash(value: Any) -> str:
    material = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_snapshot(
    bars: pd.DataFrame,
    *,
    product: str,
    build_id: str,
) -> dict[str, Any]:
    if product not in PRODUCTS:
        raise ValueError(f"unsupported CME FX product: {product}")
    required = {
        "event_time_utc",
        "adjusted_open",
        "adjusted_high",
        "adjusted_low",
        "adjusted_close",
        "volume",
    }
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"continuous futures bars missing columns: {sorted(missing)}")
    frame = bars.copy()
    frame["event_time_utc"] = pd.to_datetime(frame["event_time_utc"], utc=True)
    frame = frame.sort_values("event_time_utc").set_index("event_time_utc")
    grouped = frame.resample("15min", label="left", closed="left")
    aggregated = grouped.agg(
        open=("adjusted_open", "first"),
        high=("adjusted_high", "max"),
        low=("adjusted_low", "min"),
        close=("adjusted_close", "last"),
        volume=("volume", "sum"),
        source_minutes=("adjusted_close", "count"),
    )
    aggregated = aggregated[aggregated["source_minutes"] >= 15].copy()
    aggregated["range"] = aggregated["high"] - aggregated["low"]
    aggregated["volume_baseline"] = (
        aggregated["volume"].shift(1).rolling(20, min_periods=20).median()
    )
    aggregated["range_baseline"] = (
        aggregated["range"].shift(1).rolling(20, min_periods=20).median()
    )
    aggregated = aggregated[
        (aggregated["volume_baseline"] > 0.0)
        & (aggregated["range_baseline"] > 0.0)
    ]
    if aggregated.empty:
        raise ValueError("not enough complete CME minutes for a causal context snapshot")
    start = aggregated.index[-1]
    row = aggregated.iloc[-1]
    end = start + pd.Timedelta(minutes=15)
    price_range = float(row["high"] - row["low"])
    close_location = (
        0.0
        if price_range <= 0.0
        else 2.0 * (float(row["close"] - row["low"]) / price_range) - 1.0
    )
    identity = {
        "schema": SNAPSHOT_SCHEMA,
        "instrument": PRODUCTS[product],
        "futures_product": product,
        "bar_start_utc": _utc(start),
        "bar_end_utc": _utc(end),
        "available_at_utc": _utc(end),
        "source": {
            "provider": "DATABENTO",
            "dataset": "GLBX.MDP3",
            "schema": "ohlcv-1m",
            "continuous_build_id": build_id,
            "aggregation": "CAUSAL_15M_FROM_1M",
            "baseline": "PRIOR_20_COMPLETE_15M_MEDIAN",
        },
        "features": {
            "volume_ratio": float(row["volume"] / row["volume_baseline"]),
            "range_ratio": float(row["range"] / row["range_baseline"]),
            "return_bps": float((row["close"] / row["open"] - 1.0) * 10000.0),
            "close_location": float(max(-1.0, min(1.0, close_location))),
            "source_minutes": int(row["source_minutes"]),
        },
    }
    return {
        **identity,
        "snapshot_id": "cmectx_" + _hash(identity)[:24],
    }


def build_pack(
    root: Path,
    *,
    builds: dict[str, str],
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    snapshots = []
    for product, build_id in builds.items():
        path = (
            root
            / "data"
            / "derived"
            / "databento_continuous"
            / product
            / build_id
            / "continuous_bars_1m.parquet"
        )
        snapshots.append(
            build_snapshot(pd.read_parquet(path), product=product, build_id=build_id)
        )
    return {
        "schema": PACK_SCHEMA,
        "created_at_utc": created_at_utc
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "snapshots": snapshots,
        "authority": {
            "research_only": True,
            "execution_authority": False,
            "receiver_must_enforce_ingestion_time": True,
        },
    }


def write_pack(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
