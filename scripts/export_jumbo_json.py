#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export local TW market data to JumboChart JSON.")
    parser.add_argument("--market", required=True, choices=["TSE", "OTC"])
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--out", default="", help="Output JSON path. Defaults to data/jumbo/{MARKET}_{YYYY-MM-DD}.json")
    parser.add_argument(
        "--source-root",
        default=os.environ.get("TW_MARKET_DATA_ROOT", str(PROJECT_ROOT / "data")),
        help="Local market data root. Defaults to TW_MARKET_DATA_ROOT or ./data.",
    )
    return parser.parse_args()


def normalize_date(date_text: str) -> str:
    try:
        return datetime.strptime(date_text, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit("--date must be YYYY-MM-DD") from exc


def normalize_time(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = None
    import re

    match = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def to_number(value: Any) -> float:
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


def first_value(row: dict[str, Any], names: list[str]) -> Any:
    lower_map = {key.lower(): key for key in row}
    for name in names:
        if name in row:
            return row[name]
        lowered = name.lower()
        if lowered in lower_map:
            return row[lower_map[lowered]]
    return None


def row_market(row: dict[str, Any]) -> str:
    value = first_value(row, ["market", "market_type", "exchange", "type", "市場", "市場別"])
    return str(value).strip()


def row_date(row: dict[str, Any]) -> str:
    value = first_value(row, ["date", "trade_date", "trading_date", "日期"])
    if value is None:
        value = first_value(row, ["datetime", "timestamp", "time", "時間"])
    text = str(value or "").strip().replace("/", "-")
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text


def market_matches(row: dict[str, Any], market: str) -> bool:
    value = row_market(row)
    if not value:
        return True
    return value in MARKET_ALIASES[market]


def is_jumbo_row(row: dict[str, Any]) -> bool:
    return all(field in row for field in JUMBO_FIELDS)


def normalize_jumbo_row(row: dict[str, Any]) -> dict[str, Any] | None:
    time_value = normalize_time(row.get("time"))
    if time_value is None:
        return None
    normalized: dict[str, Any] = {"time": time_value}
    for field in NUMERIC_FIELDS:
        normalized[field] = to_number(row.get(field))
    return normalized


def read_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "records", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_sqlite(path: Path, date: str) -> list[dict[str, Any]]:
    tables = ["jumbo_data", "kbar_1m", "minute_bars", "bars_1m"]
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        existing = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for table in tables:
            if table not in existing:
                continue
            try:
                result = conn.execute(f"SELECT * FROM {table} WHERE date = ? OR trade_date = ?", (date, date)).fetchall()
            except sqlite3.Error:
                result = conn.execute(f"SELECT * FROM {table}").fetchall()
            rows.extend(dict(row) for row in result)
    return rows


def read_parquet(path: Path) -> list[dict[str, Any]]:
    try:
        import pandas as pd  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return []
    frame = pd.read_parquet(path)
    return frame.to_dict(orient="records")


def candidate_paths(root: Path, market: str, date: str) -> list[Path]:
    compact = date.replace("-", "")
    names = [
        f"{market}_{date}",
        f"{market}_{compact}",
        date,
        compact,
    ]
    dirs = [
        root,
        root / "jumbo",
        root / market,
        root / "kbar_1m",
        root / "minute",
        root / "data",
        root / "data" / "jumbo",
        root / "data" / "kbar_1m",
    ]
    paths: list[Path] = []
    for directory in dirs:
        for name in names:
            for suffix in (".json", ".csv", ".sqlite", ".db", ".parquet"):
                paths.append(directory / f"{name}{suffix}")
    return paths


def read_rows(root: Path, market: str, date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in candidate_paths(root, market, date):
        if path in seen or not path.exists() or not path.is_file():
            continue
        seen.add(path)
        if path.suffix == ".json":
            rows.extend(read_json(path))
        elif path.suffix == ".csv":
            rows.extend(read_csv(path))
        elif path.suffix in {".sqlite", ".db"}:
            rows.extend(read_sqlite(path, date))
        elif path.suffix == ".parquet":
            rows.extend(read_parquet(path))
    return rows


def derive_from_minute_rows(rows: list[dict[str, Any]], market: str, date: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        if row_date(row) and row_date(row) != date:
            continue
        if not market_matches(row, market):
            continue
        time_value = normalize_time(first_value(row, ["time", "datetime", "timestamp", "時間"]))
        if time_value is None:
            continue

        open_price = to_number(first_value(row, ["open", "Open", "open_price", "開盤價"]))
        close_price = to_number(first_value(row, ["close", "Close", "close_price", "收盤價", "price"]))
        volume = to_number(first_value(row, ["volume", "vol", "DealVol", "trade_volume", "成交量"]))
        if close_price == 0:
            continue

        bucket = buckets[time_value]
        bucket["trade_count"] += 1
        bucket["trade_volume"] += volume

        if open_price == 0 or close_price == open_price:
            bucket["unchanged_count"] += 1
            bucket["bid_count"] += 0.5
            bucket["ask_count"] += 0.5
            bucket["bid_volume"] += volume / 2
            bucket["ask_volume"] += volume / 2
        elif close_price > open_price:
            bucket["up_count"] += 1
            bucket["bid_count"] += 1
            bucket["bid_volume"] += volume
        else:
            bucket["down_count"] += 1
            bucket["ask_count"] += 1
            bucket["ask_volume"] += volume

    output = []
    for time_value in sorted(buckets):
        bucket = buckets[time_value]
        bid_count = bucket["bid_count"]
        ask_count = bucket["ask_count"]
        trade_count = bucket["trade_count"]
        output.append(
            {
                "time": time_value,
                "bid_count": int(round(bid_count)),
                "ask_count": int(round(ask_count)),
                "trade_count": int(round(trade_count)),
                "bid_volume": bucket["bid_volume"],
                "ask_volume": bucket["ask_volume"],
                "trade_volume": bucket["trade_volume"],
                "up_count": int(round(bucket["up_count"])),
                "down_count": int(round(bucket["down_count"])),
                "unchanged_count": int(round(bucket["unchanged_count"])),
                "bid_avg_volume": bucket["bid_volume"] / bid_count if bid_count else 0,
                "ask_avg_volume": bucket["ask_volume"] / ask_count if ask_count else 0,
                "trade_avg_volume": bucket["trade_volume"] / trade_count if trade_count else 0,
            }
        )
    return output


def export_rows(rows: list[dict[str, Any]], market: str, date: str) -> list[dict[str, Any]]:
    if rows and all(is_jumbo_row(row) for row in rows):
        normalized = [row for row in (normalize_jumbo_row(row) for row in rows) if row is not None]
        return sorted(normalized, key=lambda item: item["time"])
    return derive_from_minute_rows(rows, market, date)


def main() -> int:
    args = parse_args()
    date = normalize_date(args.date)
    source_root = Path(args.source_root).expanduser().resolve()
    out_path = Path(args.out).expanduser() if args.out else PROJECT_ROOT / "data" / "jumbo" / f"{args.market}_{date}.json"
    rows = read_rows(source_root, args.market, date)
    output = export_rows(rows, args.market, date) if rows else []

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wrote {len(output)} rows to {out_path}")
    print(f"test: curl 'http://127.0.0.1:8000/api/jumbo-data?market={args.market}&date={date}'")
    print("open: http://127.0.0.1:5173/jumbo-chart")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
