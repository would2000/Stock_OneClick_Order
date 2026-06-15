import { useLayoutEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import {
  buildIndexIntradayChartOption,
  DEFAULT_INTRADAY_CHART_COLORS,
  type IndexIntradayScaleMode,
  type IndexIntradayPoint,
  type IndexIntradayQuote,
  type IntradayChartColors
} from "../charts/indexIntradayChartOption";

import type { FiveTickBook, TickRecord } from "../types/api";

type IndexIntradayChartProps = {
  points: IndexIntradayPoint[];
  quote: IndexIntradayQuote;
  height?: number | string;
  fiveTick?: FiveTickBook | null;
  ticks?: TickRecord[];
  ticksHint?: string;
  // 變動時重新讀取主題 CSS 變數，讓分時圖隨風格切換對比色。
  themeKey?: string;
  // 個股走勢線統一黃色（不隨漲跌變紅綠）；指數不傳。
  unifiedPriceLine?: boolean;
  // 指數的「量」其實是成交值（金額）→ 傳 "turnover" 以「億」顯示；個股維持張/股整數。
  volumeUnit?: "lots" | "turnover";
};

// 從目前套用主題的 .appShell 讀 CSS 變數，對應到圖表配色。
function readChartColors(): IntradayChartColors {
  if (typeof document === "undefined") {
    return DEFAULT_INTRADAY_CHART_COLORS;
  }
  const host = document.querySelector(".appShell") ?? document.documentElement;
  const cs = getComputedStyle(host);
  const pick = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
  const d = DEFAULT_INTRADAY_CHART_COLORS;
  return {
    background: pick("--panel", d.background),
    text: pick("--text", d.text),
    muted: pick("--muted", d.muted),
    grid: pick("--grid", d.grid),
    rise: pick("--down", d.rise),
    fall: pick("--up", d.fall),
    accent: pick("--accent", d.accent),
    volume: pick("--chart-secondary", d.volume),
    tooltipBg: pick("--panel", d.tooltipBg),
    tooltipBorder: pick("--border", d.tooltipBorder),
    dayHigh: pick("--chart-high", d.dayHigh),
    dayLow: pick("--chart-low", d.dayLow),
    dayOpen: pick("--chart-open", d.dayOpen),
    dayClose: pick("--chart-close", d.dayClose),
    priceLine: pick("--chart-price", d.priceLine)
  };
}

function numberText(value: number | undefined, digits = 2) {
  if (value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toLocaleString("zh-TW", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  });
}

function integerText(value: number | undefined) {
  if (value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 0 });
}

// 指數的「量」其實是全市場成交值（金額，單位元）→ 換算成「億」顯示，避免 12 位數冗長。
function turnoverText(value: number | undefined) {
  if (value === undefined || Number.isNaN(value) || value <= 0) {
    return "-";
  }
  const yi = value / 1e8;
  const digits = yi >= 100 ? 0 : yi >= 10 ? 1 : 2;
  return `${yi.toLocaleString("zh-TW", { maximumFractionDigits: digits, minimumFractionDigits: 0 })} 億`;
}

function trendClass(value: number) {
  if (value > 0) {
    return "twUp";
  }
  if (value < 0) {
    return "twDown";
  }
  return "twFlat";
}

function QuoteCell({
  label,
  value,
  className = ""
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className="indexQuoteCell">
      <span>{label}</span>
      <strong className={className}>{value}</strong>
    </div>
  );
}

