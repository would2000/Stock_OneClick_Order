import time as time_module

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import require_api_key
from datetime import datetime
from typing import Any

from ..config import get_settings
from ..market_data.index_sampler import get_sampled_points
from ..market_data.jumbo_repository import load_jumbo_data
from ..market_data.repository import get_today_candidates
from ..trading.mit import cancel_mit_order, create_mit_order, list_mit_orders
from ..trading.risk import audit_order, preview_order, set_kill_switch
from ..trading.risk import is_kill_switch_enabled
from ..trading.schemas import (
    Candidate,
    CancelOrderRequest,
    HealthResponse,
    KLinePoint,
    KillSwitchRequest,
    KillSwitchResponse,
    LoginRequest,
    LoginState,
    MitOrderCreate,
    MitOrderRecord,
    OrderPreview,
    OrderRequest,
    OrderResult,
    Position,
    QuoteResponse,
    TradeRecord,
    WorkingOrder,
    YuantaStatus,
)
from ..broker import AVAILABLE_BROKERS, BROKER_LABELS, get_active_broker, get_active_client, is_sim_session, set_active_broker
from ..session import get_login_state, login as session_login, logout as session_logout, translate_broker_error
from ..yuanta.client import YuantaClientError
from .quote_stream import fetch_quotes_both_markets, get_quotes_prefer_live


router = APIRouter(prefix="/api")


INDEX_SYMBOLS = {
    "TSE": {"quote_market": "TWSE", "kline_market": "TWSE", "symbol": "IX0001", "display": "加權指數 TSE.TW"},
    "OTC": {"quote_market": "TWOTC", "kline_market": "TWOTC", "symbol": "IX0043", "display": "櫃買指數 OTC.TW"},
}

# Last good kline per (market, date). SDK kline queries time out sporadically;
# without this cache a failed refresh would degrade the chart to the sparse
# sampler points and wipe the morning's curve.
_KLINE_CACHE: dict[str, tuple[str, list[KLinePoint]]] = {}

# Minute-aggregated index points built from GetStkTickDetail (works for both
# IX0001 and IX0043, ~3000 rows per query), cached briefly because the query
# is heavy and goes through the serialized SDK lock.
_INDEX_TICK_CACHE: dict[str, tuple[str, float, list[dict[str, Any]]]] = {}
INDEX_TICK_TTL = 60.0


def _index_points_from_ticks(ticks) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    total = 0.0
    count = 0
    for tick in ticks:
        if not tick.deal_price or tick.deal_price <= 0:
            continue
        minute = tick.time[:5]
        total += tick.deal_price
        count += 1
        point = {"time": minute, "price": tick.deal_price, "avgPrice": total / count, "volume": 0}
        if points and points[-1]["time"] == minute:
            points[-1] = point
        else:
            points.append(point)
    return points


def _index_tick_points(market_key: str, selected_date: str) -> list[dict[str, Any]]:
    if selected_date != datetime.now().strftime("%Y/%m/%d"):
        return []  # Tick detail only covers today.
    spec = INDEX_SYMBOLS[market_key]
    cached = _INDEX_TICK_CACHE.get(market_key)
    now = time_module.monotonic()
    if cached and cached[0] == selected_date and now - cached[1] < INDEX_TICK_TTL:
        return cached[2]
    try:
        ticks = get_active_client().get_tick_detail(spec["symbol"], spec["quote_market"])
    except YuantaClientError:
        return cached[2] if cached and cached[0] == selected_date else []
    points = _index_points_from_ticks(ticks)
    if points:
        _INDEX_TICK_CACHE[market_key] = (selected_date, now, points)
    return points


def _index_points_from_kline(rows: list[KLinePoint]) -> list[dict[str, float | int | str]]:
    points: list[dict[str, float | int | str]] = []
    total_value = 0.0   # Σ close×volume（成交值，用於 VWAP）
    total_volume = 0
    price_sum = 0.0     # Σ close（尚無成交量時的均價 fallback）
    for index, row in enumerate(rows, start=1):
        volume = max(row.volume, 0)
        price_sum += row.close
        if volume:
            total_value += row.close * volume
            total_volume += volume
        # 一律以 VWAP 計算均價；無量時退回簡單均價。不可混用兩種累加器，
        # 否則富果指數的巨量（百億級）會在無量分鐘算出兆級均價尖刺、撐爆 Y 軸。
        avg_price = (total_value / total_volume) if total_volume > 0 else (price_sum / index)
        points.append(
            {
                "time": row.timestamp[11:16],
                "price": row.close,
                "avgPrice": avg_price,
                "volume": volume,
            }
        )
    return points


