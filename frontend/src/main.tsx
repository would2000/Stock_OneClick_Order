import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { CheckSquare, Crosshair, Link2Off, Loader2, Pencil, PlayCircle, Plus, RefreshCw, Save, Send, Square, Trash2, X } from "lucide-react";
import {
  cancelMitOrder,
  connectYuanta,
  getBrokerInfo,
  type BrokerInfo,
  createMitOrder,
  getMitOrders,
  getCandidates,
  getHealth,
  getIndexIntraday,
  getKillSwitch,
  getKline,
  getPositions,
  getQuotes,
  getWorkingOrders,
  getYuantaStatus,
  cancelWorkingOrder,
  searchSymbols,
  sendOrder,
  getAuthState,
  logout as apiLogout,
  type LoginState,
  type SymbolHit
} from "./services/api";
import { LoginScreen } from "./components/LoginScreen";
import type {
  Candidate,
  FiveTickBook,
  HealthResponse,
  IndexIntradayResponse,
  KLinePoint,
  MitOrderRecord,
  OrderPreview,
  OrderRequest,
  OrderResult,
  Position,
  Quote,
  TickRecord,
  WorkingOrder,
  YuantaStatus
} from "./types/api";
import "./styles.css";
import { useQuoteStream } from "./services/quoteStream";
import { loadDailyTicks, saveDailyTicks } from "./services/tickStore";
import type { IndexIntradayPoint, IndexIntradayQuote } from "./charts/indexIntradayChartOption";
import { IndexIntradayChart } from "./components/IndexIntradayChart";
import { IndexIntradayChartDemo } from "./pages/IndexIntradayChartDemo";
import { JumboChartDemo } from "./pages/JumboChartDemo";
import { JumboChartPage } from "./pages/JumboChartPage";

type ThemeName = "light" | "dark" | "warm" | "cool";
type MainTab = "orders" | "mit" | "inventory";
// all=全部委託、none=未成交(含取消)、partial=未完全成交、filled=已成交
type OrderFilter = "all" | "none" | "partial" | "filled";
type PortfolioTab = "live" | "watchlist";
type WatchItem = { symbol: string; name: string; cost: number; lots: number; shares: number };
type IndexIntradayModel = { points: IndexIntradayPoint[]; quote: IndexIntradayQuote };
type LightningActionKind = "order" | "mit";
type LightningAction = { kind: LightningActionKind; side: "B" | "S"; price: number; symbol: string; quantity: number };

const MIT_STATUS_TEXT: Record<MitOrderRecord["status"], string> = {
  pending: "待觸價",
  sent: "已觸發送單",
  failed: "觸發失敗",
  cancelled: "已取消"
};

// MIT 顯示狀態：已觸發(sent)依回查的成交量分 已成交/部份成交/未成交；其餘沿用觸發狀態。
function mitStatusText(m: MitOrderRecord): string {
  if (m.status !== "sent") return MIT_STATUS_TEXT[m.status] ?? m.status;
  if (m.order_cancelled) return "已取消";
  const filledLots = (m.filled_qty ?? 0) / 1000;
  if (filledLots > 0 && filledLots >= m.quantity) return "已成交";
  if (filledLots > 0) return "部份成交";
  return "未成交";
}
type PriceLadderRow = {
  price: number;
  label: string;
  isCurrent: boolean;
  isLimitUp: boolean;
  isLimitDown: boolean;
  isBid: boolean;
  isAsk: boolean;
};

const defaultOrder: OrderRequest = {
  symbol: "2885",
  side: "B",
  price: 0,
  quantity: 1,
  price_flag: "M",
  order_type: "0",
  trade_kind: 0,
  ap_code: 0,
  time_in_force: "0",
  confirm_send_order: false
};

const alerts = [
  { time: "12:45:30", symbol: "2885", level: "INFO", message: "報價刷新完成" },
  { time: "12:43:18", symbol: "2330", level: "WARN", message: "成交量高於近 20 日均量" },
  { time: "12:39:02", symbol: "6727", level: "SIGNAL", message: "盤中策略訊號預留區" }
];

const initialWatchlist: WatchItem[] = [
  { symbol: "2885", name: "元大金", cost: 35, lots: 1, shares: 0 },
  { symbol: "2330", name: "台積電", cost: 2100, lots: 1, shares: 0 },
  { symbol: "6727", name: "亞泰金屬", cost: 420, lots: 1, shares: 0 }
];

type Watchlist = { id: string; name: string; items: WatchItem[] };

const WATCHLISTS_KEY = "yuanta.watchlists.v1";

