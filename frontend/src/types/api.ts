export type HealthResponse = {
  status: string;
  yuanta_env: string;
  orders_enabled: boolean;
  database_path: string;
  market_data_root: string;
};

export type YuantaStatus = {
  state: string;
  connected: boolean;
  environment: string;
  account: string;
  account_name: string;
  last_error: string;
};

export type Candidate = {
  symbol: string;
  name: string;
  strategy_tag: string;
  score: number;
  reason: string;
  risk_level: string;
};

export type Quote = {
  market: string;
  symbol: string;
  name: string;
  deal_price: number | null;
  prev_close: number | null;
  bid_price: number | null;
  ask_price: number | null;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  total_volume: number | null;
  bid_volume?: number | null;
  ask_volume?: number | null;
  up_limit: number | null;
  down_limit: number | null;
  source: string;
};

export type TickRecord = {
  symbol: string;
  serial: number;
  time: string;
  bid_price: number | null;
  ask_price: number | null;
  deal_price: number | null;
  volume: number;
  in_out: string;
};

export type FiveTickLevel = { price: number | null; volume: number };
export type FiveTickBook = { bids: FiveTickLevel[]; asks: FiveTickLevel[] };

export type KLinePoint = {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type IndexIntradayPointResponse = {
  time: string;
  price: number;
  avgPrice: number;
  volume: number;
};

export type IndexIntradayQuoteResponse = {
  market: "TSE" | "OTC";
  symbolName: string;
  currentPrice: number;
  openPrice: number;
  highPrice: number;
  lowPrice: number;
  prevClose: number;
  avgPrice: number;
  change: number;
  changePercent: number;
  amplitudePercent: number;
  volume: number;
  lastVolume?: number | null;
  innerVolume?: number | null;
  outerVolume?: number | null;
  limitUp?: number | null;
  limitDown?: number | null;
};

export type IndexIntradayResponse = {
  points: IndexIntradayPointResponse[];
  quote: IndexIntradayQuoteResponse;
};

export type Position = {
  symbol: string;
  name: string;
  quantity: number;
  market_price: number | null;
  market_amount: number | null;
  unrealized_pnl: number | null;
};

export type OrderRequest = {
  symbol: string;
  side: "B" | "S";
  price: number;
  quantity: number;
  price_flag: string;
  order_type: string;
  trade_kind: number;
  ap_code: number;
  time_in_force: string;
  confirm_send_order: boolean;
};

export type OrderPreview = {
  accepted: boolean;
  live_order_enabled: boolean;
  message: string;
  estimated_amount: number;
  order: OrderRequest;
};

export type WorkingOrder = {
  order_no: string;
  symbol: string;
  name: string;
  side: "B" | "S";
  price: number;
  price_flag: string;
  order_type: string;
  before_qty: number;
  after_qty: number;
  ok_qty: number;
  status: string;
  cancelled?: boolean;
  accept_time?: string; // 委託成立時間
};

export type TradeRecord2 = {
  order_no: string;
  symbol: string;
  name: string;
  side: "B" | "S";
  price: number;
  quantity: number;
  time: string;
};

export type MitOrderRecord = {
  id: number;
  created_at: string;
  symbol: string;
  side: "B" | "S";
  trigger_price: number;
  quantity: number;
  direction: string;
  status: "pending" | "sent" | "failed" | "cancelled";
  triggered_at: string | null;
  order_no: string | null;
  message: string;
  filled_qty?: number; // 觸發後送出委託的成交股數（後端回查回填）
  order_cancelled?: boolean;
};

export type OrderResult = {
  accepted: boolean;
  mode: string;
  message: string;
  order_no: string | null;
};