function QuotePanel({ quote, volumeUnit }: { quote: IndexIntradayQuote; volumeUnit?: "lots" | "turnover" }) {
  const changeClass = trendClass(quote.change);
  // 指數成交值以「億」顯示；個股維持張/股整數。
  const volText = volumeUnit === "turnover" ? turnoverText : integerText;

  return (
    <div className="indexQuotePanel">
      <QuoteCell label="成交" value={numberText(quote.currentPrice)} className={changeClass} />
      <QuoteCell label={volumeUnit === "turnover" ? "單值" : "單量"} value={volText(quote.lastVolume)} />
      <QuoteCell label={volumeUnit === "turnover" ? "總值" : "總量"} value={volText(quote.volume)} className="twVolume" />
      <QuoteCell label="開盤" value={numberText(quote.openPrice)} className={trendClass(quote.openPrice - quote.prevClose)} />
      <QuoteCell label="最高" value={numberText(quote.highPrice)} className={trendClass(quote.highPrice - quote.prevClose)} />
      <QuoteCell label="最低" value={numberText(quote.lowPrice)} className={trendClass(quote.lowPrice - quote.prevClose)} />
      <QuoteCell label="均價" value={numberText(quote.avgPrice)} className={trendClass(quote.avgPrice - quote.prevClose)} />
      <QuoteCell
        label="漲跌"
        value={`${quote.change > 0 ? "▲" : quote.change < 0 ? "▼" : ""}${numberText(Math.abs(quote.change))}`}
        className={changeClass}
      />
      <QuoteCell label="幅度" value={`${numberText(quote.changePercent)}%`} className={changeClass} />
      <QuoteCell label="振幅" value={`${numberText(quote.amplitudePercent)}%`} className="twWarn" />
      <QuoteCell label="內盤" value={volText(quote.innerVolume)} className="twDown" />
      <QuoteCell label="外盤" value={volText(quote.outerVolume)} className="twUp" />
    </div>
  );
}

