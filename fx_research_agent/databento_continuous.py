from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from zoneinfo import ZoneInfo

import databento as db
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .futures_context import SUPPORTED_PRODUCTS
from .market_data import validate_manifest


ALGORITHM_VERSION = "CME_FX_CAUSAL_CONTINUOUS_V1"
CHICAGO = ZoneInfo("America/Chicago")
CHUNK_ROWS = 200_000
MAX_PRIOR_SESSION_LAG_DAYS = 4
DERIVED_DATA_CLASSES = [
    "CME_FX_CONTINUOUS_BARS",
    "CME_FX_ROLL_SCHEDULE",
    "CME_FX_CANONICAL_STATISTICS",
    "CME_FX_OUTRIGHT_DEFINITIONS",
]
PRICE_STAT_TYPES = {1, 2, 3, 4, 5, 7, 8, 10, 11, 13, 16}
STAT_TYPE_NAMES = {
    1: "OPENING_PRICE",
    2: "INDICATIVE_OPENING_PRICE",
    3: "SETTLEMENT_PRICE",
    4: "SESSION_LOW",
    5: "SESSION_HIGH",
    6: "CLEARED_VOLUME",
    7: "LOWEST_OFFER",
    8: "HIGHEST_BID",
    9: "OPEN_INTEREST",
    10: "FIXING_PRICE",
    11: "CLOSE_PRICE",
    12: "NET_CHANGE",
    13: "VWAP",
    14: "VOLATILITY",
    15: "DELTA",
    16: "UNCROSSING_PRICE",
}
ALGORITHM_SPEC = {
    "algorithm_version": ALGORITHM_VERSION,
    "session_timezone": "America/Chicago",
    "session_start_local": "17:00:00",
    "contract_filter": "POINT_IN_TIME_DEFINITION_INSTRUMENT_CLASS_F_LEG_COUNT_0",
    "roll_method": "PREVIOUS_VALID_COMPLETED_SESSION_OUTRIGHT_VOLUME_LEADER",
    "selection_information_cutoff": "STRICTLY_BEFORE_TARGET_SESSION",
    "tie_breakers": ["EARLIEST_EXPIRATION", "LEXICOGRAPHIC_SYMBOL"],
    "maximum_prior_session_lag_days": MAX_PRIOR_SESSION_LAG_DAYS,
    "price_adjustment": "CAUSAL_PRIOR_SESSION_CLOSE_RATIO_ON_ROLL",
    "degraded_date_policy": "EXCLUDE_INTERSECTING_CME_SESSIONS",
    "six_j_normalization": "INVERT_USD_PER_JPY_TO_JPY_PER_USD_WITH_OHLC_SWAP",
}


@dataclass(frozen=True)
class PackageRef:
    product: str
    source_schema: str
    package_dir: Path
    payload_path: Path
    manifest_path: Path
    payload: dict[str, Any]
    manifest: dict[str, Any]