def _index_payload(market: str, quote: QuoteResponse | None, points: list[dict[str, Any]]) -> dict[str, Any]:
    spec = INDEX_SYMBOLS[market]
    prices = [point["price"] for point in points if isinstance(point["price"], (int, float))]
    volumes = [point["volume"] for point in points if isinstance(point["volume"], int)]
    current_price = quote.deal_price if quote and quote.deal_price is not None else (prices[-1] if prices else 0)
    prev_close = quote.prev_close if quote and quote.prev_close is not None else (prices[0] if prices else current_price)
    open_price = quote.open_price if quote and quote.open_price is not None else (prices[0] if prices else current_price)
    high_price = quote.high_price if quote and quote.high_price is not None else (max(prices) if prices else current_price)
    low_price = quote.low_price if quote and quote.low_price is not None else (min(prices) if prices else current_price)
    avg_price = points[-1]["avgPrice"] if points else current_price
    total_volume = quote.total_volume if quote and quote.total_volume is not None else sum(volumes)
    change = current_price - prev_close
    limit_up = quote.up_limit if quote and quote.up_limit and quote.up_limit > 0 else None
    limit_down = quote.down_limit if quote and quote.down_limit and quote.down_limit > 0 else None

    return {
        "points": points,
        "quote": {
            "market": market,
            "symbolName": spec["display"],
            "currentPrice": current_price,
            "openPrice": open_price,
            "highPrice": high_price,
            "lowPrice": low_price,
            "prevClose": prev_close,
            "avgPrice": avg_price,
            "change": change,
            "changePercent": (change / prev_close * 100) if prev_close else 0,
            "amplitudePercent": ((high_price - low_price) / prev_close * 100) if prev_close else 0,
            "volume": total_volume,
            "lastVolume": volumes[-1] if volumes else None,
            "innerVolume": None,
            "outerVolume": None,
            "limitUp": limit_up,
            "limitDown": limit_down,
        },
    }


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        yuanta_env=settings.yuanta_env,
        orders_enabled=settings.yuanta_enable_order,
        database_path=str(settings.database_path),
        market_data_root=settings.market_data_root,
    )


@router.get("/candidates/today", response_model=list[Candidate])
def today_candidates() -> list[Candidate]:
    return get_today_candidates()


@router.get("/broker")
def broker_info() -> dict[str, Any]:
    return {
        "active": get_active_broker(),
        "available": [{"id": item, "label": BROKER_LABELS[item]} for item in AVAILABLE_BROKERS],
        "status": get_active_client().status().model_dump(),
    }


