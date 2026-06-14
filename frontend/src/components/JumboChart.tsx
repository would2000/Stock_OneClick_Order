import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { buildJumboChartOption, type JumboPoint } from "../charts/jumboChartOption";

type JumboChartProps = {
  data: JumboPoint[];
  height?: number | string;
  compact?: boolean;
};

export function JumboChart({ data, height = 900, compact = false }: JumboChartProps) {
  const option = useMemo(() => buildJumboChartOption(data, { compact }), [compact, data]);

  return (
    <ReactECharts
      option={option}
      notMerge
      lazyUpdate
      style={{
        width: "100%",
        height
      }}
    />
  );
}
