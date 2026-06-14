from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    yuanta_env: str
    orders_enabled: bool
    database_path: str
    market_data_root: str


class YuantaStatus(BaseModel):
    state: str
    connected: bool
    environment: str
    account: str = ""
    account_name: str = ""
    last_error: str = ""


class Candidate(BaseModel):
    symbol: str
    name: str
    strategy_tag: str
    score: float
    reason: str
    risk_level: str


class QuoteResponse(BaseModel):
    market: str
    symbol: str
    name: str = ""
    deal_price: float | None = None
    prev_close: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    total_volume: int | None = None
    bid_volume: int | None = None
    ask_volume: int | None = None
    up_limit: float | None = None
    down_limit: float | None = None
    source: str


class TickRecord(BaseModel):
    symbol: str
    serial: int = 0
    time: str
    bid_price: float | None = None
    ask_price: float | None = None
    deal_price: float | None = None
    volume: int = 0
    in_out: str = ""


class KLinePoint(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class Position(BaseModel):
    symbol: str
    name: str = ""
    quantity: int
    market_price: float | None = None
    market_amount: float | None = None
    cost: float | None = None
    unrealized_pnl: float | None = None


class OrderRequest(BaseModel):
    symbol: str = Field(min_length=2, max_length=12)
    side: str = Field(pattern="^[BS]$")
    price: float = Field(ge=0)
    quantity: int = Field(gt=0, le=499)
    price_flag: str = "M"
    order_type: str = "0"
    trade_kind: int = 0
    ap_code: int = 0
    time_in_force: str = "0"
    order_no: str = ""
    confirm_send_order: bool = False


class WorkingOrder(BaseModel):
    order_no: str
    symbol: str
    name: str = ""
    side: str
    price: float = 0
    price_flag: str = ""
    order_type: str = "0"
    before_qty: int = 0
    after_qty: int = 0
    ok_qty: int = 0
    status: str = ""


class TradeRecord(BaseModel):
    order_no: str
    symbol: str
    name: str = ""
    side: str
    price: float = 0
    quantity: int = 0
    time: str = ""


class CancelOrderRequest(BaseModel):
    order_no: str = Field(min_length=1)
    symbol: str = Field(min_length=2, max_length=12)
    side: str = Field(pattern="^[BS]$")
    price: float = Field(ge=0)
    quantity: int = Field(gt=0)
    price_flag: str = ""
    order_type: str = "0"


class OrderPreview(BaseModel):
    accepted: bool
    live_order_enabled: bool
    message: str
    estimated_amount: float
    order: OrderRequest


class OrderResult(BaseModel):
    accepted: bool
    mode: str
    message: str
    order_no: str | None = None


class MitOrderCreate(BaseModel):
    symbol: str = Field(min_length=2, max_length=12)
    side: str = Field(pattern="^[BS]$")
    trigger_price: float = Field(gt=0)
    quantity: int = Field(gt=0, le=499)
    reference_price: float | None = None


class MitOrderRecord(BaseModel):
    id: int
    created_at: str
    symbol: str
    side: str
    trigger_price: float
    quantity: int
    direction: str
    status: str
    triggered_at: str | None = None
    order_no: str | None = None
    message: str = ""


class LoginRequest(BaseModel):
    # sim=模擬沙盒（免安控）、yuanta=元大實單、sinopac=永豐金實單
    environment: str = Field(pattern="^(sim|yuanta|sinopac)$")
    # 留白者沿用 .env 既有設定（敏感欄位不必每次重打）。
    account: str = ""
    password: str = ""
    cert_path: str = ""
    cert_password: str = ""
    api_key: str = ""
    secret_key: str = ""
    person_id: str = ""
    # 各欄位是否記住（鍵為欄位名：account/password/cert_password/api_key/secret_key/person_id）
    remember: dict[str, bool] = {}


class LoginState(BaseModel):
    logged_in: bool
    environment: str = ""
    broker: str = ""
    broker_label: str = ""
    account: str = ""
    account_name: str = ""
    is_sim: bool = False
    message: str = ""


class KillSwitchRequest(BaseModel):
    enabled: bool


class KillSwitchResponse(BaseModel):
    enabled: bool
    message: str
