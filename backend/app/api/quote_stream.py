"""Realtime quote streaming over WebSocket.

A single background poll loop fetches the union of all subscribed symbols
through the (serialized) Yuanta SDK bridge and broadcasts to every client,
so N browser tabs cost one SDK round-trip per tick instead of N.
"""

import asyncio
import os
import secrets
import time
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import get_settings
from ..trading.schemas import QuoteResponse
from ..broker import get_active_client
from ..yuanta.client import YuantaClientError

stream_router = APIRouter()

POLL_INTERVAL = float(os.getenv("QUOTE_STREAM_INTERVAL", "1.0"))
# How often the broadcaster flushes the push-fed cache to WebSocket clients.
PUSH_FLUSH_INTERVAL = float(os.getenv("QUOTE_STREAM_PUSH_INTERVAL", "0.25"))
IDLE_INTERVAL = float(os.getenv("QUOTE_STREAM_IDLE_INTERVAL", "3.0"))
MAX_SYMBOLS = 30


def in_market_hours(now: datetime | None = None) -> bool:
    """Trading window (with margin) — outside it, background pollers must not
    hold the serialized SDK lock with doomed quote queries."""
    moment = now or datetime.now()
    if moment.weekday() >= 5:
        return False
    minutes = moment.hour * 60 + moment.minute
    return 8 * 60 + 45 <= minutes <= 14 * 60 + 5


def fetch_quotes_both_markets(symbols: list[str], market: str = "TWSE") -> list[QuoteResponse]:
    """Fetch quotes trying the requested market first, then the alternate one."""
    client = get_active_client()
    markets = [market, "TWOTC" if market == "TWSE" else "TWSE"]
    quotes_by_symbol: dict[str, QuoteResponse] = {}
    missing = list(symbols)
    for query_market in markets:
        if not missing:
            break
        rows = client.get_quotes(missing, query_market)
        quotes_by_symbol.update({row.symbol: row for row in rows})
        missing = [symbol for symbol in symbols if symbol not in quotes_by_symbol]
    return [quotes_by_symbol[symbol] for symbol in symbols if symbol in quotes_by_symbol]


def get_quotes_prefer_live(symbols: list[str]) -> list[QuoteResponse]:
    """Serve from the push-fed cache; fall back to an SDK query for the rest.

    Symbols not yet subscribed get subscribed here, so subsequent calls are
    answered from memory at push latency.
    """
    client = get_active_client()
    try:
        client.subscribe_quotes(symbols)
    except YuantaClientError:
        pass
    rows = client.get_live_quotes(symbols)
    missing = [symbol for symbol in symbols if symbol not in {row.symbol for row in rows}]
    if missing:
        rows += fetch_quotes_both_markets(missing)
    return rows


