"use client";

import { useEffect, useRef } from "react";
import { LineSeries, LineStyle } from "lightweight-charts";
import { toLineData } from "@/lib/chartData";
import { resolveChartColors, safeRemoveSeries, useChart } from "@/hooks/useChart";

interface Props {
  rsi: number;
  signal: "overbought" | "oversold" | "neutral";
  history: number[];
  dates?: string[];
}

export default function RSIChart({ rsi, signal, history, dates }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chart = useChart(containerRef);

  useEffect(() => {
    if (!chart) return;
    const colors = resolveChartColors();
    const series = chart.addSeries(LineSeries, {
      color: "#8b5cf6",
      lineWidth: 2,
      priceLineVisible: false,
    });
    series.setData(toLineData(history, dates));
    series.createPriceLine({
      price: 70,
      color: "rgba(239, 68, 68, 0.5)",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: "70",
    });
    series.createPriceLine({
      price: 30,
      color: "rgba(34, 197, 94, 0.5)",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: "30",
    });
    chart.timeScale().fitContent();
    return () => safeRemoveSeries(chart, series);
  }, [chart, history, dates]);

  const signalColor =
    signal === "overbought" ? "text-red-500" : signal === "oversold" ? "text-green-500" : "text-muted-foreground";

  return (
    <div>
      <div ref={containerRef} className="h-[300px] w-full" />
      <p className="text-xs text-muted-foreground mt-2 text-center">
        RSI({14}): <span className="font-semibold text-foreground">{rsi.toFixed(1)}</span> —{" "}
        <span className={`font-medium ${signalColor}`}>{signal}</span>
      </p>
    </div>
  );
}