function newListId(): string {
  return `list-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
}

function loadWatchlists(): Watchlist[] {
  try {
    const raw = window.localStorage.getItem(WATCHLISTS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Watchlist[];
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed
          .filter((list) => list && typeof list.id === "string")
          .map((list) => ({
            id: list.id,
            name: list.name || "選股",
            items: (Array.isArray(list.items) ? list.items : []).map((item) => ({
              symbol: String(item.symbol ?? ""),
              name: String(item.name ?? ""),
              cost: Number(item.cost) || 0,
              lots: Number(item.lots) || 0,
              shares: Number(item.shares) || 0
            }))
          }));
      }
    }
  } catch {
    // 壞掉的儲存就用預設
  }
  return [{ id: newListId(), name: "選股1", items: initialWatchlist }];
}

type ColResize = {
  widths: Record<number, number>;
  startResize: (index: number) => (event: React.MouseEvent) => void;
  tableStyle: React.CSSProperties | undefined;
};

function useColResize(): ColResize {
  const [widths, setWidths] = useState<Record<number, number>>({});
  const startResize = useCallback(
    (index: number) => (event: React.MouseEvent) => {
      event.preventDefault();
      event.stopPropagation();
      const th = (event.currentTarget as HTMLElement).closest("th");
      if (!th) return;
      const startX = event.clientX;
      const startWidth = th.getBoundingClientRect().width;
      const onMove = (move: MouseEvent) => {
        const next = Math.max(36, Math.round(startWidth + move.clientX - startX));
        setWidths((prev) => ({ ...prev, [index]: next }));
      };
      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
      document.body.style.cursor = "col-resize";
    },
    []
  );
  const tableStyle = useMemo<React.CSSProperties | undefined>(
    () => (Object.keys(widths).length > 0 ? { tableLayout: "fixed" } : undefined),
    [widths]
  );
  return { widths, startResize, tableStyle };
}

function Th({ col, resize, children }: { col: number; resize: ColResize; children?: React.ReactNode }) {
  const width = resize.widths[col];
  return (
    <th style={width ? { width, minWidth: width, maxWidth: width } : undefined}>
      {children}
      <span className="colResizer" onMouseDown={resize.startResize(col)} />
    </th>
  );
}

function numberText(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toLocaleString("zh-TW", { maximumFractionDigits: digits });
}

function priceTick(price: number) {
  if (price < 10) return 0.01;
  if (price < 50) return 0.05;
  if (price < 100) return 0.1;
  if (price < 500) return 0.5;
  if (price < 1000) return 1;
  return 5;
}

function roundToTick(price: number, tick: number) {
  return Math.round(price / tick) * tick;
}

function formatPrice(value: number) {
  return Number.isInteger(value) ? value.toLocaleString("zh-TW") : value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

function buildPriceLadder(quote: Quote | undefined, fallbackPrice: number): PriceLadderRow[] {
  const current = quote?.deal_price || fallbackPrice || 0;
  if (!current) {
    return [];
  }
  const tick = priceTick(current);
  const upLimit = quote?.up_limit && quote.up_limit > 0 ? quote.up_limit : current + tick * 20;
  const downLimit = quote?.down_limit && quote.down_limit > 0 ? quote.down_limit : Math.max(tick, current - tick * 20);
  const top = roundToTick(Math.max(upLimit, current), tick);
  const bottom = roundToTick(Math.min(downLimit, current), tick);
  const currentRounded = roundToTick(current, tick);
  const bidRounded = quote?.bid_price && quote.bid_price > 0 ? roundToTick(quote.bid_price, tick) : null;
  const askRounded = quote?.ask_price && quote.ask_price > 0 ? roundToTick(quote.ask_price, tick) : null;
  const rows: PriceLadderRow[] = [];

  for (let price = top; price >= bottom - tick / 2; price -= tick) {
    const normalized = Math.round(price * 100) / 100;
    rows.push({
      price: normalized,
      label: formatPrice(normalized),
      isCurrent: Math.abs(normalized - currentRounded) < tick / 2,
      isLimitUp: Math.abs(normalized - upLimit) < tick / 2,
      isLimitDown: Math.abs(normalized - downLimit) < tick / 2,
      isBid: bidRounded !== null && Math.abs(normalized - bidRounded) < tick / 2,
      isAsk: askRounded !== null && Math.abs(normalized - askRounded) < tick / 2
    });
  }

  return rows;
}

function klineToIndexPoints(points: KLinePoint[]): IndexIntradayPoint[] {
  let totalPriceVolume = 0;
  let totalVolume = 0;
  return points
    .map((point) => {
      const volume = Math.max(0, point.volume);
      totalPriceVolume += point.close * volume;
      totalVolume += volume;
      return {
        time: point.timestamp.slice(11, 16),
        price: point.close,
        avgPrice: totalVolume ? totalPriceVolume / totalVolume : point.close,
        volume
      };
    })
    .sort((left, right) => left.time.localeCompare(right.time));
}

function buildEmptyIndexModel(market: "TSE" | "OTC", symbolName: string): IndexIntradayModel {
  return {
    points: [],
    quote: {
      market,
      symbolName,
      currentPrice: 0,
      openPrice: 0,
      highPrice: 0,
      lowPrice: 0,
      prevClose: 0,
      avgPrice: 0,
      change: 0,
      changePercent: 0,
      amplitudePercent: 0,
      volume: 0
    }
  };
}

function modelFromIndexResponse(response: IndexIntradayResponse): IndexIntradayModel {
  return {
    points: response.points,
    quote: {
      ...response.quote,
      lastVolume: response.quote.lastVolume ?? undefined,
      innerVolume: response.quote.innerVolume ?? undefined,
      outerVolume: response.quote.outerVolume ?? undefined,
      limitUp: response.quote.limitUp ?? undefined,
      limitDown: response.quote.limitDown ?? undefined
    }
  };
}

function buildIndexModelFromPoints(
  market: "TSE" | "OTC",
  symbolName: string,
  points: IndexIntradayPoint[],
  prevClose: number,
  quote?: Quote
): IndexIntradayModel {
  const prices = points.map((point) => point.price);
  const volumes = points.map((point) => point.volume);
  const currentPrice = quote?.deal_price ?? prices[prices.length - 1] ?? prevClose;
  const highPrice = Math.max(...prices, currentPrice);
  const lowPrice = Math.min(...prices, currentPrice);
  const openPrice = prices[0] ?? currentPrice;
  const avgPrice = points[points.length - 1]?.avgPrice ?? currentPrice;
  const volume = quote?.total_volume ?? volumes.reduce((sum, item) => sum + item, 0);
  const change = currentPrice - prevClose;

  return {
    points,
    quote: {
      market,
      symbolName,
      currentPrice,
      bidPrice: quote?.bid_price ?? currentPrice,
      askPrice: quote?.ask_price ?? currentPrice,
      openPrice,
      highPrice,
      lowPrice,
      prevClose,
      avgPrice,
      change,
      changePercent: prevClose ? (change / prevClose) * 100 : 0,
      amplitudePercent: prevClose ? ((highPrice - lowPrice) / prevClose) * 100 : 0,
      volume,
      lastVolume: volumes[volumes.length - 1],
      innerVolume: Math.round(volume * 0.52),
      outerVolume: Math.round(volume * 0.48),
      volumeIncreasePercent: 0,
      limitUp: Math.round(prevClose * 1.1 * 100) / 100,
      limitDown: Math.round(prevClose * 0.9 * 100) / 100
    }
  };
}

function buildStockQuoteOnlyModel(symbol: string, name: string, fallbackPrice: number, quote?: Quote): IndexIntradayModel {
  const currentPrice = quote?.deal_price ?? fallbackPrice;
  const prevClose = quote?.prev_close ?? currentPrice;
  const openPrice = quote?.open_price ?? currentPrice;
  const highPrice = quote?.high_price ?? currentPrice;
  const lowPrice = quote?.low_price ?? currentPrice;
  const avgPrice = currentPrice;
  const change = currentPrice - prevClose;
  return {
    points: [],
    quote: {
      market: quote?.market === "TWOTC" ? "OTC" : "TSE",
      symbolName: `${name} ${symbol}`,
      currentPrice,
      bidPrice: quote?.bid_price ?? undefined,
      askPrice: quote?.ask_price ?? undefined,
      openPrice,
      highPrice,
      lowPrice,
      prevClose,
      avgPrice,
      change,
      changePercent: prevClose ? (change / prevClose) * 100 : 0,
      amplitudePercent: prevClose ? ((highPrice - lowPrice) / prevClose) * 100 : 0,
      volume: quote?.total_volume ?? 0,
      lastVolume: undefined,
      innerVolume: undefined,
      outerVolume: undefined,
      limitUp: quote?.up_limit ?? undefined,
      limitDown: quote?.down_limit ?? undefined
    }
  };
}

function mergeIndexLiveQuote(model: IndexIntradayModel, live: Quote | undefined): IndexIntradayModel {
  const price = live?.deal_price;
  if (!price || price <= 0) {
    return model;
  }
  const prevClose = live?.prev_close && live.prev_close > 0 ? live.prev_close : model.quote.prevClose;
  const change = prevClose ? price - prevClose : model.quote.change;
  return {
    ...model,
    quote: {
      ...model.quote,
      currentPrice: price,
      prevClose,
      change,
      changePercent: prevClose ? (change / prevClose) * 100 : model.quote.changePercent,
      highPrice: Math.max(model.quote.highPrice, price),
      lowPrice: model.quote.lowPrice > 0 ? Math.min(model.quote.lowPrice, price) : price,
      volume: live?.total_volume || model.quote.volume
    }
  };
}

function isSamePriceScale(left: number | null | undefined, right: number | null | undefined) {
  if (!left || !right || left <= 0 || right <= 0) {
    return false;
  }
  const ratio = Math.max(left, right) / Math.min(left, right);
  return ratio <= 2.5;
}

function buildStockIntradayModel(
  symbol: string,
  name: string,
  fallbackPrice: number,
  quote?: Quote,
  kline: KLinePoint[] = []
): IndexIntradayModel {
  if (kline.length > 0) {
    const points = klineToIndexPoints(kline);
    const klineLastPrice = points[points.length - 1]?.price;
    // Only sanity-check the price scale against a real quote; the synthetic
    // fallback price (e.g. watchlist cost or the 50 default) must not veto a
    // valid kline while quotes are still loading.
    const klineMatchesSelectedSymbol = quote?.deal_price ? isSamePriceScale(klineLastPrice, quote.deal_price) : true;

    if (klineMatchesSelectedSymbol) {
      const quoteMatchesKline = isSamePriceScale(quote?.deal_price, klineLastPrice);
      const compatibleQuote = quoteMatchesKline ? quote : undefined;
      const prevClose = kline[0]?.open || points[0]?.price || compatibleQuote?.deal_price || fallbackPrice;
      return buildIndexModelFromPoints("TSE", `${name} ${symbol}`, points, prevClose, compatibleQuote);
    }
  }

  if (quote?.deal_price) {
    return buildStockQuoteOnlyModel(symbol, name, fallbackPrice, quote);
  }

  return buildEmptyIndexModel("TSE", `${name} ${symbol}`);
}

type AppProps = {
  theme: ThemeName;
  setTheme: (theme: ThemeName) => void;
  onLogout: () => void;
};

function App({ theme, setTheme, onLogout }: AppProps) {
  const [mainTab, setMainTab] = useState<MainTab>("orders");
  const ordersResize = useColResize();
  const mitResize = useColResize();
  const [indexTab, setIndexTab] = useState<"TSE" | "OTC">("TSE");
  const [portfolioTab, setPortfolioTab] = useState<PortfolioTab>("live");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [yuantaStatus, setYuantaStatus] = useState<YuantaStatus | null>(null);
  const [brokerInfo, setBrokerInfo] = useState<BrokerInfo | null>(null);
  const brokerLabel =
    (({ yuanta: "元大證券", sinopac: "永豐金證券", sim: "模擬環境" } as Record<string, string>)[brokerInfo?.active ?? ""]) ??
    brokerInfo?.available.find((item) => item.id === brokerInfo.active)?.label ??
    "—";
  // 模擬沙盒以 active broker 判定（登入時設定）。未知時視為「非模擬」以採安全預設（強制確認）。
  const isSimEnv = brokerInfo?.active === "sim";
  const [killSwitchOn, setKillSwitchOn] = useState(false);
  const [order, setOrder] = useState<OrderRequest>(defaultOrder);
  const [lastOrderResult, setLastOrderResult] = useState<OrderResult | null>(null);
  const [watchlists, setWatchlists] = useState<Watchlist[]>(loadWatchlists);
  const [activeWatchlistId, setActiveWatchlistId] = useState<string>(() => watchlists[0]?.id ?? "");
  const activeWatchlist = watchlists.find((list) => list.id === activeWatchlistId) ?? watchlists[0];
  const watchlist = activeWatchlist?.items ?? [];
  const [watchlistDraft, setWatchlistDraft] = useState<WatchItem[]>(initialWatchlist);
  const [watchlistEditing, setWatchlistEditing] = useState(false);
  const [renamingList, setRenamingList] = useState(false);
  const [listNameDraft, setListNameDraft] = useState("");
  const [confirmingDeleteList, setConfirmingDeleteList] = useState(false);
  const [editHits, setEditHits] = useState<SymbolHit[]>([]);
  const [editHitRow, setEditHitRow] = useState(-1);
  const editSearchTimerRef = useRef(0);
  const MAX_WATCHLISTS = 10;
  const [selectedSymbol, setSelectedSymbol] = useState("2885");
  const [selectedKline, setSelectedKline] = useState<KLinePoint[]>([]);
  const [tseIndex, setTseIndex] = useState<IndexIntradayModel>(() => buildEmptyIndexModel("TSE", "加權指數 TSE.TW"));
  const [otcIndex, setOtcIndex] = useState<IndexIntradayModel>(() => buildEmptyIndexModel("OTC", "櫃買指數 OTC.TW"));
  const [pendingLightningAction, setPendingLightningAction] = useState<LightningAction | null>(null);
  const [confirmBeforeSend, setConfirmBeforeSend] = useState(true);
  const [mitOrders, setMitOrders] = useState<MitOrderRecord[]>([]);
  const [workingOrders, setWorkingOrders] = useState<WorkingOrder[]>([]);
  // 委託查詢表的篩選與資料（抓「全部委託」後在前端分 4 類；與 workingOrders 分開，避免影響閃電面板/統計）。
  const [orderFilter, setOrderFilter] = useState<OrderFilter>("all");
  const [orderReport, setOrderReport] = useState<WorkingOrder[]>([]);
  const [invSelected, setInvSelected] = useState<Set<string>>(new Set());
  const [orderSelected, setOrderSelected] = useState<Set<string>>(new Set()); // 委託查詢勾選（key=order_no）
  const [mitSelected, setMitSelected] = useState<Set<number>>(new Set()); // MIT 勾選（key=id）
  const [invLots, setInvLots] = useState<Record<string, number>>({});
  const [invConfirmOpen, setInvConfirmOpen] = useState(false);
  const [invPriceMode, setInvPriceMode] = useState<"current" | "up" | "down">("current");
  const [symbolHits, setSymbolHits] = useState<SymbolHit[]>([]);
  const [symbolSearchOpen, setSymbolSearchOpen] = useState(false);
  const symbolSearchTimerRef = useRef(0);

  function handleSymbolInput(value: string) {
    setOrder((current) => ({ ...current, symbol: value }));
    window.clearTimeout(symbolSearchTimerRef.current);
    const query = value.trim();
    if (!query) {
      setSymbolHits([]);
      setSymbolSearchOpen(false);
      return;
    }
    symbolSearchTimerRef.current = window.setTimeout(() => {
      searchSymbols(query)
        .then((hits) => {
          setSymbolHits(hits);
          setSymbolSearchOpen(hits.length > 0);
        })
        .catch(() => setSymbolHits([]));
    }, 180);
  }

  function pickSymbol(hit: SymbolHit) {
    setSymbolSearchOpen(false);
    setSymbolHits([hit]);
    setOrder((current) => ({ ...current, symbol: hit.code }));
    selectForChart(hit.code);
  }
  const [message, setMessage] = useState("待命。");
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false);
  // 同步送單鎖：useState 的 busy/sending 為非同步更新，擋不住同一個事件迴圈內的連點。
  // 所有「會送出/平倉/建立委託」的入口都先搶這把 ref 鎖，避免重複下單。
  const submitLockRef = useRef(false);
  const priceLadderRef = useRef<HTMLDivElement | null>(null);
  // 手動捲動後暫停自動置中（永久，直到明確按置中/換股才恢復），避免掛單看價時被跳回。
  const ladderPausedRef = useRef(false);
  const ladderProgrammaticScrollRef = useRef(false);

  const selectedSymbols = useMemo(() => {
    const symbols = new Set<string>();
    candidates.forEach((item) => symbols.add(item.symbol));
    watchlist.forEach((item) => symbols.add(item.symbol));
    positions.forEach((item) => symbols.add(item.symbol));
    return Array.from(symbols).filter(Boolean).slice(0, 20);
  }, [candidates, watchlist, positions]);

  const streamSymbols = useMemo(() => {
    const symbols = new Set(selectedSymbols);
    if (selectedSymbol) symbols.add(selectedSymbol);
    if (order.symbol) symbols.add(order.symbol);
    // Index symbols ride the same push stream so the index quote strips
    // update at push latency, exactly like the stock chart.
    symbols.add("IX0001");
    symbols.add("IX0043");
    return Array.from(symbols);
  }, [selectedSymbols, selectedSymbol, order.symbol]);

  const [ticks, setTicks] = useState<TickRecord[]>([]);
  const [fiveTick, setFiveTick] = useState<FiveTickBook | null>(null);
  const [ladderLoading, setLadderLoading] = useState(false);

  const handleFiveTick = useCallback((symbol: string, book: FiveTickBook) => {
    if (symbol === selectedSymbolRef.current) {
      setFiveTick(book);
      setLadderLoading(false); // 五檔到了就關閉載入中
    }
  }, []);

  const handleTicks = useCallback((symbol: string, incoming: TickRecord[]) => {
    if (!incoming.length || incoming[0].symbol !== selectedSymbolRef.current) {
      return;
    }
    setTicks((current) => {
      // Merge the push snapshot with accumulated history, dedup by serial.
      const merged = new Map<string, TickRecord>();
      const keyOf = (tick: TickRecord) =>
        tick.serial ? `s${tick.serial}` : `${tick.time}|${tick.deal_price}|${tick.volume}`;
      current.forEach((tick) => merged.set(keyOf(tick), tick));
      incoming.forEach((tick) => merged.set(keyOf(tick), tick));
      const list = Array.from(merged.values())
        .sort((a, b) => (a.serial || 0) - (b.serial || 0) || a.time.localeCompare(b.time))
        .slice(-2000);
      void saveDailyTicks(incoming[0].symbol, list);
      return list;
    });
  }, []);

  const mergeQuotes = useCallback((incoming: Quote[]) => {
    if (!incoming.length) {
      return;
    }
    setQuotes((current) => {
      const merged = new Map(current.map((quote) => [quote.symbol, quote]));
      incoming.forEach((quote) => merged.set(quote.symbol, quote));
      return Array.from(merged.values());
    });
  }, []);

  const selectedSymbolRef = useRef(selectedSymbol);
  selectedSymbolRef.current = selectedSymbol;

  const streamStatus = useQuoteStream({
    enabled: Boolean(yuantaStatus?.connected),
    symbols: streamSymbols,
    tickSymbol: selectedSymbol,
    onQuotes: mergeQuotes,
    onTicks: handleTicks,
    onFiveTick: handleFiveTick
  });

  useEffect(() => {
    let cancelled = false;
    setTicks([]);
    setFiveTick(null);
    setLadderLoading(true); // 切換商品 → 先顯示五檔載入中，避免誤判舊資料
    // 保險：若該檔遲遲沒有五檔推播（盤後／冷門股），最多顯示數秒後自動關閉。
    const loadingTimer = window.setTimeout(() => {
      if (!cancelled) setLadderLoading(false);
    }, 3000);
    void loadDailyTicks(selectedSymbol).then((stored) => {
      if (!cancelled && stored.length && selectedSymbolRef.current === selectedSymbol) {
        setTicks((current) => (current.length ? current : stored));
      }
    });
    return () => {
      cancelled = true;
      window.clearTimeout(loadingTimer);
    };
  }, [selectedSymbol]);

  const quoteBySymbol = useMemo(() => {
    return new Map(quotes.map((quote) => [quote.symbol, quote]));
  }, [quotes]);

  const [nameCache, setNameCache] = useState<Record<string, string>>({});
  // 把各來源（報價/候選/搜尋/自選/庫存）學到的股票名稱累積進快取，之後即使來源變動也持久。
  useEffect(() => {
    setNameCache((current) => {
      const next = { ...current };
      let changed = false;
      const remember = (sym: string, nm?: string) => {
        const name = (nm || "").trim();
        if (sym && name && name !== sym && next[sym] !== name) {
          next[sym] = name;
          changed = true;
        }
      };
      quotes.forEach((q) => remember(q.symbol, q.name));
      candidates.forEach((c) => remember(c.symbol, c.name));
      watchlist.forEach((w) => remember(w.symbol, w.name));
      positions.forEach((p) => remember(p.symbol, p.name));
      symbolHits.forEach((h) => remember(h.code, h.name));
      return changed ? next : current;
    });
  }, [quotes, candidates, watchlist, positions, symbolHits]);

  // 統一的 symbol→名稱 解析（含快取）。fugle 報價常缺 name，這裡彙整所有來源，
  // 並由下方 effect 把學到的名稱存進快取持久化，避免圖表標題退回顯示成代號（如「2885 2885」）。
  const nameFor = (symbol: string) =>
    nameCache[symbol] ||
    quoteBySymbol.get(symbol)?.name ||
    symbolHits.find((hit) => hit.code === symbol)?.name ||
    candidates.find((item) => item.symbol === symbol)?.name ||
    watchlist.find((item) => item.symbol === symbol)?.name ||
    positions.find((item) => item.symbol === symbol)?.name ||
    "";

  const selectedName = nameFor(selectedSymbol) || selectedSymbol;
  const selectedQuote = quoteBySymbol.get(selectedSymbol);
  const selectedWatchItem = watchlist.find((item) => item.symbol === selectedSymbol);
  const selectedPosition = positions.find((item) => item.symbol === selectedSymbol);
  // 閃電下單商品欄位的股票名稱（隨 order.symbol 代號變動）。
  const orderName = nameFor(order.symbol);
  const selectedFallbackPrice =
    selectedQuote?.deal_price ||
    selectedPosition?.market_price ||
    selectedWatchItem?.cost ||
    50;
  const selectedPriceLadder = useMemo(
    () => buildPriceLadder(selectedQuote, selectedFallbackPrice),
    [selectedFallbackPrice, selectedQuote]
  );
  const fiveVolByPrice = useMemo(() => {
    const map = new Map<number, { bid?: number; ask?: number }>();
    fiveTick?.bids.forEach((level) => {
      if (level.price && level.volume) {
        const key = Math.round(level.price * 100);
        map.set(key, { ...map.get(key), bid: level.volume });
      }
    });
    fiveTick?.asks.forEach((level) => {
      if (level.price && level.volume) {
        const key = Math.round(level.price * 100);
        map.set(key, { ...map.get(key), ask: level.volume });
      }
    });
    return map;
  }, [fiveTick]);
  const workingByPrice = useMemo(() => {
    const map = new Map<string, WorkingOrder[]>();
    workingOrders
      .filter((item) => item.symbol === selectedSymbol && item.after_qty - item.ok_qty > 0)
      .forEach((item) => {
        const key = `${Math.round(item.price * 100)}|${item.side}`;
        map.set(key, [...(map.get(key) ?? []), item]);
      });
    return map;
  }, [workingOrders, selectedSymbol]);
  const pendingMitByPrice = useMemo(() => {
    const map = new Map<string, MitOrderRecord[]>();
    mitOrders
      .filter((item) => item.status === "pending" && item.symbol === selectedSymbol)
      .forEach((item) => {
        const key = `${Math.round(item.trigger_price * 100)}|${item.side}`;
        map.set(key, [...(map.get(key) ?? []), item]);
      });
    return map;
  }, [mitOrders, selectedSymbol]);
  // 全刪按鈕上方的統計：目前商品買/賣方的委託與 MIT 觸價總張數。
  const flashTotals = useMemo(() => {
    let buyOrder = 0;
    let buyMit = 0;
    let sellOrder = 0;
    let sellMit = 0;
    workingOrders.forEach((item) => {
      if (item.symbol !== selectedSymbol) return;
      const lots = Math.round((item.after_qty - item.ok_qty) / 1000);
      if (lots <= 0) return;
      if (item.side === "B") buyOrder += lots;
      else sellOrder += lots;
    });
    mitOrders.forEach((item) => {
      if (item.status !== "pending" || item.symbol !== selectedSymbol) return;
      if (item.side === "B") buyMit += item.quantity;
      else sellMit += item.quantity;
    });
    return { buyOrder, buyMit, sellOrder, sellMit };
  }, [workingOrders, mitOrders, selectedSymbol]);
  // 委託查詢表要顯示的資料：抓全部委託後，依「成交量 vs 委託量 + 取消旗標」分 4 類。
  const displayedOrders = useMemo(() => {
    return orderReport.filter((o) => {
      if (orderFilter === "none") return !!o.cancelled || o.ok_qty === 0; // 未成交（含取消單）
      if (orderFilter === "partial") return !o.cancelled && o.ok_qty > 0 && o.ok_qty < o.after_qty;
      if (orderFilter === "filled") return !o.cancelled && o.ok_qty > 0 && o.ok_qty >= o.after_qty;
      return true; // all
    });
  }, [orderFilter, orderReport]);
  // 可刪的委託（未取消且尚有未成交剩餘）／可取消的 MIT（等待中）——只有這些列才顯示勾選框與刪/取消鈕。
  const isOrderCancellable = (o: WorkingOrder) => !o.cancelled && o.after_qty - o.ok_qty > 0;
  const cancellableOrderNos = displayedOrders.filter(isOrderCancellable).map((o) => o.order_no);
  const pendingMitIds = mitOrders.filter((m) => m.status === "pending").map((m) => m.id);
  const latestTick = ticks[ticks.length - 1];
  const tseIndexDisplay = useMemo(
    () => mergeIndexLiveQuote(tseIndex, quoteBySymbol.get("IX0001")),
    [tseIndex, quoteBySymbol]
  );
  const otcIndexDisplay = useMemo(
    () => mergeIndexLiveQuote(otcIndex, quoteBySymbol.get("IX0043")),
    [otcIndex, quoteBySymbol]
  );
  const selectedIndex = useMemo(
    () => buildStockIntradayModel(selectedSymbol, selectedName, selectedFallbackPrice, selectedQuote, selectedKline),
    [selectedFallbackPrice, selectedKline, selectedName, selectedQuote, selectedSymbol]
  );

  function referencePriceForSymbol(symbol: string) {
    return (
      quoteBySymbol.get(symbol)?.deal_price ||
      positions.find((item) => item.symbol === symbol)?.market_price ||
      watchlist.find((item) => item.symbol === symbol)?.cost ||
      0
    );
  }

  const centerLadder = useCallback((force = false, targetPrice?: number) => {
    const container = priceLadderRef.current;
    if (!container) {
      return;
    }
    let targetRow: HTMLElement | null = null;
    if (targetPrice && targetPrice > 0) {
      // Pick the row closest to the requested price.
      let bestDistance = Number.POSITIVE_INFINITY;
      container.querySelectorAll<HTMLElement>("[data-price]").forEach((row) => {
        const price = Number(row.dataset.price);
        const distance = Math.abs(price - targetPrice);
        if (distance < bestDistance) {
          bestDistance = distance;
          targetRow = row;
        }
      });
    } else {
      targetRow = container.querySelector<HTMLElement>("[data-current='true']");
    }
    if (!targetRow) {
      return;
    }
    // 使用者手動捲動過就不自動置中（除非明確強制），避免看別的價位時被跳回。
    if (!force && ladderPausedRef.current) {
      return;
    }
    ladderProgrammaticScrollRef.current = true;
    // scrollIntoView is robust against offset-parent changes, unlike manual
    // offsetTop math which broke when the dock became its own grid column.
    (targetRow as HTMLElement).scrollIntoView({ block: "center" });
    if (force) {
      // 明確置中（回到現價／換股）後恢復自動跟價。
      ladderPausedRef.current = false;
    }
  }, []);

  function centerOnBook() {
    // Center between the latest deal price and the five-level book midpoint.
    const deal = selectedQuote?.deal_price ?? 0;
    const bestBid = fiveTick?.bids[0]?.price ?? 0;
    const bestAsk = fiveTick?.asks[0]?.price ?? 0;
    const bookMid = bestBid > 0 && bestAsk > 0 ? (bestBid + bestAsk) / 2 : bestBid || bestAsk;
    const target = deal > 0 && bookMid > 0 ? (deal + bookMid) / 2 : deal || bookMid;
    centerLadder(true, target || undefined);
    // 五檔置中後維持此視角，不被自動跟價蓋掉（暫停自動置中）。
    ladderPausedRef.current = true;
  }

  function handleLadderScroll() {
    if (ladderProgrammaticScrollRef.current) {
      ladderProgrammaticScrollRef.current = false;
      return;
    }
    // 手動捲動 → 暫停自動置中，直到明確按「回到現價／五檔置中」或換股。
    ladderPausedRef.current = true;
  }

  useEffect(() => {
    centerLadder(true);
  }, [selectedSymbol, centerLadder]);

  useEffect(() => {
    centerLadder();
  }, [selectedPriceLadder, centerLadder]);

  async function loadBase() {
    setBusy(true);
    try {
      const [healthRes, candidatesRes, riskRes, statusRes] = await Promise.all([
        getHealth(),
        getCandidates(),
        getKillSwitch(),
        getYuantaStatus()
      ]);
      setHealth(healthRes);
      setCandidates(candidatesRes);
      setKillSwitchOn(riskRes.enabled);
      setYuantaStatus(statusRes);
      if (candidatesRes.length > 0) {
        setOrder((current) => ({ ...current, symbol: candidatesRes[0].symbol }));
      }
      void refreshMitOrders();
      void getBrokerInfo().then(setBrokerInfo).catch(() => undefined);
      setMessage("報價已連線。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "報價連線失敗。");
    } finally {
      setBusy(false);
    }
  }

  async function refreshQuotes(silent = false) {
    const symbols = selectedSymbols.length ? selectedSymbols : [order.symbol];
    if (!silent) {
      setBusy(true);
    }
    try {
      setQuotes(await getQuotes(symbols));
      setYuantaStatus(await getYuantaStatus());
      if (!silent) {
        setMessage("報價已更新。");
      }
    } catch (error) {
      if (!silent) {
        setMessage(error instanceof Error ? error.message : "報價更新失敗。");
      }
    } finally {
      if (!silent) {
        setBusy(false);
      }
    }
  }

  async function refreshMarketData(silent = false) {
    await refreshQuotes(silent);
    void refreshSelectedKline();
    refreshIndexIntraday(silent);
  }

  async function refreshMitOrders() {
    try {
      setMitOrders(await getMitOrders());
    } catch {
      // Transient failures keep the last known list visible.
    }
  }

  async function refreshWorkingOrders() {
    if (!yuantaStatus?.connected) {
      return;
    }
    try {
      setWorkingOrders(await getWorkingOrders());
    } catch {
      // Transient failures keep the last known list visible.
    }
  }

  // 委託查詢表用：一律抓「全部委託」，前端再依成交量分 4 類顯示。
  async function refreshOrderReport() {
    if (!yuantaStatus?.connected) {
      return;
    }
    try {
      setOrderReport(await getWorkingOrders("all"));
    } catch {
      // 靜默：暫時失敗時保留上次清單。
    }
  }

  function workingRemainingLots(item: WorkingOrder) {
    return Math.max(1, Math.round((item.after_qty - item.ok_qty) / 1000));
  }

  async function cancelOneWorkingOrder(item: WorkingOrder) {
    setBusy(true);
    try {
      const result = await cancelWorkingOrder({
        order_no: item.order_no,
        symbol: item.symbol,
        side: item.side,
        price: item.price,
        quantity: workingRemainingLots(item),
        price_flag: item.price_flag,
        order_type: item.order_type
      });
      setMessage(result.accepted ? `已刪單 ${item.order_no}（${item.name}）` : `刪單失敗：${result.message}`);
      await refreshWorkingOrders();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "刪單失敗。");
    } finally {
      setBusy(false);
    }
  }

  function invDefaultLots(position: Position) {
    return Math.max(1, Math.floor(position.quantity / 1000));
  }

  function invLotsFor(position: Position) {
    return invLots[position.symbol] ?? invDefaultLots(position);
  }

  function invPriceFor(symbol: string): number {
    const quote = quoteBySymbol.get(symbol);
    if (invPriceMode === "up") {
      return quote?.up_limit && quote.up_limit > 0 ? quote.up_limit : 0;
    }
    if (invPriceMode === "down") {
      return quote?.down_limit && quote.down_limit > 0 ? quote.down_limit : 0;
    }
    return quote?.deal_price && quote.deal_price > 0 ? quote.deal_price : 0;
  }

  async function sendInventoryOrders() {
    const targets = positions.filter((item) => invSelected.has(item.symbol));
    if (!targets.length) {
      return;
    }
    if (submitLockRef.current) {
      return;
    }
    submitLockRef.current = true;
    setInvConfirmOpen(false);
    setBusy(true);
    const failures: string[] = [];
    let sent = 0;
    try {
      for (const position of targets) {
        const price = invPriceFor(position.symbol);
        const request: OrderRequest = {
          ...defaultOrder,
          symbol: position.symbol,
          side: "S",
          price,
          price_flag: price > 0 ? "" : "M",
          quantity: invLotsFor(position),
          confirm_send_order: true
        };
        try {
          const result = await sendOrder(request);
          if (result.accepted) {
            sent += 1;
          } else {
            failures.push(`${position.symbol}:${result.message}`);
          }
        } catch (error) {
          failures.push(position.symbol);
        }
      }
      setMessage(
        failures.length
          ? `庫存送單完成 ${sent} 筆，失敗：${failures.join("、")}`
          : `庫存送單完成，共 ${sent} 筆。`
      );
      void refreshWorkingOrders();
      void refreshOrderReport();
      void refreshPositions(true); // 部位有變動立刻更新
    } finally {
      setBusy(false);
      submitLockRef.current = false;
    }
  }

  // Cancels are deliberately exempt from the confirm-before-send dialog:
  // removing risk should never be slowed down.
  async function cancelRowOrders(side: "B" | "S", price: number, options?: { allPrices?: boolean }) {
    const priceKey = Math.round(price * 100);
    const mits = mitOrders.filter(
      (item) =>
        item.status === "pending" &&
        item.symbol === selectedSymbol &&
        item.side === side &&
        (options?.allPrices || Math.round(item.trigger_price * 100) === priceKey)
    );
    const workings = workingOrders.filter(
      (item) =>
        item.symbol === selectedSymbol &&
        item.side === side &&
        item.after_qty - item.ok_qty > 0 &&
        (options?.allPrices || Math.round(item.price * 100) === priceKey)
    );
    if (!mits.length && !workings.length) {
      setMessage("該價位沒有可刪的單。");
      return;
    }
    setBusy(true);
    const failures: string[] = [];
    try {
      for (const item of mits) {
        try {
          await cancelMitOrder(item.id);
        } catch (error) {
          failures.push(`MIT#${item.id}`);
        }
      }
      for (const item of workings) {
        try {
          const result = await cancelWorkingOrder({
            order_no: item.order_no,
            symbol: item.symbol,
            side: item.side,
            price: item.price,
            quantity: workingRemainingLots(item),
            price_flag: item.price_flag,
            order_type: item.order_type
          });
          if (!result.accepted) {
            failures.push(`${item.order_no}:${result.message}`);
          }
        } catch (error) {
          failures.push(item.order_no);
        }
      }
      await Promise.all([refreshMitOrders(), refreshWorkingOrders()]);
      setMessage(
        failures.length
          ? `刪單部分失敗：${failures.join("、")}`
          : `已刪除 ${mits.length + workings.length} 筆${side === "B" ? "買" : "賣"}方委託/觸價單。`
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleCancelMit(id: number) {
    setBusy(true);
    try {
      await cancelMitOrder(id);
      await refreshMitOrders();
      setMessage("MIT 觸價單已取消。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "MIT 取消失敗。");
    } finally {
      setBusy(false);
    }
  }

  // 委託查詢：批次刪除「已勾選且仍可刪」的委託（已成交／已取消無法刪）。
  async function cancelSelectedOrders() {
    const targets = displayedOrders.filter(
      (o) => orderSelected.has(o.order_no) && !o.cancelled && o.after_qty - o.ok_qty > 0
    );
    if (!targets.length) {
      setMessage("沒有可刪除的委託（已成交／已取消無法刪）。");
      return;
    }
    if (!window.confirm(`確定刪除選取的 ${targets.length} 筆委託？`)) {
      return;
    }
    setBusy(true);
    let ok = 0;
    const fails: string[] = [];
    try {
      for (const item of targets) {
        try {
          const result = await cancelWorkingOrder({
            order_no: item.order_no,
            symbol: item.symbol,
            side: item.side,
            price: item.price,
            quantity: workingRemainingLots(item),
            price_flag: item.price_flag,
            order_type: item.order_type
          });
          if (result.accepted) ok += 1;
          else fails.push(item.order_no);
        } catch {
          fails.push(item.order_no);
        }
      }
      setMessage(fails.length ? `刪單完成 ${ok} 筆，失敗：${fails.join("、")}` : `已刪單 ${ok} 筆。`);
      setOrderSelected(new Set());
      await Promise.all([refreshWorkingOrders(), refreshOrderReport()]);
    } finally {
      setBusy(false);
    }
  }

  // MIT：批次取消「已勾選且狀態為等待中」的觸價單。
  async function cancelSelectedMit() {
    const targets = mitOrders.filter((m) => mitSelected.has(m.id) && m.status === "pending");
    if (!targets.length) {
      setMessage("沒有可取消的觸價單（僅「等待中」可取消）。");
      return;
    }
    if (!window.confirm(`確定取消選取的 ${targets.length} 筆 MIT 觸價單？`)) {
      return;
    }
    setBusy(true);
    let ok = 0;
    let fail = 0;
    try {
      for (const item of targets) {
        try {
          await cancelMitOrder(item.id);
          ok += 1;
        } catch {
          fail += 1;
        }
      }
      setMessage(fail ? `取消完成 ${ok} 筆，失敗 ${fail} 筆。` : `已取消 ${ok} 筆 MIT 觸價單。`);
      setMitSelected(new Set());
      await refreshMitOrders();
    } finally {
      setBusy(false);
    }
  }

  async function refreshPositions(silent = false) {
    if (silent && !yuantaStatus?.connected) {
      return;
    }
    if (!silent) {
      setBusy(true);
    }
    try {
      setPositions(await getPositions());
      if (!silent) {
        setYuantaStatus(await getYuantaStatus());
        setMessage("庫存已更新。");
      }
    } catch (error) {
      if (!silent) {
        setMessage(error instanceof Error ? error.message : "庫存更新失敗。");
      }
    } finally {
      if (!silent) {
        setBusy(false);
      }
    }
  }

  async function refreshSelectedKline(symbol = selectedSymbol, attempt = 0) {
    if (!yuantaStatus?.connected || !symbol) {
      return;
    }
    try {
      const quote = quoteBySymbol.get(symbol);
      const quoteMarket = quote?.market === "TWSE" || quote?.market === "TWOTC" ? quote.market : undefined;
      const rows = await getKline(symbol, quoteMarket);
      if (selectedSymbolRef.current !== symbol) {
        return; // Stale response for a symbol the user already left.
      }
      const lastClose = rows[rows.length - 1]?.close;
      const scaleOk = !quote?.deal_price || isSamePriceScale(lastClose, quote.deal_price);
      if (rows.length > 0 && scaleOk) {
        setSelectedKline(rows);
        return;
      }
      throw new Error("kline unavailable");
    } catch {
      // Yuanta SDK requests are serialized and occasionally time out (502).
      // Retry a couple of times instead of leaving the chart blank until the
      // next 15s cycle.
      if (attempt < 2 && selectedSymbolRef.current === symbol) {
        window.setTimeout(() => void refreshSelectedKline(symbol, attempt + 1), 2500);
      }
    }
  }

  async function refreshOneIndexIntraday(market: "TSE" | "OTC", silent = false) {
    try {
      const data = await getIndexIntraday(market);
      if (market === "TSE") {
        setTseIndex((current) => {
          const next = modelFromIndexResponse(data);
          return next.points.length > 0 || current.points.length === 0 ? next : { ...next, points: current.points };
        });
      } else {
        setOtcIndex((current) => {
          const next = modelFromIndexResponse(data);
          return next.points.length > 0 || current.points.length === 0 ? next : { ...next, points: current.points };
        });
      }
      if (!silent) {
        setMessage(`${market === "TSE" ? "加權指數" : "櫃買指數"}分時已更新。`);
      }
    } catch (error) {
      if (!silent) {
        setMessage(error instanceof Error ? error.message : `${market === "TSE" ? "加權指數" : "櫃買指數"}分時更新失敗。`);
      }
    }
  }

  function refreshIndexIntraday(silent = false) {
    void refreshOneIndexIntraday("TSE", silent);
    void refreshOneIndexIntraday("OTC", silent);
  }

  function armLightningAction(kind: LightningActionKind, side: "B" | "S", price: number) {
    // P1-6：未連線券商一律不送單。
    if (!yuantaStatus?.connected) {
      setMessage("未連線券商，無法下單。請重新登入。");
      return;
    }
    // P1-7：限價單以真實漲跌停驗證（有資料時），避免下到超出漲跌停的價位。
    if (price > 0) {
      const up = selectedQuote?.up_limit ?? null;
      const down = selectedQuote?.down_limit ?? null;
      if (up && price > up + 1e-6) {
        setMessage(`價格 ${formatPrice(price)} 超過漲停 ${formatPrice(up)}，已擋下。`);
        return;
      }
      if (down && price < down - 1e-6) {
        setMessage(`價格 ${formatPrice(price)} 低於跌停 ${formatPrice(down)}，已擋下。`);
        return;
      }
    }
    const action: LightningAction = { kind, side, price, symbol: selectedSymbol, quantity: order.quantity };
    // P0-2：實單環境一律強制二次確認，「免確認」只在模擬沙盒生效。
    if (confirmBeforeSend || !isSimEnv) {
      setPendingLightningAction(action);
      setMessage(
        `${kind === "mit" ? "MIT 觸價單" : "委託單"}待確認：${selectedName} ${selectedSymbol} ${
          side === "B" ? "買進" : "賣出"
        } ${price > 0 ? formatPrice(price) : "市價"}`
      );
      return;
    }
    void performLightningAction(action);
  }

  async function performLightningAction(action: LightningAction) {
    // 同步鎖：擋住連點 MIT 格 / 階梯下單格 / 市價買賣造成的重複送單。
    if (submitLockRef.current) {
      return;
    }
    submitLockRef.current = true;
    setPendingLightningAction(null);

    if (action.kind === "mit") {
      setBusy(true);
      try {
        await createMitOrder({
          symbol: action.symbol,
          side: action.side,
          trigger_price: action.price,
          quantity: action.quantity,
          reference_price: quoteBySymbol.get(action.symbol)?.deal_price ?? null
        });
        await refreshMitOrders();
        setMainTab("mit");
        setMessage(
          killSwitchOn
            ? "MIT 觸價單已登錄，但風控停損目前啟用中——觸價也不會送單。"
            : "MIT 觸價單已登錄，觸價後將自動以市價送單。"
        );
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "MIT 觸價單建立失敗。");
      } finally {
        setBusy(false);
        submitLockRef.current = false;
      }
      return;
    }

    const request: OrderRequest = {
      ...order,
      symbol: action.symbol,
      side: action.side,
      price: action.price,
      price_flag: action.price > 0 ? "" : "M",
      quantity: action.quantity,
      confirm_send_order: true
    };
    setOrder(request);
    setSending(true);
    setBusy(true);
    try {
      const result = await sendOrder(request);
      setLastOrderResult(result);
      setMessage(`${result.accepted ? "送單已送出" : "送單被擋"}：${result.message}`);
      if (result.accepted) {
        void refreshWorkingOrders();
        void refreshOrderReport();
        void refreshPositions(true); // 部位有變動立刻更新
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "送單失敗。");
    } finally {
      setSending(false);
      setBusy(false);
      submitLockRef.current = false;
    }
  }

  async function confirmLightningAction() {
    if (pendingLightningAction) {
      await performLightningAction(pendingLightningAction);
    }
  }

  async function handleConnect() {
    setBusy(true);
    try {
      const status = await connectYuanta();
      setYuantaStatus(status);
      setMessage(status.connected ? `${brokerLabel}已連線。` : status.last_error || `${brokerLabel}連線失敗。`);
      if (status.connected) {
        refreshIndexIntraday(true);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${brokerLabel}連線失敗。`);
      setYuantaStatus(await getYuantaStatus().catch(() => null));
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    setBusy(true);
    try {
      await apiLogout();
    } catch {
      // 即使後端登出失敗，前端仍回到登入畫面。
    } finally {
      setBusy(false);
      onLogout();
    }
  }

  function selectForChart(symbol: string) {
    setSelectedSymbol(symbol);
    setSelectedKline([]);
    setOrder((current) => ({ ...current, symbol }));
    void refreshSelectedKline(symbol);
  }

  function updateWatchItem(index: number, patch: Partial<WatchItem>) {
    setWatchlistDraft((current) => current.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)));
  }

  function addWatchItem() {
    setWatchlistDraft((current) => [...current, { symbol: "", name: "", cost: 0, lots: 0, shares: 0 }]);
  }

  function deleteWatchItem(index: number) {
    setWatchlistDraft((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  function openWatchlistEditor() {
    setWatchlistDraft(watchlist);
    setWatchlistEditing(true);
  }

  function saveWatchlistEditor() {
    const cleaned = watchlistDraft.filter((item) => item.symbol.trim());
    setWatchlists((current) => current.map((list) => (list.id === activeWatchlistId ? { ...list, items: cleaned } : list)));
    setWatchlistEditing(false);
    setMessage(`「${activeWatchlist?.name ?? "自選股"}」已儲存。`);
  }

  function cancelWatchlistEditor() {
    setWatchlistDraft(watchlist);
    setWatchlistEditing(false);
  }

  // ---- 多清單管理 ----
  function addWatchlist() {
    if (watchlists.length >= MAX_WATCHLISTS) {
      setMessage(`自選清單最多 ${MAX_WATCHLISTS} 個，無法再新增。`);
      return;
    }
    const id = newListId();
    const used = new Set(watchlists.map((list) => list.name));
    let n = watchlists.length + 1;
    while (used.has(`選股${n}`)) n += 1;
    setWatchlists((current) => [...current, { id, name: `選股${n}`, items: [] }]);
    setActiveWatchlistId(id);
    setWatchlistEditing(false);
    setMessage(`已新增清單「選股${n}」。`);
  }

  function requestDeleteWatchlist() {
    if (watchlists.length <= 1) {
      setMessage("至少需保留一個清單。");
      return;
    }
    setRenamingList(false);
    setConfirmingDeleteList(true);
  }

  function confirmDeleteWatchlist() {
    const removed = activeWatchlist?.name ?? "";
    const remaining = watchlists.filter((list) => list.id !== activeWatchlistId);
    setWatchlists(remaining);
    setActiveWatchlistId(remaining[0].id);
    setWatchlistEditing(false);
    setConfirmingDeleteList(false);
    setMessage(`已刪除清單「${removed}」。`);
  }

  function startRenameList() {
    setConfirmingDeleteList(false);
    setListNameDraft(activeWatchlist?.name ?? "");
    setRenamingList(true);
  }

  // ---- 自選股編輯器的代碼搜尋（仿閃電下單下拉）----
  function handleEditSymbolInput(index: number, value: string) {
    updateWatchItem(index, { symbol: value });
    window.clearTimeout(editSearchTimerRef.current);
    const query = value.trim();
    if (!query) {
      setEditHits([]);
      setEditHitRow(-1);
      return;
    }
    setEditHitRow(index);
    editSearchTimerRef.current = window.setTimeout(() => {
      searchSymbols(query)
        .then((hits) => setEditHits(hits))
        .catch(() => setEditHits([]));
    }, 180);
  }

  function pickEditSymbol(index: number, hit: SymbolHit) {
    setWatchlistDraft((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? { ...item, symbol: hit.code, name: hit.name } : item))
    );
    setEditHits([]);
    setEditHitRow(-1);
  }

  function saveRenameList() {
    const name = listNameDraft.trim();
    if (!name) {
      setRenamingList(false);
      return;
    }
    setWatchlists((current) => current.map((list) => (list.id === activeWatchlistId ? { ...list, name } : list)));
    setRenamingList(false);
    setMessage("清單名稱已更新。");
  }

  useEffect(() => {
    void loadBase();
  }, []);

  // 自選清單持久化到瀏覽器（非機密的偏好資料）。
  useEffect(() => {
    try {
      window.localStorage.setItem(WATCHLISTS_KEY, JSON.stringify(watchlists));
    } catch {
      // 無法寫入（如隱私模式）就略過
    }
  }, [watchlists]);

  useEffect(() => {
    if (!yuantaStatus?.connected) {
      return;
    }
    const timer = window.setInterval(() => {
      if (streamStatus !== "live") {
        void refreshQuotes(true);
      }
      void refreshSelectedKline();
      refreshIndexIntraday(true);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [yuantaStatus?.connected, streamStatus, selectedSymbols.join(",")]);

  useEffect(() => {
    if (!yuantaStatus?.connected) {
      return;
    }
    const tick = () => {
      void refreshMitOrders();
      void refreshWorkingOrders();
      void refreshPositions(true);
      void getKillSwitch().then((result) => setKillSwitchOn(result.enabled)).catch(() => undefined);
      if (mainTab === "orders") {
        void refreshOrderReport();
      }
    };
    tick(); // 連線/登入後立即載入一次（含庫存、風控狀態），之後每 5 秒自動更新。
    const timer = window.setInterval(tick, 5000);
    return () => window.clearInterval(timer);
  }, [yuantaStatus?.connected]);

  // P2-10：送單結果 8 秒後自動淡出，避免上一筆結果一直停在畫面被誤判為本次結果。
  useEffect(() => {
    if (!lastOrderResult) {
      return;
    }
    const timer = window.setTimeout(() => setLastOrderResult(null), 8000);
    return () => window.clearTimeout(timer);
  }, [lastOrderResult]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "SELECT" || target.tagName === "TEXTAREA")) {
        return;
      }
      if (event.key === "Escape" && pendingLightningAction) {
        event.preventDefault();
        setPendingLightningAction(null);
        setMessage("已取消待確認委託。");
      } else if (event.key === "Enter" && pendingLightningAction && !busy) {
        event.preventDefault();
        void confirmLightningAction();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [pendingLightningAction, busy]);

  useEffect(() => {
    void refreshSelectedKline();
    if (yuantaStatus?.connected) {
      refreshIndexIntraday(true);
    }
  }, [yuantaStatus?.connected, selectedSymbol]);

  // 切換到「委託查詢」分頁時立即載入全部委託，不必等下一次輪詢。
  useEffect(() => {
    if (mainTab === "orders") {
      void refreshOrderReport();
    }
  }, [mainTab]);

  return (
    <main className={`appShell theme-${theme}`}>
      <header className="commandBar">
        <div className="brandBlock">
          <h1>股票自動交易</h1>
          <p>
            {(() => {
              const env = (yuantaStatus?.environment ?? health?.yuanta_env ?? "").toUpperCase();
              // 以登入時設定的 active broker 為準（最可靠）；未載入前才退回環境字串判斷。
              const isSim = brokerInfo ? brokerInfo.active === "sim" : env === "SIM" || env === "UAT";
              return (
                <>
                  {brokerLabel}
                  <i className={`envBadge ${isSim ? "sim" : "live"}`}>{isSim ? "模擬單" : "實單"}</i>
                  {yuantaStatus?.connected ? "已連線" : "未連線"}
                  {killSwitchOn ? <i className="killBadge" title="風控停損啟用中，所有委託被擋">風控停損中</i> : null}
                </>
              );
            })()}
          </p>
        </div>
        <div className="testDock">
          <button onClick={() => void handleLogout()} disabled={busy} title="登出並返回登入畫面">
            <Link2Off size={15} /> 登出
          </button>
          <button onClick={() => void refreshMarketData()} disabled={busy} title="更新報價與分時">
            <RefreshCw size={15} /> 報價
          </button>
          <button onClick={() => void refreshPositions()} disabled={busy} title="更新庫存">
            <PlayCircle size={15} /> 庫存
          </button>
          <select value={theme} onChange={(event) => setTheme(event.target.value as ThemeName)} title="Theme">
            <option value="light">淺色</option>
            <option value="dark">深色</option>
            <option value="warm">暖色</option>
            <option value="cool">冷色</option>
          </select>
        </div>
      </header>

      <section className="messageLine">
        <span>{message}</span>
        <span className="messageRight">
          <i className={`streamBadge ${streamStatus}`}>
            {streamStatus === "live" ? "即時報價" : streamStatus === "connecting" ? "串流連線中" : "輪詢報價"}
          </i>
          <b>{yuantaStatus?.account_name || "未連線"}</b>
        </span>
      </section>

      <div className="layoutGrid">
        <section className="zone zone1 terminalPanel">
          <div className="tabs">
            <button className={mainTab === "orders" ? "active" : ""} onClick={() => setMainTab("orders")}>證券成交委託查詢</button>
            <button className={mainTab === "mit" ? "active" : ""} onClick={() => setMainTab("mit")}>MIT 委託單</button>
            <button className={mainTab === "inventory" ? "active" : ""} onClick={() => setMainTab("inventory")}>證券 庫存下單</button>
          </div>
          <div className="workArea">
            <div className="queryPane">
              <div className="filterBar">
                <select><option>全部帳號</option></select>
                <select><option>全部交易</option></select>
                <select
                  value={orderFilter}
                  onChange={(event) => setOrderFilter(event.target.value as OrderFilter)}
                >
                  <option value="all">全部委託</option>
                  <option value="none">未成交委託</option>
                  <option value="partial">未完全成交委託</option>
                  <option value="filled">已成交委託</option>
                </select>
                <button
                  onClick={() => {
                    void refreshWorkingOrders();
                    void refreshOrderReport();
                    void refreshPositions();
                  }}
                  disabled={busy}
                >
                  查詢
                </button>
                <button onClick={() => void refreshQuotes()} disabled={busy}>報價</button>
              </div>
              {mainTab === "orders" ? (
                <div className="scrollPane">
                  <div className="watchToolbar invToolbar">
                    <button
                      disabled={busy || cancellableOrderNos.length === 0 || orderSelected.size === cancellableOrderNos.length}
                      onClick={() => setOrderSelected(new Set(cancellableOrderNos))}
                    >
                      <CheckSquare size={14} />全部選擇
                    </button>
                    <button
                      disabled={busy || orderSelected.size === 0}
                      onClick={() => setOrderSelected(new Set())}
                    >
                      <Square size={14} />全部取消
                    </button>
                    <button
                      className="danger"
                      disabled={busy || orderSelected.size === 0}
                      onClick={() => void cancelSelectedOrders()}
                    >
                      <Trash2 size={14} />全部刪單（{orderSelected.size}）
                    </button>
                  </div>
                  <table className="denseTable adaptiveTable" style={ordersResize.tableStyle}>
                    <thead>
                      <tr>
                        {["動作", "商品", "買賣", "價格", "委託", "成交", "剩餘", "狀態", "委託書號"].map((label, index) => (
                          <Th key={label} col={index} resize={ordersResize}>{label}</Th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {displayedOrders.map((item) => (
                        <tr key={item.order_no} onClick={() => selectForChart(item.symbol)}>
                          <td className="actionCell">
                            {isOrderCancellable(item) ? (
                              <>
                                <input
                                  type="checkbox"
                                  className="rowCheck"
                                  checked={orderSelected.has(item.order_no)}
                                  onClick={(event) => event.stopPropagation()}
                                  onChange={(event) => {
                                    const checked = event.target.checked;
                                    setOrderSelected((current) => {
                                      const next = new Set(current);
                                      if (checked) next.add(item.order_no);
                                      else next.delete(item.order_no);
                                      return next;
                                    });
                                  }}
                                />
                                <button
                                  className="iconButton danger"
                                  disabled={busy}
                                  title="刪單（免確認）"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void cancelOneWorkingOrder(item);
                                  }}
                                >
                                  <X size={13} />
                                </button>
                              </>
                            ) : null}
                          </td>
                          <td>{item.name} {item.symbol}</td>
                          <td className={item.side === "B" ? "down" : "up"}>{item.side === "B" ? "買" : "賣"}</td>
                          <td>{item.price_flag === "M" ? "市價" : numberText(item.price)}</td>
                          <td>{numberText(item.after_qty / 1000, 0)}</td>
                          <td>{numberText(item.ok_qty / 1000, 0)}</td>
                          <td>{numberText((item.after_qty - item.ok_qty) / 1000, 0)}</td>
                          <td>
                            {item.cancelled
                              ? "已取消"
                              : item.ok_qty > 0 && item.ok_qty >= item.after_qty
                                ? "已成交"
                                : item.ok_qty > 0
                                  ? "部份成交"
                                  : "未成交"}
                          </td>
                          <td>{item.order_no}</td>
                        </tr>
                      ))}
                      {displayedOrders.length === 0 ? (
                        <tr><td colSpan={9}>{yuantaStatus?.connected ? "今日無符合條件的委託。" : "請先連線券商後按「查詢」。"}</td></tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              ) : null}
              {mainTab === "mit" ? (
                <div className="scrollPane">
                  <div className="watchToolbar invToolbar">
                    <button
                      disabled={busy || pendingMitIds.length === 0 || mitSelected.size === pendingMitIds.length}
                      onClick={() => setMitSelected(new Set(pendingMitIds))}
                    >
                      <CheckSquare size={14} />全部選擇
                    </button>
                    <button
                      disabled={busy || mitSelected.size === 0}
                      onClick={() => setMitSelected(new Set())}
                    >
                      <Square size={14} />全部取消
                    </button>
                    <button
                      className="danger"
                      disabled={busy || mitSelected.size === 0}
                      onClick={() => void cancelSelectedMit()}
                    >
                      <Trash2 size={14} />全部刪單（{mitSelected.size}）
                    </button>
                  </div>
                <table className="denseTable tradeTable" style={mitResize.tableStyle}>
                  <thead>
                    <tr>
                      {["動作", "商品", "買賣", "觸價", "委託", "成交", "剩餘", "狀態", "時間", "觸發單號"].map((label, index) => (
                        <Th key={label} col={index} resize={mitResize}>{label}</Th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {mitOrders.map((item) => (
                      <tr key={item.id} onClick={() => selectForChart(item.symbol)}>
                        <td className="actionCell">
                          {item.status === "pending" ? (
                            <>
                              <input
                                type="checkbox"
                                className="rowCheck"
                                checked={mitSelected.has(item.id)}
                                onClick={(event) => event.stopPropagation()}
                                onChange={(event) => {
                                  const checked = event.target.checked;
                                  setMitSelected((current) => {
                                    const next = new Set(current);
                                    if (checked) next.add(item.id);
                                    else next.delete(item.id);
                                    return next;
                                  });
                                }}
                              />
                              <button
                                className="iconButton danger"
                                title="取消觸價單"
                                disabled={busy}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void handleCancelMit(item.id);
                                }}
                              >
                                <X size={13} />
                              </button>
                            </>
                          ) : null}
                        </td>
                        <td>{nameFor(item.symbol)} {item.symbol}</td>
                        <td className={item.side === "B" ? "down" : "up"}>{item.side === "B" ? "買" : "賣"}</td>
                        <td>{formatPrice(item.trigger_price)}</td>
                        <td>{item.quantity}</td>
                        <td>{numberText((item.filled_qty ?? 0) / 1000, 0)}</td>
                        <td>{numberText(item.quantity - (item.filled_qty ?? 0) / 1000, 0)}</td>
                        <td title={item.message}>{mitStatusText(item)}</td>
                        <td>{item.created_at.replace("T", " ")}</td>
                        <td>{item.order_no || "-"}</td>
                      </tr>
                    ))}
                    {mitOrders.length === 0 ? (
                      <tr><td colSpan={10}>尚無 MIT 觸價單。於閃電下單點 MIT 建立。</td></tr>
                    ) : null}
                  </tbody>
                </table>
                </div>
              ) : null}
              {mainTab === "inventory" ? (
                <div className="scrollPane">
                  <div className="watchToolbar invToolbar">
                    <button
                      disabled={busy || positions.length === 0 || invSelected.size === positions.length}
                      onClick={() => setInvSelected(new Set(positions.map((item) => item.symbol)))}
                    >
                      <CheckSquare size={14} />全部選擇
                    </button>
                    <button
                      disabled={busy || invSelected.size === 0}
                      onClick={() => setInvSelected(new Set())}
                    >
                      <Square size={14} />全部取消
                    </button>
                    <button
                      className="primary"
                      disabled={busy || invSelected.size === 0}
                      onClick={() => {
                        setInvPriceMode("current");
                        setInvConfirmOpen(true);
                      }}
                    >
                      <Send size={14} />全部送出（{invSelected.size}）
                    </button>
                  </div>
                  <table className="denseTable">
                    <thead><tr><th>選取</th><th>代號</th><th>名稱</th><th>庫存(張)</th><th>現價</th><th>送出張數</th><th>市值</th><th>未實現</th></tr></thead>
                    <tbody>
                      {positions.map((position) => {
                        const quote = quoteBySymbol.get(position.symbol);
                        const livePrice = quote?.deal_price ?? position.market_price;
                        const liveMarketAmount = livePrice ? livePrice * position.quantity : position.market_amount;
                        const checked = invSelected.has(position.symbol);
                        return (
                          <tr key={position.symbol} onClick={() => selectForChart(position.symbol)}>
                            <td onClick={(event) => event.stopPropagation()}>
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() =>
                                  setInvSelected((current) => {
                                    const next = new Set(current);
                                    if (next.has(position.symbol)) {
                                      next.delete(position.symbol);
                                    } else {
                                      next.add(position.symbol);
                                    }
                                    return next;
                                  })
                                }
                              />
                            </td>
                            <td>{position.symbol}</td>
                            <td>{position.name}</td>
                            <td>{numberText(position.quantity / 1000, 0)}</td>
                            <td>{numberText(livePrice)}</td>
                            <td onClick={(event) => event.stopPropagation()}>
                              <input
                                type="number"
                                min={1}
                                max={invDefaultLots(position)}
                                className="invLotsInput"
                                value={invLotsFor(position)}
                                onChange={(event) =>
                                  setInvLots((current) => ({
                                    ...current,
                                    [position.symbol]: Math.max(1, Math.min(invDefaultLots(position), Number(event.target.value) || 1))
                                  }))
                                }
                              />
                            </td>
                            <td>{numberText(liveMarketAmount, 0)}</td>
                            <td className={(position.unrealized_pnl ?? 0) >= 0 ? "down" : "up"}>{numberText(position.unrealized_pnl, 0)}</td>
                          </tr>
                        );
                      })}
                      {positions.length === 0 ? (
                        <tr><td colSpan={8}>尚無庫存。請先連線券商並按上方「庫存」更新。</td></tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </div>
          </div>
        </section>

        <aside className="zone zoneFlash terminalPanel orderDock">
              <div className="windowTitle">
                <strong>閃電下單</strong>
                <span className="lightningTitleTools">
                  <i className={`flashEnvTag ${isSimEnv ? "sim" : "live"}`}>{isSimEnv ? "模擬" : "實單"}</i>
                  {isSimEnv ? (() => {
                    const isFugle = (selectedQuote?.source ?? "").startsWith("fugle");
                    return (
                      <i
                        className={`flashSrcTag ${isFugle ? "real" : "synthetic"}`}
                        title={isFugle ? "報價來源：富果 Fugle 真實行情" : "報價來源：本機合成（無富果金鑰或取不到）"}
                      >
                        {isFugle ? "富果即時" : "合成"}
                      </i>
                    );
                  })() : null}
                  <button type="button" className="iconButton" onClick={() => centerLadder(true)} title="回到現價 (置中)">
                    <Crosshair size={13} />
                  </button>
                  僅證券
                </span>
              </div>
              <div className="lightningHeader">
                <label className="symbolSearch">商品
                  <input
                    value={order.symbol}
                    placeholder="代號或名稱"
                    onChange={(event) => handleSymbolInput(event.target.value)}
                    onFocus={() => symbolHits.length && setSymbolSearchOpen(true)}
                    onBlur={() => window.setTimeout(() => setSymbolSearchOpen(false), 150)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && symbolHits.length) {
                        event.preventDefault();
                        pickSymbol(symbolHits[0]);
                      } else if (event.key === "Escape") {
                        setSymbolSearchOpen(false);
                      }
                    }}
                  />
                  {symbolSearchOpen ? (
                    <div className="symbolSuggest">
                      {symbolHits.map((hit) => (
                        <button type="button" key={hit.code} onMouseDown={(event) => { event.preventDefault(); pickSymbol(hit); }}>
                          <b>{hit.code}</b>
                          <span>{hit.name}</span>
                          <i>{hit.exchange}</i>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </label>
                <label>張數<input
                  type="number"
                  min="1"
                  max="499"
                  step="1"
                  inputMode="numeric"
                  value={order.quantity || ""}
                  onChange={(event) => {
                    const value = event.target.value;
                    setOrder({ ...order, quantity: value === "" ? 0 : Math.min(499, Math.max(0, Math.floor(Number(value) || 0))) });
                  }}
                  onBlur={() => { if (!order.quantity || order.quantity < 1) setOrder((current) => ({ ...current, quantity: 1 })); }}
                /></label>
              </div>
              <div className="qtyQuick">
                {[1, 2, 3, 5, 10, 15, 20, 50].map((lots) => (
                  <button
                    type="button"
                    key={lots}
                    className={order.quantity === lots ? "selected" : ""}
                    onClick={() => setOrder({ ...order, quantity: lots })}
                  >
                    {lots}
                  </button>
                ))}
              </div>
              {(() => {
                const deal = selectedQuote?.deal_price ?? null;
                const prev = selectedQuote?.prev_close ?? null;
                const change = deal !== null && prev !== null && prev > 0 ? deal - prev : null;
                const trendClass = change === null || change === 0 ? "" : change > 0 ? "down" : "up";
                return (
                  <div className="flashQuoteStrip">
                    <b className="flashSym" title={orderName || selectedName}>{orderName || selectedName}</b>
                    <span>成交價</span>
                    <b className={trendClass}>{numberText(deal)}</b>
                    <span>漲跌</span>
                    <b className={trendClass}>
                      {change === null ? "-" : `${change > 0 ? "▲" : change < 0 ? "▼" : ""}${numberText(Math.abs(change))}`}
                    </b>
                    <span>單量</span>
                    <b>{latestTick ? numberText(latestTick.volume, 0) : "-"}</b>
                    <span>總量</span>
                    <b className="volText">{numberText(selectedQuote?.total_volume, 0)}</b>
                  </div>
                );
              })()}
              <div className="lightningBody">
                <div className="priceLadder">
                  {ladderLoading && yuantaStatus?.connected ? (
                    <div className="ladderLoading">
                      <Loader2 size={16} className="spin" />
                      <span>五檔報價載入中…</span>
                    </div>
                  ) : null}
                  <div className="ladderHeader">
                    <span>刪單</span><span>MIT</span><span>買進</span><span>委買</span><span>價格</span><span>委賣</span><span>賣出</span><span>MIT</span><span>刪單</span>
                  </div>
                  <div className="ladderRows" ref={priceLadderRef} onScroll={handleLadderScroll}>
                    {selectedPriceLadder.map((row) => {
                      const priceKey = Math.round(row.price * 100);
                      const fiveLevel = fiveVolByPrice.get(priceKey);
                      const pendingBuys = pendingMitByPrice.get(`${priceKey}|B`) ?? [];
                      const pendingSells = pendingMitByPrice.get(`${priceKey}|S`) ?? [];
                      const workingBuys = workingByPrice.get(`${priceKey}|B`) ?? [];
                      const workingSells = workingByPrice.get(`${priceKey}|S`) ?? [];
                      const inBook = Boolean(fiveLevel?.bid || fiveLevel?.ask);
                      const isArmed =
                        pendingLightningAction !== null &&
                        pendingLightningAction.symbol === selectedSymbol &&
                        Math.abs(pendingLightningAction.price - row.price) < 0.001;
                      const cancelCell = (mits: MitOrderRecord[], workings: WorkingOrder[], side: "B" | "S") => {
                        const total =
                          mits.reduce((sum, item) => sum + item.quantity, 0) +
                          workings.reduce((sum, item) => sum + workingRemainingLots(item), 0);
                        return total ? (
                          <button
                            type="button"
                            className={`cancelCell ${side === "B" ? "buy" : "sell"}`}
                            title={`刪除此價位 ${mits.length} 筆觸價單與 ${workings.length} 筆委託單`}
                            disabled={busy}
                            onClick={() => void cancelRowOrders(side, row.price)}
                          >
                            ✕{total}
                          </button>
                        ) : (
                          <span className="cancelCell empty" />
                        );
                      };
                      return (
                        <div
                          className={`ladderRow ${row.isCurrent ? "current" : ""} ${row.isLimitUp ? "limitUp" : ""} ${row.isLimitDown ? "limitDown" : ""} ${isArmed ? "armed" : ""}`}
                          key={row.price}
                          data-current={row.isCurrent ? "true" : undefined}
                          data-price={row.price}
                        >
                          {cancelCell(pendingBuys, workingBuys, "B")}
                          <button type="button" className="mitCell buy" onClick={() => armLightningAction("mit", "B", row.price)}>
                            {pendingBuys.length ? pendingBuys.reduce((sum, item) => sum + item.quantity, 0) : ""}
                          </button>
                          <button
                            type="button"
                            className={`orderCell buy ${inBook ? "inBook" : ""}`}
                            onClick={() => armLightningAction("order", "B", row.price)}
                          >
                            {workingBuys.length ? workingBuys.reduce((sum, item) => sum + workingRemainingLots(item), 0) : ""}
                          </button>

                          <span className={`fiveVolCell bid ${row.isBid ? "best" : ""}`}>
                            {fiveLevel?.bid ? fiveLevel.bid.toLocaleString("zh-TW") : ""}
                          </span>
                          <strong>{row.isLimitUp ? "漲停 " : row.isLimitDown ? "跌停 " : ""}{row.label}</strong>
                          <span className={`fiveVolCell ask ${row.isAsk ? "best" : ""}`}>
                            {fiveLevel?.ask ? fiveLevel.ask.toLocaleString("zh-TW") : ""}
                          </span>
                          <button
                            type="button"
                            className={`orderCell sell ${inBook ? "inBook" : ""}`}
                            onClick={() => armLightningAction("order", "S", row.price)}
                          >
                            {workingSells.length ? workingSells.reduce((sum, item) => sum + workingRemainingLots(item), 0) : ""}
                          </button>
                          <button type="button" className="mitCell sell" onClick={() => armLightningAction("mit", "S", row.price)}>
                            {pendingSells.length ? pendingSells.reduce((sum, item) => sum + item.quantity, 0) : ""}
                          </button>
                          {cancelCell(pendingSells, workingSells, "S")}
                        </div>
                      );
                    })}
                  </div>
                  <div className="flashStats">
                    <span className="flashStatBuy">委買 {flashTotals.buyOrder}・MIT {flashTotals.buyMit} 張</span>
                    <span className="flashStatSell">委賣 {flashTotals.sellOrder}・MIT {flashTotals.sellMit} 張</span>
                  </div>
                  <div className="flashBar">
                    <button type="button" onClick={() => void cancelRowOrders("B", 0, { allPrices: true })} disabled={busy}>買單全刪</button>
                    <button type="button" className="flashBuy" disabled={busy || !yuantaStatus?.connected} onClick={() => armLightningAction("order", "B", 0)}>市價買</button>
                    <button type="button" onClick={() => centerOnBook()}>五檔置中</button>
                    <button type="button" className="flashSell" disabled={busy || !yuantaStatus?.connected} onClick={() => armLightningAction("order", "S", 0)}>市價賣</button>
                    <button type="button" onClick={() => void cancelRowOrders("S", 0, { allPrices: true })} disabled={busy}>賣單全刪</button>
                  </div>
                </div>
              </div>
              <label className="check">
                <input type="checkbox" checked={confirmBeforeSend} onChange={(event) => setConfirmBeforeSend(event.target.checked)} />
                送單前二次確認
              </label>
              {sending ? <div className="sendingHint"><Loader2 size={14} className="spin" /> 委託送出中…</div> : null}
              {lastOrderResult ? <div className={lastOrderResult.accepted ? "sendResult ok" : "sendResult blocked"}><strong>{lastOrderResult.accepted ? "送單已接受" : "送單未送出"}</strong><span>{lastOrderResult.message}</span></div> : null}
        </aside>

        {invConfirmOpen ? (
          <div className="confirmOverlay" onClick={() => setInvConfirmOpen(false)}>
            <div className="confirmDialog invConfirmDialog" onClick={(event) => event.stopPropagation()}>
              <div className="windowTitle">
                <strong>庫存下單確認</strong>
                <span>賣出 {invSelected.size} 檔（必經二次確認）</span>
              </div>
              <div className="segmented invPriceModes">
                <button type="button" className={invPriceMode === "current" ? "selected" : ""} onClick={() => setInvPriceMode("current")}>現價</button>
                <button type="button" className={invPriceMode === "up" ? "selected" : ""} onClick={() => setInvPriceMode("up")}>漲停</button>
                <button type="button" className={invPriceMode === "down" ? "selected" : ""} onClick={() => setInvPriceMode("down")}>跌停</button>
              </div>
              <table className="denseTable">
                <thead><tr><th>商品</th><th>張數</th><th>委託價</th><th>預估金額</th></tr></thead>
                <tbody>
                  {positions.filter((item) => invSelected.has(item.symbol)).map((position) => {
                    const price = invPriceFor(position.symbol);
                    const lots = invLotsFor(position);
                    return (
                      <tr key={position.symbol}>
                        <td>{position.name} {position.symbol}</td>
                        <td>{lots}</td>
                        <td className={invPriceMode === "up" ? "down" : invPriceMode === "down" ? "up" : ""}>
                          {price > 0 ? numberText(price) : "市價"}
                        </td>
                        <td>{price > 0 ? numberText(price * lots * 1000, 0) : "-"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="confirmDialogActions">
                <button className="primary" onClick={() => void sendInventoryOrders()} disabled={busy}>
                  {busy ? <Loader2 size={15} className="spin" /> : <Send size={15} />} 確認全部送出
                </button>
                <button onClick={() => setInvConfirmOpen(false)} disabled={busy}>取消</button>
              </div>
            </div>
          </div>
        ) : null}

        {pendingLightningAction ? (
          <div className="confirmOverlay" onClick={() => setPendingLightningAction(null)}>
            <div className="confirmDialog" onClick={(event) => event.stopPropagation()}>
              <div className="windowTitle">
                <strong>委託確認</strong>
                <span>{pendingLightningAction.kind === "mit" ? "MIT 觸價單" : "一般委託"}</span>
              </div>
              <div className={`confirmEnvBanner ${isSimEnv ? "sim" : "live"}`}>
                {isSimEnv ? "模擬環境（沙盒，不會真實成交）" : `⚠️ 實單環境・${brokerLabel}・將以真實帳戶成交`}
              </div>
              <dl>
                <div><dt>商品</dt><dd>{selectedName} {pendingLightningAction.symbol}</dd></div>
                <div><dt>買賣</dt><dd className={pendingLightningAction.side === "B" ? "down" : "up"}>{pendingLightningAction.side === "B" ? "買進" : "賣出"}</dd></div>
                <div><dt>價格</dt><dd>{pendingLightningAction.price > 0 ? formatPrice(pendingLightningAction.price) : "市價"}</dd></div>
                <div><dt>張數</dt><dd>{pendingLightningAction.quantity} 張</dd></div>
                <div><dt>預估</dt><dd>{pendingLightningAction.price > 0 ? `${(pendingLightningAction.price * pendingLightningAction.quantity * 1000).toLocaleString("zh-TW")} 元` : "依市價成交"}</dd></div>
              </dl>
              <div className="confirmDialogActions">
                <button className="primary" onClick={() => void confirmLightningAction()} disabled={busy} title="Enter 確認">
                  {sending ? <Loader2 size={15} className="spin" /> : <Send size={15} />} 確認送出 ⏎
                </button>
                <button onClick={() => setPendingLightningAction(null)} disabled={busy} title="Esc 取消">取消 Esc</button>
              </div>
            </div>
          </div>
        ) : null}

        <section className="zone zone2 terminalPanel">
          <div className="windowTitle"><strong>警示紀錄</strong><span>盤中策略訊號</span></div>
          <table className="denseTable alertTable">
            <thead><tr><th>時間</th><th>代碼</th><th>等級</th><th>訊息</th></tr></thead>
            <tbody>
              {alerts.map((alert) => <tr key={`${alert.time}-${alert.symbol}`}><td>{alert.time}</td><td>{alert.symbol}</td><td className={alert.level === "WARN" ? "down" : "up"}>{alert.level}</td><td>{alert.message}</td></tr>)}
            </tbody>
          </table>
        </section>

        <div className="zone zone3 indexTabZone">
          <div className="footerTabBar indexTabBar">
            <button type="button" className={indexTab === "TSE" ? "active" : ""} onClick={() => setIndexTab("TSE")}>加權指數</button>
            <button type="button" className={indexTab === "OTC" ? "active" : ""} onClick={() => setIndexTab("OTC")}>櫃買指數</button>
          </div>
          {indexTab === "TSE" ? (
            <IndexIntradayChart points={tseIndexDisplay.points} quote={tseIndexDisplay.quote} height="100%" themeKey={theme} unifiedPriceLine />
          ) : (
            <IndexIntradayChart points={otcIndexDisplay.points} quote={otcIndexDisplay.quote} height="100%" themeKey={theme} unifiedPriceLine />
          )}
        </div>
        <div className="zone zone4">
          <IndexIntradayChart
            points={selectedIndex.points}
            quote={selectedIndex.quote}
            height="100%"
            fiveTick={fiveTick}
            ticks={ticks}
            ticksHint={streamStatus === "live" ? "等待成交推播（盤中有成交即顯示）" : "需連線券商並啟用即時報價"}
            themeKey={theme}
            unifiedPriceLine
          />
        </div>

        <section className="zone zone6 terminalPanel">
          <div className="tabs">
            <button className={portfolioTab === "live" ? "active" : ""} onClick={() => setPortfolioTab("live")}>全部庫存 報價組合</button>
            <button className={portfolioTab === "watchlist" ? "active" : ""} onClick={() => setPortfolioTab("watchlist")}>自選股庫存</button>
          </div>
          {portfolioTab === "live" ? (
            <table className="denseTable selectableTable">
              <thead><tr><th>商品</th><th>代碼</th><th>成交</th><th>庫存</th><th>損益</th></tr></thead>
              <tbody>
                {positions.map((position) => {
                  const quote = quoteBySymbol.get(position.symbol);
                  const livePrice = quote?.deal_price ?? position.market_price;
                  return (
                    <tr key={position.symbol} className={selectedSymbol === position.symbol ? "selectedRow" : ""} onClick={() => selectForChart(position.symbol)}>
                      <td>{position.name}</td><td>{position.symbol}</td><td>{numberText(livePrice)}</td><td>{position.quantity}</td><td className={(position.unrealized_pnl ?? 0) >= 0 ? "down" : "up"}>{numberText(position.unrealized_pnl, 0)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : watchlistEditing ? (
            <>
              <div className="watchToolbar">
                <span className="watchlistEditLabel">編輯「{activeWatchlist?.name ?? "自選股"}」</span>
                <button onClick={addWatchItem}><Plus size={14} />新增</button>
                <button onClick={saveWatchlistEditor}><Save size={14} />儲存</button>
                <button onClick={cancelWatchlistEditor}><X size={14} />取消</button>
              </div>
              <table className="denseTable editableTable">
                <thead><tr><th>商品</th><th>代碼</th><th>成本</th><th>張數</th><th>股數</th><th>刪除</th></tr></thead>
                <tbody>
                  {watchlistDraft.map((item, index) => {
                    return (
                      <tr key={index}>
                        <td><input className="readonlyInput" value={item.name} readOnly tabIndex={-1} placeholder="（搜尋代碼自動帶入）" /></td>
                        <td className="symbolTd">
                          <div className="editSymbolCell">
                            <input
                              value={item.symbol}
                              placeholder="代號或名稱"
                              onChange={(event) => handleEditSymbolInput(index, event.target.value)}
                              onFocus={() => { if (editHits.length) setEditHitRow(index); }}
                              onBlur={() => window.setTimeout(() => setEditHitRow((row) => (row === index ? -1 : row)), 150)}
                              onKeyDown={(event) => {
                                if (event.key === "Enter" && editHitRow === index && editHits.length) {
                                  event.preventDefault();
                                  pickEditSymbol(index, editHits[0]);
                                } else if (event.key === "Escape") {
                                  setEditHitRow(-1);
                                }
                              }}
                            />
                            {editHitRow === index && editHits.length ? (
                              <div className="symbolSuggest">
                                {editHits.map((hit) => (
                                  <button type="button" key={hit.code} onMouseDown={(event) => { event.preventDefault(); pickEditSymbol(index, hit); }}>
                                    <b>{hit.code}</b>
                                    <span>{hit.name}</span>
                                    <i>{hit.exchange}</i>
                                  </button>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        </td>
                        <td><input type="number" value={item.cost} onChange={(event) => updateWatchItem(index, { cost: Number(event.target.value) })} /></td>
                        <td><input type="number" min="0" value={item.lots} onChange={(event) => updateWatchItem(index, { lots: Math.max(0, Number(event.target.value) || 0) })} /></td>
                        <td><input type="number" min="0" value={item.shares} onChange={(event) => updateWatchItem(index, { shares: Math.max(0, Number(event.target.value) || 0) })} /></td>
                        <td><button className="iconButton danger" onClick={() => deleteWatchItem(index)} title="刪除"><Trash2 size={14} /></button></td>
                      </tr>
                    );
                  })}
                  {watchlistDraft.length === 0 ? (
                    <tr><td colSpan={6}>按「新增」加入股票。</td></tr>
                  ) : null}
                </tbody>
              </table>
            </>
          ) : (
            <>
              <div className="watchToolbar watchlistBar">
                {confirmingDeleteList ? (
                  <>
                    <span className="watchlistEditLabel deleteWarn">刪除「{activeWatchlist?.name}」？無法復原</span>
                    <button className="danger" onClick={confirmDeleteWatchlist} title="確定刪除此清單"><Trash2 size={14} />確定刪除</button>
                    <button onClick={() => setConfirmingDeleteList(false)} title="取消"><X size={14} />取消</button>
                  </>
                ) : renamingList ? (
                  <>
                    <input
                      className="listNameInput"
                      value={listNameDraft}
                      autoFocus
                      placeholder="清單名稱"
                      onChange={(event) => setListNameDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          saveRenameList();
                        } else if (event.key === "Escape") {
                          setRenamingList(false);
                        }
                      }}
                    />
                    <button onClick={saveRenameList} title="確定改名"><Save size={14} /></button>
                    <button onClick={() => setRenamingList(false)} title="取消"><X size={14} /></button>
                  </>
                ) : (
                  <>
                    <select value={activeWatchlistId} onChange={(event) => setActiveWatchlistId(event.target.value)} title="切換清單">
                      {watchlists.map((list) => (
                        <option key={list.id} value={list.id}>{list.name}</option>
                      ))}
                    </select>
                    <button onClick={addWatchlist} disabled={watchlists.length >= MAX_WATCHLISTS} title={watchlists.length >= MAX_WATCHLISTS ? `最多 ${MAX_WATCHLISTS} 個清單` : "新增清單"}><Plus size={14} /></button>
                    <button onClick={startRenameList} title="清單改名"><Pencil size={13} />改名</button>
                    <button className="danger" onClick={requestDeleteWatchlist} disabled={watchlists.length <= 1} title="刪除清單"><Trash2 size={14} /></button>
                    <button onClick={openWatchlistEditor} title="編輯清單內股票">編輯股票</button>
                  </>
                )}
              </div>
              <table className="denseTable selectableTable">
                <thead><tr><th>商品</th><th>代碼</th><th>成本</th><th>張數</th><th>股數</th><th>現價</th><th>損益</th><th>報酬率</th></tr></thead>
                <tbody>
                  {watchlist.map((item, index) => {
                    const quote = quoteBySymbol.get(item.symbol);
                    const price = quote?.deal_price ?? 0;
                    // 總持股 = 張數 × 1000 + 零股股數；損益以總股數計。
                    const totalShares = item.lots * 1000 + (item.shares ?? 0);
                    const pnl = price && item.cost ? (price - item.cost) * totalShares : 0;
                    const roi = price && item.cost ? ((price - item.cost) / item.cost) * 100 : 0;
                    return (
                      <tr key={`${item.symbol}-${index}`} className={selectedSymbol === item.symbol ? "selectedRow" : ""} onClick={() => item.symbol && selectForChart(item.symbol)}>
                        <td>{item.name}</td>
                        <td>{item.symbol}</td>
                        <td>{numberText(item.cost)}</td>
                        <td>{numberText(item.lots, 0)}</td>
                        <td>{numberText(item.shares ?? 0, 0)}</td>
                        <td>{numberText(price)}</td>
                        <td className={pnl >= 0 ? "down" : "up"}>{numberText(pnl, 0)}</td>
                        <td className={roi >= 0 ? "down" : "up"}>{numberText(roi)}%</td>
                      </tr>
                    );
                  })}
                  {watchlist.length === 0 ? (
                    <tr><td colSpan={8}>此清單尚無股票，按「編輯股票」新增。</td></tr>
                  ) : null}
                </tbody>
              </table>
            </>
          )}
        </section>
      </div>
    </main>
  );
}

// 登入閘門：未登入時只顯示登入畫面，登入成功才掛載下單介面（App）。
// 主題狀態提升到此，登入畫面與下單介面共用同一主題。
function AuthGate() {
  const [theme, setTheme] = useState<ThemeName>("dark");
  const [authState, setAuthState] = useState<LoginState | null | undefined>(undefined);

  useEffect(() => {
    getAuthState()
      .then((state) => setAuthState(state.logged_in ? state : null))
      .catch(() => setAuthState(null));
  }, []);

  if (authState === undefined) {
    return (
      <main className={`appShell theme-${theme}`}>
        <div className="loginScreen"><div className="loginCard"><p className="loginNote">載入中…</p></div></div>
      </main>
    );
  }

  if (!authState) {
    return (
      <main className={`appShell theme-${theme}`}>
        <LoginScreen onLoggedIn={(state) => setAuthState(state)} />
      </main>
    );
  }

  return <App theme={theme} setTheme={setTheme} onLogout={() => setAuthState(null)} />;
}

const RootComponent =
  window.location.pathname === "/jumbo-chart-demo"
    ? JumboChartDemo
    : window.location.pathname === "/index-intraday-demo"
      ? IndexIntradayChartDemo
      : window.location.pathname === "/jumbo-chart"
        ? JumboChartPage
        : AuthGate;

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RootComponent />
  </React.StrictMode>
);
