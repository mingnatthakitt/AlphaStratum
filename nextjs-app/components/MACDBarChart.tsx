"use client";

import { useEffect, useRef } from "react";
import { HistogramSeries, LineSeries } from "lightweight-charts";
import { toHistogramData, toLineData } from "@/lib/chartData";
import { safeRemoveSeries, useChart } from "@/hooks/useChart";

interface Props {
  macd: number;
  signal: number;
  histogram: number;
  macdHistory: number[];
  signalHistory: number[];
  histogramHistory: number[];
  dates?: string[];
}

export default function MACDBarChart({
  macd,
  signal,
  histogram,
  macdHistory,
  signalHistory,
  histogramHistory,
  dates,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chart = useChart(containerRef);

  useEffect(() => {
    if (!chart) return;

    const histSeries = chart.addSeries(HistogramSeries, { priceLineVisible: false });
    histSeries.setData(toHistogramData(histogramHistory, dates));

    const macdSeries = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 2 });
    macdSeries.setData(toLineData(macdHistory, dates));

    const signalSeries = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 2 });
    signalSeries.setData(toLineData(signalHistory, dates));

    chart.timeScale().fitContent();
    return () => {
      safeRemoveSeries(chart, histSeries);
      safeRemoveSeries(chart, macdSeries);
      safeRemoveSeries(chart, signalSeries);
    };
  }, [chart, macdHistory, signalHistory, histogramHistory, dates]);

  return (
    <div>
      <div ref={containerRef} className="h-[300px] w-full" />
      <p className="text-xs text-muted-foreground mt-2 text-center">
        MACD(12,26,9): <span className="font-semibold text-foreground">{macd.toFixed(3)}</span> · signal{" "}
        {signal.toFixed(3)} · histogram{" "}
        <span className={histogram >= 0 ? "text-green-500" : "text-red-500"}>{histogram.toFixed(3)}</span>
      </p>
    </div>
  );
}
