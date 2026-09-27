"use client";

import { useEffect, useRef } from "react";
import { AreaSeries } from "lightweight-charts";
import type { GarchResult } from "@/lib/api";
import { toLineData } from "@/lib/chartData";
import { safeRemoveSeries, useChart } from "@/hooks/useChart";

interface Props {
  data: GarchResult;
}

export default function GarchChart({ data }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chart = useChart(containerRef);

  useEffect(() => {
    if (!chart) return;
    const series = chart.addSeries(AreaSeries, {
      lineColor: "#8b5cf6",
      topColor: "rgba(139, 92, 246, 0.25)",
      bottomColor: "rgba(139, 92, 246, 0.02)",
      lineWidth: 2,
      priceLineVisible: false,
    });
    series.setData(toLineData(data.forecast, data.forecastDates));
    chart.timeScale().fitContent();
    return () => safeRemoveSeries(chart, series);
  }, [chart, data]);

  return (
    <div>
      <div ref={containerRef} className="h-[300px] w-full" />
      <p className="text-xs text-muted-foreground mt-2 text-center">
        GARCH(1,1) forecast — current conditional volatility:{" "}
        <span className="font-semibold text-foreground">{(data.currentVol * 100).toFixed(2)}%</span> daily
      </p>
    </div>
  );
}
