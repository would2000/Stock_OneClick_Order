"""Shared order submission pipeline for manual and server-side triggered orders."""

from __future__ import annotations

import threading
import time

from ..api.quote_stream import get_quotes_prefer_live
from ..broker import get_active_client, is_sim_session
from ..session import get_login_state
from ..yuanta.client import YuantaClientError
from .risk import audit_order, is_kill_switch_enabled, preview_order
from .schemas import OrderRequest, OrderResult


ORDER_RATE_WINDOW = 2.0
ORDER_RATE_MAX = 20
_recent_order_times: list[float] = []
_rate_lock = threading.Lock()


def _audit_mode(source: str, mode: str) -> str:
    return mode if source == "manual" else f"{source}-{mode}"


def _rate_limited() -> bool:
    now = time.monotonic()
    with _rate_lock:
        _recent_order_times[:] = [t for t in _recent_order_times if now - t < ORDER_RATE_WINDOW]
        if len(_recent_order_times) >= ORDER_RATE_MAX:
            return True
        _recent_order_times.append(now)
        return False


def _reference_price(order: OrderRequest) -> float | None:
    try:
        quotes = get_quotes_prefer_live([order.symbol])
    except Exception:  # noqa: BLE001
        return None
    if quotes and quotes[0].deal_price:
        return float(quotes[0].deal_price)
    return None


def submit_order(
    order: OrderRequest,
    *,
    source: str = "manual",
    reference_price: float | None = None,
    require_login: bool = True,
    raise_broker_errors: bool = False,
) -> OrderResult:
    """Apply server-side safety checks, send through the active broker, and audit once."""
    if require_login and not get_login_state().logged_in:
        message = "尚未登入，無法下單。"
        audit_order(order, _audit_mode(source, "blocked"), "blocked", message)
        return OrderResult(accepted=False, mode="blocked", message=message)

    if _rate_limited():
        message = "下單頻率過高，已暫時擋下，請稍候再試。"
        audit_order(order, _audit_mode(source, "blocked"), "blocked", message)
        return OrderResult(accepted=False, mode="blocked", message=message)

    if is_kill_switch_enabled():
        message = "風控停損啟用中，已擋下委託。"
        audit_order(order, _audit_mode(source, "blocked"), "blocked", message)
        return OrderResult(accepted=False, mode="blocked", message=message)

    if not is_sim_session():
        price = reference_price if reference_price is not None else _reference_price(order)
        preview = preview_order(order, reference_price=price)
        if not preview.accepted:
            audit_order(order, _audit_mode(source, "blocked"), "blocked", preview.message)
            return OrderResult(accepted=False, mode="blocked", message=preview.message)

    try:
        result = get_active_client().send_stock_order(order)
    except YuantaClientError as exc:
        audit_order(order, _audit_mode(source, "live"), "error", str(exc))
        if raise_broker_errors:
            raise
        return OrderResult(accepted=False, mode="error", message=str(exc))

    audit_order(order, _audit_mode(source, result.mode), "accepted" if result.accepted else "blocked", result.message)
    return result
