from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

from ..config import get_settings
from collections import deque

from ..trading.schemas import (
    KLinePoint,
    OrderRequest,
    OrderResult,
    Position,
    QuoteResponse,
    TickRecord,
    TradeRecord,
    WorkingOrder,
    YuantaStatus,
)


def resolve_sdk_dir(root: Path) -> Path:
    """選出元大 SDK 資料夾：環境變數 YUANTA_SDK_DIR > 平台慣用名 > 自動探索。

    元大各平台 SDK 的資料夾名稱不同，這裡避免寫死單一平台。
    （與 yuanta_smoke_test.py 內的同名函式保持一致。）
    """
    override = os.environ.get("YUANTA_SDK_DIR", "").strip()
    if override:
        path = Path(override).expanduser()
        return path if path.is_absolute() else root / path

    machine = platform.machine().lower()
    system = platform.system()
    if system == "Darwin":
        preferred = (
            "YuantaSparkAPI_osx-arm64_Python"
            if machine in ("arm64", "aarch64")
            else "YuantaSparkAPI_osx-x64_Python"
        )
    elif system == "Windows":
        preferred = "YuantaSparkAPI_win-x64_Python"
    elif system == "Linux":
        preferred = "YuantaSparkAPI_linux-x64_Python"
    else:
        preferred = "YuantaSparkAPI_osx-arm64_Python"

    if (root / preferred).is_dir():
        return root / preferred
    # 後備：抓專案內任何 YuantaSparkAPI_*_Python 目錄
    for candidate in sorted(root.glob("YuantaSparkAPI_*_Python")):
        if candidate.is_dir():
            return candidate
    # 都找不到 → 回傳平台慣用名，交由呼叫端的存在性檢查輸出明確錯誤
    return root / preferred


def _read_int_attr(obj: Any, names: tuple[str, ...]) -> int | None:
    """從 .NET 物件取第一個存在且可轉 int 的屬性（不分大小寫）。

    元大的日期/時間欄位是自訂結構（TYuantaDate / TYuantaTime），直接 str() 只會拿到
    型別名，必須改取子屬性（Year/Month/Day、Hour/Minute/Second）。
    """
    if obj is None:
        return None
    available = {a.lower(): a for a in dir(obj) if not a.startswith("_")}
    for name in names:
        attr = available.get(name.lower())
        if attr is None:
            continue
        try:
            return int(getattr(obj, attr))
        except (TypeError, ValueError):
            continue
    return None


def _format_yuanta_stamp(date_obj: Any, time_obj: Any) -> str:
    """把元大委託回報的 AcceptDate/AcceptTime 轉成 'YYYY-MM-DD HH:MM:SS'。

    - 結構型（TYuantaDate/TYuantaTime）：取 Year/Month/Day、Hour/Minute/Second 子屬性。
    - 純值型（部分環境直接回字串/數字）：直接採用。
    - 取不到就回空字串——絕不把 .NET 型別名（YuantaOneAPI.TYuantaXxx）顯示給使用者。
    """

    def _plain(value: Any) -> str | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            text = value.strip()
            if text and "YuantaOneAPI" not in text:
                return text
        return None

    plain_date, plain_time = _plain(date_obj), _plain(time_obj)
    if plain_date or plain_time:
        return f"{plain_date or ''} {plain_time or ''}".strip()

    # 真實欄位名（經實機 dir() 確認）：TYuantaDate=ushtYear/bytMon/bytDay、
    # TYuantaTime=bytHour/bytMin/bytSec；其餘為其他環境的備援候選。
    year = _read_int_attr(date_obj, ("ushtYear", "Year", "yyyy", "sYear", "bytYear"))
    month = _read_int_attr(date_obj, ("bytMon", "Month", "mm", "bytMonth"))
    day = _read_int_attr(date_obj, ("bytDay", "Day", "dd"))
    hour = _read_int_attr(time_obj, ("bytHour", "Hour", "hh"))
    minute = _read_int_attr(time_obj, ("bytMin", "Minute", "min", "bytMinute"))
    second = _read_int_attr(time_obj, ("bytSec", "Second", "sec", "ss", "bytSecond"))

    if year is not None and 0 < year < 1911:  # 萬一回的是民國年，補成西元年。
        year += 1911

    date_part = (
        f"{year:04d}-{month:02d}-{day:02d}"
        if None not in (year, month, day)
        else ""
    )
    time_part = (
        f"{hour:02d}:{minute:02d}:{second:02d}"
        if None not in (hour, minute, second)
        else ""
    )
    return f"{date_part} {time_part}".strip()


class YuantaClientError(RuntimeError):
    pass


class YuantaClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.root = self.settings.project_root
        self.sdk_dir = resolve_sdk_dir(self.root)
        self.dotnet_root = self.root / ".dotnet"
        self.runtime_config = self.root / "pythonnet.runtimeconfig.json"
        self._bootstrapped = False
        self._lifecycle_lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._api: Any | None = None
        self._event_handler: Any | None = None
        self._login_event: threading.Event | None = None
        self._pending_action: str | None = None
        self._pending_event: threading.Event | None = None
        self._pending_payload: Any | None = None
        self._state = "disconnected"
        self._connected = False
        self._account_name = ""
        self._last_error = ""
        self._live_lock = threading.Lock()
        self._live_quotes: dict[str, QuoteResponse] = {}
        self._subscribed: set[str] = set()
        self._live_version = 0
        self._ticks: dict[str, deque[TickRecord]] = {}
        self._tick_subscribed: set[str] = set()
        self._tick_version = 0
        self._tick_date = ""
        self._five_ticks: dict[str, dict] = {}
        self._five_subscribed: set[str] = set()
        self._five_version = 0

    def _require_config(self) -> None:
        missing = [
            key
            for key, value in {
                "YUANTA_ACCOUNT": self.settings.yuanta_account,
                "YUANTA_PASSWORD": self.settings.yuanta_password,
                "YUANTA_CERT_PATH": self.settings.yuanta_cert_path,
                "YUANTA_CERT_PASSWORD": self.settings.yuanta_cert_password,
            }.items()
            if not value
        ]
        if missing:
            raise YuantaClientError(f"Missing Yuanta configuration: {', '.join(missing)}")

        cert_path = Path(self.settings.yuanta_cert_path).expanduser()
        if not cert_path.exists():
            raise YuantaClientError(f"Certificate not found: {cert_path}")

    def _bootstrap_dotnet(self) -> None:
        if self._bootstrapped:
            return

        if not self.sdk_dir.exists():
            raise YuantaClientError(f"SDK folder not found: {self.sdk_dir}")
        if not self.dotnet_root.exists():
            raise YuantaClientError("Missing .dotnet runtime. See README.md installation steps.")

        from pythonnet import load  # noqa: PLC0415

        sys.path.append(str(self.sdk_dir))
        os.environ.setdefault("PYTHONNET_RUNTIME", "coreclr")
        os.environ.setdefault("DOTNET_ROOT", str(self.dotnet_root))
        os.environ["PATH"] = f"{self.dotnet_root}{os.pathsep}{os.environ.get('PATH', '')}"
        load("coreclr", runtime_config=str(self.runtime_config), dotnet_root=str(self.dotnet_root))

        import clr  # noqa: PLC0415

        clr.AddReference("System.Collections")
        clr.AddReference("YuantaSparkAPI")
        self._bootstrapped = True

    def _check_certificate_password(self) -> None:
        openssl = shutil.which("openssl")
        if not openssl:
            return

        cert_path = Path(self.settings.yuanta_cert_path).expanduser().resolve()
        result = subprocess.run(
            [openssl, "pkcs12", "-in", str(cert_path), "-nokeys", "-noout", "-passin", "stdin"],
            input=f"{self.settings.yuanta_cert_password}\n",
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip().splitlines()[0] if result.stderr.strip() else "invalid password"
            raise YuantaClientError(f"Certificate password check failed: {message}")

    def _environment_mode(self):
        from YuantaOneAPI import enumEnvironmentMode  # noqa: PLC0415

        value = self.settings.yuanta_env.upper()
        if value == "PROD":
            return enumEnvironmentMode.PROD
        if value == "UAT":
            return enumEnvironmentMode.UAT
        raise YuantaClientError("YUANTA_ENV must be UAT or PROD.")

    def _market_type(self, market: str):
        from YuantaOneAPI import enumMarketType  # noqa: PLC0415

        return getattr(enumMarketType, (market or self.settings.default_market).upper())

    def _kline_type(self, value: str):
        from YuantaOneAPI import KLineType  # noqa: PLC0415

        aliases = {
            "1M": 0,
            "5M": 1,
            "15M": 2,
            "30M": 3,
            "60M": 4,
            "DAY": 11,
            "D": 11,
            "DAILY": 11,
            "WEEK": 12,
            "W": 12,
            "MONTH": 13,
            "M": 13,
        }
        raw = value.strip().upper()
        if raw in aliases:
            return KLineType(aliases[raw])
        return KLineType(int(raw))

    def _on_response(self, int_mark, dw_index, str_index, obj_handle, obj_value):
        if str_index == "Login":
            status = obj_value.LoginStatus
            self._connected = getattr(status, "Count", 0) > 0
            if self._connected:
                self._state = "connected"
                self._last_error = ""
                first = obj_value.LoginList[0] if obj_value.LoginList.Count else None
                self._account_name = str(first.Name) if first is not None else ""
            else:
                self._state = "error"
                self._last_error = f"{getattr(status, 'MsgCode', '')} {getattr(status, 'MsgContent', '')}".strip()

            if self._login_event is not None:
                self._login_event.set()
            return

        if str_index == "SubscribeWatchlistAll":
            self._apply_quote_push(obj_value)
            return

        if str_index == "SubscribeStockTick":
            self._apply_tick_push(obj_value)
            return

        if str_index == "SubscribeFiveTickA":
            self._apply_five_tick_push(obj_value)
            return

        if self._pending_action == str_index:
            self._pending_payload = obj_value
            if self._pending_event is not None:
                self._pending_event.set()

    @staticmethod
    def _push_flag(result: Any) -> int:
        text = str(result.IndexFlag)
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else -1

    @staticmethod
    def _normalize_price(value: float, quote: QuoteResponse) -> float | None:
        # Push frames use a different decimal scale than the snapshot for some
        # symbols (observed: index pushes arrive /100). Rescale by powers of
        # 100 until the value is in the same ballpark as the reference price.
        if value <= 0:
            return None
        reference = (
            quote.prev_close
            if quote.prev_close and quote.prev_close > 0
            else quote.deal_price if quote.deal_price and quote.deal_price > 0 else None
        )
        if reference:
            for _ in range(2):
                ratio = value / reference
                if ratio < 0.05:
                    value *= 100
                elif ratio > 20:
                    value /= 100
                else:
                    break
            if not (0.05 <= value / reference <= 20):
                return None  # Still implausible: drop the frame.
        return value

    def _apply_tick_push(self, result: Any) -> None:
        try:
            symbol = str(result.StkCode)
            today = datetime.now().strftime("%Y-%m-%d")
            with self._live_lock:
                if self._tick_date != today:
                    # Date rollover: drop yesterday's buffers.
                    for buffered in self._ticks.values():
                        buffered.clear()
                    self._tick_date = today
                buffer = self._ticks.get(symbol)
                if buffer is None:
                    return
                quote = self._live_quotes.get(symbol)
                reference = quote or QuoteResponse(market="", symbol=symbol, source="tick")
                tick_time = result.Time
                time_text = f"{int(tick_time.bytHour):02d}:{int(tick_time.bytMin):02d}:{int(tick_time.bytSec):02d}"
                deal = self._normalize_price(float(result.DealPrice), reference)
                bid = self._normalize_price(float(result.BuyPrice), reference)
                ask = self._normalize_price(float(result.SellPrice), reference)
                try:
                    serial = int(result.SerialNo)
                except Exception:
                    serial = 0
                if serial and buffer and buffer[-1].serial and serial <= buffer[-1].serial:
                    return  # Already covered by the backfilled history.
                buffer.append(
                    TickRecord(
                        symbol=symbol,
                        serial=serial,
                        time=time_text,
                        bid_price=bid,
                        ask_price=ask,
                        deal_price=deal,
                        volume=int(result.DealVol),
                        in_out=str(result.InOutFlag),
                    )
                )
                self._tick_version += 1
        except Exception:
            pass

    @property
    def tick_version(self) -> int:
        return self._tick_version

    @property
    def tick_subscribed_symbols(self) -> set[str]:
        with self._live_lock:
            return set(self._tick_subscribed)

    def get_ticks(self, symbol: str, limit: int = 50) -> list[TickRecord]:
        with self._live_lock:
            buffer = self._ticks.get(symbol)
            if not buffer:
                return []
            return list(buffer)[-limit:]

    def _tick_request_items(self, symbols: list[str]):
        from System.Collections.Generic import List  # noqa: PLC0415
        from YuantaOneAPI import StockTick  # noqa: PLC0415

        items = List[StockTick]()
        with self._live_lock:
            for symbol in symbols:
                tick = StockTick()
                quote = self._live_quotes.get(symbol)
                try:
                    tick.MarketType = self._market_type(quote.market if quote else "TWSE")
                except Exception:
                    tick.MarketType = self._market_type("TWSE")
                tick.StockCode = symbol
                items.Add(tick)
        return items

    def _apply_five_tick_push(self, result: Any) -> None:
        try:
            symbol = str(result.StkCode)
            flag = self._push_flag(result)
            with self._live_lock:
                if symbol not in self._five_subscribed:
                    return
                book = self._five_ticks.setdefault(symbol, {"bids": [], "asks": []})
                quote = self._live_quotes.get(symbol)
                reference = quote or QuoteResponse(market="", symbol=symbol, source="fivetick")

                def levels(payload: Any, price_attr: str, vol_attr: str) -> list[dict]:
                    rows = []
                    for level in range(1, 6):
                        raw_price = float(getattr(payload, f"{price_attr}{level}", 0) or 0)
                        price = self._normalize_price(raw_price, reference)
                        volume = int(getattr(payload, f"{vol_attr}{level}", 0) or 0)
                        rows.append({"price": price, "volume": volume})
                    return rows

                if flag in (50, 51):
                    payload = getattr(result, f"IndexFlag_{flag}")
                    book["bids"] = levels(payload, "BuyPrice", "BuyVol")
                    book["asks"] = levels(payload, "SellPrice", "SellVol")
                elif flag in (20, 42):  # buy-side update
                    payload = getattr(result, f"IndexFlag_{flag}")
                    book["bids"] = levels(payload, "Price", "Vol")
                elif flag in (21, 43):  # sell-side update
                    payload = getattr(result, f"IndexFlag_{flag}")
                    book["asks"] = levels(payload, "Price", "Vol")
                else:
                    return
                self._five_version += 1
        except Exception:
            pass

    @property
    def five_tick_version(self) -> int:
        return self._five_version

    @property
    def five_tick_subscribed_symbols(self) -> set[str]:
        with self._live_lock:
            return set(self._five_subscribed)

    def get_five_ticks(self, symbol: str) -> dict | None:
        with self._live_lock:
            book = self._five_ticks.get(symbol)
            return {"bids": list(book["bids"]), "asks": list(book["asks"])} if book else None

    def _five_tick_request_items(self, symbols: list[str]):
        from System.Collections.Generic import List  # noqa: PLC0415
        from YuantaOneAPI import FiveTickA  # noqa: PLC0415

        items = List[FiveTickA]()
        with self._live_lock:
            for symbol in symbols:
                item = FiveTickA()
                quote = self._live_quotes.get(symbol)
                try:
                    item.MarketType = self._market_type(quote.market if quote else "TWSE")
                except Exception:
                    item.MarketType = self._market_type("TWSE")
                item.StockCode = symbol
                items.Add(item)
        return items

    def subscribe_five_ticks(self, symbol: str) -> None:
        self._ensure_connected()
        if symbol in self.five_tick_subscribed_symbols:
            return
        self.subscribe_quotes([symbol])
        items = self._five_tick_request_items([symbol])
        with self._request_lock:
            if self._api is None:
                raise YuantaClientError("Yuanta API is not connected.")
            self._api.SubscribeFiveTickA(self.settings.yuanta_account, items)
        with self._live_lock:
            self._five_subscribed.add(symbol)

    def unsubscribe_five_ticks(self, symbol: str) -> None:
        if symbol not in self.five_tick_subscribed_symbols or self._api is None:
            return
        items = self._five_tick_request_items([symbol])
        with self._request_lock:
            if self._api is None:
                return
            self._api.UnSubscribeFiveTickA(self.settings.yuanta_account, items)
        with self._live_lock:
            self._five_subscribed.discard(symbol)
            self._five_ticks.pop(symbol, None)

    @staticmethod
    def _tick_time_text(ts: Any) -> str:
        for attrs in (("bytHour", "bytMin", "bytSec"), ("Hour", "Minute", "Second")):
            if all(hasattr(ts, attr) for attr in attrs):
                hour, minute, second = (int(getattr(ts, attr)) for attr in attrs)
                return f"{hour:02d}:{minute:02d}:{second:02d}"
        text = str(ts)
        return text[:8] if ":" in text else text

    def get_tick_detail(self, symbol: str, market: str, select_type: int = 1, count: int = 5000) -> list[TickRecord]:
        """Query the full intraday time-and-sales history for a symbol."""
        payload = self._run_action(
            "GetStkTickDetail", wait=10.0, symbol=symbol, market=market, select_type=select_type, count=count
        )
        with self._live_lock:
            quote = self._live_quotes.get(symbol)
        reference = quote or QuoteResponse(market=market, symbol=symbol, source="tick")
        rows: list[TickRecord] = []
        for item in payload.StickDetailList:
            try:
                rows.append(
                    TickRecord(
                        symbol=symbol,
                        serial=int(item.SeqNo),
                        time=self._tick_time_text(item.TimeStamp),
                        bid_price=self._normalize_price(float(item.BuyPrice), reference),
                        ask_price=self._normalize_price(float(item.SellPrice), reference),
                        deal_price=self._normalize_price(float(item.DealPrice), reference),
                        volume=int(item.DealVol),
                        in_out=str(item.InOutFlag),
                    )
                )
            except Exception:
                continue
        rows.sort(key=lambda row: row.serial)
        return rows

    def _merge_tick_history(self, symbol: str, history: list[TickRecord]) -> None:
        if not history:
            return
        with self._live_lock:
            buffer = self._ticks.get(symbol)
            if buffer is None:
                return
            merged: dict[int, TickRecord] = {tick.serial: tick for tick in history if tick.serial}
            extra = [tick for tick in buffer if not tick.serial]
            for tick in buffer:
                if tick.serial:
                    merged[tick.serial] = tick
            combined = sorted(merged.values(), key=lambda tick: tick.serial) + extra
            buffer.clear()
            buffer.extend(combined[-buffer.maxlen :] if buffer.maxlen else combined)
            self._tick_version += 1

    def subscribe_ticks(self, symbol: str) -> None:
        self._ensure_connected()
        if symbol in self.tick_subscribed_symbols:
            return
        # Quote subscription seeds the market lookup used to route the tick
        # subscription to TWSE vs TWOTC.
        self.subscribe_quotes([symbol])
        items = self._tick_request_items([symbol])
        with self._request_lock:
            if self._api is None:
                raise YuantaClientError("Yuanta API is not connected.")
            self._api.SubscribeStockTick(self.settings.yuanta_account, items)
        with self._live_lock:
            self._tick_subscribed.add(symbol)
            # Full-day buffer per symbol so switching charts never loses the
            # ticks that arrived while another symbol was displayed.
            self._ticks.setdefault(symbol, deque(maxlen=5000))
            quote = self._live_quotes.get(symbol)
        # Backfill today's history via GetStkTickDetail so the panel is
        # complete even for symbols that just entered the watch set.
        try:
            history = self.get_tick_detail(symbol, quote.market if quote else "TWSE")
        except YuantaClientError:
            history = []
        self._merge_tick_history(symbol, history)

    def unsubscribe_ticks(self, symbol: str) -> None:
        if symbol not in self.tick_subscribed_symbols or self._api is None:
            return
        items = self._tick_request_items([symbol])
        with self._request_lock:
            if self._api is None:
                return
            self._api.UnSubscribeStockTick(self.settings.yuanta_account, items)
        with self._live_lock:
            self._tick_subscribed.discard(symbol)
            self._ticks.pop(symbol, None)

    def _apply_quote_push(self, result: Any) -> None:
        try:
            symbol = str(result.StkCode)
            flag = self._push_flag(result)
            with self._live_lock:
                quote = self._live_quotes.get(symbol)
                if quote is None:
                    return
                if flag == 22:
                    payload = result.IndexFlag_22
                    quote.bid_volume = int(payload.BuyVol)
                    quote.ask_volume = int(payload.SellVol)
                elif flag == 28:
                    payload = result.IndexFlag_28
                    bid = self._normalize_price(float(payload.BuyPrice), quote)
                    ask = self._normalize_price(float(payload.SellPrice), quote)
                    if bid:
                        quote.bid_price = bid
                    if ask:
                        quote.ask_price = ask
                elif flag == 29:
                    payload = result.IndexFlag_29
                    deal = self._normalize_price(float(payload.Deal), quote)
                    if deal:
                        quote.deal_price = deal
                        if not quote.high_price or deal > quote.high_price:
                            quote.high_price = deal
                        if not quote.low_price or deal < quote.low_price:
                            quote.low_price = deal
                    total = int(payload.TotalVol)
                    if total > 0:
                        quote.total_volume = total
                else:
                    return
                quote.source = "yuanta-push"
                self._live_version += 1
        except Exception:
            # Never let a malformed push frame kill the SDK callback thread.
            pass

    def _create_api(self):
        from YuantaOneAPI import OnResponseEventHandler, YuantaSparkAPITrader, enumLogType  # noqa: PLC0415

        api = YuantaSparkAPITrader(str(self.root / "logs"))
        self._event_handler = OnResponseEventHandler(self._on_response)
        api.OnResponse += self._event_handler
        api.SetLogType(enumLogType.COMMON)
        return api

    def status(self) -> YuantaStatus:
        return YuantaStatus(
            state=self._state,
            connected=self._connected,
            environment=self.settings.yuanta_env,
            account=self.settings.yuanta_account,
            account_name=self._account_name,
            last_error=self._last_error,
        )

    def connect(self, wait: float = 10.0) -> YuantaStatus:
        self._require_config()
        self._check_certificate_password()
        self._bootstrap_dotnet()

        with self._lifecycle_lock:
            if self._connected and self._api is not None:
                return self.status()

            self.disconnect()
            self._state = "connecting"
            self._last_error = ""
            self._login_event = threading.Event()
            self._api = self._create_api()
            try:
                self._api.Open(self._environment_mode())
                time.sleep(2)
                self._api.Login(
                    str(Path(self.settings.yuanta_cert_path).expanduser().resolve()),
                    self.settings.yuanta_cert_password,
                    self.settings.yuanta_account,
                    self.settings.yuanta_password,
                )

                if not self._login_event.wait(wait):
                    self._state = "error"
                    self._last_error = "Login response timeout."
                    self._dispose_api()
                    raise YuantaClientError(self._last_error)
                if not self._connected:
                    message = self._last_error or "Login failed."
                    self._dispose_api()
                    raise YuantaClientError(message)
                return self.status()
            except Exception as exc:
                if not isinstance(exc, YuantaClientError):
                    self._state = "error"
                    self._last_error = str(exc)
                    self._dispose_api()
                raise

    def disconnect(self) -> YuantaStatus:
        with self._lifecycle_lock:
            self._dispose_api()
            self._connected = False
            self._state = "disconnected"
            self._pending_action = None
            self._pending_event = None
            self._pending_payload = None
            with self._live_lock:
                self._live_quotes.clear()
                self._subscribed.clear()
                self._ticks.clear()
                self._tick_subscribed.clear()
                self._five_ticks.clear()
                self._five_subscribed.clear()
            return self.status()

    @property
    def live_version(self) -> int:
        return self._live_version

    @property
    def subscribed_symbols(self) -> set[str]:
        with self._live_lock:
            return set(self._subscribed)

    def get_live_quotes(self, symbols: list[str]) -> list[QuoteResponse]:
        with self._live_lock:
            return [self._live_quotes[symbol].model_copy() for symbol in symbols if symbol in self._live_quotes]

    def subscribe_quotes(self, symbols: list[str]) -> None:
        """Subscribe symbols for push updates, seeding the cache with a snapshot."""
        self._ensure_connected()
        todo = [symbol for symbol in symbols if symbol not in self.subscribed_symbols]
        if not todo:
            return

        seeded: dict[str, QuoteResponse] = {}
        for market in ("TWSE", "TWOTC"):
            missing = [symbol for symbol in todo if symbol not in seeded]
            if not missing:
                break
            try:
                for row in self.get_quotes(missing, market):
                    seeded[row.symbol] = row
            except YuantaClientError:
                continue
        with self._live_lock:
            self._live_quotes.update(seeded)

        from System.Collections.Generic import List  # noqa: PLC0415
        from YuantaOneAPI import WatchlistAll  # noqa: PLC0415

        with self._request_lock:
            if self._api is None:
                raise YuantaClientError("Yuanta API is not connected.")
            items = List[WatchlistAll]()
            for symbol in todo:
                watch = WatchlistAll()
                market = seeded[symbol].market if symbol in seeded else "TWSE"
                try:
                    watch.MarketType = self._market_type(market)
                except Exception:
                    watch.MarketType = self._market_type("TWSE")
                watch.StockCode = symbol
                items.Add(watch)
            self._api.SubscribeWatchlistAll(self.settings.yuanta_account, items)
        with self._live_lock:
            self._subscribed.update(todo)

    def unsubscribe_quotes(self, symbols: list[str]) -> None:
        current = self.subscribed_symbols
        todo = [symbol for symbol in symbols if symbol in current]
        if not todo or self._api is None:
            return

        from System.Collections.Generic import List  # noqa: PLC0415
        from YuantaOneAPI import WatchlistAll  # noqa: PLC0415

        with self._request_lock:
            if self._api is None:
                return
            items = List[WatchlistAll]()
            with self._live_lock:
                for symbol in todo:
                    watch = WatchlistAll()
                    quote = self._live_quotes.get(symbol)
                    try:
                        watch.MarketType = self._market_type(quote.market if quote else "TWSE")
                    except Exception:
                        watch.MarketType = self._market_type("TWSE")
                    watch.StockCode = symbol
                    items.Add(watch)
            self._api.UnSubscribeWatchlistAll(self.settings.yuanta_account, items)
        with self._live_lock:
            for symbol in todo:
                self._subscribed.discard(symbol)
                self._live_quotes.pop(symbol, None)

    def _dispose_api(self) -> None:
        api = self._api
        self._api = None
        if api is None:
            return
        try:
            api.LogOut()
        except Exception:
            pass
        try:
            api.Close()
        except Exception:
            pass
        try:
            api.Dispose()
        except Exception:
            pass

    def _ensure_connected(self) -> None:
        if not self._connected or self._api is None:
            self.connect()

    def _run_action(self, action: str, wait: float = 8.0, **kwargs: Any) -> Any:
        self._ensure_connected()

        with self._request_lock:
            if self._api is None:
                raise YuantaClientError("Yuanta API is not connected.")

            self._pending_action = action
            self._pending_event = threading.Event()
            self._pending_payload = None
            self._dispatch(self._api, action, **kwargs)

            if not self._pending_event.wait(wait):
                self._pending_action = None
                self._pending_event = None
                raise YuantaClientError(f"{action} response timeout.")

            payload = self._pending_payload
            self._pending_action = None
            self._pending_event = None
            self._pending_payload = None
            return payload

    def _dispatch(self, api: Any, action: str, **kwargs: Any) -> None:
        from System.Collections.Generic import List  # noqa: PLC0415
        from YuantaOneAPI import Quote, StockOrder  # noqa: PLC0415

        account = self.settings.yuanta_account

        if action == "GetWatchListAll":
            quotes = List[Quote]()
            for symbol in kwargs["symbols"]:
                quote = Quote()
                quote.MarketType = self._market_type(kwargs["market"])
                quote.StockCode = symbol
                quotes.Add(quote)
            api.GetWatchListAll(account, quotes)
            return

        if action == "GetStoreSummary":
            api.GetStoreSummary(account)
            return

        if action == "GetKLine":
            api.GetKLine(
                account,
                self._kline_type(kwargs["kline_type"]),
                self._market_type(kwargs["market"]),
                kwargs["symbol"],
                kwargs["start_date"],
                kwargs["end_date"],
            )
            return

        if action == "GetOrderTradeReport":
            api.GetOrderTradeReport(False, account)
            return

        if action == "GetStkTickDetail":
            from YuantaOneAPI import enumStkTickSelectType  # noqa: PLC0415

            api.GetStkTickDetail(
                account,
                self._market_type(kwargs["market"]),
                kwargs["symbol"],
                enumStkTickSelectType(int(kwargs.get("select_type", 1))),
                kwargs.get("start_time", "09:00:00"),
                kwargs.get("end_time", "14:00:00"),
                int(kwargs.get("count", 5000)),
            )
            return

        if action == "SendStockOrder":
            req: OrderRequest = kwargs["order"]
            order = StockOrder()
            order.Identify = 1
            order.Account = account
            order.APCode = req.ap_code
            order.TradeKind = req.trade_kind
            order.OrderType = req.order_type
            order.StkCode = req.symbol
            order.PriceFlag = req.price_flag
            order.Price = req.price
            order.OrderQty = req.quantity
            order.BuySell = req.side
            order.OrderNo = req.order_no
            order.TradeDate = datetime.today().strftime("%Y/%m/%d")
            order.BasketNo = ""
            order.Time_in_force = req.time_in_force
            orders = List[StockOrder]()
            orders.Add(order)
            api.SendStockOrder(account, orders)
            return

        raise YuantaClientError(f"Unsupported action: {action}")

    def get_quotes(self, symbols: list[str], market: str) -> list[QuoteResponse]:
        payload = self._run_action("GetWatchListAll", symbols=symbols, market=market)
        rows = []
        for item in payload.QueryWatchList:
            rows.append(
                QuoteResponse(
                    market=str(item.MarketNo),
                    symbol=str(item.StkCode),
                    name=str(item.StkName),
                    deal_price=float(item.DealPrice),
                    prev_close=float(item.YstPrice),
                    bid_price=float(item.BuyPrice),
                    ask_price=float(item.SellPrice),
                    open_price=float(item.OpenPrice),
                    high_price=float(item.HighPrice),
                    low_price=float(item.LowPrice),
                    total_volume=int(item.TotalVol),
                    up_limit=float(item.UpStopPrice),
                    down_limit=float(item.DownStopPrice),
                    source="yuanta",
                )
            )
        return rows

    def get_positions(self) -> list[Position]:
        payload = self._run_action("GetStoreSummary")
        rows = []
        for item in payload.StkStoreList:
            quantity = int(item.StockQty)
            position_type = self._store_position_type(item)
            # 融券為放空部位，統一以負股數表示（與沙盒／未實現損益多空慣例一致）。
            if position_type == "融券" and quantity > 0:
                quantity = -quantity
            rows.append(
                Position(
                    symbol=str(item.StkCode),
                    name=str(item.StkName),
                    quantity=quantity,
                    market_price=float(item.MarketPrice),
                    market_amount=float(item.MarketAmt),
                    cost=float(item.Cost),
                    unrealized_pnl=float(item.ReturnAmt),
                    position_type=position_type,
                )
            )
        return rows

    @staticmethod
    def _store_position_type(item) -> str:
        """元大庫存列的部位種類（現股／融資／融券）。

        ⚠️ 待實機驗證：StkStoreList 的交易類別欄位名與代碼對照無法在無 SDK 下確認，
        此處防禦式嘗試常見欄位名（TradeKind/OrderType/Trust/CrdType...），對照常見
        代碼（融資=3、融券=4、現股=0），取不到時一律視為現股。實機請印出 item 屬性核對。
        """
        raw = None
        for attr in ("TradeKind", "OrderType", "Trust", "CrdType", "TradeType", "MarginKind"):
            value = getattr(item, attr, None)
            if value not in (None, ""):
                raw = str(value).strip()
                break
        if raw is None:
            return "現股"
        token = raw.lower()
        if any(k in token for k in ("融資", "margin", "3")) and "融券" not in raw:
            return "融資"
        if any(k in token for k in ("融券", "short", "4")):
            return "融券"
        return "現股"

    def get_kline(
        self,
        symbol: str,
        market: str,
        start_date: str,
        end_date: str,
        kline_type: str = "1M",
    ) -> list[KLinePoint]:
        payload = self._run_action(
            "GetKLine",
            wait=10.0,
            symbol=symbol,
            market=market,
            start_date=start_date,
            end_date=end_date,
            kline_type=kline_type,
        )
        rows = []
        for item in payload.KLineList:
            ts = item.TimeStamp
            rows.append(
                KLinePoint(
                    timestamp=f"{ts.Year:04d}-{ts.Month:02d}-{ts.Day:02d} {ts.Hour:02d}:{ts.Minute:02d}:{ts.Second:02d}",
                    open=float(item.OpenPrice),
                    high=float(item.HighPrice),
                    low=float(item.LowPrice),
                    close=float(item.ClosePrice),
                    volume=int(item.DealVol),
                )
            )
        return rows

    def _parse_order_result(self, payload: Any) -> OrderResult:
        first = payload.ResultList[0] if payload.ResultList.Count else None
        if first is None:
            return OrderResult(accepted=False, mode="live", message="券商未回傳下單結果。")
        accepted = str(first.ReplyCode) == "0"
        return OrderResult(
            accepted=accepted,
            mode="live",
            message=str(first.Advisory),
            order_no=str(first.OrderNO),
        )

    def send_stock_order(self, order: OrderRequest) -> OrderResult:
        if not self.settings.yuanta_enable_order:
            return OrderResult(accepted=False, mode="blocked", message="下單總開關未開啟（YUANTA_ENABLE_ORDER 非 YES）。")
        if not order.confirm_send_order:
            return OrderResult(accepted=False, mode="blocked", message="尚未確認送單。")

        return self._parse_order_result(self._run_action("SendStockOrder", order=order))

    def cancel_stock_order(self, order: OrderRequest) -> OrderResult:
        """Cancel a working order (TradeKind 04 + original order number)."""
        if not order.order_no:
            return OrderResult(accepted=False, mode="blocked", message="刪單需要委託書號。")
        return self._parse_order_result(self._run_action("SendStockOrder", order=order))

    def get_stock_orders(self) -> list[WorkingOrder]:
        """Today's stock order report (委託回報)."""
        payload = self._run_action("GetOrderTradeReport", wait=10.0)
        rows: list[WorkingOrder] = []
        for item in payload.StkOrderList:
            try:
                order_no = str(item.OrderNo).strip()
                if not order_no:
                    continue
                symbol = str(getattr(item, "StkCode", "") or getattr(item, "CompanyNo", "")).strip()
                # 元大實測：CancelFlag 恆為 'N'，不能用來判斷取消。真正的取消/刪單訊號是
                # CancelQty>0（被取消數量），且 OrderStatus=30 代表委託已取消/失效且無成交。
                order_status = str(getattr(item, "OrderStatus", "")).strip()
                cancel_qty = int(getattr(item, "CancelQty", 0) or 0)
                cancelled = cancel_qty > 0 or order_status == "30"
                accept_time = _format_yuanta_stamp(
                    getattr(item, "AcceptDate", None),
                    getattr(item, "AcceptTime", None),
                )
                rows.append(
                    WorkingOrder(
                        order_no=order_no,
                        symbol=symbol,
                        name=str(getattr(item, "StkName", "")).strip(),
                        side=str(item.BS).strip(),
                        price=float(item.Price),
                        price_flag=str(getattr(item, "PriceFlag", "")).strip(),
                        order_type=str(getattr(item, "OrderType", "0")).strip() or "0",
                        before_qty=int(item.BeforeQty),
                        after_qty=int(item.AfterQty),
                        ok_qty=int(item.OkQty),
                        status=order_status,
                        cancelled=cancelled,
                        accept_time=accept_time,
                    )
                )
            except Exception:
                continue
        return rows

    def get_stock_trades(self) -> list[TradeRecord]:
        """Today's stock fills (成交回報)."""
        payload = self._run_action("GetOrderTradeReport", wait=10.0)
        rows: list[TradeRecord] = []
        for item in payload.StkTradeList:
            try:
                # DateTime 是合併結構（同時含 Year/Month/Day 與 Hour/Minute/Second），
                # 故同一物件同時當日期與時間來源傳入。
                stamp = item.DateTime
                time_text = _format_yuanta_stamp(stamp, stamp)
                deal_price = float(getattr(item, "SPrice", 0) or 0) or float(getattr(item, "OPrice", 0) or 0)
                rows.append(
                    TradeRecord(
                        order_no=str(item.OrderNo).strip(),
                        symbol=str(getattr(item, "StkCode", "") or getattr(item, "CompanyNo", "")).strip(),
                        name=str(getattr(item, "StkName", "")).strip(),
                        side=str(item.BS).strip(),
                        price=deal_price,
                        quantity=int(item.OkQty),
                        time=time_text,
                    )
                )
            except Exception:
                continue
        rows.sort(key=lambda row: row.time, reverse=True)
        return rows


_client: YuantaClient | None = None


def get_yuanta_client() -> YuantaClient:
    global _client
    if _client is None:
        _client = YuantaClient()
    return _client
