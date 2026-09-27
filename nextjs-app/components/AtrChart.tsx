"use client";

import { useEffect, useRef } from "react";
import { LineSeries } from "lightweight-charts";
import type { AtrResult } from "@/lib/api";
import { toLineData } from "@/lib/chartData";
import { safeRemoveSeries, useChart } from "@/hooks/useChart";

interface Props {
  data: AtrResult;
}

export default function AtrChart({ data }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chart = useChart(containerRef);

  useEffect(() => {
    if (!chart) return;
    const series = chart.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 2,
      priceLineVisible: true,
    });
    series.setData(toLineData(data.history, data.dates));
    chart.timeScale().fitContent();
    return () => safeRemoveSeries(chart, series);
  }, [chart, data]);

  const signalColor =
    data.signal === "high" ? "text-red-500" : data.signal === "low" ? "text-green-500" : "text-muted-foreground";

  return (
    <div>
      <div ref={containerRef} className="h-[300px] w-full" />
      <p className="text-xs text-muted-foreground mt-2 text-center">
        ATR({data.period}): <span className="font-semibold text-foreground">{data.atr.toFixed(2)}</span> (
        {data.atrPercent.toFixed(2)}% of price) —{" "}
        <span className={`font-medium ${signalColor}`}>{data.signal} volatility</span>
      </p>
    </div>
  );
}
