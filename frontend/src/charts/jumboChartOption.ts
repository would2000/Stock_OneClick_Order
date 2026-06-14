import type { EChartsOption, SeriesOption } from "echarts";

export type JumboPoint = {
  time: string;
  bid_count: number;
  ask_count: number;
  trade_count: number;
  bid_volume: number;
  ask_volume: number;
  trade_volume: number;
  up_count: number;
  down_count: number;
  unchanged_count: number;
  bid_avg_volume: number;
  ask_avg_volume: number;
  trade_avg_volume: number;
};

type JumboField = keyof JumboPoint;

type LineSpec = {
  name: string;
  field: Exclude<JumboField, "time">;
  gridIndex: number;
  color: string;
};

const REQUIRED_FIELDS: JumboField[] = [
  "time",
  "bid_count",
  "ask_count",
  "trade_count",
  "bid_volume",
  "ask_volume",
  "trade_volume",
  "up_count",
  "down_count",
  "unchanged_count",
  "bid_avg_volume",
  "ask_avg_volume",
  "trade_avg_volume"
];

const LINE_SPECS: LineSpec[] = [
  { name: "委買筆數", field: "bid_count", gridIndex: 0, color: "#00d46a" },
  { name: "委賣筆數", field: "ask_count", gridIndex: 0, color: "#ff4d5e" },
  { name: "成交筆數", field: "trade_count", gridIndex: 0, color: "#ffd84a" },
  { name: "委買張數", field: "bid_volume", gridIndex: 1, color: "#16c784" },
  { name: "委賣張數", field: "ask_volume", gridIndex: 1, color: "#ff6674" },
  { name: "成交張數", field: "trade_volume", gridIndex: 1, color: "#b56cff" },
  { name: "漲家數", field: "up_count", gridIndex: 2, color: "#2ee66d" },
  { name: "跌家數", field: "down_count", gridIndex: 2, color: "#ff3348" },
  { name: "平盤家數", field: "unchanged_count", gridIndex: 2, color: "#aeb7bd" },
  { name: "每筆委買", field: "bid_avg_volume", gridIndex: 3, color: "#8df0a4" },
  { name: "每筆委賣", field: "ask_avg_volume", gridIndex: 3, color: "#ff9aa3" },
  { name: "每筆成交平均張數", field: "trade_avg_volume", gridIndex: 3, color: "#e0a7ff" }
];

const GRID_TITLES = ["筆數", "張數", "家數", "平均張數"];
const IMPORTANT_TIMES = new Set(["09:00", "10:00", "11:00", "12:00", "13:00", "13:30"]);

type TooltipDatum = {
  axisValue?: string | number;
  seriesName?: string;
  value?: unknown;
  marker?: string;
};

type BuildJumboChartOptionOptions = {
  compact?: boolean;
};

function formatValue(value: unknown): string {
  if (typeof value !== "number") {
    return String(value ?? "-");
  }
  return value.toLocaleString("zh-TW", {
    maximumFractionDigits: 2
  });
}

function isTooltipDatum(value: unknown): value is TooltipDatum {
  return typeof value === "object" && value !== null;
}

function formatTooltip(params: unknown): string {
  const items = Array.isArray(params) ? params.filter(isTooltipDatum) : isTooltipDatum(params) ? [params] : [];
  const time = items[0]?.axisValue ?? "";
  const lines = items.map((item) => {
    const marker = item.marker ?? "";
    const name = item.seriesName ?? "";
    return `${marker}${name}: <b>${formatValue(item.value)}</b>`;
  });
  return [`<b>${time}</b>`, ...lines].join("<br/>");
}

function assertValidData(data: JumboPoint[]): void {
  data.forEach((point, index) => {
    REQUIRED_FIELDS.forEach((field) => {
      if (!(field in point)) {
        throw new Error(`JumboPoint at index ${index} is missing field "${field}".`);
      }
      const value = point[field];
      if (field === "time") {
        if (typeof value !== "string" || value.length === 0) {
          throw new Error(`JumboPoint at index ${index} has invalid "time".`);
        }
        return;
      }
      if (typeof value !== "number" || Number.isNaN(value)) {
        throw new Error(`JumboPoint at index ${index} has invalid numeric field "${field}".`);
      }
    });
  });
}