class QuoteBroadcaster:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, set[str]] = {}
        self._tick_symbols: dict[WebSocket, str] = {}
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        # Symbols we already tried to seed after hours — one attempt each, so
        # a dead symbol can't recreate the after-hours SDK polling jam.
        self._after_hours_seeded: set[str] = set()

    async def register(self, websocket: WebSocket, subprotocol: str | None = None) -> None:
        await websocket.accept(subprotocol=subprotocol)
        async with self._lock:
            self._clients[websocket] = set()
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._poll_loop())

    async def subscribe(self, websocket: WebSocket, symbols: list[str], tick_symbol: str = "") -> None:
        cleaned = [item.strip() for item in symbols if item and item.strip()][:MAX_SYMBOLS]
        async with self._lock:
            if websocket in self._clients:
                self._clients[websocket] = set(cleaned)
                tick = tick_symbol.strip()
                if tick:
                    self._tick_symbols[websocket] = tick
                else:
                    self._tick_symbols.pop(websocket, None)

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.pop(websocket, None)
            self._tick_symbols.pop(websocket, None)

    async def _snapshot(self) -> tuple[list[WebSocket], list[str], list[str]]:
        async with self._lock:
            sockets = list(self._clients.keys())
            symbols: set[str] = set()
            for subscribed in self._clients.values():
                symbols.update(subscribed)
            tick_symbols = sorted(set(self._tick_symbols.values()))
            return sockets, sorted(symbols), tick_symbols

    async def _broadcast(self, sockets: list[WebSocket], payload: dict) -> None:
        for websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:
                await self.unregister(websocket)

    async def _poll_loop(self) -> None:
        last_version = -1
        last_tick_version = -1
        last_tick_symbols: list[str] = []
        last_five_version = -1
        last_full_push = 0.0
        while True:
            sockets, symbols, tick_symbols = await self._snapshot()
            if not sockets:
                return
            client = get_active_client()
            if not symbols or not client.status().connected:
                await self._broadcast(sockets, {"type": "status", "connected": client.status().connected})
                await asyncio.sleep(IDLE_INTERVAL)
                continue
            if not in_market_hours():
                # After hours: serve the cache; allow a single seeding attempt
                # per unseen symbol so a freshly searched stock still shows
                # its closing quote instead of an empty ladder.
                rows = client.get_live_quotes(symbols)
                cached = {row.symbol for row in rows}
                fresh = [s for s in symbols if s not in cached and s not in self._after_hours_seeded]
                if fresh:
                    self._after_hours_seeded.update(fresh)
                    try:
                        rows += await asyncio.to_thread(get_quotes_prefer_live, fresh)
                    except YuantaClientError:
                        pass
                if rows:
                    await self._broadcast(sockets, {"type": "quotes", "data": [row.model_dump() for row in rows]})
                # Short cadence: cache reads are free, and a newly searched
                # symbol must show its quote within seconds, not 30s.
                await asyncio.sleep(3)
                continue
            try:
                # Keep SDK push subscriptions in sync with the union of all
                # client subscriptions, then flush the in-memory cache.
                desired = set(symbols)
                current = client.subscribed_symbols
                stale = sorted(current - desired)
                if stale:
                    await asyncio.to_thread(client.unsubscribe_quotes, stale)
                rows = await asyncio.to_thread(get_quotes_prefer_live, symbols)
                version = client.live_version
                now = time.monotonic()
                # Skip the frame when nothing moved, but emit a heartbeat
                # frame at least once per POLL_INTERVAL.
                if version != last_version or now - last_full_push >= POLL_INTERVAL:
                    last_version = version
                    last_full_push = now
                    await self._broadcast(
                        sockets,
                        {"type": "quotes", "data": [row.model_dump() for row in rows]},
                    )

                # Subscribe ticks for every watched symbol (not just the one
                # being displayed) so the backend accumulates a gap-free
                # full-day buffer per symbol; switching charts only changes
                # which buffer gets broadcast.
                tick_targets = {symbol for symbol in set(symbols) | set(tick_symbols) if not symbol.startswith("IX")}
                current_ticks = client.tick_subscribed_symbols
                for symbol in tick_targets - current_ticks:
                    await asyncio.to_thread(client.subscribe_ticks, symbol)
                for symbol in current_ticks - tick_targets:
                    await asyncio.to_thread(client.unsubscribe_ticks, symbol)
                tick_version = client.tick_version
                tick_selection_changed = tick_symbols != last_tick_symbols
                if tick_symbols and (tick_version != last_tick_version or tick_selection_changed):
                    last_tick_version = tick_version
                    last_tick_symbols = list(tick_symbols)
                    for symbol in tick_symbols:
                        # Full-day snapshot when the user switches symbol;
                        # a small tail window for routine updates.
                        ticks = client.get_ticks(symbol, limit=8000 if tick_selection_changed else 500)
                        await self._broadcast(
                            sockets,
                            {"type": "ticks", "symbol": symbol, "data": [tick.model_dump() for tick in ticks]},
                        )
                # Five-level order book follows the displayed symbol(s).
                five_targets = {symbol for symbol in tick_symbols if not symbol.startswith("IX")}
                current_five = client.five_tick_subscribed_symbols
                for symbol in five_targets - current_five:
                    await asyncio.to_thread(client.subscribe_five_ticks, symbol)
                for symbol in current_five - five_targets:
                    await asyncio.to_thread(client.unsubscribe_five_ticks, symbol)
                five_version = client.five_tick_version
                if five_targets and (five_version != last_five_version or tick_selection_changed):
                    last_five_version = five_version
                    for symbol in five_targets:
                        book = client.get_five_ticks(symbol)
                        if book:
                            await self._broadcast(sockets, {"type": "fivetick", "symbol": symbol, "data": book})
            except YuantaClientError as exc:
                await self._broadcast(sockets, {"type": "error", "message": str(exc)})
                await asyncio.sleep(IDLE_INTERVAL)
                continue
            await asyncio.sleep(PUSH_FLUSH_INTERVAL)


broadcaster = QuoteBroadcaster()


@stream_router.websocket("/api/ws/quotes")
async def quotes_websocket(websocket: WebSocket) -> None:
    # 認證：金鑰以 WebSocket subprotocol 夾帶（避免寫進 URL 被 log）。未通過則拒絕握手。
    expected = get_settings().api_key
    offered = websocket.scope.get("subprotocols") or []
    provided = offered[0] if offered else ""
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        await websocket.close(code=1008)  # policy violation
        return
    await broadcaster.register(websocket, subprotocol=provided)
    try:
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict) and isinstance(message.get("symbols"), list):
                await broadcaster.subscribe(
                    websocket,
                    [str(item) for item in message["symbols"]],
                    str(message.get("tick_symbol", "") or ""),
                )
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.unregister(websocket)
