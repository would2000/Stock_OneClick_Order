"""Server-side intraday sampler for index symbols.

The Yuanta SDK serves 1-minute kline for the TSE index but times out for the
OTC index (IX0043), so the OTC chart cannot be backfilled from kline. Instead
this sampler builds the intraday series itself: during market hours it reads
the push-fed quote cache once per interval and accumulates per-minute points
(price / cumulative average / volume delta). Samples persist to a JSON file so
a mid-session backend restart keeps the morning's curve.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from threading import Lock

from ..config import get_settings
from ..broker import get_active_client
from ..yuanta.client import YuantaClientError

logger = logging.getLogger("index_sampler")

SAMPLE_INTERVAL = float(os.getenv("INDEX_SAMPLE_INTERVAL", "30"))

# Mirrors INDEX_SYMBOLS in routes.py (kept local to avoid a circular import).
SAMPLED_INDEXES = {
    "TSE": "IX0001",
    "OTC": "IX0043",
}

_lock = Lock()
_date = ""
_points: dict[str, list[dict]] = {market: [] for market in SAMPLED_INDEXES}
_accum: dict[str, dict] = {market: {"pv": 0.0, "vol": 0, "count": 0, "price_sum": 0.0} for market in SAMPLED_INDEXES}
_loaded = False


def _store_path() -> str:
    settings = get_settings()
    return str(settings.data_dir / "index_samples.json")


def _save() -> None:
    try:
        with open(_store_path(), "w", encoding="utf-8") as handle:
            json.dump({"date": _date, "points": _points, "accum": _accum}, handle)
    except OSError:
        logger.exception("Failed to persist index samples")


def _load() -> None:
    global _date, _points, _accum, _loaded
    _loaded = True
    try:
        with open(_store_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return
    if data.get("date") != datetime.now().strftime("%Y-%m-%d"):
        return
    _date = data["date"]
    for market in SAMPLED_INDEXES:
        _points[market] = list(data.get("points", {}).get(market, []))
        stored = data.get("accum", {}).get(market)
        if stored:
            _accum[market] = stored


def _reset_for(date_text: str) -> None:
    global _date
    _date = date_text
    for market in SAMPLED_INDEXES:
        _points[market] = []
        _accum[market] = {"pv": 0.0, "vol": 0, "count": 0, "price_sum": 0.0}


def get_sampled_points(market: str) -> list[dict]:
    with _lock:
        if not _loaded:
            _load()
        if _date != datetime.now().strftime("%Y-%m-%d"):
            return []
        return list(_points.get(market, []))


def _record_sample(market: str, price: float, total_volume: int | None) -> None:
    now = datetime.now()
    minute = now.strftime("%H:%M")
    accum = _accum[market]
    points = _points[market]

    last_total = accum.get("last_total", 0)
    volume_delta = max(0, (total_volume or 0) - last_total) if total_volume else 0
    if total_volume:
        accum["last_total"] = total_volume

    if volume_delta > 0:
        accum["pv"] += price * volume_delta
        accum["vol"] += volume_delta
    accum["count"] += 1
    accum["price_sum"] += price
    avg_price = accum["pv"] / accum["vol"] if accum["vol"] > 0 else accum["price_sum"] / accum["count"]

    point = {"time": minute, "price": price, "avgPrice": avg_price, "volume": volume_delta}
    if points and points[-1]["time"] == minute:
        points[-1] = point
    else:
        points.append(point)


def _in_market_hours(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 <= minutes <= 13 * 60 + 35


async def run_index_sampler() -> None:
    from ..api.quote_stream import get_quotes_prefer_live

    while True:
        try:
            now = datetime.now()
            client = get_active_client()
            if _in_market_hours(now) and client.status().connected:
                today = now.strftime("%Y-%m-%d")
                with _lock:
                    if not _loaded:
                        _load()
                    if _date != today:
                        _reset_for(today)
                for market, symbol in SAMPLED_INDEXES.items():
                    try:
                        rows = await asyncio.to_thread(get_quotes_prefer_live, [symbol])
                    except YuantaClientError:
                        continue
                    quote = rows[0] if rows else None
                    if quote and quote.deal_price and quote.deal_price > 0:
                        with _lock:
                            _record_sample(market, quote.deal_price, quote.total_volume)
                with _lock:
                    _save()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Index sampler tick failed")
        await asyncio.sleep(SAMPLE_INTERVAL)
