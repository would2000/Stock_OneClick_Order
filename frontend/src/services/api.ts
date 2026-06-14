import type {
  Candidate,
  HealthResponse,
  IndexIntradayResponse,
  KLinePoint,
  MitOrderRecord,
  OrderPreview,
  OrderRequest,
  OrderResult,
  Position,
  Quote,
  TradeRecord2,
  WorkingOrder,
  YuantaStatus
} from "../types/api";

// 後端敏感端點需要 X-API-Key。金鑰由 Vite 於建置/開發時從 VITE_API_KEY 注入，
// 僅在 localhost 單機環境使用，用以擋住同機其他程序與跨來源 CSRF。
const API_KEY = import.meta.env.VITE_API_KEY ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      ...init?.headers
    }
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail ?? `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export type BrokerInfo = {
  active: string;
  available: { id: string; label: string }[];
  status: YuantaStatus;
};

export function getBrokerInfo() {
  return request<BrokerInfo>("/api/broker");
}

export type LoginEnvironment = "sim" | "yuanta" | "sinopac";

export type LoginState = {
  logged_in: boolean;
  environment: string;
  broker: string;
  broker_label: string;
  account: string;
  account_name: string;
  is_sim: boolean;
  message: string;
};

export type LoginPayload = {
  environment: LoginEnvironment;
  account?: string;
  password?: string;
  cert_path?: string;
  cert_password?: string;
  api_key?: string;
  secret_key?: string;
  person_id?: string;
  remember?: Record<string, boolean>;
};

export function getAuthState() {
  return request<LoginState>("/api/auth/state");
}

export function getRemembered() {
  return request<{ fields: string[]; certs: { yuanta: string; sinopac: string } }>("/api/auth/remembered");
}

export function login(payload: LoginPayload) {
  return request<LoginState>("/api/auth/login", { method: "POST", body: JSON.stringify(payload) });
}

export function logout() {
  return request<LoginState>("/api/auth/logout", { method: "POST" });
}

export function uploadCert(filename: string, contentBase64: string) {
  return request<{ path: string; filename: string }>("/api/auth/upload-cert", {
    method: "POST",
    body: JSON.stringify({ filename, content_base64: contentBase64 })
  });
}

export function selectBroker(broker: string) {
  return request<BrokerInfo>("/api/broker/select", {
    method: "POST",
    body: JSON.stringify({ broker })
  });
}

export type SymbolHit = { code: string; name: string; exchange: string };

export function searchSymbols(q: string) {
  return request<SymbolHit[]>(`/api/symbols/search?q=${encodeURIComponent(q)}`);
}

export function getHealth() {
  return request<HealthResponse>("/api/health");
}

export function getCandidates() {
  return request<Candidate[]>("/api/candidates/today");
}

export function getYuantaStatus() {
  return request<YuantaStatus>("/api/yuanta/status");
}

export function connectYuanta() {
  return request<YuantaStatus>("/api/yuanta/connect", { method: "POST" });
}

export function disconnectYuanta() {
  return request<YuantaStatus>("/api/yuanta/disconnect", { method: "POST" });
}

export function getQuotes(symbols: string[]) {
  return request<Quote[]>(`/api/quotes?symbols=${encodeURIComponent(symbols.join(","))}`);
}

export function getPositions() {
  return request<Position[]>("/api/positions");
}

export function getKline(symbol: string, market?: string) {
  const marketQuery = market ? `&market=${encodeURIComponent(market)}` : "";
  return request<KLinePoint[]>(`/api/kline?symbol=${encodeURIComponent(symbol)}${marketQuery}&kline_type=1M`);
}

export function getIndexIntraday(market: "TSE" | "OTC") {
  return request<IndexIntradayResponse>(`/api/index-intraday?market=${market}`);
}

export function previewOrder(order: OrderRequest) {
  return request<OrderPreview>("/api/orders/preview", {
    method: "POST",
    body: JSON.stringify(order)
  });
}

export function sendOrder(order: OrderRequest) {
  return request<OrderResult>("/api/orders/send", {
    method: "POST",
    body: JSON.stringify(order)
  });
}

export function getOrderTrades() {
  return request<TradeRecord2[]>("/api/orders/trades");
}

export function getWorkingOrders() {
  return request<WorkingOrder[]>("/api/orders/working");
}

export function cancelWorkingOrder(payload: {
  order_no: string;
  symbol: string;
  side: "B" | "S";
  price: number;
  quantity: number;
  price_flag?: string;
  order_type?: string;
}) {
  return request<OrderResult>("/api/orders/cancel", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getMitOrders() {
  return request<MitOrderRecord[]>("/api/mit-orders");
}

export function createMitOrder(payload: {
  symbol: string;
  side: "B" | "S";
  trigger_price: number;
  quantity: number;
  reference_price?: number | null;
}) {
  return request<MitOrderRecord>("/api/mit-orders", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function cancelMitOrder(id: number) {
  return request<MitOrderRecord>(`/api/mit-orders/${id}/cancel`, { method: "POST" });
}

export function setKillSwitch(enabled: boolean) {
  return request<{ enabled: boolean; message: string }>("/api/risk/kill-switch", {
    method: "POST",
    body: JSON.stringify({ enabled })
  });
}

export function getKillSwitch() {
  return request<{ enabled: boolean; message: string }>("/api/risk/kill-switch");
}