class ParquetSink:
    def __init__(self, path: Path, schema: pa.Schema) -> None:
        self.path = path
        self.schema = schema
        self.writer: pq.ParquetWriter | None = None
        self.row_count = 0

    def append(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        table = pa.Table.from_pandas(frame, schema=self.schema, preserve_index=False, safe=True)
        if self.writer is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.writer = pq.ParquetWriter(
                self.path,
                self.schema,
                compression="zstd",
                compression_level=9,
                use_dictionary=True,
            )
        self.writer.write_table(table)
        self.row_count += table.num_rows

    def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            self.writer = None
        if not self.path.is_file():
            empty = pa.Table.from_arrays(
                [pa.array([], type=field.type) for field in self.schema],
                schema=self.schema,
            )
            pq.write_table(empty, self.path, compression="zstd", compression_level=9)


BARS_SCHEMA = pa.schema([
    ("product", pa.string()),
    ("event_time_utc", pa.timestamp("ns", tz="UTC")),
    ("session_date", pa.date32()),
    ("source_symbol", pa.string()),
    ("source_open", pa.float64()),
    ("source_high", pa.float64()),
    ("source_low", pa.float64()),
    ("source_close", pa.float64()),
    ("volume", pa.int64()),
    ("normalized_open", pa.float64()),
    ("normalized_high", pa.float64()),
    ("normalized_low", pa.float64()),
    ("normalized_close", pa.float64()),
    ("adjustment_factor", pa.float64()),
    ("adjusted_open", pa.float64()),
    ("adjusted_high", pa.float64()),
    ("adjusted_low", pa.float64()),
    ("adjusted_close", pa.float64()),
    ("selected_from_session", pa.date32()),
    ("leader_volume", pa.int64()),
    ("roll_session", pa.bool_()),
    ("previous_symbol", pa.string()),
    ("adjustment_status", pa.string()),
])

SCHEDULE_SCHEMA = pa.schema([
    ("product", pa.string()),
    ("session_date", pa.date32()),
    ("selected_from_session", pa.date32()),
    ("selected_symbol", pa.string()),
    ("previous_symbol", pa.string()),
    ("leader_volume", pa.int64()),
    ("calendar_lag_days", pa.int16()),
    ("roll_session", pa.bool_()),
    ("adjustment_factor", pa.float64()),
    ("adjustment_status", pa.string()),
])

DEFINITIONS_SCHEMA = pa.schema([
    ("product", pa.string()),
    ("available_at_utc", pa.timestamp("ns", tz="UTC")),
    ("event_time_utc", pa.timestamp("ns", tz="UTC")),
    ("instrument_id", pa.int64()),
    ("symbol", pa.string()),
    ("activation_utc", pa.timestamp("ns", tz="UTC")),
    ("expiration_utc", pa.timestamp("ns", tz="UTC")),
    ("minimum_price_increment", pa.float64()),
    ("currency", pa.string()),
    ("settlement_currency", pa.string()),
    ("unit_of_measure", pa.string()),
    ("maturity_year", pa.int32()),
    ("maturity_month", pa.int16()),
    ("update_action", pa.string()),
])

STATISTICS_SCHEMA = pa.schema([
    ("product", pa.string()),
    ("available_at_utc", pa.timestamp("ns", tz="UTC")),
    ("event_time_utc", pa.timestamp("ns", tz="UTC")),
    ("reference_time_utc", pa.timestamp("ns", tz="UTC")),
    ("availability_session_date", pa.date32()),
    ("instrument_id", pa.int64()),
    ("source_symbol", pa.string()),
    ("stat_type", pa.int16()),
    ("stat_name", pa.string()),
    ("normalized_stat_type", pa.int16()),
    ("normalized_stat_name", pa.string()),
    ("source_price", pa.float64()),
    ("normalized_price", pa.float64()),
    ("quantity", pa.float64()),
    ("update_action", pa.int16()),
    ("stat_flags", pa.int16()),
    ("selected_symbol", pa.string()),
    ("is_selected_contract", pa.bool_()),
])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def cme_session_date(value: pd.Timestamp | datetime) -> date:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    local = stamp.tz_convert(CHICAGO)
    session = local.date() + (timedelta(days=1) if local.time() >= time(17, 0) else timedelta())
    return session


def session_dates(values: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    index = pd.DatetimeIndex(pd.to_datetime(values, utc=True))
    local = index.tz_convert(CHICAGO)
    normalized = local.normalize().tz_localize(None)
    shifted = normalized + pd.to_timedelta((local.hour >= 17).astype(np.int8), unit="D")
    return shifted.date


def excluded_session_dates(excluded_utc_dates: Iterable[str]) -> set[date]:
    sessions: set[date] = set()
    for text in excluded_utc_dates:
        day = date.fromisoformat(str(text))
        for clock in (time(0, 0), time(23, 59, 59)):
            sessions.add(cme_session_date(datetime.combine(day, clock, tzinfo=timezone.utc)))
    return sessions


def normalize_ohlc(
    product: str, open_price: float, high: float, low: float, close: float
) -> tuple[float, float, float, float]:
    if product != "6J":
        return float(open_price), float(high), float(low), float(close)
    if min(open_price, high, low, close) <= 0:
        raise ValueError("6J prices must be positive before inverse normalization")
    return 1.0 / open_price, 1.0 / low, 1.0 / high, 1.0 / close


def normalize_close(product: str, close: float) -> float:
    if product == "6J":
        if close <= 0:
            raise ValueError("6J close must be positive before inverse normalization")
        return 1.0 / close
    return float(close)


def build_roll_schedule(aggregates: pd.DataFrame, product: str) -> pd.DataFrame:
    if aggregates.empty:
        return pd.DataFrame(columns=[field.name for field in SCHEDULE_SCHEMA])
    frame = aggregates.copy()
    frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.date
    frame["normalized_close"] = [
        normalize_close(product, float(value)) for value in frame["last_close"]
    ]
    expiry_fallback = pd.Timestamp.max.tz_localize("UTC")
    frame["expiration_sort"] = pd.to_datetime(frame["expiration_utc"], utc=True).fillna(expiry_fallback)
    leaders = (
        frame.sort_values(
            ["session_date", "volume", "expiration_sort", "symbol"],
            ascending=[True, False, True, True],
        )
        .drop_duplicates("session_date", keep="first")
        .set_index("session_date")
    )
    close_by_session = {
        session: dict(zip(group["symbol"], group["normalized_close"]))
        for session, group in frame.groupby("session_date", sort=True)
    }
    sessions = sorted(leaders.index)
    rows: list[dict[str, Any]] = []
    previous_selected: str | None = None
    previous_factor: float | None = None
    for index in range(1, len(sessions)):
        source_session = sessions[index - 1]
        target_session = sessions[index]
        lag = (target_session - source_session).days
        leader = leaders.loc[source_session]
        selected = str(leader["symbol"])
        status = "UNCHANGED_CONTRACT"
        factor = previous_factor
        roll = previous_selected is not None and selected != previous_selected
        if lag > MAX_PRIOR_SESSION_LAG_DAYS:
            selected = None
            factor = None
            status = "SKIP_STALE_PRIOR_SESSION"
            roll = False
        elif previous_selected is None or previous_factor is None:
            factor = 1.0
            status = "INITIAL_CAUSAL_SEGMENT"
        elif roll:
            closes = close_by_session[source_session]
            old_close = closes.get(previous_selected)
            new_close = closes.get(selected)
            if old_close and new_close and old_close > 0 and new_close > 0:
                factor = previous_factor * old_close / new_close
                status = "CAUSAL_PRIOR_SESSION_RATIO_ROLL"
            else:
                factor = None
                status = "SKIP_ROLL_OVERLAP_UNAVAILABLE"
                selected = None
                roll = False
        rows.append({
            "product": product,
            "session_date": target_session,
            "selected_from_session": source_session,
            "selected_symbol": selected,
            "previous_symbol": previous_selected,
            "leader_volume": int(leader["volume"]),
            "calendar_lag_days": lag,
            "roll_session": bool(roll),
            "adjustment_factor": factor,
            "adjustment_status": status,
        })
        previous_selected = selected
        previous_factor = factor
    return pd.DataFrame(rows, columns=[field.name for field in SCHEDULE_SCHEMA])


def discover_packages(package_root: Path, product: str) -> dict[str, PackageRef]:
    if product not in SUPPORTED_PRODUCTS:
        raise ValueError(f"unsupported CME FX product: {product}")
    found: dict[str, PackageRef] = {}
    for payload_path in sorted(package_root.glob("*/*.package-index.payload.json")):
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        if payload.get("canonical_product") != product:
            continue
        source_schema = str(payload.get("source_schema") or "")
        category = "bars" if source_schema.startswith("ohlcv-") else source_schema
        if category not in {"bars", "statistics", "definition"}:
            continue
        manifest_path = payload_path.with_name(
            payload_path.name.replace(".package-index.payload.json", ".market.manifest.json")
        )
        manifest = validate_manifest(manifest_path)
        if category in found:
            raise ValueError(f"multiple {category} packages found for {product}")
        found[category] = PackageRef(
            product=product,
            source_schema=source_schema,
            package_dir=payload_path.parent,
            payload_path=payload_path,
            manifest_path=manifest_path,
            payload=payload,
            manifest=manifest,
        )
    missing = sorted({"bars", "statistics", "definition"} - set(found))
    if missing:
        raise ValueError(f"missing Databento packages for {product}: {missing}")
    return found


def iter_dbn_frames(reference: PackageRef) -> Iterator[pd.DataFrame]:
    source_files = [reference.package_dir / str(item["filename"]) for item in reference.payload["files"]]
    for path in sorted(source_files):
        converted = db.DBNStore.from_file(path).to_df(map_symbols=True, count=CHUNK_ROWS)
        if isinstance(converted, pd.DataFrame):
            yield converted
        else:
            yield from converted


def _excluded_utc_dates(packages: dict[str, PackageRef]) -> list[str]:
    values = {
        str(value)
        for reference in packages.values()
        for value in reference.payload.get("quality", {}).get("excluded_dates", [])
    }
    return sorted(values)


def load_definitions(
    reference: PackageRef, product: str, excluded_utc: set[str]
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    parts: list[pd.DataFrame] = []
    for source in iter_dbn_frames(reference):
        frame = source.reset_index()
        available_column = source.index.name or "ts_recv"
        if available_column not in frame:
            raise ValueError("definition package is missing its availability timestamp")
        frame = frame[
            (frame["instrument_class"].astype(str) == "F")
            & (pd.to_numeric(frame["leg_count"], errors="coerce").fillna(-1) == 0)
            & (frame["group"].astype(str) == product)
            & (frame["security_type"].astype(str) == "FUT")
            & (frame["security_update_action"].astype(str) != "D")
        ].copy()
        if frame.empty:
            continue
        frame["available_at_utc"] = pd.to_datetime(frame[available_column], utc=True)
        frame["event_time_utc"] = pd.to_datetime(frame["ts_event"], utc=True)
        frame = frame[~frame["available_at_utc"].dt.date.astype(str).isin(excluded_utc)]
        if frame.empty:
            continue
        output = pd.DataFrame({
            "product": product,
            "available_at_utc": frame["available_at_utc"],
            "event_time_utc": frame["event_time_utc"],
            "instrument_id": pd.to_numeric(frame["instrument_id"]).astype("int64"),
            "symbol": frame["raw_symbol"].astype(str),
            "activation_utc": pd.to_datetime(frame["activation"], utc=True, errors="coerce"),
            "expiration_utc": pd.to_datetime(frame["expiration"], utc=True, errors="coerce"),
            "minimum_price_increment": pd.to_numeric(frame["min_price_increment"], errors="coerce"),
            "currency": frame["currency"].astype(str),
            "settlement_currency": frame["settl_currency"].astype(str),
            "unit_of_measure": frame["unit_of_measure"].astype(str),
            "maturity_year": pd.to_numeric(frame["maturity_year"], errors="coerce").fillna(0).astype("int32"),
            "maturity_month": pd.to_numeric(frame["maturity_month"], errors="coerce").fillna(0).astype("int16"),
            "update_action": frame["security_update_action"].astype(str),
        })
        parts.append(output)
    if not parts:
        raise ValueError(f"no valid outright definitions found for {product}")
    definitions = pd.concat(parts, ignore_index=True).sort_values(["available_at_utc", "symbol"])
    state_columns = [
        "symbol", "instrument_id", "activation_utc", "expiration_utc",
        "minimum_price_increment", "currency", "settlement_currency",
        "unit_of_measure", "maturity_year", "maturity_month", "update_action",
    ]
    definitions = definitions.drop_duplicates(state_columns, keep="first").reset_index(drop=True)
    contracts: dict[str, dict[str, Any]] = {}
    for symbol, group in definitions.groupby("symbol", sort=True):
        first = group.sort_values("available_at_utc").iloc[0]
        contracts[str(symbol)] = {
            "first_available_at": pd.Timestamp(first["available_at_utc"]),
            "activation_utc": pd.Timestamp(first["activation_utc"]),
            "expiration_utc": pd.Timestamp(first["expiration_utc"]),
            "minimum_price_increment": float(first["minimum_price_increment"]),
        }
    return definitions, contracts


def _prepare_bar_frame(
    source: pd.DataFrame,
    contracts: dict[str, dict[str, Any]],
    excluded_sessions: set[date],
) -> pd.DataFrame:
    frame = source.reset_index()
    timestamp_column = source.index.name or "ts_event"
    frame["event_time_utc"] = pd.to_datetime(frame[timestamp_column], utc=True)
    frame["symbol"] = frame["symbol"].astype(str)
    frame = frame[frame["symbol"].isin(contracts)].copy()
    if frame.empty:
        return frame
    first_available = frame["symbol"].map({key: value["first_available_at"] for key, value in contracts.items()})
    frame = frame[frame["event_time_utc"] >= first_available].copy()
    frame["session_date"] = session_dates(frame["event_time_utc"])
    return frame[~frame["session_date"].isin(excluded_sessions)].copy()


def aggregate_sessions(
    reference: PackageRef,
    contracts: dict[str, dict[str, Any]],
    excluded_sessions: set[date],
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for source in iter_dbn_frames(reference):
        frame = _prepare_bar_frame(source, contracts, excluded_sessions)
        if frame.empty:
            continue
        frame = frame.sort_values("event_time_utc")
        volume = frame.groupby(["session_date", "symbol"], as_index=False)["volume"].sum()
        closes = frame.groupby(["session_date", "symbol"], as_index=False).tail(1)[
            ["session_date", "symbol", "event_time_utc", "close"]
        ].rename(columns={"event_time_utc": "last_event_time_utc", "close": "last_close"})
        parts.append(volume.merge(closes, on=["session_date", "symbol"], how="inner"))
    if not parts:
        raise ValueError("no valid outright bar aggregates were produced")
    combined = pd.concat(parts, ignore_index=True)
    volumes = combined.groupby(["session_date", "symbol"], as_index=False)["volume"].sum()
    closes = combined.sort_values("last_event_time_utc").groupby(
        ["session_date", "symbol"], as_index=False
    ).tail(1)[["session_date", "symbol", "last_event_time_utc", "last_close"]]
    output = volumes.merge(closes, on=["session_date", "symbol"], how="inner")
    output["expiration_utc"] = output["symbol"].map({
        key: value["expiration_utc"] for key, value in contracts.items()
    })
    return output.sort_values(["session_date", "symbol"]).reset_index(drop=True)


def _normalized_bar_columns(frame: pd.DataFrame, product: str) -> pd.DataFrame:
    output = frame.copy()
    if product == "6J":
        if (output[["open", "high", "low", "close"]] <= 0).any(axis=None):
            raise ValueError("6J bars contain nonpositive prices")
        output["normalized_open"] = 1.0 / output["open"]
        output["normalized_high"] = 1.0 / output["low"]
        output["normalized_low"] = 1.0 / output["high"]
        output["normalized_close"] = 1.0 / output["close"]
    else:
        for name in ("open", "high", "low", "close"):
            output[f"normalized_{name}"] = pd.to_numeric(output[name], errors="raise").astype(float)
    return output


def write_continuous_bars(
    reference: PackageRef,
    product: str,
    contracts: dict[str, dict[str, Any]],
    excluded_sessions: set[date],
    schedule: pd.DataFrame,
    sink: ParquetSink,
) -> None:
    usable = schedule[schedule["selected_symbol"].notna()].copy()
    maps = {
        column: dict(zip(usable["session_date"], usable[column]))
        for column in (
            "selected_symbol", "selected_from_session", "leader_volume", "roll_session",
            "previous_symbol", "adjustment_factor", "adjustment_status",
        )
    }
    for source in iter_dbn_frames(reference):
        frame = _prepare_bar_frame(source, contracts, excluded_sessions)
        if frame.empty:
            continue
        frame["selected_symbol"] = frame["session_date"].map(maps["selected_symbol"])
        frame = frame[frame["symbol"] == frame["selected_symbol"]].copy()
        if frame.empty:
            continue
        frame = _normalized_bar_columns(frame, product)
        frame["adjustment_factor"] = frame["session_date"].map(maps["adjustment_factor"])
        output = pd.DataFrame({
            "product": product,
            "event_time_utc": frame["event_time_utc"],
            "session_date": frame["session_date"],
            "source_symbol": frame["symbol"],
            "source_open": pd.to_numeric(frame["open"]).astype(float),
            "source_high": pd.to_numeric(frame["high"]).astype(float),
            "source_low": pd.to_numeric(frame["low"]).astype(float),
            "source_close": pd.to_numeric(frame["close"]).astype(float),
            "volume": pd.to_numeric(frame["volume"]).astype("int64"),
            "normalized_open": frame["normalized_open"].astype(float),
            "normalized_high": frame["normalized_high"].astype(float),
            "normalized_low": frame["normalized_low"].astype(float),
            "normalized_close": frame["normalized_close"].astype(float),
            "adjustment_factor": frame["adjustment_factor"].astype(float),
        })
        for name in ("open", "high", "low", "close"):
            output[f"adjusted_{name}"] = output[f"normalized_{name}"] * output["adjustment_factor"]
        output["selected_from_session"] = frame["session_date"].map(maps["selected_from_session"])
        output["leader_volume"] = frame["session_date"].map(maps["leader_volume"]).astype("int64")
        output["roll_session"] = frame["session_date"].map(maps["roll_session"]).astype(bool)
        output["previous_symbol"] = frame["session_date"].map(maps["previous_symbol"])
        output["adjustment_status"] = frame["session_date"].map(maps["adjustment_status"])
        sink.append(output[[field.name for field in BARS_SCHEMA]])


def _normalized_stat_type(product: str, stat_type: pd.Series) -> pd.Series:
    values = pd.to_numeric(stat_type, errors="coerce").fillna(0).astype("int16")
    if product == "6J":
        return values.replace({4: 5, 5: 4, 7: 8, 8: 7}).astype("int16")
    return values


def write_statistics(
    reference: PackageRef,
    product: str,
    contracts: dict[str, dict[str, Any]],
    excluded_utc: set[str],
    excluded_sessions: set[date],
    schedule: pd.DataFrame,
    sink: ParquetSink,
) -> None:
    selection_map = dict(zip(schedule["session_date"], schedule["selected_symbol"]))
    first_available_map = {key: value["first_available_at"] for key, value in contracts.items()}
    for source in iter_dbn_frames(reference):
        frame = source.reset_index()
        available_column = source.index.name or "ts_recv"
        frame["available_at_utc"] = pd.to_datetime(frame[available_column], utc=True)
        frame["event_time_utc"] = pd.to_datetime(frame["ts_event"], utc=True)
        frame["reference_time_utc"] = pd.to_datetime(frame["ts_ref"], utc=True, errors="coerce")
        frame["symbol"] = frame["symbol"].astype(str)
        frame = frame[frame["symbol"].isin(contracts)].copy()
        if frame.empty:
            continue
        first_available = frame["symbol"].map(first_available_map)
        frame = frame[frame["available_at_utc"] >= first_available].copy()
        frame = frame[~frame["available_at_utc"].dt.date.astype(str).isin(excluded_utc)]
        frame["availability_session_date"] = session_dates(frame["available_at_utc"])
        frame = frame[~frame["availability_session_date"].isin(excluded_sessions)].copy()
        if frame.empty:
            continue
        source_type = pd.to_numeric(frame["stat_type"], errors="coerce").fillna(0).astype("int16")
        normalized_type = _normalized_stat_type(product, source_type)
        source_price = pd.to_numeric(frame["price"], errors="coerce").astype(float)
        normalized_price = pd.Series(np.nan, index=frame.index, dtype=float)
        level_mask = source_type.isin(PRICE_STAT_TYPES) & source_price.gt(0)
        if product == "6J":
            normalized_price.loc[level_mask] = 1.0 / source_price.loc[level_mask]
        else:
            normalized_price.loc[level_mask] = source_price.loc[level_mask]
        quantity = pd.to_numeric(frame["quantity"], errors="coerce").astype(float)
        quantity = quantity.mask(quantity >= float(np.iinfo(np.int64).max))
        selected = frame["availability_session_date"].map(selection_map)
        output = pd.DataFrame({
            "product": product,
            "available_at_utc": frame["available_at_utc"],
            "event_time_utc": frame["event_time_utc"],
            "reference_time_utc": frame["reference_time_utc"],
            "availability_session_date": frame["availability_session_date"],
            "instrument_id": pd.to_numeric(frame["instrument_id"]).astype("int64"),
            "source_symbol": frame["symbol"],
            "stat_type": source_type,
            "stat_name": source_type.map(STAT_TYPE_NAMES).fillna("UNKNOWN"),
            "normalized_stat_type": normalized_type,
            "normalized_stat_name": normalized_type.map(STAT_TYPE_NAMES).fillna("UNKNOWN"),
            "source_price": source_price,
            "normalized_price": normalized_price,
            "quantity": quantity,
            "update_action": pd.to_numeric(frame["update_action"]).astype("int16"),
            "stat_flags": pd.to_numeric(frame["stat_flags"]).astype("int16"),
            "selected_symbol": selected,
            "is_selected_contract": frame["symbol"].eq(selected),
        })
        sink.append(output[[field.name for field in STATISTICS_SCHEMA]])


def _output_entry(root: Path, path: Path, data_class: str, rows: int) -> dict[str, Any]:
    return {
        "data_class": data_class,
        "path": str(path.relative_to(root)),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "row_count": rows,
    }


def build_product(package_root: Path, output_root: Path, product: str) -> dict[str, Any]:
    packages = discover_packages(package_root, product)
    excluded_utc = _excluded_utc_dates(packages)
    excluded_sessions = excluded_session_dates(excluded_utc)
    source_packages = []
    for category, reference in sorted(packages.items()):
        source_packages.append({
            "category": category,
            "source_schema": reference.source_schema,
            "source_job_id": reference.payload["source_job_id"],
            "manifest_id": reference.manifest["manifest_id"],
            "manifest_sha256": sha256_file(reference.manifest_path),
            "payload_sha256": reference.manifest["payload_sha256"],
        })
    identity = {
        "product": product,
        "algorithm_spec": ALGORITHM_SPEC,
        "source_packages": source_packages,
        "excluded_utc_dates": excluded_utc,
    }
    build_id = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:20].upper()
    final_dir = output_root / product / build_id
    final_manifest = final_dir / f"{product.lower()}.causal-continuous.market.manifest.json"
    if final_dir.exists():
        validate_manifest(final_manifest)
        return {
            "status": "UNCHANGED",
            "product": product,
            "build_id": build_id,
            "manifest_path": str(final_manifest),
        }

    final_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{build_id}.", dir=final_dir.parent) as temp_name:
        temp_dir = Path(temp_name)
        definitions, contracts = load_definitions(
            packages["definition"], product, set(excluded_utc)
        )
        aggregates = aggregate_sessions(packages["bars"], contracts, excluded_sessions)
        schedule = build_roll_schedule(aggregates, product)
        if schedule.empty or not schedule["selected_symbol"].notna().any():
            raise ValueError(f"no causal roll schedule could be built for {product}")

        definitions_path = temp_dir / "outright_definitions.parquet"
        schedule_path = temp_dir / "roll_schedule.parquet"
        bars_path = temp_dir / "continuous_bars_1m.parquet"
        statistics_path = temp_dir / "official_statistics.parquet"
        definitions_sink = ParquetSink(definitions_path, DEFINITIONS_SCHEMA)
        definitions_sink.append(definitions[[field.name for field in DEFINITIONS_SCHEMA]])
        definitions_sink.close()
        schedule_sink = ParquetSink(schedule_path, SCHEDULE_SCHEMA)
        schedule_sink.append(schedule[[field.name for field in SCHEDULE_SCHEMA]])
        schedule_sink.close()
        bars_sink = ParquetSink(bars_path, BARS_SCHEMA)
        write_continuous_bars(
            packages["bars"], product, contracts, excluded_sessions, schedule, bars_sink
        )
        bars_sink.close()
        statistics_sink = ParquetSink(statistics_path, STATISTICS_SCHEMA)
        write_statistics(
            packages["statistics"], product, contracts, set(excluded_utc),
            excluded_sessions, schedule, statistics_sink,
        )
        statistics_sink.close()

        outputs = [
            _output_entry(temp_dir, bars_path, "CME_FX_CONTINUOUS_BARS", bars_sink.row_count),
            _output_entry(temp_dir, schedule_path, "CME_FX_ROLL_SCHEDULE", schedule_sink.row_count),
            _output_entry(
                temp_dir, statistics_path, "CME_FX_CANONICAL_STATISTICS", statistics_sink.row_count
            ),
            _output_entry(
                temp_dir, definitions_path, "CME_FX_OUTRIGHT_DEFINITIONS", definitions_sink.row_count
            ),
        ]
        source_window_start = max(
            str(reference.manifest["window_start_utc"]) for reference in packages.values()
        )
        source_window_end = min(
            str(reference.manifest["window_end_utc"]) for reference in packages.values()
        )
        payload = {
            "schema": ALGORITHM_VERSION,
            "build_id": build_id,
            "canonical_product": product,
            "normalized_spot_orientation": {
                "6E": "EUR_USD",
                "6J": "USD_JPY",
                "6A": "AUD_USD",
            }[product],
            "algorithm_spec": ALGORITHM_SPEC,
            "source_packages": source_packages,
            "window_start_utc": source_window_start,
            "window_end_utc": source_window_end,
            "quality": {
                "excluded_utc_dates": excluded_utc,
                "excluded_session_dates": sorted(value.isoformat() for value in excluded_sessions),
                "exclusion_policy": "EXCLUDE_INTERSECTING_CME_SESSIONS",
            },
            "outputs": outputs,
            "authority": {
                "research_context_only": True,
                "automatic_campaign_approval": False,
                "automatic_signal_activation": False,
                "execution_authority": False,
            },
        }
        payload_path = temp_dir / f"{product.lower()}.causal-continuous.payload.json"
        payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest = {
            "manifest_id": f"CME_FX_CAUSAL_{product}_{build_id}",
            "schema": "FX_MARKET_DATA_EXPORT_V1",
            "created_at_utc": source_window_end,
            "source_system": "DATABENTO_CAUSAL_CONTINUOUS_BUILDER",
            "instrument": product,
            "window_start_utc": source_window_start,
            "window_end_utc": source_window_end,
            "payload_sha256": sha256_file(payload_path),
            "payload_path": payload_path.name,
            "freshness_status": "FRESH",
            "gap_status": "COMPLETE_WITH_DECLARED_EXCLUSIONS",
            "data_classes": DERIVED_DATA_CLASSES,
            "row_counts": {item["data_class"]: item["row_count"] for item in outputs},
            "provider_provenance": {
                "provider": "DATABENTO",
                "source_dataset": "GLBX.MDP3",
                "canonical_product": product,
                "source_job_ids": [item["source_job_id"] for item in source_packages],
                "derivation_algorithm": ALGORITHM_VERSION,
                "aggressor_side_method": "NONE",
            },
        }
        manifest_path = temp_dir / final_manifest.name
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validate_manifest(manifest_path)
        temp_dir.replace(final_dir)
    return {
        "status": "BUILT",
        "product": product,
        "build_id": build_id,
        "manifest_path": str(final_manifest),
        "row_counts": {item["data_class"]: item["row_count"] for item in outputs},
        "excluded_utc_date_count": len(excluded_utc),
        "excluded_session_count": len(excluded_sessions),
    }

