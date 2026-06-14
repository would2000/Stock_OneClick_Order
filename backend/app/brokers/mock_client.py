"""純本機模擬沙盒券商：不連任何真實券商、不需任何憑證/金鑰。

下單無條件接受、無風控（符合「模擬環境無安控、可隨意下單」）。報價以固定基準價
合成，讓閃電下單階梯可用；委託/成交/部位全部記在記憶體。介面與 Yuanta/Shioaji
client 一致（duck typing），由 broker.get_active_client() 在登入模擬環境時回傳。
"""

import json
import threading
from datetime import datetime

from ..database import connect
from ..trading.schemas import (
    OrderRequest,
    OrderResult,
    Position,
    QuoteResponse,
    YuantaStatus,
)

BASE_PRICE = 100.0
_SIM_STATE_KEY = "mock"


class MockBrokerClient:
    def __init__(self) -> None:
        self._connected = False
        self._lock = threading.Lock()
        self._orders: dict[str, dict] = {}
        self._trades: list = []
        self._positions: dict[str, dict] = {}
        self._seq = 0
        self._load()

    # ---------- persistence ----------
    def _load(self) -> None:
        """從 trading.db 還原沙盒委託/成交/部位，讓模擬帳戶跨重啟保留。"""
        try:
            with connect() as conn:
                row = conn.execute(
                    "SELECT value FROM sim_state WHERE key = ?", (_SIM_STATE_KEY,)
                ).fetchone()
        except Exception:  # noqa: BLE001  # 表格尚未建立等情況，視為空帳戶
            return
        if row is None:
            return
        try:
            data = json.loads(row["value"])
        except (ValueError, TypeError):
            return
        self._orders = data.get("orders", {})
        self._trades = data.get("trades", [])
        self._positions = data.get("positions", {})
        self._seq = int(data.get("seq", 0))

    def _save(self) -> None:
        """把目前沙盒狀態整包寫回 trading.db（資料量小，整包覆寫即可）。

        呼叫端需自行持有 self._lock，以確保寫出的是一致快照。"""
        payload = json.dumps(
            {
                "orders": self._orders,
                "trades": self._trades,
                "positions": self._positions,
                "seq": self._seq,
            }
        )
        now = datetime.now().isoformat(timespec="seconds")
        with connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sim_state(key, value, updated_at) VALUES (?, ?, ?)",
                (_SIM_STATE_KEY, payload, now),
            )

    # ---------- lifecycle ----------
    def connect(self) -> YuantaStatus:
        self._connected = True
        return self.status()

    def disconnect(self) -> YuantaStatus:
        self._connected = False
        return self.status()

    def status(self) -> YuantaStatus:
        return YuantaStatus(
            state="connected" if self._connected else "disconnected",
            connected=self._connected,
            environment="SIM",
            account="SIMULATION",
            account_name="模擬帳號",
            last_error="",
        )

    def reset(self) -> None:
        with self._lock:
            self._orders.clear()
            self._trades.clear()
            self._positions.clear()
            self._seq = 0
            self._save()

    # ---------- quotes ----------
    @staticmethod
    def _fugle():
        from .fugle_client import get_fugle  # noqa: PLC0415

        return get_fugle()

    def _synthetic(self, symbol: str, market: str = "TWSE") -> QuoteResponse:
        return QuoteResponse(
            market=market,
            symbol=symbol,
            name="",
            deal_price=BASE_PRICE,
            prev_close=BASE_PRICE,
            open_price=BASE_PRICE,
            high_price=BASE_PRICE,
            low_price=BASE_PRICE,
            bid_price=BASE_PRICE,
            ask_price=BASE_PRICE,
            total_volume=0,
            up_limit=round(BASE_PRICE * 1.1, 1),
            down_limit=round(BASE_PRICE * 0.9, 1),
            source="mock",
        )

    def _quote(self, symbol: str, market: str = "TWSE") -> QuoteResponse:
        # 沙盒以富果真實行情為主；無金鑰/取不到時退回合成報價（仍可測下單）。
        real = self._fugle().get_quote(symbol)
        return real if real is not None else self._synthetic(symbol, market)

    def get_quotes(self, symbols: list[str], market: str = "TWSE") -> list[QuoteResponse]:
        return [self._quote(symbol, market) for symbol in symbols]

    def get_live_quotes(self, symbols: list[str]) -> list[QuoteResponse]:
        fugle = self._fugle()
        if not fugle.enabled:
            return [self._quote(symbol) for symbol in symbols]
        return fugle.get_live(symbols)

    def subscribe_quotes(self, symbols: list[str]) -> None:
        self._fugle().subscribe(symbols)

    def unsubscribe_quotes(self, symbols: list[str]) -> None:
        self._fugle().unsubscribe(symbols)

    def subscribe_ticks(self, symbol: str) -> None:
        self._fugle().subscribe([symbol])

    def unsubscribe_ticks(self, symbol: str) -> None:
        return None

    def subscribe_five_ticks(self, symbol: str) -> None:
        self._fugle().subscribe([symbol])

    def unsubscribe_five_ticks(self, symbol: str) -> None:
        return None

    @property
    def live_version(self) -> int:
        return self._fugle().live_version

    @property
    def subscribed_symbols(self) -> set[str]:
        return self._fugle().subscribed

    @property
    def tick_version(self) -> int:
        return self._fugle().tick_version

    @property
    def tick_subscribed_symbols(self) -> set[str]:
        return self._fugle().subscribed

    @property
    def five_tick_version(self) -> int:
        return self._fugle().five_version

    @property
    def five_tick_subscribed_symbols(self) -> set[str]:
        return self._fugle().subscribed

    def get_ticks(self, symbol: str, limit: int = 50) -> list:
        return self._fugle().get_live_ticks(symbol, limit=limit)

    def get_tick_detail(self, symbol: str, market: str = "TWSE", select_type: int = 1, count: int = 5000) -> list:
        return self._fugle().get_trades(symbol, limit=count)

    def get_five_ticks(self, symbol: str) -> dict | None:
        return self._fugle().get_live_five(symbol)

    def get_kline(self, symbol: str, market: str, start_date: str, end_date: str, kline_type: str = "1M") -> list:
        return self._fugle().get_candles(symbol)

    # ---------- orders ----------
    def send_stock_order(self, order: OrderRequest) -> OrderResult:
        with self._lock:
            self._seq += 1
            order_no = f"SIM{self._seq:06d}"
            shares = order.quantity * 1000
            is_market = order.price_flag == "M" or order.price <= 0
            fill_price = BASE_PRICE if is_market else order.price
            self._orders[order_no] = {
                "order_no": order_no,
                "symbol": order.symbol,
                "side": order.side,
                "price": 0.0 if is_market else order.price,
                "price_flag": order.price_flag,
                "order_type": order.order_type,
                "before_qty": shares,
                "after_qty": shares,
                "ok_qty": shares if is_market else 0,
                "status": "20",
            }
            if is_market:
                self._trades.append(
                    {
                        "order_no": order_no,
                        "symbol": order.symbol,
                        "side": order.side,
                        "price": fill_price,
                        "quantity": shares,
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
                self._apply_fill(order.symbol, order.side, shares, fill_price)
            self._save()
        return OrderResult(accepted=True, mode="sim", message="模擬下單成功（沙盒）", order_no=order_no)

    def cancel_stock_order(self, order: OrderRequest) -> OrderResult:
        with self._lock:
            row = self._orders.get(order.order_no)
            if row is not None:
                # 保留紀錄並標記為取消，讓「全部委託」可顯示為取消單（取消單歸類於未成交）。
                row["cancelled"] = True
            self._save()
        return OrderResult(accepted=True, mode="sim", message="模擬刪單成功", order_no=order.order_no)

    def _apply_fill(self, symbol: str, side: str, shares: int, price: float) -> None:
        pos = self._positions.setdefault(symbol, {"qty": 0, "cost": 0.0})
        if side == "B":
            total = pos["cost"] * pos["qty"] + price * shares
            pos["qty"] += shares
            pos["cost"] = total / pos["qty"] if pos["qty"] else 0.0
        else:
            pos["qty"] = max(0, pos["qty"] - shares)

    def get_stock_orders(self) -> list:
        from ..trading.schemas import WorkingOrder  # noqa: PLC0415

        # 回傳今日全部委託（含已成交）；未成交/已成交的篩選交由 route 的 status 參數處理。
        with self._lock:
            return [WorkingOrder(**row) for row in self._orders.values()]

    def get_stock_trades(self) -> list:
        from ..trading.schemas import TradeRecord  # noqa: PLC0415

        with self._lock:
            return [TradeRecord(**row) for row in reversed(self._trades)]

    def get_positions(self) -> list[Position]:
        with self._lock:
            rows = []
            for symbol, pos in self._positions.items():
                if pos["qty"] <= 0:
                    continue
                rows.append(
                    Position(
                        symbol=symbol,
                        name="",
                        quantity=pos["qty"],
                        market_price=BASE_PRICE,
                        market_amount=BASE_PRICE * pos["qty"],
                        cost=pos["cost"],
                        unrealized_pnl=(BASE_PRICE - pos["cost"]) * pos["qty"],
                    )
                )
            return rows


_mock_client: MockBrokerClient | None = None


def get_mock_client() -> MockBrokerClient:
    global _mock_client
    if _mock_client is None:
        _mock_client = MockBrokerClient()
    return _mock_client
