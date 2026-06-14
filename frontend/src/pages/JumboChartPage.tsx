import { useCallback, useEffect, useState } from "react";
import { JumboChart } from "../components/JumboChart";
import type { JumboPoint } from "../charts/jumboChartOption";
import { fetchJumboData, type JumboMarket } from "../services/jumboDataService";

function todayText() {
  return new Date().toISOString().slice(0, 10);
}

export function JumboChartPage() {
  const [market, setMarket] = useState<JumboMarket>("TSE");
  const [date, setDate] = useState(todayText());
  const [data, setData] = useState<JumboPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchJumboData({ market, date }));
    } catch (unknownError) {
      setData([]);
      setError(unknownError instanceof Error ? unknownError.message : "載入江波資料失敗");
    } finally {
      setLoading(false);
    }
  }, [date, market]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  return (
    <main style={{ minHeight: "100vh", width: "100%", background: "#050606", color: "#f4f7f5", padding: 16 }}>
      <header style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <h1 style={{ fontSize: 24, margin: 0, marginRight: "auto" }}>台股江波走勢圖</h1>
        <label style={{ display: "grid", gap: 4, fontSize: 13 }}>
          Market
          <select value={market} onChange={(event) => setMarket(event.target.value as JumboMarket)}>
            <option value="TSE">TSE</option>
            <option value="OTC">OTC</option>
          </select>
        </label>
        <label style={{ display: "grid", gap: 4, fontSize: 13 }}>
          Date
          <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
        </label>
        <button onClick={() => void loadData()} disabled={loading}>
          Reload
        </button>
      </header>

      {loading ? <p>Loading...</p> : null}
      {error ? <p style={{ color: "#ff6674" }}>{error}</p> : null}
      {!loading && !error && data.length === 0 ? <p>查無資料</p> : null}
      {!loading && !error && data.length > 0 ? <JumboChart data={data} /> : null}
    </main>
  );
}
