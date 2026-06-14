"""Server-side MIT (Market-If-Touched) trigger orders.

Pending orders are persisted in SQLite and evaluated by a background engine
against streamed quotes. When the deal price touches the trigger level the
engine fires a market order through the same preview/risk/audit pipeline as
manual orders, so the kill switch, amount cap and YUANTA_ENABLE_ORDER all
still apply.
"""

import asyncio
import logging
import os
from datetime import datetime

from ..database import connect
from ..trading.risk import audit_order, is_kill_switch_enabled, preview_order
from ..trading.schemas import MitOrderCreate, MitOrderRecord, OrderRequest, QuoteResponse
from ..broker import get_active_client, is_sim_session
from ..yuanta.client import YuantaClientError

logger = logging.getLogger("mit")

ENGINE_INTERVAL = float(os.getenv("MIT_ENGINE_INTERVAL", "1.0"))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _record(row) -> MitOrderRecord:
    return MitOrderRecord(**dict(row))


def create_mit_order(request: MitOrderCreate) -> MitOrderRecord:
    # The trigger direction is locked in at creation from the reference price:
    # price must fall to a lower trigger, or rise to a higher one. Without a
    # reference the engine resolves it from the first quote it sees.
    direction = ""
    if request.reference_price and request.reference_price > 0:
        if request.reference_price > request.trigger_price:
            direction = "down"
        elif request.reference_price < request.trigger_price:
            direction = "up"
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO mit_orders(created_at, symbol, side, trigger_price, quantity, direction, status, message) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', '')",
            (_now(), request.symbol, request.side, request.trigger_price, request.quantity, direction),
        )
        row = conn.execute("SELECT * FROM mit_orders WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _record(row)


def list_mit_orders(limit: int = 100) -> list[MitOrderRecord]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM mit_orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_record(row) for row in rows]


def list_pending_mit_orders() -> list[MitOrderRecord]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM mit_orders WHERE status = 'pending' ORDER BY id").fetchall()
    return [_record(row) for row in rows]


def cancel_mit_order(order_id: int) -> MitOrderRecord | None:
    with connect() as conn:
        conn.execute(
            "UPDATE mit_orders SET status = 'cancelled', message = ? WHERE id = ? AND status = 'pending'",
            (f"cancelled at {_now()}", order_id),
        )
        row = conn.execute("SELECT * FROM mit_orders WHERE id = ?", (order_id,)).fetchone()
    return _record(row) if row else None


def _update_mit_order(order_id: int, **fields) -> None:
    keys = ", ".join(f"{key} = ?" for key in fields)
    with connect() as conn:
        conn.execute(f"UPDATE mit_orders SET {keys} WHERE id = ?", (*fields.values(), order_id))


def _set_direction(order_id: int, direction: str) -> None:
    _update_mit_order(order_id, direction=direction)


def _should_trigger(order: MitOrderRecord, deal_price: float) -> bool:
    if order.direction == "down":
        return deal_price <= order.trigger_price
    if order.direction == "up":
        return deal_price >= order.trigger_price
    return False


def _fire_order(order: MitOrderRecord, deal_price: float) -> None:
    request = OrderRequest(
        symbol=order.symbol,
        side=order.side,
        price=0,
        quantity=order.quantity,
        price_flag="M",
        confirm_send_order=True,
    )
    triggered_at = _now()
    # 模擬沙盒不做風控；實單以觸發價當市價單參考價估算金額。
    if not is_sim_session():
        preview = preview_order(request, reference_price=deal_price)
        if not preview.accepted:
            audit_order(request, "mit-blocked", "blocked", preview.message)
            _update_mit_order(order.id, status="failed", triggered_at=triggered_at, message=preview.message)
            return
    try:
        result = get_active_client().send_stock_order(request)
    except YuantaClientError as exc:
        audit_order(request, "mit-live", "error", str(exc))
        _update_mit_order(order.id, status="failed", triggered_at=triggered_at, message=str(exc))
        return
    audit_order(request, "mit-" + result.mode, "accepted" if result.accepted else "blocked", result.message)
    _update_mit_order(
        order.id,
        status="sent" if result.accepted else "failed",
        triggered_at=triggered_at,
        order_no=result.order_no,
        message=f"觸發價 {deal_price}：{result.message}",
    )


def evaluate_mit_orders(quotes_by_symbol: dict[str, QuoteResponse]) -> None:
    for order in list_pending_mit_orders():
        quote = quotes_by_symbol.get(order.symbol)
        deal_price = quote.deal_price if quote else None
        if deal_price is None or deal_price <= 0:
            continue
        if not order.direction:
            if deal_price > order.trigger_price:
                _set_direction(order.id, "down")
                order.direction = "down"
            elif deal_price < order.trigger_price:
                _set_direction(order.id, "up")
                order.direction = "up"
            else:
                order.direction = "down"  # already touching: fire immediately
        if _should_trigger(order, deal_price):
            _fire_order(order, deal_price)


async def run_mit_engine() -> None:
    # Import here to avoid a circular import at module load time.
    from ..api.quote_stream import get_quotes_prefer_live, in_market_hours

    while True:
        try:
            pending = await asyncio.to_thread(list_pending_mit_orders)
            client = get_active_client()
            sim = is_sim_session()
            if pending and client.status().connected and (sim or (not is_kill_switch_enabled() and in_market_hours())):
                symbols = sorted({order.symbol for order in pending})
                rows = await asyncio.to_thread(get_quotes_prefer_live, symbols)
                quotes_by_symbol = {row.symbol: row for row in rows}
                await asyncio.to_thread(evaluate_mit_orders, quotes_by_symbol)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MIT engine tick failed")
        await asyncio.sleep(ENGINE_INTERVAL)