@router.post("/broker/select", dependencies=[Depends(require_api_key)])
def broker_select(payload: dict[str, str]) -> dict[str, Any]:
    name = str(payload.get("broker", "")).lower()
    try:
        set_active_broker(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return broker_info()


@router.get("/auth/state", response_model=LoginState, dependencies=[Depends(require_api_key)])
def auth_state() -> LoginState:
    return get_login_state()


@router.get("/auth/remembered", dependencies=[Depends(require_api_key)])
def auth_remembered() -> dict[str, Any]:
    # 只回傳「已記住的欄位名」（Settings 屬性，不含值）與「留白時會沿用的憑證檔名」。
    from pathlib import Path  # noqa: PLC0415

    from ..session import remembered_fields  # noqa: PLC0415

    settings = get_settings()

    def _name(path: str) -> str:
        path = (path or "").strip()
        return Path(path).name if path else ""

    return {
        "fields": remembered_fields(),
        "certs": {
            "yuanta": _name(settings.yuanta_cert_path),
            "sinopac": _name(settings.shioaji_ca_path),
        },
    }


@router.post("/auth/login", response_model=LoginState, dependencies=[Depends(require_api_key)])
def auth_login(payload: LoginRequest) -> LoginState:
    try:
        state = session_login(payload)
    except YuantaClientError as exc:
        raise HTTPException(status_code=502, detail=translate_broker_error(str(exc))) from exc
    if not state.logged_in:
        raise HTTPException(status_code=502, detail=translate_broker_error(state.message))
    return state


@router.post("/auth/logout", response_model=LoginState, dependencies=[Depends(require_api_key)])
def auth_logout() -> LoginState:
    return session_logout()


@router.post("/auth/upload-cert", dependencies=[Depends(require_api_key)])
def auth_upload_cert(payload: dict[str, str]) -> dict[str, str]:
    """登入畫面以瀏覽檔案匯入 .pfx：前端讀檔轉 base64 上傳，存到受限執行階段
    目錄並回傳實際路徑，避免使用者手打路徑出錯。"""
    import base64  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    filename = Path(str(payload.get("filename", "")).strip()).name
    content_b64 = str(payload.get("content_base64", ""))
    if not filename or not content_b64:
        raise HTTPException(status_code=400, detail="缺少憑證檔名或內容。")
    if not filename.lower().endswith((".pfx", ".p12")):
        raise HTTPException(status_code=400, detail="僅接受 .pfx / .p12 憑證檔。")
    try:
        data = base64.b64decode(content_b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="憑證內容解碼失敗。") from exc

    dest_dir = get_settings().data_dir / "runtime_certs"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    dest.write_bytes(data)
    try:
        dest.chmod(0o600)
    except OSError:
        pass
    return {"path": str(dest), "filename": filename}


_SYMBOLS_CACHE: dict[str, Any] = {"mtime": 0.0, "rows": []}


def _load_symbols() -> list[dict[str, str]]:
    path = get_settings().data_dir / "symbols.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    if mtime != _SYMBOLS_CACHE["mtime"]:
        import json  # noqa: PLC0415

        try:
            _SYMBOLS_CACHE["rows"] = json.loads(path.read_text(encoding="utf-8"))
            _SYMBOLS_CACHE["mtime"] = mtime
        except (OSError, ValueError):
            return _SYMBOLS_CACHE["rows"]
    return _SYMBOLS_CACHE["rows"]


@router.get("/symbols/search")
def symbols_search(q: str = Query(..., min_length=1), limit: int = Query(default=15, le=50)) -> list[dict[str, str]]:
    query = q.strip().upper()
    rows = _load_symbols()
    hits = []
    for row in rows:
        code = row["code"].upper()
        name = row["name"].upper()
        if code.startswith(query) or query in name or query in code:
            hits.append(row)
    # Rank plain 4-digit stocks above warrants/ETNs, exact matches first.
    hits.sort(
        key=lambda row: (
            row["name"].upper() != query and row["code"].upper() != query,
            len(row["code"]) != 4,
            not row["code"].upper().startswith(query) and not row["name"].upper().startswith(query),
            row["code"],
        )
    )
    return hits[:limit]


@router.get("/yuanta/status", response_model=YuantaStatus)
def yuanta_status() -> YuantaStatus:
    return get_active_client().status()


@router.post("/yuanta/connect", response_model=YuantaStatus, dependencies=[Depends(require_api_key)])
def yuanta_connect() -> YuantaStatus:
    try:
        return get_active_client().connect()
    except YuantaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/yuanta/disconnect", response_model=YuantaStatus, dependencies=[Depends(require_api_key)])
def yuanta_disconnect() -> YuantaStatus:
    return get_active_client().disconnect()


@router.get("/quotes", response_model=list[QuoteResponse])
def quotes(
    symbols: str = Query(default=""),
    market: str = Query(default="TWSE"),
) -> list[QuoteResponse]:
    selected = [item.strip() for item in symbols.split(",") if item.strip()]
    if not selected:
        selected = [get_settings().default_symbol]

    try:
        return fetch_quotes_both_markets(selected, market)
    except YuantaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/positions", response_model=list[Position])
def positions() -> list[Position]:
    try:
        return get_active_client().get_positions()
    except YuantaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/kline", response_model=list[KLinePoint])
def kline(
    symbol: str = Query(..., min_length=2, max_length=12),
    market: str = Query(default="TWSE"),
    kline_type: str = Query(default="1M"),
    date: str = Query(default=""),
) -> list[KLinePoint]:
    selected_date = date or datetime.now().strftime("%Y/%m/%d")
    try:
        return get_active_client().get_kline(symbol, market, selected_date, selected_date, kline_type)
    except YuantaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/index-intraday")
def index_intraday(
    market: str = Query(..., pattern="^(TSE|OTC)$"),
    date: str = Query(default=""),
) -> dict[str, Any]:
    market_key = market.upper()
    spec = INDEX_SYMBOLS[market_key]
    selected_date = date or datetime.now().strftime("%Y/%m/%d")
    client = get_active_client()
    quote: QuoteResponse | None = None
    rows: list[KLinePoint] = []

    try:
        # Served from the push-fed cache when subscribed, avoiding an extra
        # serialized SDK round-trip that competes with kline queries.
        quotes = get_quotes_prefer_live([spec["symbol"]])
        quote = quotes[0] if quotes else None
    except YuantaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # 元大 SDK 只供 TSE 指數 kline（OTC 會 timeout）；模擬環境走富果，兩個指數都有 kline。
    if market_key == "TSE" or is_sim_session():
        try:
            rows = client.get_kline(spec["symbol"], spec["kline_market"], selected_date, selected_date, "1M")
        except YuantaClientError:
            rows = []
        if rows:
            _KLINE_CACHE[market_key] = (selected_date, rows)
        else:
            cached_date, cached_rows = _KLINE_CACHE.get(market_key, ("", []))
            if cached_date == selected_date:
                rows = cached_rows

    points = _index_points_from_kline(rows)
    if not points:
        # Both indexes serve full-day tick history; far more complete than
        # the sampler, which only covers the time since backend startup.
        points = _index_tick_points(market_key, selected_date)
    sampled = get_sampled_points(market_key)
    if points:
        # Extend the kline curve with sampler minutes newer than its tail, so
        # a lagging kline feed doesn't freeze the chart.
        have = {point["time"] for point in points}
        last_time = points[-1]["time"]
        last_avg = points[-1]["avgPrice"]
        # Carry the kline's cumulative average forward — the sampler's own
        # short-window average is discontinuous and draws a vertical artifact.
        points = points + [
            {**item, "avgPrice": last_avg}
            for item in sampled
            if item["time"] not in have and item["time"] > last_time
        ]
    else:
        # No kline at all (OTC, or TSE before the first successful query):
        # serve the sampler series built from realtime push quotes.
        points = sampled

    return _index_payload(market_key, quote, points)


@router.get("/jumbo-data")
def jumbo_data(
    market: str = Query(..., pattern="^(TSE|OTC)$"),
    date: str = Query(..., min_length=8),
) -> list[dict[str, object]]:
    return load_jumbo_data(market, date)


@router.post("/orders/preview", response_model=OrderPreview, dependencies=[Depends(require_api_key)])
def order_preview(order: OrderRequest) -> OrderPreview:
    preview = preview_order(order)
    audit_order(order, "preview", "accepted" if preview.accepted else "blocked", preview.message)
    return preview


@router.post("/orders/send", response_model=OrderResult, dependencies=[Depends(require_api_key)])
def send_order(order: OrderRequest) -> OrderResult:
    if not get_login_state().logged_in:
        raise HTTPException(status_code=401, detail="尚未登入，無法下單。")
    # 模擬沙盒：無任何安控、可隨意下單，跳過風控預覽。
    if not is_sim_session():
        # 市價單需即時參考價估算金額（讓金額上限對市價單也生效）。
        reference_price: float | None = None
        try:
            quotes = get_quotes_prefer_live([order.symbol])
            if quotes and quotes[0].deal_price:
                reference_price = float(quotes[0].deal_price)
        except Exception:  # noqa: BLE001
            reference_price = None
        preview = preview_order(order, reference_price=reference_price)
        if not preview.accepted:
            audit_order(order, "blocked", "blocked", preview.message)
            return OrderResult(accepted=False, mode="blocked", message=preview.message)

    try:
        result = get_active_client().send_stock_order(order)
    except YuantaClientError as exc:
        audit_order(order, "live", "error", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit_order(order, result.mode, "accepted" if result.accepted else "blocked", result.message)
    return result


@router.get("/tick-detail")
def tick_detail(
    symbol: str = Query(..., min_length=2, max_length=12),
    market: str = Query(default="TWSE"),
    select_type: int = Query(default=1),
    count: int = Query(default=5000),
) -> list[dict[str, Any]]:
    try:
        rows = get_active_client().get_tick_detail(symbol, market, select_type, count)
    except YuantaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [row.model_dump() for row in rows]


@router.get("/debug/raw-trades", dependencies=[Depends(require_api_key)])
def debug_raw_trades() -> list[str]:
    client = get_active_client()
    api = getattr(client, "_api", None)
    if api is None or not hasattr(api, "list_trades"):
        return ["no shioaji api"]
    try:
        api.update_status(api.stock_account)
    except Exception as exc:
        return [f"update_status error: {exc}"]
    out = []
    for trade in api.list_trades():
        try:
            status = str(trade.status.status).replace("Status.", "")
            out.append(
                f"id={trade.order.id} status={status} qty={trade.order.quantity} "
                f"deal_qty={getattr(trade.status, 'deal_quantity', None)} price={trade.order.price}"
            )
        except Exception as exc:
            out.append(f"PARSE ERROR: {type(exc).__name__}: {exc}")
    return out


@router.get("/orders/working", response_model=list[WorkingOrder])
def working_orders(status: str = "unfilled") -> list[WorkingOrder]:
    """今日委託查詢。status：all=全部委託(含已成交/取消)、unfilled=未結案委託(預設,供閃電面板)。

    四類分類（已成交/未完全成交/未成交/取消）由前端依 ok_qty、after_qty 與 cancelled 判斷。
    """
    try:
        rows = [row for row in get_active_client().get_stock_orders() if row.order_no]
    except YuantaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if status == "all":
        return rows
    # 預設 unfilled：已委託(狀態 20)、未取消、且尚有未成交剩餘（閃電面板/統計用）。
    return [
        row
        for row in rows
        if row.status == "20" and not row.cancelled and row.after_qty - row.ok_qty > 0
    ]


@router.get("/orders/trades", response_model=list[TradeRecord])
def order_trades() -> list[TradeRecord]:
    try:
        return get_active_client().get_stock_trades()
    except YuantaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/orders/cancel", response_model=OrderResult, dependencies=[Depends(require_api_key)])
def cancel_order(request: CancelOrderRequest) -> OrderResult:
    order = OrderRequest(
        symbol=request.symbol,
        side=request.side,
        price=request.price,
        quantity=request.quantity,
        price_flag=request.price_flag,
        order_type=request.order_type,
        trade_kind=4,
        order_no=request.order_no,
        confirm_send_order=True,
    )
    try:
        result = get_active_client().cancel_stock_order(order)
    except YuantaClientError as exc:
        audit_order(order, "cancel", "error", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    audit_order(order, "cancel", "accepted" if result.accepted else "blocked", result.message)
    return result


@router.get("/mit-orders", response_model=list[MitOrderRecord])
def mit_orders() -> list[MitOrderRecord]:
    return list_mit_orders()


@router.post("/mit-orders", response_model=MitOrderRecord, dependencies=[Depends(require_api_key)])
def add_mit_order(request: MitOrderCreate) -> MitOrderRecord:
    if not get_login_state().logged_in:
        raise HTTPException(status_code=401, detail="尚未登入，無法建立 MIT 觸價單。")
    return create_mit_order(request)


@router.post("/mit-orders/{order_id}/cancel", response_model=MitOrderRecord, dependencies=[Depends(require_api_key)])
def cancel_mit(order_id: int) -> MitOrderRecord:
    record = cancel_mit_order(order_id)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到 MIT 觸價單。")
    return record


@router.post("/risk/kill-switch", response_model=KillSwitchResponse, dependencies=[Depends(require_api_key)])
def kill_switch(request: KillSwitchRequest) -> KillSwitchResponse:
    return set_kill_switch(request.enabled)


@router.get("/risk/kill-switch", response_model=KillSwitchResponse)
def kill_switch_status() -> KillSwitchResponse:
    enabled = is_kill_switch_enabled()
    return KillSwitchResponse(
        enabled=enabled,
        message="風控停損已啟用，所有委託將被擋下。" if enabled else "風控停損已解除。",
    )
