from datetime import datetime

from .schemas import KillSwitchResponse, OrderPreview, OrderRequest
from ..database import connect
from ..config import get_settings


MAX_SINGLE_ORDER_AMOUNT = 300_000
MAX_SINGLE_ORDER_LOTS = 499  # 單筆張數硬上限（普通交易單筆上限），超過須走鉅額/分盤


def is_tradeable_symbol(symbol: str) -> bool:
    """指數（加權 IX0001、櫃買 IX0043 等，元大指數代碼以 IX 開頭）不可下單。
    在風控層提前擋下，給明確訊息，避免送到券商才回拒或觸發合約查無錯誤。"""
    code = (symbol or "").strip().upper()
    if not code:
        return False
    return not code.startswith("IX")


def is_kill_switch_enabled() -> bool:
    with connect() as conn:
        row = conn.execute("SELECT value FROM risk_state WHERE key = ?", ("kill_switch",)).fetchone()
    return bool(row and row["value"] == "ON")


def set_kill_switch(enabled: bool) -> KillSwitchResponse:
    value = "ON" if enabled else "OFF"
    with connect() as conn:
        conn.execute(
            "INSERT INTO risk_state(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            ("kill_switch", value, datetime.now().isoformat(timespec="seconds")),
        )
    return KillSwitchResponse(
        enabled=enabled,
        message="風控停損已啟用，所有委託將被擋下。" if enabled else "風控停損已解除。",
    )


def preview_order(order: OrderRequest, reference_price: float | None = None) -> OrderPreview:
    settings = get_settings()
    is_market = order.price_flag == "M" or order.price <= 0
    # 市價單 price=0：改用即時參考價估算金額，避免金額上限對市價單失效。
    ref = order.price if order.price > 0 else (reference_price or 0)
    estimated_amount = ref * order.quantity * 1000
    reasons: list[str] = []

    if is_kill_switch_enabled():
        reasons.append("風控停損啟用中")
    if not is_tradeable_symbol(order.symbol):
        reasons.append(f"標的 {order.symbol or '(空)'} 不可下單（指數無法委託）")
    if order.side not in {"B", "S"}:
        reasons.append("買賣別必須為 B（買）或 S（賣）")
    if order.price_flag != "M" and order.price <= 0:
        reasons.append("限價單價格必須大於 0")
    if order.quantity > MAX_SINGLE_ORDER_LOTS:
        reasons.append(f"單筆張數 {order.quantity} 超過上限 {MAX_SINGLE_ORDER_LOTS} 張")
    if estimated_amount > MAX_SINGLE_ORDER_AMOUNT:
        reasons.append(
            f"預估金額 {estimated_amount:,.0f} 超過單筆上限 {MAX_SINGLE_ORDER_AMOUNT:,} 元"
            f"{'（市價單以參考價估算）' if is_market else ''}"
        )
    elif is_market and ref <= 0:
        # 市價單但取不到參考價 → 無法估金額，保守擋下避免無上限市價單。
        reasons.append("市價單暫時無法取得參考價估算金額，請改用限價或稍後再試")

    accepted = not reasons
    message = "委託預覽通過。" if accepted else "已擋下：" + "；".join(reasons)
    return OrderPreview(
        accepted=accepted,
        live_order_enabled=settings.yuanta_enable_order,
        message=message,
        estimated_amount=estimated_amount,
        order=order,
    )


def audit_order(order: OrderRequest, mode: str, status: str, message: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO order_audit(
                created_at, mode, symbol, side, price, quantity, price_flag, order_type,
                trade_kind, ap_code, time_in_force, status, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                mode,
                order.symbol,
                order.side,
                order.price,
                order.quantity,
                order.price_flag,
                order.order_type,
                order.trade_kind,
                order.ap_code,
                order.time_in_force,
                status,
                message,
            ),
        )
