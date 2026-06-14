import type { JumboPoint } from "../charts/jumboChartOption";
import { normalizeJumboData } from "../adapters/jumboDataAdapter";

export type JumboMarket = "TSE" | "OTC";

export type FetchJumboDataParams = {
  market: JumboMarket;
  date: string;
  endpoint?: string;
};

async function requestRawJumboData(params: FetchJumboDataParams): Promise<unknown> {
  const endpoint = params.endpoint ?? "/api/jumbo-data";
  const searchParams = new URLSearchParams({
    market: params.market,
    date: params.date
  });

  const response = await fetch(`${endpoint}?${searchParams.toString()}`, {
    headers: {
      Accept: "application/json"
    }
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    const message =
      typeof detail === "object" && detail !== null && "detail" in detail
        ? String(detail.detail)
        : `Failed to fetch jumbo data: ${response.status}`;
    throw new Error(message);
  }

  return response.json();
}

export async function fetchJumboData(params: FetchJumboDataParams): Promise<JumboPoint[]> {
  const rawData = await requestRawJumboData(params);
  return normalizeJumboData(rawData);
}

export async function loadJumboDataExample() {
  let loading = true;
  let data: JumboPoint[] = [];
  let error: string | null = null;

  try {
    data = await fetchJumboData({
      market: "TSE",
      date: "2026-06-10"
    });
  } catch (unknownError) {
    error = unknownError instanceof Error ? unknownError.message : "Unknown jumbo data error.";
  } finally {
    loading = false;
  }

  return { loading, data, error };
}
