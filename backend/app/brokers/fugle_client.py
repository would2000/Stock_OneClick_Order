"""富果 Fugle MarketData 報價轉接層。

模擬環境（沙盒）以富果真實行情取代合成報價：報價/五檔/分時K線/逐筆成交。
REST 為主（含 TTL 快取以節省 API 額度），之後再補 WebSocket 即時推播。
漲跌停價富果只給布林旗標，這裡以前一日收盤 ±10% 依台股 tick 計算。

未設定 FUGLE_API_KEY 或取資料失敗時，呼叫端可 fallback（回 None / 空），由
mock client 退回合成報價，確保沙盒仍可用。
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any

from ..config import get_settings
from ..trading.schemas import KLinePoint, QuoteResponse, TickRecord

logger = logging.getLogger("fugle")

QUOTE_TTL = 2.0  # 報價快取秒數，避免高頻輪詢打爆富果額度
CANDLE_TTL = 20.0
TRADES_TTL = 5.0


def _tick_size(price: float) -> float:
    if price < 10:
        return 0.01
    if price < 50:
        return 0.05
    if price < 100:
        return 0.1
    if price < 500:
        return 0.5
    if price < 1000:
        return 1.0
    return 5.0


def _round_to_tick(price: float, *, up: bool) -> float:
    """漲停向下取整到 tick、跌停向上取整到 tick（符合台股漲跌停取整慣例）。"""
    tick = _tick_size(price)
    units = price / tick
    rounded = (int(units) if up else (int(units) if units == int(units) else int(units) + 1))
    return round(rounded * tick, 2)


def _limits(prev_close: float) -> tuple[float | None, float | None]:
    if not prev_close or prev_close <= 0:
        return None, None
    up = _round_to_tick(prev_close * 1.1, up=True)
    down = _round_to_tick(prev_close * 0.9, up=False)
    return up, down


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _epoch_to_hms(value: Any) -> str:
    """富果時間欄位為 epoch（微秒）。自動偵測秒/毫秒/微秒/奈秒，轉成 HH:MM:SS。"""
    v = _num(value)
    if not v:
        return ""
    if v > 1e17:
        v /= 1e9  # 奈秒
    elif v > 1e14:
        v /= 1e6  # 微秒
    elif v > 1e11:
        v /= 1e3  # 毫秒
    try:
        return datetime.fromtimestamp(v).strftime("%H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


class FugleMarketData:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._rest = None
        self._lock = threading.Lock()
        self._quote_cache: dict[str, tuple[float, QuoteResponse]] = {}
        self._candle_cache: dict[str, tuple[float, list[KLinePoint]]] = {}
        self._trade_cache: dict[str, tuple[float, list[TickRecord]]] = {}
        self._five_cache: dict[str, dict] = {}
        # ---- WebSocket 即時推播狀態 ----
        self._ws = None
        self._ws_authed = False
        self._desired: set[str] = set()  # 想訂閱的代碼
        self._live: dict[str, QuoteResponse] = {}  # push 維護的即時報價
        self._live_five: dict[str, dict] = {}  # push 維護的五檔
        self._live_ticks: dict[str, deque] = {}  # push 累積的逐筆
        self._serial = 0
        self._live_version = 0
        self._tick_version = 0
        self._five_version = 0
        self._seed_attempt: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.settings.fugle_api_key)

    def _client(self):
        if self._rest is None:
            from fugle_marketdata import RestClient  # noqa: PLC0415

            self._rest = RestClient(api_key=self.settings.fugle_api_key)
        return self._rest

    # ---------- 報價 ----------
    def get_quote(self, symbol: str) -> QuoteResponse | None:
        if not self.enabled:
            return None
        now = time.monotonic()
        cached = self._quote_cache.get(symbol)
        if cached and now - cached[0] < QUOTE_TTL:
            return cached[1].model_copy()
        try:
            raw = self._client().stock.intraday.quote(symbol=symbol)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fugle quote %s 失敗: %s", symbol, exc)
            return cached[1].model_copy() if cached else None
        quote = self._map_quote(symbol, raw)
        if quote is None:
            return cached[1].model_copy() if cached else None
        self._quote_cache[symbol] = (now, quote)
        # 順帶更新五檔快取
        self._five_cache[symbol] = self._five_from_raw(raw)
        return quote.model_copy()

    def _map_quote(self, symbol: str, raw: dict) -> QuoteResponse | None:
        if not isinstance(raw, dict):
            return None
        bids = raw.get("bids") or []
        asks = raw.get("asks") or []
        total = raw.get("total") or {}
        last_trade = raw.get("lastTrade") or {}
        # 盤後 lastPrice 會是 null，改用 closePrice 顯示最後值（指數亦同）。
        deal = _num(raw.get("lastPrice")) or _num(last_trade.get("price")) or _num(raw.get("closePrice"))
        prev_close = _num(raw.get("previousClose"))
        up_limit, down_limit = _limits(prev_close or 0.0)
        market = str(raw.get("market") or raw.get("exchange") or "").upper()
        market = "TWOTC" if market in ("OTC", "TPEX", "TWOTC") else "TWSE"
        return QuoteResponse(
            market=market,
            symbol=symbol,
            name=str(raw.get("name") or ""),
            deal_price=deal,
            prev_close=prev_close,
            open_price=_num(raw.get("openPrice")),
            high_price=_num(raw.get("highPrice")),
            low_price=_num(raw.get("lowPrice")),
            bid_price=_num(bids[0].get("price")) if bids else None,
            bid_volume=int(_num(bids[0].get("size")) or 0) if bids else None,
            ask_price=_num(asks[0].get("price")) if asks else None,
            ask_volume=int(_num(asks[0].get("size")) or 0) if asks else None,
            total_volume=int(_num(total.get("tradeVolume")) or 0),
            up_limit=up_limit,
            down_limit=down_limit,
            source="fugle",
        )

    # ---------- 五檔 ----------
    def get_five_ticks(self, symbol: str) -> dict | None:
        if not self.enabled:
            return None
        if symbol not in self._five_cache:
            self.get_quote(symbol)  # 觸發一次抓取以填五檔
        return self._five_cache.get(symbol)

    def _five_from_raw(self, raw: dict) -> dict:
        def level(items):
            out = []
            for item in (items or [])[:5]:
                price = _num(item.get("price"))
                size = int(_num(item.get("size")) or 0)
                if price:
                    out.append({"price": price, "volume": size})
            return out

        return {"bids": level(raw.get("bids")), "asks": level(raw.get("asks"))}

    # ---------- 分時 K 線 ----------
    def get_candles(self, symbol: str) -> list[KLinePoint]:
        if not self.enabled:
            return []
        now = time.monotonic()
        cached = self._candle_cache.get(symbol)
        if cached and now - cached[0] < CANDLE_TTL:
            return list(cached[1])
        try:
            raw = self._client().stock.intraday.candles(symbol=symbol, timeframe="1")
        except Exception as exc:  # noqa: BLE001
            logger.warning("fugle candles %s 失敗: %s", symbol, exc)
            return list(cached[1]) if cached else []
        rows: list[KLinePoint] = []
        for item in (raw.get("data") if isinstance(raw, dict) else raw) or []:
            try:
                rows.append(
                    KLinePoint(
                        timestamp=str(item.get("date") or item.get("time") or ""),
                        open=_num(item.get("open")) or 0.0,
                        high=_num(item.get("high")) or 0.0,
                        low=_num(item.get("low")) or 0.0,
                        close=_num(item.get("close")) or 0.0,
                        volume=int(_num(item.get("volume")) or 0),
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        self._candle_cache[symbol] = (now, rows)
        return list(rows)

    # ---------- 逐筆成交 ----------
    def get_trades(self, symbol: str, limit: int = 5000) -> list[TickRecord]:
        if not self.enabled:
            return []
        now = time.monotonic()
        cached = self._trade_cache.get(symbol)
        if cached and now - cached[0] < TRADES_TTL:
            return cached[1][-limit:]
        try:
            raw = self._client().stock.intraday.trades(symbol=symbol, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fugle trades %s 失敗: %s", symbol, exc)
            return cached[1][-limit:] if cached else []
        rows: list[TickRecord] = []
        for index, item in enumerate((raw.get("data") if isinstance(raw, dict) else raw) or []):
            try:
                rows.append(
                    TickRecord(
                        symbol=symbol,
                        serial=int(_num(item.get("serial")) or index),
                        time=_epoch_to_hms(item.get("time")),
                        bid_price=_num(item.get("bid")),
                        ask_price=_num(item.get("ask")),
                        deal_price=_num(item.get("price")),
                        volume=int(_num(item.get("size")) or 0),
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        self._trade_cache[symbol] = (now, rows)
        return rows[-limit:]

    # ---------- WebSocket 即時推播 ----------
    def _channels_for(self, symbol: str) -> list[tuple[str, str]]:
        if symbol.upper().startswith("IX"):
            return [("indices", symbol)]
        return [("trades", symbol), ("books", symbol)]

    def _ensure_ws(self) -> None:
        if self._ws is not None or not self.enabled:
            return
        try:
            from fugle_marketdata import WebSocketClient  # noqa: PLC0415

            ws = WebSocketClient(api_key=self.settings.fugle_api_key)
            stock = ws.stock
            stock.on("authenticated", lambda *a: self._on_ws_auth())
            stock.on("message", self._on_ws_message)
            stock.on("error", lambda e: logger.warning("fugle ws error: %s", str(e)[:120]))
            stock.connect()
            self._ws = ws
        except Exception as exc:  # noqa: BLE001
            logger.warning("fugle ws 啟動失敗: %s", exc)
            self._ws = None

    def _ws_subscribe(self, symbol: str) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            for channel, sym in self._channels_for(symbol):
                ws.stock.subscribe({"channel": channel, "symbol": sym})
        except Exception as exc:  # noqa: BLE001
            logger.warning("fugle ws subscribe %s 失敗: %s", symbol, exc)

    def _on_ws_auth(self) -> None:
        self._ws_authed = True
        for symbol in list(self._desired):  # 連線/重連後重訂閱
            self._ws_subscribe(symbol)

    def _on_ws_message(self, message: Any) -> None:
        try:
            import json  # noqa: PLC0415

            msg = json.loads(message) if isinstance(message, str) else message
            if not isinstance(msg, dict):
                return
            event = msg.get("event")
            if event == "authenticated":
                self._on_ws_auth()
                return
            if event not in ("snapshot", "data"):
                return
            channel = msg.get("channel")
            data = msg.get("data") or {}
            symbol = str(data.get("symbol") or "")
            if not symbol:
                return
            with self._lock:
                quote = self._live.get(symbol)
                if channel == "trades":
                    price = _num(data.get("price"))
                    volume = _num(data.get("volume"))
                    if quote is not None:
                        if price:
                            quote.deal_price = price
                            if quote.high_price is None or price > quote.high_price:
                                quote.high_price = price
                            if quote.low_price is None or price < quote.low_price:
                                quote.low_price = price
                        if volume:
                            quote.total_volume = int(volume)
                        if data.get("bid"):
                            quote.bid_price = _num(data.get("bid"))
                        if data.get("ask"):
                            quote.ask_price = _num(data.get("ask"))
                        quote.source = "fugle-ws"
                    buf = self._live_ticks.setdefault(symbol, deque(maxlen=8000))
                    self._serial += 1
                    buf.append(
                        TickRecord(
                            symbol=symbol,
                            serial=self._serial,
                            time=_epoch_to_hms(data.get("time")),
                            bid_price=_num(data.get("bid")),
                            ask_price=_num(data.get("ask")),
                            deal_price=price,
                            volume=int(_num(data.get("size")) or 0),
                        )
                    )
                    self._live_version += 1
                    self._tick_version += 1
                elif channel == "books":
                    bids = data.get("bids") or []
                    asks = data.get("asks") or []
                    self._live_five[symbol] = self._five_from_raw(data)
                    if quote is not None:
                        if bids:
                            quote.bid_price = _num(bids[0].get("price"))
                            quote.bid_volume = int(_num(bids[0].get("size")) or 0)
                        if asks:
                            quote.ask_price = _num(asks[0].get("price"))
                            quote.ask_volume = int(_num(asks[0].get("size")) or 0)
                    self._five_version += 1
                    self._live_version += 1
                elif channel == "indices":
                    idx = _num(data.get("index"))
                    if quote is not None and idx:
                        quote.deal_price = idx
                        quote.source = "fugle-ws"
                    self._live_version += 1
        except Exception:  # noqa: BLE001
            pass

    def subscribe(self, symbols: list[str]) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        for symbol in symbols:
            if not symbol:
                continue
            first = symbol not in self._desired
            # REST 種子（含前收/開高低/漲跌停/名稱）；失敗時節流每 15 秒最多重試一次，
            # 避免速率限制時反覆打 REST。WS 之後即時 patch 此種子。
            if symbol not in self._live and now - self._seed_attempt.get(symbol, 0.0) > 15:
                self._seed_attempt[symbol] = now
                seed = self.get_quote(symbol)
                if seed is not None:
                    with self._lock:
                        self._live[symbol] = seed
            if first:
                self._desired.add(symbol)
                self._ensure_ws()
                if self._ws_authed:
                    self._ws_subscribe(symbol)

    def unsubscribe(self, symbols: list[str]) -> None:
        ws = self._ws
        for symbol in symbols:
            self._desired.discard(symbol)
            with self._lock:
                self._live.pop(symbol, None)
                self._live_five.pop(symbol, None)
                self._live_ticks.pop(symbol, None)
            if ws is not None:
                try:
                    for channel, sym in self._channels_for(symbol):
                        ws.stock.unsubscribe({"channel": channel, "symbol": sym})
                except Exception:  # noqa: BLE001
                    pass

    def get_live(self, symbols: list[str]) -> list[QuoteResponse]:
        with self._lock:
            return [self._live[s].model_copy() for s in symbols if s in self._live]

    def get_live_five(self, symbol: str) -> dict | None:
        with self._lock:
            book = self._live_five.get(symbol)
            if book:
                return {"bids": list(book["bids"]), "asks": list(book["asks"])}
        return self.get_five_ticks(symbol)

    def get_live_ticks(self, symbol: str, limit: int = 50) -> list[TickRecord]:
        with self._lock:
            buf = self._live_ticks.get(symbol)
            return list(buf)[-limit:] if buf else []

    @property
    def subscribed(self) -> set[str]:
        return set(self._desired)

    @property
    def live_version(self) -> int:
        return self._live_version

    @property
    def tick_version(self) -> int:
        return self._tick_version

    @property
    def five_version(self) -> int:
        return self._five_version

    def close(self) -> None:
        """best-effort 關閉 WS 連線（設定變更/重置時用），避免舊金鑰的連線殘留。"""
        ws = self._ws
        self._ws = None
        self._ws_authed = False
        if ws is not None:
            try:
                ws.stock.disconnect()
            except Exception:  # noqa: BLE001
                pass


_fugle: FugleMarketData | None = None


def get_fugle() -> FugleMarketData:
    global _fugle
    if _fugle is None:
        _fugle = FugleMarketData()
    return _fugle


def reset_fugle() -> None:
    """丟棄目前的 Fugle 單例（含快取的 REST/WS），下次取用時以最新設定（如新 API key）重建。"""
    global _fugle
    if _fugle is not None:
        _fugle.close()
    _fugle = None