function buildSeries(data: JumboPoint[]): SeriesOption[] {
  return LINE_SPECS.map((spec) => ({
    name: spec.name,
    type: "line",
    showSymbol: false,
    color: spec.color,
    xAxisIndex: spec.gridIndex,
    yAxisIndex: spec.gridIndex,
    lineStyle: {
      color: spec.color,
      width: 1.35
    },
    itemStyle: {
      color: spec.color
    },
    emphasis: {
      focus: "series"
    },
    data: data.map((point) => point[spec.field])
  }));
}

export function buildJumboChartOption(data: JumboPoint[], options: BuildJumboChartOptionOptions = {}): EChartsOption {
  assertValidData(data);

  const times = data.map((point) => point.time);
  const compact = options.compact ?? false;

  return {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: {
        type: "cross"
      },
      backgroundColor: "rgba(10, 14, 16, 0.92)",
      borderColor: "#41525a",
      textStyle: {
        color: "#edf5f7"
      },
      formatter: formatTooltip
    },
    legend: {
      type: "scroll",
      top: compact ? 24 : 42,
      left: compact ? 8 : 12,
      right: compact ? 8 : 12,
      height: compact ? 24 : 42,
      pageIconColor: "#dfe7ea",
      pageIconInactiveColor: "#5c6970",
      pageTextStyle: {
        color: "#c9d6db"
      },
      textStyle: {
        color: "#e5e7eb",
        fontSize: compact ? 10 : 12
      },
      data: LINE_SPECS.map((spec) => spec.name)
    },
    axisPointer: {
      link: [{ xAxisIndex: [0, 1, 2, 3] }]
    },
    grid: [
      compact
        ? { top: 54, left: 52, right: 10, height: "18%" }
        : { top: 76, left: 72, right: 28, height: "21%" },
      compact
        ? { top: "34%", left: 52, right: 10, height: "18%" }
        : { top: "32%", left: 72, right: 28, height: "21%" },
      compact
        ? { top: "58%", left: 52, right: 10, height: "15%" }
        : { top: "56%", left: 72, right: 28, height: "17%" },
      compact
        ? { top: "78%", left: 52, right: 10, height: "10%" }
        : { top: "77%", left: 72, right: 28, height: "11%" }
    ],
    xAxis: [0, 1, 2, 3].map((index) => ({
      type: "category",
      gridIndex: index,
      boundaryGap: false,
      data: times,
      axisLabel: {
        color: "#9fb0b7",
        show: index === 3,
        hideOverlap: true,
        interval: (_tickIndex: number, value: string) => IMPORTANT_TIMES.has(value),
        formatter: (value: string) => (IMPORTANT_TIMES.has(value) ? value : "")
      },
      axisLine: {
        lineStyle: { color: "#3b474d" }
      },
      axisTick: {
        show: index === 3
      }
    })),
    yAxis: [0, 1, 2, 3].map((index) => ({
      type: "value",
      gridIndex: index,
      scale: true,
      name: GRID_TITLES[index],
      nameGap: compact ? 24 : 34,
      nameLocation: "middle",
      nameTextStyle: {
        color: "#c8d5da",
        fontWeight: 600,
        fontSize: compact ? 10 : 12,
        padding: [0, compact ? 12 : 22, 0, 0]
      },
      axisLabel: {
        color: "#9fb0b7",
        fontSize: compact ? 10 : 12,
        formatter: (value: number) => value.toLocaleString("zh-TW", { maximumFractionDigits: 2 })
      },
      splitLine: {
        lineStyle: {
          color: "#263238",
          opacity: 0.85
        }
      }
    })),
    dataZoom: [
      {
        type: "inside",
        xAxisIndex: [0, 1, 2, 3],
        filterMode: "none"
      },
      {
        type: "slider",
        xAxisIndex: [0, 1, 2, 3],
        bottom: compact ? 2 : 8,
        height: compact ? 14 : 22,
        filterMode: "none",
        borderColor: "#3b474d",
        fillerColor: "rgba(88, 135, 150, 0.24)",
        handleStyle: {
          color: "#9fb0b7"
        },
        textStyle: {
          color: "#9fb0b7"
        }
      }
    ],
    series: buildSeries(data)
  };
}
