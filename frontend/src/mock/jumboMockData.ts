import type { JumboPoint } from "../charts/jumboChartOption";

function pad(value: number) {
  return String(value).padStart(2, "0");
}

function buildIntradayTimes() {
  const times: string[] = [];
  for (let totalMinutes = 9 * 60; totalMinutes <= 13 * 60 + 30; totalMinutes += 1) {
    const hour = Math.floor(totalMinutes / 60);
    const minute = totalMinutes % 60;
    times.push(`${pad(hour)}:${pad(minute)}`);
  }
  return times;
}

export const jumboMockData: JumboPoint[] = buildIntradayTimes().map((time, index) => {
  const morningPulse = Math.exp(-index / 55);
  const middayWave = Math.sin(index / 11);
  const longWave = Math.cos(index / 37);
  const trend = index * 0.18;
  const volatility = Math.sin(index / 3.7) * 18 + Math.cos(index / 8.5) * 11;

  const bidCount = Math.round(780 + trend + morningPulse * 220 + volatility);
  const askCount = Math.round(760 + trend * 0.9 + morningPulse * 180 - volatility * 0.75);
  const tradeCount = Math.round(420 + morningPulse * 160 + Math.abs(middayWave) * 90 + longWave * 35);

  const bidVolume = Math.round(bidCount * (1.8 + morningPulse * 0.7 + Math.sin(index / 15) * 0.18));
  const askVolume = Math.round(askCount * (1.75 + morningPulse * 0.6 + Math.cos(index / 16) * 0.16));
  const tradeVolume = Math.round(tradeCount * (2.1 + morningPulse * 0.9 + Math.abs(Math.sin(index / 9)) * 0.3));

  const upCount = Math.round(420 + Math.sin(index / 18) * 90 + longWave * 45 + trend * 0.1);
  const downCount = Math.round(510 - Math.sin(index / 18) * 80 - longWave * 35 + morningPulse * 60);
  const unchangedCount = Math.round(260 + Math.cos(index / 25) * 35);

  return {
    time,
    bid_count: Math.max(1, bidCount),
    ask_count: Math.max(1, askCount),
    trade_count: Math.max(1, tradeCount),
    bid_volume: Math.max(1, bidVolume),
    ask_volume: Math.max(1, askVolume),
    trade_volume: Math.max(1, tradeVolume),
    up_count: Math.max(1, upCount),
    down_count: Math.max(1, downCount),
    unchanged_count: Math.max(1, unchangedCount),
    bid_avg_volume: bidVolume / Math.max(1, bidCount),
    ask_avg_volume: askVolume / Math.max(1, askCount),
    trade_avg_volume: tradeVolume / Math.max(1, tradeCount)
  };
});
