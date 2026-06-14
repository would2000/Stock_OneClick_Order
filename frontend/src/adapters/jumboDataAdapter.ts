import type { JumboPoint } from "../charts/jumboChartOption";

type RawJumboRecord = Record<string, unknown>;
type JumboNumericField = Exclude<keyof JumboPoint, "time">;

const FIELD_ALIASES: Record<keyof JumboPoint, string[]> = {
  time: ["time", "Time", "timestamp", "Timestamp", "datetime", "date_time", "時間"],
  bid_count: ["bid_count", "bidCount", "bidCnt", "buy_count", "buyCount", "委買筆數"],
  ask_count: ["ask_count", "askCount", "askCnt", "sell_count", "sellCount", "委賣筆數"],
  trade_count: ["trade_count", "tradeCount", "deal_count", "dealCount", "成交筆數"],
  bid_volume: ["bid_volume", "bidVolume", "buy_volume", "buyVolume", "委買張數"],
  ask_volume: ["ask_volume", "askVolume", "sell_volume", "sellVolume", "委賣張數"],
  trade_volume: ["trade_volume", "tradeVolume", "deal_volume", "dealVolume", "成交張數"],
  up_count: ["up_count", "upCount", "rise_count", "riseCount", "漲家數"],
  down_count: ["down_count", "downCount", "fall_count", "fallCount", "跌家數"],
  unchanged_count: ["unchanged_count", "unchangedCount", "flat_count", "flatCount", "平盤家數"],
  bid_avg_volume: ["bid_avg_volume", "bidAvgVolume", "buy_avg_volume", "buyAvgVolume", "每筆委買"],
  ask_avg_volume: ["ask_avg_volume", "askAvgVolume", "sell_avg_volume", "sellAvgVolume", "每筆委賣"],
  trade_avg_volume: [
    "trade_avg_volume",
    "tradeAvgVolume",
    "deal_avg_volume",
    "dealAvgVolume",
    "每筆成交平均張數"
  ]
};

const NUMERIC_FIELDS: JumboNumericField[] = [
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

export const jumboAdapterExampleRawData: RawJumboRecord[] = [
  {
    timestamp: "2026-06-10 09:00:00",
    bidCount: "820",
    askCount: "790",
    tradeCount: "430",
    bidVolume: "1420",
    askVolume: "1360",
    tradeVolume: "980",
    upCount: "420",
    downCount: "510",
    unchangedCount: "260",
    bidAvgVolume: "1.73",
    askAvgVolume: "1.72",
    tradeAvgVolume: "2.28"
  },
  {
    timestamp: "09:01",
    bidCount: 835,
    askCount: 782,
    tradeCount: 446,
    bidVolume: 1488,
    askVolume: 1344,
    tradeVolume: 1015,
    upCount: 428,
    downCount: 503,
    unchangedCount: 263,
    bidAvgVolume: 1.78,
    askAvgVolume: 1.72,
    tradeAvgVolume: 2.28
  }
];

export const jumboAdapterExample = normalizeJumboData(jumboAdapterExampleRawData);

function readAlias(record: RawJumboRecord, field: keyof JumboPoint): unknown {
  const aliases = FIELD_ALIASES[field];
  for (const alias of aliases) {
    if (Object.prototype.hasOwnProperty.call(record, alias)) {
      return record[alias];
    }
  }
  return undefined;
}

function normalizeTime(value: unknown): string | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return `${String(value.getHours()).padStart(2, "0")}:${String(value.getMinutes()).padStart(2, "0")}`;
  }

  const text = String(value).trim();
  const match = text.match(/(\d{1,2}):(\d{2})(?::\d{2})?/);
  if (!match) {
    return null;
  }

  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    return null;
  }

  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function toNumber(value: unknown): number {
  if (value === null || value === undefined || value === "") {
    return 0;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : 0;
  }
  const normalized = String(value).trim().replace(/,/g, "");
  if (normalized === "") {
    return 0;
  }
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : 0;
}

function timeSortValue(time: string): number {
  const [hour, minute] = time.split(":").map(Number);
  return hour * 60 + minute;
}

export function normalizeJumboData(rawData: unknown): JumboPoint[] {
  if (!Array.isArray(rawData)) {
    throw new Error("normalizeJumboData expected an array.");
  }

  return rawData
    .map((rawRecord, index) => {
      if (typeof rawRecord !== "object" || rawRecord === null || Array.isArray(rawRecord)) {
        throw new Error(`Record at index ${index} must be an object.`);
      }

      const record = rawRecord as RawJumboRecord;
      const missingFields: string[] = [];
      const rawTime = readAlias(record, "time");
      const time = normalizeTime(rawTime);
      if (time === null) {
        missingFields.push("time");
      }

      const numericValues = NUMERIC_FIELDS.reduce<Partial<Record<JumboNumericField, number>>>((acc, field) => {
        const rawValue = readAlias(record, field);
        if (rawValue === undefined) {
          missingFields.push(field);
          return acc;
        }
        acc[field] = toNumber(rawValue);
        return acc;
      }, {});

      if (missingFields.length > 0) {
        throw new Error(`Record at index ${index} is missing required fields: ${missingFields.join(", ")}.`);
      }

      return {
        time: time as string,
        bid_count: numericValues.bid_count as number,
        ask_count: numericValues.ask_count as number,
        trade_count: numericValues.trade_count as number,
        bid_volume: numericValues.bid_volume as number,
        ask_volume: numericValues.ask_volume as number,
        trade_volume: numericValues.trade_volume as number,
        up_count: numericValues.up_count as number,
        down_count: numericValues.down_count as number,
        unchanged_count: numericValues.unchanged_count as number,
        bid_avg_volume: numericValues.bid_avg_volume as number,
        ask_avg_volume: numericValues.ask_avg_volume as number,
        trade_avg_volume: numericValues.trade_avg_volume as number
      };
    })
    .sort((left, right) => timeSortValue(left.time) - timeSortValue(right.time));
}
