import { JumboChart } from "../components/JumboChart";
import { jumboMockData } from "../mock/jumboMockData";

export function JumboChartDemo() {
  return (
    <main style={{ minHeight: "100vh", width: "100%", background: "#050606", color: "#f4f7f5", padding: 16 }}>
      <h1 style={{ fontSize: 24, margin: "0 0 16px" }}>台股江波走勢圖 Demo</h1>
      <JumboChart data={jumboMockData} />
    </main>
  );
}
