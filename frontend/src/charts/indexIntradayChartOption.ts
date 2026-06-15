import type { EChartsOption, SeriesOption } from "echarts";

export type IndexIntradayPoint = {
  time: string;
  price: number;
  avgPrice: number;
  volume: number;
  // 每分 K 的開高低收（個股由 kline 帶入）。缺值時 OHLC 模式以「前一收盤→本收盤」推導 K 棒。
  open?: number;
  high?: number;
  low?: number;
  close?: number;
};

export type IndexIntradayQuote = {
  market: "TSE" | "OTC";
  symbolName: string;

  currentPrice: number;
  bidPrice?: number;
  askPrice?: number;

  openPrice: number;
  highPrice: number;
  lowPrice: number;
  prevClose: number;
  avgPrice: number;

  change: number;
  changePercent: number;
  amplitudePercent: number;

  volume: number;
  lastVolume?: number;
  innerVolume?: number;
  outerVolume?: number;
  volumeIncreasePercent?: number;

  limitUp?: number;
  limitDown?: number;
};

type TooltipDatum = {
  axisValue?: string | number;
  seriesName?: string;
  value?: unknown;
  marker?: string;
};

type MarkLineItem = {
  name: string;
  yAxis: number;
  lineStyle: {
    color: string;
    type?: "solid" | "dashed" | "dotted";
    width: number;
  };
  label: {
    show: boolean;
    color: string;
    formatter: string;
    position: "insideEndTop" | "insideEndBottom" | "end";
  };
};

type MarkPointItem = {
  type?: "max" | "min";
  name: string;
  coord?: [string, number];
  value?: number;
  itemStyle: { color: string };
  label: {
    show: boolean;
    position: "top" | "bottom" | "left" | "right" | "inside";
    color: string;
    fontSize: number;
    fontWeight: number;
    formatter: string;
  };
};

export type IndexIntradayScaleMode = "absolute" | "relative";

// 圖表配色，由元件依當前主題從 CSS 變數讀入後傳進來，使分時圖隨風格變對比色。
export type IntradayChartColors = {
  background: string;
  text: string;
  muted: string;
  grid: string;
  rise: string; // 漲（台股紅）
  fall: string; // 跌（台股綠）
  accent: string; // 平盤線、漲跌停標籤
  volume: string; // 成交量柱
  tooltipBg: string;
  tooltipBorder: string;
  dayHigh: string; // 當日最高點
  dayLow: string; // 當日最低點
  dayOpen: string; // 開盤點
  dayClose: string; // 收盤/現價點
  priceLine: string; // 個股走勢線統一色（黃，依主題調整對比）
};

// 預設＝原本寫死的深色，未傳 colors 時行為不變（含既有 demo / 測試）。
export const DEFAULT_INTRADAY_CHART_COLORS: IntradayChartColors = {
  background: "#000000",
  text: "#d7dde0",
  muted: "#9aa3a8",
  grid: "#2c3032",
  rise: "#ff2b2b",
  fall: "#18df4d",
  accent: "#1486a8",
  volume: "rgba(0, 128, 200, 0.78)",
  tooltipBg: "rgba(0, 0, 0, 0.92)",
  tooltipBorder: "#3a3f42",
  dayHigh: "#ff3b3b",
  dayLow: "#22c55e",
  dayOpen: "#6fb8ff",
  dayClose: "#ffd633",
  priceLine: "#f5d31a"
};

type BuildIndexIntradayChartOptionOptions = {
  scaleMode?: IndexIntradayScaleMode;
  colors?: IntradayChartColors;
  // 個股走勢線統一用黃色（不隨漲跌變紅綠）；指數維持紅綠不傳此旗標。
  unifiedPriceLine?: boolean;
  // 走勢線改以 OHLC K 棒呈現。
  showOHLC?: boolean;
};

const IMPORTANT_TIMES = new Set(["09:00", "10:00", "11:00", "12:00", "13:00", "13:30"]);

// Full trading session 09:00–13:30 in 1-minute steps, so the x-axis is always
// the complete session instead of stretching as new data arrives.
const SESSION_TIMES: string[] = (() => {
  const times: string[] = [];
  for (let minutes = 9 * 60; minutes <= 13 * 60 + 30; minutes += 1) {
    const hour = String(Math.floor(minutes / 60)).padStart(2, "0");
    const minute = String(minutes % 60).padStart(2, "0");
    times.push(`${hour}:${minute}`);
  }
  return times;
})();