function FiveTickPanel({ book, prevClose }: { book: FiveTickBook | null; prevClose: number }) {
  const levels = Array.from({ length: 5 }, (_, index) => ({
    bid: book?.bids[index] ?? { price: null, volume: 0 },
    ask: book?.asks[index] ?? { price: null, volume: 0 }
  }));
  const maxVolume = Math.max(
    1,
    ...levels.flatMap((level) => [level.bid.volume, level.ask.volume])
  );
  const priceClass = (price: number | null) =>
    price === null || !prevClose ? "twFlat" : trendClass(price - prevClose);

  return (
    <table className="fiveTickTable">
      <thead>
        <tr><th>買量</th><th>買價</th><th>賣價</th><th>賣量</th></tr>
      </thead>
      <tbody>
        {levels.map((level, index) => (
          <tr key={index}>
            <td className="fiveVol bid">
              <i style={{ width: `${(level.bid.volume / maxVolume) * 100}%` }} />
              <span>{level.bid.volume ? integerText(level.bid.volume) : "-"}</span>
            </td>
            <td className={priceClass(level.bid.price)}>{level.bid.price === null ? "-" : numberText(level.bid.price)}</td>
            <td className={priceClass(level.ask.price)}>{level.ask.price === null ? "-" : numberText(level.ask.price)}</td>
            <td className="fiveVol ask">
              <i style={{ width: `${(level.ask.volume / maxVolume) * 100}%` }} />
              <span>{level.ask.volume ? integerText(level.ask.volume) : "-"}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function looseNumberText(value: number | null) {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

function TickList({ ticks, hint }: { ticks: TickRecord[]; hint: string }) {
  return (
    <div className="tickTableWrap">
      <table className="denseTable tickTable">
        <thead><tr><th>時間</th><th>買進</th><th>賣出</th><th>成交</th><th>單量</th></tr></thead>
        <tbody>
          {[...ticks].reverse().map((tick, index) => {
            const dealClass =
              tick.deal_price !== null && tick.ask_price !== null && tick.deal_price >= tick.ask_price
                ? "tickOut"
                : tick.deal_price !== null && tick.bid_price !== null && tick.deal_price <= tick.bid_price
                  ? "tickIn"
                  : "tickFlat";
            return (
              <tr key={`${tick.serial || tick.time}-${index}`}>
                <td>{tick.time}</td>
                <td className="tickIn">{looseNumberText(tick.bid_price)}</td>
                <td className="tickOut">{looseNumberText(tick.ask_price)}</td>
                <td className={dealClass}>{looseNumberText(tick.deal_price)}</td>
                <td>{tick.volume.toLocaleString("zh-TW")}</td>
              </tr>
            );
          })}
          {ticks.length === 0 ? <tr><td colSpan={5} className="tickEmpty">{hint}</td></tr> : null}
        </tbody>
      </table>
    </div>
  );
}

export function IndexIntradayChart({ points, quote, height = 760, fiveTick, ticks, ticksHint, themeKey, unifiedPriceLine, volumeUnit }: IndexIntradayChartProps) {
  const [scaleMode, setScaleMode] = useState<IndexIntradayScaleMode>("relative");
  const [showOHLC, setShowOHLC] = useState(false);
  const [footerTab, setFooterTab] = useState<"five" | "stats">("five");
  const [colors, setColors] = useState<IntradayChartColors>(() => readChartColors());
  // 主題切換後（themeKey 改變）於 DOM 套用新 class 後重讀 CSS 變數。
  useLayoutEffect(() => {
    setColors(readChartColors());
  }, [themeKey]);
  const hasFooterTabs = fiveTick !== undefined;
  const hasQuote = quote.currentPrice > 0;
  const option = useMemo(
    () => (points.length > 0 ? buildIndexIntradayChartOption(points, quote, { scaleMode, colors, unifiedPriceLine, showOHLC }) : null),
    [points, quote, scaleMode, colors, unifiedPriceLine, showOHLC]
  );

  return (
    <section className={hasFooterTabs ? "indexIntradayShell withFooterTabs" : "indexIntradayShell"} style={{ height }}>
      <header className="indexIntradayHeader">
        <div>
          <h1>{quote.symbolName}</h1>
          <span>{points[points.length - 1]?.time ?? "--:--"}</span>
        </div>
        <div className="indexIntradayHeaderTools">
          <div className="indexScaleToggle" aria-label="OHLC 顯示">
            <button
              className={!showOHLC ? "active" : ""}
              onClick={() => setShowOHLC((on) => !on)}
              type="button"
              title="切換 OHLC（K 棒）顯示"
            >
              OHLC
            </button>
          </div>
          <div className="indexScaleToggle" aria-label="價格縮放模式">
            <button
              className={scaleMode === "relative" ? "active" : ""}
              onClick={() => setScaleMode("relative")}
              type="button"
            >
              相對
            </button>
            <button
              className={scaleMode === "absolute" ? "active" : ""}
              onClick={() => setScaleMode("absolute")}
              type="button"
            >
              絕對
            </button>
          </div>
        </div>
      </header>
      <div className="indexIntradayChartArea">
        {option ? (
          <ReactECharts
            option={option}
            notMerge
            lazyUpdate
            style={{
              width: "100%",
              height: "100%"
            }}
          />
        ) : (
          <div className="indexIntradayEmpty">{hasQuote ? "尚無真實分時線，已載入即時報價" : "等待真實分時資料"}</div>
        )}
      </div>
      {points.length > 0 || hasQuote ? (
        hasFooterTabs ? (
          <div className="chartFooterTabs">
            <div className="footerTabBar">
              <button type="button" className={footerTab === "five" ? "active" : ""} onClick={() => setFooterTab("five")}>
                最佳五檔
              </button>
              <button type="button" className={footerTab === "stats" ? "active" : ""} onClick={() => setFooterTab("stats")}>
                行情資訊
              </button>
            </div>
            {footerTab === "five" ? (
              <div className="fiveWithTicks">
                <FiveTickPanel book={fiveTick ?? null} prevClose={quote.prevClose} />
                <TickList ticks={ticks ?? []} hint={ticksHint ?? "等待成交推播"} />
              </div>
            ) : (
              <QuotePanel quote={quote} volumeUnit={volumeUnit} />
            )}
          </div>
        ) : (
          <QuotePanel quote={quote} volumeUnit={volumeUnit} />
        )
      ) : null}
    </section>
  );
}
