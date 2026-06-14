import { useMemo } from "react";
import { IndexIntradayChart } from "../components/IndexIntradayChart";
import type { IndexIntradayPoint, IndexIntradayQuote } from "../charts/indexIntradayChartOption";

function pad(value: number) {
  return String(value).padStart(2, "0");
}

function buildDemoPoints(): IndexIntradayPoint[] {
  const points: IndexIntradayPoint[] = [];
  let price = 23120;
  let totalPriceVolume = 0;
  let totalVolume = 0;

  for (let totalMinutes = 9 * 60; totalMinutes <= 13 * 60 + 30; totalMinutes += 1) {
    const index = totalMinutes - 9 * 60;
    const hour = Math.floor(totalMinutes / 60);
    const minute = totalMinutes % 60;
    const time = `${pad(hour)}:${pad(minute)}`;
    const openingPulse = Math.exp(-index / 42);
    const selloff = index > 118 ? -360 * (1 - Math.exp(-(index - 118) / 18)) : 0;
    const rebound = index > 165 ? 130 * Math.sin((index - 165) / 22) : 0;
    const tail = index > 250 ? -70 + (index - 250) * 1.8 : 0;
    const wave = Math.sin(index / 7) * 34 + Math.cos(index / 19) * 22;
    price = 23120 + openingPulse * 165 + wave + selloff + rebound + tail;

    const volume =
      680 +
      Math.round(openingPulse * 2100) +
      Math.round(Math.abs(Math.sin(index / 5.4)) * 480) +
      (index > 112 && index < 142 ? Math.round(2600 * Math.exp(-Math.abs(index - 126) / 10)) : 0) +
      (index > 250 ? Math.round((index - 250) * 52) : 0);

    totalPriceVolume += price * volume;
    totalVolume += volume;

    points.push({
      time,
      price: Math.round(price * 100) / 100,
      avgPrice: Math.round((totalPriceVolume / totalVolume) * 100) / 100,
      volume
    });
  }

  return points;
}

function buildDemoQuote(points: IndexIntradayPoint[]): IndexIntradayQuote {
  const prices = points.map((point) => point.price);
  const volumes = points.map((point) => point.volume);
  const currentPrice = prices[prices.length - 1];
  const openPrice = prices[0];
  const highPrice = Math.max(...prices);
  const lowPrice = Math.min(...prices);
  const prevClose = 23150;
  const change = currentPrice - prevClose;
  const volume = volumes.reduce((sum, item) => sum + item, 0);

  return {
    market: "TSE",
    symbolName: "加權指數 TSE.TW",
    currentPrice,
    bidPrice: currentPrice - 0.58,
    askPrice: currentPrice + 0.42,
    openPrice,
    highPrice,
    lowPrice,
    prevClose,
    avgPrice: points[points.length - 1].avgPrice,
    change,
    changePercent: (change / prevClose) * 100,
    amplitudePercent: ((highPrice - lowPrice) / prevClose) * 100,
    volume,
    lastVolume: volumes[volumes.length - 1],
    innerVolume: Math.round(volume * 0.54),
    outerVolume: Math.round(volume * 0.46),
    volumeIncreasePercent: 18.42,
    limitUp: Math.round(prevClose * 1.1 * 100) / 100,
    limitDown: Math.round(prevClose * 0.9 * 100) / 100
  };
}

export function IndexIntradayChartDemo() {
  const points = useMemo(() => buildDemoPoints(), []);
  const quote = useMemo(() => buildDemoQuote(points), [points]);

  return (
    <main className="indexIntradayDemoPage">
      <IndexIntradayChart points={points} quote={quote} height={760} />
    </main>
  );
}
