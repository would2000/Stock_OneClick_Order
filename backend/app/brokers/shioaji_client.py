"""SinoPac (永豐金) broker client built on Shioaji.

Implements the same duck-typed surface as YuantaClient so quote streaming,
the MIT engine, the index sampler and all REST routes work unchanged when
this broker is active. Shioaji pushes ticks and 5-level book natively, so
the live caches are fed by真 callbacks instead of polling.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import get_settings
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
from ..yuanta.client import YuantaClientError


class ShioajiClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._api: Any | None = None
        self._lifecycle_lock = threading.RLock()
        self._live_lock = threading.Lock()
        self._state = "disconnected"
        self._connected = False
        self._account_name = ""
        self._last_error = ""
        self._live_quotes: dict[str, QuoteResponse] = {}
        self._subscribed: set[str] = set()
        self._live_version = 0
        self._ticks: dict[str, deque[TickRecord]] = {}
        self._tick_subscribed: set[str] = set()
        self._tick_version = 0
        self._five_ticks: dict[str, dict] = {}
        self._five_subscribed: set[str] = set()
        self._five_version = 0
        self._tick_serial = 0

    # ---------- lifecycle ----------

    def _require_config(self) -> None:
        if not self.settings.shioaji_api_key or not self.settings.shioaji_secret_key:
            raise YuantaClientError("Missing SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY in .env")

    def status(self) -> YuantaStatus:
        return YuantaStatus(
            state=self._state,
            connected=self._connected,
            environment="SIM" if self.settings.shioaji_simulation else "PROD",
            account=self.settings.shioaji_person_id,
            account_name=self._account_name,
            last_error=self._last_error,
        )

    def connect(self) -> YuantaStatus:
        self._require_config()
        with self._lifecycle_lock:
            if self._connected and self._api is not None:
                return self.status()
            import shioaji as sj  # noqa: PLC0415

            self._state = "connecting"
            try:
                api = sj.Shioaji(simulation=self.settings.shioaji_simulation)
                accounts = api.login(
                    api_key=self.settings.shioaji_api_key,
                    secret_key=self.settings.shioaji_secret_key,
                    contracts_timeout=30000,
                )
                # CA is only required for live orders; simulation works without
                # it, so a bad CA password must not block paper trading.
                if (
                    not self.settings.shioaji_simulation
                    and self.settings.shioaji_ca_path
                    and self.settings.shioaji_ca_password
                ):
                    api.activate_ca(
                        ca_path=str(Path(self.settings.shioaji_ca_path).expanduser()),
                        ca_passwd=self.settings.shioaji_ca_password,
                        person_id=self.settings.shioaji_person_id or None,
                    )
                self._api = api
                self._install_callbacks(api)
                self._connected = True
                self._state = "connected"
                self._last_error = ""
                stock_account = getattr(api, "stock_account", None)
                self._account_name = str(getattr(stock_account, "username", "") or (accounts[0].username if accounts else ""))
                threading.Thread(target=self._dump_symbols, daemon=True).start()
            except Exception as exc:
                self._state = "error"
                self._last_error = str(exc)
                self._api = None
                raise YuantaClientError(f"Shioaji login failed: {exc}") from exc
            return self.status()

    def _dump_symbols(self) -> None:
        """Persist the full contract list to data/symbols.json so symbol
        search works for both brokers, even before SinoPac connects again."""
        api = self._api
        if api is None:
            return
        import json  # noqa: PLC0415

        rows = []
        try:
            for kind in api.Contracts.Stocks:
                for contract in kind:
                    code = str(getattr(contract, "code", "")).strip()
                    name = str(getattr(contract, "name", "")).strip()
                    if not code or not name:
                        continue
                    exchange = str(getattr(contract, "exchange", "")).replace("Exchange.", "")
                    rows.append({"code": code, "name": name, "exchange": exchange})
        except Exception:
            return
        if not rows:
            return
        try:
            path = self.settings.data_dir / "symbols.json"
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def disconnect(self) -> YuantaStatus:
        with self._lifecycle_lock:
            api = self._api
            self._api = None
            self._connected = False
            self._state = "disconnected"
            with self._live_lock:
                self._live_quotes.clear()
                self._subscribed.clear()
                self._ticks.clear()
                self._tick_subscribed.clear()
                self._five_ticks.clear()
                self._five_subscribed.clear()
            if api is not None:
                try:
                    api.logout()
                except Exception:
                    pass
            return self.status()

    def _ensure_connected(self) -> Any:
        if not self._connected or self._api is None:
            self.connect()
        return self._api

    def _contract(self, symbol: str):
        api = self._ensure_connected()
        # Shioaji raises KeyError("Contract not found: ...") for unknown codes
        # (e.g. Yuanta-style index symbols IX0001/IX0043 that have no Shioaji
        # stock contract), so the plain None-check never fired and the raw
        # KeyError leaked as a 500. Normalize any lookup miss to the domain
        # error that callers already handle (graceful degrade to sampler).
        try:
            contract = api.Contracts.Stocks[symbol]
        except KeyError:
            contract = None
        if contract is None:
            raise YuantaClientError(f"Unknown symbol: {symbol}")
        return contract

    # ---------- push callbacks ----------

    def _install_callbacks(self, api: Any) -> None:
        @api.on_tick_stk_v1()
        def _on_tick(exchange, tick):  # noqa: ANN001
            try:
                symbol = str(tick.code)
                price = float(tick.close)
                with self._live_lock:
                    quote = self._live_quotes.get(symbol)
                    if quote is not None and price > 0:
                        quote.deal_price = price
                        quote.total_volume = int(tick.total_volume)
                        if not quote.high_price or price > quote.high_price:
                            quote.high_price = price
                        if not quote.low_price or price < quote.low_price:
                            quote.low_price = price
                        quote.source = "shioaji-push"
                        self._live_version += 1
                    buffer = self._ticks.get(symbol)
                    if buffer is not None and not bool(getattr(tick, "simtrade", 0)):
                        self._tick_serial += 1
                        buffer.append(
                            TickRecord(
                                symbol=symbol,
                                serial=self._tick_serial,
                                time=str(tick.datetime)[11:19],
                                bid_price=float(getattr(tick, "bid_price", 0) or 0) or None,
                                ask_price=float(getattr(tick, "ask_price", 0) or 0) or None,
                                deal_price=price,
                                volume=int(tick.volume),
                                in_out=str(getattr(tick, "tick_type", "")),
                            )
                        )
                        self._tick_version += 1
            except Exception:
                pass

        @api.on_bidask_stk_v1()
        def _on_bidask(exchange, bidask):  # noqa: ANN001
            try:
                symbol = str(bidask.code)
                bids = [{"price": float(p), "volume": int(v)} for p, v in zip(bidask.bid_price, bidask.bid_volume)]
                asks = [{"price": float(p), "volume": int(v)} for p, v in zip(bidask.ask_price, bidask.ask_volume)]
                with self._live_lock:
                    self._five_ticks[symbol] = {"bids": bids, "asks": asks}
                    self._five_version += 1
                    quote = self._live_quotes.get(symbol)
                    if quote is not None:
                        if bids and bids[0]["price"] > 0:
                            quote.bid_price = bids[0]["price"]
                            quote.bid_volume = bids[0]["volume"]
                        if asks and asks[0]["price"] > 0:
                            quote.ask_price = asks[0]["price"]
                            quote.ask_volume = asks[0]["volume"]
                        self._live_version += 1
            except Exception:
                pass

    # ---------- quotes ----------

    def _snapshot_quote(self, symbol: str) -> QuoteResponse | None:
        api = self._ensure_connected()
        try:
            contract = self._contract(symbol)
            snap = api.snapshots([contract])[0]
        except Exception:
            return None
        return QuoteResponse(
            market="TWSE" if str(getattr(contract, "exchange", "TSE")) in ("TSE", "Exchange.TSE") else "TWOTC",
            symbol=symbol,
            name=str(contract.name),
            deal_price=float(snap.close) if snap.close else None,
            prev_close=float(contract.reference) if contract.reference else None,
            bid_price=float(snap.buy_price) if snap.buy_price else None,
            ask_price=float(snap.sell_price) if snap.sell_price else None,
            open_price=float(snap.open) if snap.open else None,
            high_price=float(snap.high) if snap.high else None,
            low_price=float(snap.low) if snap.low else None,
            total_volume=int(snap.total_volume) if snap.total_volume else None,
            up_limit=float(contract.limit_up) if contract.limit_up else None,
            down_limit=float(contract.limit_down) if contract.limit_down else None,
            source="shioaji",
        )

    def get_quotes(self, symbols: list[str], market: str = "TWSE") -> list[QuoteResponse]:
        rows = []
        for symbol in symbols:
            quote = self._snapshot_quote(symbol)
            if quote:
                rows.append(quote)
        return rows

    @property
    def live_version(self) -> int:
        return self._live_version

    @property
    def subscribed_symbols(self) -> set[str]:
        with self._live_lock:
            return set(self._subscribed)

    def get_live_quotes(self, symbols: list[str]) -> list[QuoteResponse]:
        with self._live_lock:
            return [self._live_quotes[s].model_copy() for s in symbols if s in self._live_quotes]

    def subscribe_quotes(self, symbols: list[str]) -> None:
        api = self._ensure_connected()
        import shioaji as sj  # noqa: PLC0415

        todo = [s for s in symbols if s not in self.subscribed_symbols]
        for symbol in todo:
            quote = self._snapshot_quote(symbol)
            if quote is None:
                continue
            with self._live_lock:
                self._live_quotes[symbol] = quote
            try:
                api.quote.subscribe(self._contract(symbol), quote_type=sj.constant.QuoteType.Tick, version=sj.constant.QuoteVersion.v1)
            except Exception:
                continue
            with self._live_lock:
                self._subscribed.add(symbol)

    def unsubscribe_quotes(self, symbols: list[str]) -> None:
        api = self._api
        if api is None:
            return
        import shioaji as sj  # noqa: PLC0415

        for symbol in symbols:
            if symbol not in self.subscribed_symbols:
                continue
            try:
                api.quote.unsubscribe(self._contract(symbol), quote_type=sj.constant.QuoteType.Tick, version=sj.constant.QuoteVersion.v1)
            except Exception:
                pass
            with self._live_lock:
                self._subscribed.discard(symbol)
                self._live_quotes.pop(symbol, None)

    # ---------- ticks (time & sales) ----------

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
            return list(buffer)[-limit:] if buffer else []

    def get_tick_detail(self, symbol: str, market: str = "TWSE", select_type: int = 1, count: int = 5000) -> list[TickRecord]:
        api = self._ensure_connected()
        contract = self._contract(symbol)
        data = api.ticks(contract=contract, date=datetime.now().strftime("%Y-%m-%d"))
        rows: list[TickRecord] = []
        for index, ts in enumerate(data.ts):
            try:
                rows.append(
                    TickRecord(
                        symbol=symbol,
                        serial=index + 1,
                        time=str(datetime.fromtimestamp(ts / 1_000_000_000))[11:19],
                        bid_price=float(data.bid_price[index]) or None,
                        ask_price=float(data.ask_price[index]) or None,
                        deal_price=float(data.close[index]) or None,
                        volume=int(data.volume[index]),
                        in_out=str(data.tick_type[index]),
                    )
                )
            except Exception:
                continue
        return rows[-count:]

    def subscribe_ticks(self, symbol: str) -> None:
        if symbol in self.tick_subscribed_symbols:
            return
        self.subscribe_quotes([symbol])
        with self._live_lock:
            self._tick_subscribed.add(symbol)
            self._ticks.setdefault(symbol, deque(maxlen=5000))
        try:
            history = self.get_tick_detail(symbol, "TWSE")
        except Exception:
            history = []
        if history:
            with self._live_lock:
                buffer = self._ticks.get(symbol)
                if buffer is not None and not buffer:
                    buffer.extend(history[-5000:])
                    self._tick_serial = max(self._tick_serial, len(history))
                    self._tick_version += 1

    def unsubscribe_ticks(self, symbol: str) -> None:
        with self._live_lock:
            self._tick_subscribed.discard(symbol)
            self._ticks.pop(symbol, None)

    # ---------- five-level book ----------

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

    def subscribe_five_ticks(self, symbol: str) -> None:
        if symbol in self.five_tick_subscribed_symbols:
            return
        api = self._ensure_connected()
        import shioaji as sj  # noqa: PLC0415

        self.subscribe_quotes([symbol])
        try:
            api.quote.subscribe(self._contract(symbol), quote_type=sj.constant.QuoteType.BidAsk, version=sj.constant.QuoteVersion.v1)
        except Exception as exc:
            raise YuantaClientError(f"BidAsk subscribe failed: {exc}") from exc
        with self._live_lock:
            self._five_subscribed.add(symbol)

    def unsubscribe_five_ticks(self, symbol: str) -> None:
        api = self._api
        if api is None or symbol not in self.five_tick_subscribed_symbols:
            return
        import shioaji as sj  # noqa: PLC0415

        try:
            api.quote.unsubscribe(self._contract(symbol), quote_type=sj.constant.QuoteType.BidAsk, version=sj.constant.QuoteVersion.v1)
        except Exception:
            pass
        with self._live_lock:
            self._five_subscribed.discard(symbol)
            self._five_ticks.pop(symbol, None)

    # ---------- portfolio / history ----------

    def get_positions(self) -> list[Position]:
        api = self._ensure_connected()
        rows = []
        try:
            positions = api.list_positions(api.stock_account)
        except Exception as exc:
            raise YuantaClientError(f"list_positions failed: {exc}") from exc
        for item in positions:
            quantity = int(item.quantity) * 1000  # shares, to match Yuanta semantics
            price = float(item.last_price or 0)
            rows.append(
                Position(
                    symbol=str(item.code),
                    name=str(item.code),
                    quantity=quantity,
                    market_price=price or None,
                    market_amount=price * quantity if price else None,
                    cost=float(item.price or 0) or None,
                    unrealized_pnl=float(item.pnl or 0),
                )
            )
        return rows

    def get_kline(self, symbol: str, market: str, start_date: str, end_date: str, kline_type: str = "1M") -> list[KLinePoint]:
        api = self._ensure_connected()
        contract = self._contract(symbol)
        start = start_date.replace("/", "-")
        end = end_date.replace("/", "-")
        try:
            kbars = api.kbars(contract=contract, start=start, end=end)
        except Exception as exc:
            raise YuantaClientError(f"kbars failed: {exc}") from exc
        rows = []
        for index, ts in enumerate(kbars.ts):
            try:
                stamp = datetime.fromtimestamp(ts / 1_000_000_000)
                rows.append(
                    KLinePoint(
                        timestamp=stamp.strftime("%Y-%m-%d %H:%M:%S"),
                        open=float(kbars.Open[index]),
                        high=float(kbars.High[index]),
                        low=float(kbars.Low[index]),
                        close=float(kbars.Close[index]),
                        volume=int(kbars.Volume[index]),
                    )
                )
            except Exception:
                continue
        return rows

    # ---------- orders ----------

    def send_stock_order(self, order: OrderRequest) -> OrderResult:
        # Simulation orders are free paper trades — exempt from the global
        # live-order switch, which keeps guarding Yuanta PROD and SinoPac live.
        if not self.settings.yuanta_enable_order and not self.settings.shioaji_simulation:
            return OrderResult(accepted=False, mode="blocked", message="下單總開關未開啟（YUANTA_ENABLE_ORDER 非 YES）。")
        if not order.confirm_send_order:
            return OrderResult(accepted=False, mode="blocked", message="尚未確認送單。")
        api = self._ensure_connected()
        import shioaji as sj  # noqa: PLC0415

        contract = self._contract(order.symbol)
        is_market = order.price_flag == "M" or order.price <= 0
        sj_order = api.Order(
            price=0 if is_market else order.price,
            quantity=order.quantity,
            action=sj.constant.Action.Buy if order.side == "B" else sj.constant.Action.Sell,
            price_type=sj.constant.StockPriceType.MKT if is_market else sj.constant.StockPriceType.LMT,
            order_type=sj.constant.OrderType.ROD,
            order_lot=sj.constant.StockOrderLot.Common,
            account=api.stock_account,
        )
        try:
            trade = api.place_order(contract, sj_order)
            # Refresh once so an immediate exchange rejection (after-hours,
            # price outside limits...) is reported instead of PendingSubmit.
            api.update_status(api.stock_account)
        except Exception as exc:
            return OrderResult(accepted=False, mode="live", message=str(exc))
        status = str(trade.status.status).replace("Status.", "")
        reason = str(getattr(trade.status, "msg", "") or "").strip()
        accepted = "Failed" not in status and "Cancelled" not in status
        message = status + ("：" + reason if reason else "")
        return OrderResult(accepted=accepted, mode="live", message=message, order_no=str(trade.order.id))

    def _find_trade(self, order_no: str):
        api = self._ensure_connected()
        api.update_status(api.stock_account)
        for trade in api.list_trades():
            if str(trade.order.id) == order_no or str(getattr(trade.order, "ordno", "")) == order_no:
                return trade
        return None

    def cancel_stock_order(self, order: OrderRequest) -> OrderResult:
        api = self._ensure_connected()
        trade = self._find_trade(order.order_no)
        if trade is None:
            return OrderResult(accepted=False, mode="live", message=f"找不到委託單 {order.order_no}。")
        try:
            api.cancel_order(trade)
            api.update_status(api.stock_account)
        except Exception as exc:
            return OrderResult(accepted=False, mode="live", message=str(exc))
        return OrderResult(accepted=True, mode="live", message="刪單已送出", order_no=order.order_no)

    def get_stock_orders(self) -> list[WorkingOrder]:
        api = self._ensure_connected()
        try:
            api.update_status(api.stock_account)
            trades = api.list_trades()
        except Exception as exc:
            raise YuantaClientError(f"list_trades failed: {exc}") from exc
        rows = []
        for trade in trades:
            try:
                status = str(trade.status.status).replace("Status.", "").removeprefix("Order")
                qty = int(trade.order.quantity)
                filled = int(getattr(trade.status, "deal_quantity", 0) or 0)
                cancel_qty = int(getattr(trade.status, "cancel_quantity", 0) or 0)
                # Shioaji order lifecycle: PendingSubmit → PreSubmitted →
                # Submitted → PartFilled/Filled | Cancelled | Failed | Inactive.
                working = status in ("PendingSubmit", "PreSubmitted", "Submitted", "PartFilled")
                cancelled = status in ("Cancelled", "Failed", "Inactive") or cancel_qty > 0
                # 委託成立時間（Shioaji 提供 order_datetime，型別為 datetime）。
                order_dt = getattr(trade.status, "order_datetime", None)
                accept_time = str(order_dt)[:19] if order_dt else ""
                rows.append(
                    WorkingOrder(
                        order_no=str(trade.order.id),
                        symbol=str(trade.contract.code),
                        name=str(getattr(trade.contract, "name", "")),
                        side="B" if "Buy" in str(trade.order.action) else "S",
                        price=float(trade.order.price),
                        price_flag="M" if "MKT" in str(trade.order.price_type) else "",
                        order_type="0",
                        before_qty=qty * 1000,
                        after_qty=qty * 1000,
                        # 用實際成交量；只有 Filled 才強制等於委託量（避免 deal_quantity 尚未更新）。
                        # 取消/失敗單成交量維持實際值（通常 0），不再誤算成全量而顯示「已成交」。
                        ok_qty=(qty if status == "Filled" else filled) * 1000,
                        status="20" if working else status,
                        cancelled=cancelled,
                        accept_time=accept_time,
                    )
                )
            except Exception:
                continue
        return rows

    def get_stock_trades(self) -> list[TradeRecord]:
        api = self._ensure_connected()
        try:
            api.update_status(api.stock_account)
            trades = api.list_trades()
        except Exception as exc:
            raise YuantaClientError(f"list_trades failed: {exc}") from exc
        rows = []
        for trade in trades:
            for deal in getattr(trade.status, "deals", []) or []:
                try:
                    rows.append(
                        TradeRecord(
                            order_no=str(trade.order.id),
                            symbol=str(trade.contract.code),
                            name=str(getattr(trade.contract, "name", "")),
                            side="B" if "Buy" in str(trade.order.action) else "S",
                            price=float(deal.price),
                            quantity=int(deal.quantity) * 1000,
                            time=str(datetime.fromtimestamp(deal.ts))[11:19],
                        )
                    )
                except Exception:
                    continue
        rows.sort(key=lambda row: row.time, reverse=True)
        return rows


_client: ShioajiClient | None = None


def get_shioaji_client() -> ShioajiClient:
    global _client
    if _client is None:
        _client = ShioajiClient()
    return _client
