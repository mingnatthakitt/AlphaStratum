"use client";

import { useEffect, useRef } from "react";
import { AreaSeries, CandlestickSeries, Time, type ISeriesApi } from "lightweight-charts";
import type { OHLCVData } from "@/lib/api";
import { safeRemoveSeries, useChart } from "@/hooks/useChart";

interface Props {
  data: OHLCVData[];
  symbol: string;
  view?: "candle" | "area";
}

export default function CandlestickChart({ data, symbol, view = "candle" }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chart = useChart(containerRef);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const areaRef = useRef<ISeriesApi<"Area"> | null>(null);

  useEffect(() => {
    if (!chart) return;

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });
    const areaSeries = chart.addSeries(AreaSeries, {
      lineColor: "#3b82f6",
      topColor: "rgba(59, 130, 246, 0.25)",
      bottomColor: "rgba(59, 130, 246, 0.02)",
      lineWidth: 2,
      priceLineVisible: false,
    });
    candleRef.current = candlestickSeries;
    areaRef.current = areaSeries;

    candlestickSeries.setData(
      data.map((d) => ({
        time: d.date as Time,
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
      })),
    );
    areaSeries.setData(data.map((d) => ({ time: d.date as Time, value: d.close })));
    chart.timeScale().fitContent();

    return () => {
      safeRemoveSeries(chart, candlestickSeries);
      safeRemoveSeries(chart, areaSeries);
      candleRef.current = null;
      areaRef.current = null;
    };
  }, [chart, data]);

  // Toggle candlestick vs area view
  useEffect(() => {
    candleRef.current?.applyOptions({ visible: view === "candle" });
    areaRef.current?.applyOptions({ visible: view === "area" });
  }, [view, chart]);

  return (
    <div>
      <div ref={containerRef} className="h-[400px] w-full" />
      <p className="text-xs text-muted-foreground mt-2 text-center">
        Data sourced from Yahoo Finance — {data.length} trading days shown
      </p>
    </div>
  );
}
