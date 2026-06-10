"use client";

import { useEffect, useRef, useMemo, useCallback } from "react";
import { createChart, IChartApi, Time, AreaSeries } from "lightweight-charts";
import type { OHLCVData } from "@/lib/api";

interface Props {
  primary: { data: OHLCVData[]; symbol: string };
  secondary: { data: OHLCVData[]; symbol: string };
}

/** Normalize an OHLCV close array to % change from first value. */
function toPercentChange(ohlcv: OHLCVData[]): { time: Time; value: number }[] {
  if (ohlcv.length === 0) return [];
  const base = ohlcv[0].close;
  if (!base || base === 0 || isNaN(base)) return [];
  return ohlcv.map((d) => ({
    time: d.date as Time,
    value: ((d.close - base) / base) * 100,
  }));
}

export default function CompareChart({ primary, secondary }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<{ primary: any; secondary: any } | null>(null);

  // Memoize normalized data so useEffect dependency is stable by reference
  const primaryData = useMemo(() => toPercentChange(primary.data), [primary.data]);
  const secondaryData = useMemo(() => toPercentChange(secondary.data), [secondary.data]);

  // Stable legend strings
  const primaryLabel = useMemo(() => primary.symbol, [primary.symbol]);
  const secondaryLabel = useMemo(() => secondary.symbol, [secondary.symbol]);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: "transparent" },
        textColor: "hsl(var(--muted-foreground))",
      },
      grid: {
        vertLines: { color: "hsl(var(--border))" },
        horzLines: { color: "hsl(var(--border))" },
      },
      crosshair: { mode: 1 },
      timeScale: {
        borderColor: "hsl(var(--border))",
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: "hsl(var(--border))",
      },
    });

    const primarySeries = chart.addSeries(AreaSeries, {
      lineColor: "#3b82f6",
      topColor: "rgba(59, 130, 246, 0.2)",
      bottomColor: "rgba(59, 130, 246, 0.01)",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      priceFormat: { format: "percent", precision: 2, decimals: 2 },
    });

    const secondarySeries = chart.addSeries(AreaSeries, {
      lineColor: "#f59e0b",
      topColor: "rgba(245, 158, 11, 0.2)",
      bottomColor: "rgba(245, 158, 11, 0.01)",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      priceFormat: { format: "percent", precision: 2, decimals: 2 },
    });

    primarySeries.setData(primaryData);
    secondarySeries.setData(secondaryData);

    seriesRef.current = { primary: primarySeries, secondary: secondarySeries };
    chartRef.current = chart;
    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };

    window.addEventListener("resize", handleResize);
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(containerRef.current);

    return () => {
      window.removeEventListener("resize", handleResize);
      resizeObserver.disconnect();
      chart.remove();
    };
    // Only depend on memoized data arrays — stable references prevent unnecessary redraws
 }, [primaryData, secondaryData]);

  return (
    <div>
      <div ref={containerRef} className="h-[400px] w-full" />
      <div className="flex items-center justify-center gap-6 mt-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm bg-blue-500/80" />
          {primaryLabel}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm bg-amber-500/80" />
          {secondaryLabel}
        </span>
        <span>Normalized % change from first data point of each ticker</span>
      </div>
    </div>
  );
}
