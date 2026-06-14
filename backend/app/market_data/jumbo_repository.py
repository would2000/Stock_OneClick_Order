from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
import csv
import json
import re
import sqlite3
from typing import Any

from ..config import get_settings


JUMBO_FIELDS = [
    "time",
    "bid_count",
    "ask_count",
    "trade_count",
    "bid_volume",
    "ask_volume",
    "trade_volume",
    "up_count",
    "down_count",
    "unchanged_count",
    "bid_avg_volume",
    "ask_avg_volume",
    "trade_avg_volume",
]
NUMERIC_FIELDS = [field for field in JUMBO_FIELDS if field != "time"]
MARKET_ALIASES = {
    "TSE": {"TSE", "TWSE", "上市", "tse", "twse"},
    "OTC": {"OTC", "TPEX", "TPEx", "上櫃", "otc", "tpex"},
}


def _normalize_date_key(date: str) -> str:
    return date.strip().replace("/", "-")


def _today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _normalize_time(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _to_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _first_value(row: dict[str, Any], names: list[str]) -> Any:
    lower_map = {key.lower(): key for key in row}
    for name in names:
        if name in row:
            return row[name]
        lower_name = name.lower()
        if lower_name in lower_map:
            return row[lower_map[lower_name]]
    return None


def _row_date(row: dict[str, Any]) -> str:
    value = _first_value(row, ["date", "trade_date", "trading_date", "日期"])
    if value is None:
        value = _first_value(row, ["datetime", "timestamp", "time", "時間"])
    text = str(value or "").strip().replace("/", "-")
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _market_matches(row: dict[str, Any], market: str) -> bool:
    value = _first_value(row, ["market", "market_type", "exchange", "type", "市場", "市場別"])
    text = str(value or "").strip()
    if not text:
        return True
    return text in MARKET_ALIASES[market]


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "records", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _json_file_paths(market: str, date: str) -> list[Path]:
    settings = get_settings()
    market_key = market.strip().upper()
    date_key = _normalize_date_key(date)
    compact_date = date_key.replace("-", "")
    root = settings.data_dir / "jumbo"

    return [
        root / f"{market_key}_{date_key}.json",
        root / f"{market_key}_{compact_date}.json",
        root / market_key / f"{date_key}.json",
        root / market_key / f"{compact_date}.json",
    ]


def _load_json_file_provider(market: str, date: str) -> list[dict[str, Any]]:
    for path in _json_file_paths(market, date):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _extract_records(payload)
    return []


def _realtime_root_candidates() -> list[Path]:
    settings = get_settings()
    roots = [
        settings.data_dir / "realtime",
        settings.data_dir / "today",
        settings.data_dir / "cache",
        settings.data_dir / "quotes",
        settings.data_dir / "minute",
        settings.data_dir / "kbar_1m",
    ]
    market_root = Path(settings.market_data_root).expanduser()
    roots.extend(
        [
            market_root,
            market_root / "realtime",
            market_root / "today",
            market_root / "cache",
            market_root / "quotes",
            market_root / "minute",
            market_root / "kbar_1m",
            market_root / "data",
            market_root / "data" / "realtime",
            market_root / "data" / "today",
            market_root / "data" / "minute",
            market_root / "data" / "kbar_1m",
        ]
    )
    seen: set[Path] = set()
    output: list[Path] = []
    for root in roots:
        resolved = root.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists() and resolved.is_dir():
            output.append(resolved)
    return output


def _realtime_file_paths(market: str, date: str) -> list[Path]:
    date_key = _normalize_date_key(date)
    compact_date = date_key.replace("-", "")
    names = [
        f"{market}_{date_key}",
        f"{market}_{compact_date}",
        f"{market}_today",
        f"today_{market}",
        date_key,
        compact_date,
        "today",
        "latest",
        "realtime",
    ]
    suffixes = [".json", ".csv", ".sqlite", ".sqlite3", ".db", ".parquet"]
    paths: list[Path] = []
    seen: set[Path] = set()
    for root in _realtime_root_candidates():
        for directory in (root, root / market):
            if not directory.exists() or not directory.is_dir():
                continue
            for name in names:
                for suffix in suffixes:
                    path = directory / f"{name}{suffix}"
                    if path not in seen:
                        seen.add(path)
                        paths.append(path)
    return paths


def _read_json(path: Path) -> list[dict[str, Any]]:
    return _extract_records(json.loads(path.read_text(encoding="utf-8")))


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_sqlite(path: Path, date: str) -> list[dict[str, Any]]:
    preferred = ["jumbo_data", "realtime_jumbo", "kbar_1m", "minute_bars", "bars_1m", "quotes"]
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        tables = [
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        for table in preferred + [table for table in tables if table not in preferred]:
            if table not in tables:
                continue
            columns = {
                row["name"]
                for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
            where_parts: list[str] = []
            params: list[str] = []
            for column in ("date", "trade_date", "trading_date"):
                if column in columns:
                    where_parts.append(f'"{column}" = ?')
                    params.append(date)
            sql = f'SELECT * FROM "{table}"'
            if where_parts:
                sql += " WHERE " + " OR ".join(where_parts)
            try:
                result = conn.execute(sql, params).fetchall()
            except sqlite3.Error:
                continue
            rows.extend(dict(row) for row in result)
            if rows:
                break
    return rows


def _read_parquet(path: Path) -> list[dict[str, Any]]:
    try:
        import pandas as pd  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return []
    frame = pd.read_parquet(path)
    return frame.to_dict(orient="records")


def _read_realtime_rows(market: str, date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _realtime_file_paths(market, date):
        if not path.exists() or not path.is_file():
            continue
        if path.suffix == ".json":
            rows.extend(_read_json(path))
        elif path.suffix == ".csv":
            rows.extend(_read_csv(path))
        elif path.suffix in {".sqlite", ".sqlite3", ".db"}:
            rows.extend(_read_sqlite(path, date))
        elif path.suffix == ".parquet":
            rows.extend(_read_parquet(path))
        if rows:
            return rows
    return rows


def _has_jumbo_fields(row: dict[str, Any]) -> bool:
    return all(field in row for field in JUMBO_FIELDS)


def _normalize_jumbo_row(row: dict[str, Any]) -> dict[str, Any] | None:
    time_value = _normalize_time(row.get("time"))
    if time_value is None:
        return None
    normalized: dict[str, Any] = {"time": time_value}
    for field in NUMERIC_FIELDS:
        normalized[field] = _to_number(row.get(field))
    return normalized


def _normalize_true_jumbo_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = [row for row in (_normalize_jumbo_row(row) for row in rows) if row is not None]
    return sorted(output, key=lambda item: item["time"])


def _derive_synthetic_jumbo_from_ohlcv(
    rows: list[dict[str, Any]],
    market: str,
    date: str,
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        row_date = _row_date(row)
        if row_date and row_date != date:
            continue
        if not _market_matches(row, market):
            continue
        time_value = _normalize_time(_first_value(row, ["time", "datetime", "timestamp", "時間"]))
        if time_value is None:
            continue

        open_price = _to_number(_first_value(row, ["open", "Open", "open_price", "開盤價"]))
        close_price = _to_number(
            _first_value(row, ["close", "Close", "close_price", "收盤價", "price", "last_price"])
        )
        volume = _to_number(
            _first_value(row, ["volume", "vol", "DealVol", "trade_volume", "成交量", "volume_sum"])
        )
        if close_price == 0:
            continue

        bucket = buckets[time_value]
        bucket["trade_count"] += 1
        bucket["trade_volume"] += volume

        if open_price == 0 or close_price == open_price:
            bucket["unchanged_count"] += 1
        elif close_price > open_price:
            bucket["up_count"] += 1
        else:
            bucket["down_count"] += 1

    output: list[dict[str, Any]] = []
    for time_value in sorted(buckets):
        bucket = buckets[time_value]
        trade_count = bucket["trade_count"]
        trade_volume = bucket["trade_volume"]

        # Minute OHLCV cannot infer true order-book bid/ask counts or volumes.
        # Keep bid/ask related values at 0 so the frontend shows synthetic jumbo data honestly.
        output.append(
            {
                "time": time_value,
                "bid_count": 0,
                "ask_count": 0,
                "trade_count": int(round(trade_count)),
                "bid_volume": 0,
                "ask_volume": 0,
                "trade_volume": trade_volume,
                "up_count": int(round(bucket["up_count"])),
                "down_count": int(round(bucket["down_count"])),
                "unchanged_count": int(round(bucket["unchanged_count"])),
                "bid_avg_volume": 0,
                "ask_avg_volume": 0,
                "trade_avg_volume": trade_volume / trade_count if trade_count else 0,
            }
        )
    return output


def _load_realtime_today_provider(market: str, date: str) -> list[dict[str, Any]]:
    rows = _read_realtime_rows(market, date)
    if not rows:
        return []
    if all(_has_jumbo_fields(row) for row in rows):
        return _normalize_true_jumbo_rows(rows)
    return _derive_synthetic_jumbo_from_ohlcv(rows, market, date)


def load_jumbo_data(market: str, date: str) -> list[dict[str, Any]]:
    market_key = market.strip().upper()
    date_key = _normalize_date_key(date)

    if date_key == _today_key():
        realtime_rows = _load_realtime_today_provider(market_key, date_key)
        if realtime_rows:
            return realtime_rows

    return _load_json_file_provider(market_key, date_key)