function formatNumber(value: number, digits = 2) {
  return value.toLocaleString("zh-TW", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  });
}

function formatLooseNumber(value: unknown) {
  if (typeof value !== "number") {
    return String(value ?? "-");
  }
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

function isTooltipDatum(value: unknown): value is TooltipDatum {
  return typeof value === "object" && value !== null;
}

function formatTooltip(params: unknown) {
  const items = Array.isArray(params) ? params.filter(isTooltipDatum) : isTooltipDatum(params) ? [params] : [];
  const time = items[0]?.axisValue ?? "";
  const lines = items
    .filter((item) => item.value !== null && item.value !== undefined && item.seriesName !== "priceBridge")
    .map((item) => `${item.marker ?? ""}${item.seriesName ?? ""}: <b>${formatLooseNumber(item.value)}</b>`);
  return [`<b>${time}</b>`, ...lines].join("<br/>");
}

function assertValidPoints(points: IndexIntradayPoint[]) {
  points.forEach((point, index) => {
    if (!point.time) {
      throw new Error(`IndexIntradayPoint at index ${index} has invalid time.`);
    }
    (["price", "avgPrice", "volume"] as const).forEach((field) => {
      if (typeof point[field] !== "number" || Number.isNaN(point[field])) {
        throw new Error(`IndexIntradayPoint at index ${index} has invalid ${field}.`);
      }
    });
  });
}

function yAxisBounds(
  points: IndexIntradayPoint[],
  quote: IndexIntradayQuote,
  scaleMode: IndexIntradayScaleMode,
  showOHLC = false
) {
  const values = [
    ...points.map((point) => point.price),
    ...points.map((point) => point.avgPrice),
    quote.currentPrice,
    quote.openPrice,
    quote.highPrice,
    quote.lowPrice,
    quote.prevClose,
    quote.avgPrice
  ].filter((value): value is number => typeof value === "number" && Number.isFinite(value));

  // K 棒模式：把每分 K 的實際高低也納入，y 軸自適應到不裁切任何 K 棒影線。
  if (showOHLC) {
    for (const point of points) {
      if (typeof point.high === "number" && Number.isFinite(point.high)) {
        values.push(point.high);
      }
      if (typeof point.low === "number" && Number.isFinite(point.low)) {
        values.push(point.low);
      }
    }
  }

  if (scaleMode === "absolute") {
    if (quote.limitUp !== undefined) {
      values.push(quote.limitUp);
    }
    if (quote.limitDown !== undefined) {
      values.push(quote.limitDown);
    }
  }

  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const padding =
    scaleMode === "absolute"
      ? Math.max((maxValue - minValue) * 0.06, Math.abs(quote.prevClose) * 0.002, 1)
      : Math.max((maxValue - minValue) * 0.18, Math.abs(quote.prevClose) * 0.0008, 0.01);
  return {
    min: Math.floor((minValue - padding) * 100) / 100,
    max: Math.ceil((maxValue + padding) * 100) / 100
  };
}

function buildPriceSeries(
  prices: (number | null)[],
  avg: (number | null)[],
  quote: IndexIntradayQuote,
  scaleMode: IndexIntradayScaleMode,
  colors: IntradayChartColors,
  times: string[],
  priceLineColor?: string,
  showOHLC = false,
  candleData: (number | string)[][] = []
): SeriesOption[] {
  // 個股統一黃線（priceLineColor）；否則隨漲跌紅綠（指數用）。
  const priceColor = priceLineColor ?? (quote.change >= 0 ? colors.rise : colors.fall);

  // 開／高／低／收／均 各放一個彩色點，價格數字標在點上。
  // 一律用即時報價值（盤中隨行情每筆更新），位置取序列首/末/極值索引。
  let firstIdx = -1;
  let lastIdx = -1;
  let hiIdx = -1;
  let loIdx = -1;
  let hiVal = -Infinity;
  let loVal = Infinity;
  for (let i = 0; i < prices.length; i += 1) {
    const value = prices[i];
    if (value === null || !Number.isFinite(value)) {
      continue;
    }
    if (firstIdx < 0) {
      firstIdx = i;
    }
    lastIdx = i;
    if (value > hiVal) {
      hiVal = value;
      hiIdx = i;
    }
    if (value < loVal) {
      loVal = value;
      loIdx = i;
    }
  }
  // 以 O:/H:/L:/C: 前綴區分，數字標在點上。高=主題紅(--down)、低=主題綠(--up)，
  // 開/收=主題對比色(--text)；皆取自主題變數，四種風格主題都清楚顯示。
  const markPointData: MarkPointItem[] = [];
  const addPoint = (
    name: string,
    index: number,
    value: number | undefined,
    prefix: string,
    position: MarkPointItem["label"]["position"],
    color: string
  ): void => {
    if (index < 0 || typeof value !== "number" || !(value > 0) || index >= times.length) {
      return;
    }
    markPointData.push({
      name,
      coord: [times[index], value],
      value,
      itemStyle: { color },
      label: { show: true, position, color, fontSize: 11, fontWeight: 700, formatter: `${prefix}{c}` }
    });
  };
  addPoint("最高", hiIdx, quote.highPrice, "H:", "top", colors.rise);
  addPoint("最低", loIdx, quote.lowPrice, "L:", "bottom", colors.fall);
  addPoint("開盤", firstIdx, quote.openPrice, "O:", "right", colors.text);
  addPoint("收盤", lastIdx, quote.currentPrice, "C:", "left", colors.text);

  const markLineData: MarkLineItem[] = [
    {
      name: "平盤",
      yAxis: quote.prevClose,
      lineStyle: { color: colors.accent, width: 1.1 },
      label: { show: true, color: colors.accent, formatter: `平盤 ${formatNumber(quote.prevClose)}`, position: "insideEndTop" }
    }
  ];

  if (scaleMode === "absolute" && quote.limitUp !== undefined) {
    markLineData.push({
      name: "漲停價",
      yAxis: quote.limitUp,
      lineStyle: { color: colors.rise, type: "dotted", width: 1 },
      label: { show: true, color: colors.accent, formatter: `漲停 ${formatNumber(quote.limitUp)}`, position: "insideEndTop" }
    });
  }

  if (scaleMode === "absolute" && quote.limitDown !== undefined) {
    markLineData.push({
      name: "跌停價",
      yAxis: quote.limitDown,
      lineStyle: { color: colors.fall, type: "dotted", width: 1 },
      label: { show: true, color: colors.accent, formatter: `跌停 ${formatNumber(quote.limitDown)}`, position: "insideEndBottom" }
    });
  }

  // 均價線末端標上目前均價數值，直接顯示在走勢圖上（個股／指數通用）。
  const avgMarkPointData: MarkPointItem[] = [];
  if (lastIdx >= 0 && typeof quote.avgPrice === "number" && quote.avgPrice > 0) {
    const avgVal = Math.round(quote.avgPrice * 100) / 100;
    avgMarkPointData.push({
      name: "均價",
      coord: [times[lastIdx], avgVal],
      value: avgVal,
      itemStyle: { color: colors.muted },
      // 往內（left）標示，避免在圖最右緣往外溢出被裁切（與收盤 C: 同側、不同 y 不重疊）。
      label: { show: true, position: "left", color: colors.muted, fontSize: 11, fontWeight: 700, formatter: `均{c}` }
    });
  }

  // K 棒模式：用蠟燭圖取代走勢線（漲紅 colors.rise／跌綠 colors.fall），平盤/漲跌停線沿用 markLine。
  const priceSeries: SeriesOption = showOHLC
    ? {
        name: "K線",
        type: "candlestick",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: candleData,
        barWidth: "60%",
        itemStyle: {
          color: colors.rise,
          color0: colors.fall,
          borderColor: colors.rise,
          borderColor0: colors.fall
        },
        z: 4,
        markLine: {
          symbol: "none",
          silent: true,
          data: markLineData
        }
      }
    : {
        name: "成交",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        data: prices,
        lineStyle: { color: priceColor, width: 1.8 },
        itemStyle: { color: priceColor },
        z: 4,
        markLine: {
          symbol: "none",
          silent: true,
          data: markLineData
        },
        markPoint: {
          symbol: "circle",
          symbolSize: 8,
          silent: true,
          data: markPointData
        }
      };

  return [
    priceSeries,
    {
      name: "日均線",
      type: "line",
      xAxisIndex: 0,
      yAxisIndex: 0,
      showSymbol: false,
      data: avg,
      lineStyle: { color: colors.muted, width: 1.35 },
      itemStyle: { color: colors.muted },
      z: 3,
      markPoint: {
        symbol: "circle",
        symbolSize: 6,
        silent: true,
        data: avgMarkPointData
      }
    }
  ];
}

export function buildIndexIntradayChartOption(
  points: IndexIntradayPoint[],
  quote: IndexIntradayQuote,
  options: BuildIndexIntradayChartOptionOptions = {}
): EChartsOption {
  assertValidPoints(points);

  const scaleMode = options.scaleMode ?? "absolute";
  const colors = options.colors ?? DEFAULT_INTRADAY_CHART_COLORS;
  const showOHLC = options.showOHLC ?? false;
  const pointByTime = new Map(points.map((point) => [point.time, point]));
  const times = SESSION_TIMES;
  const prices = times.map((time) => pointByTime.get(time)?.price ?? null);
  const avg = times.map((time) => pointByTime.get(time)?.avgPrice ?? null);
  const volume = times.map((time) => pointByTime.get(time)?.volume ?? null);
  const maxVolume = Math.max(...points.map((point) => point.volume), 1);
  const bounds = yAxisBounds(points, quote, scaleMode, showOHLC);

  // 每根 K 棒以 [開, 收, 低, 高] 表示（ECharts candlestick 順序）。有實際 OHLC（個股 kline）
  // 用實值；指數等只有收盤序列者，以「前一收盤→本收盤」推導 K 棒，仍能呈現分鐘漲跌。
  let prevCloseForCandle = Number.isFinite(quote.prevClose) ? quote.prevClose : null;
  const candleData: (number | string)[][] = times.map((time) => {
    const point = pointByTime.get(time);
    if (!point) {
      return ["-", "-", "-", "-"];
    }
    const close = typeof point.close === "number" ? point.close : point.price;
    const hasRealOHLC =
      typeof point.open === "number" && typeof point.high === "number" && typeof point.low === "number";
    const open = hasRealOHLC ? (point.open as number) : prevCloseForCandle ?? point.price;
    const high = hasRealOHLC ? (point.high as number) : Math.max(open, close);
    const low = hasRealOHLC ? (point.low as number) : Math.min(open, close);
    prevCloseForCandle = close;
    return [open, close, low, high];
  });

  return {
    backgroundColor: colors.background,
    animation: false,
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      backgroundColor: colors.tooltipBg,
      borderColor: colors.tooltipBorder,
      textStyle: { color: colors.text },
      formatter: formatTooltip
    },
    legend: {
      show: false
    },
    axisPointer: {
      link: [{ xAxisIndex: [0] }]
    },
    grid: [
      { left: 64, right: 24, top: 16, bottom: 8 }
    ],
    xAxis: [
      {
      type: "category",
      gridIndex: 0,
      data: times,
      // K 棒模式留邊距，避免首/末根 K 棒被格線裁切；走勢線維持貼邊。
      boundaryGap: showOHLC,
      axisLabel: {
        show: true,
        color: colors.muted,
        fontSize: 13,
        hideOverlap: true,
        interval: (_index: number, value: string) => IMPORTANT_TIMES.has(value),
        formatter: (value: string) => (IMPORTANT_TIMES.has(value) ? value : "")
      },
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: true }
      }
    ],
    yAxis: [
      {
        type: "value",
        gridIndex: 0,
        min: bounds.min,
        max: bounds.max,
        scale: true,
        axisLabel: {
          color: (value?: string | number) => {
            const numericValue = typeof value === "number" ? value : Number(value);
            if (!Number.isFinite(numericValue)) {
              return colors.text;
            }
            return numericValue > quote.prevClose ? colors.rise : numericValue < quote.prevClose ? colors.fall : colors.text;
          },
          fontSize: 13,
          formatter: (value: number) => formatNumber(value)
        },
        axisLine: { lineStyle: { color: colors.grid } },
        splitLine: { lineStyle: { color: colors.grid, width: 1 } }
      },
      {
        type: "value",
        gridIndex: 0,
        min: 0,
        max: maxVolume * 4,
        axisLabel: {
          show: false
        },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false }
      }
    ],
    series: [
      ...buildPriceSeries(
        prices,
        avg,
        quote,
        scaleMode,
        colors,
        times,
        options.unifiedPriceLine ? colors.priceLine : undefined,
        showOHLC,
        candleData
      ),
      {
        name: "成交量",
        type: "bar",
        xAxisIndex: 0,
        yAxisIndex: 1,
        data: volume,
        barWidth: "62%",
        itemStyle: { color: colors.volume },
        z: 0
      }
    ]
  };
}
