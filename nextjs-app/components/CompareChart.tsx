"use client";

import { useEffect, useMemo, useRef } from "react";
import { AreaSeries, Time } from "lightweight-charts";
import type { OHLCVData } from "@/lib/api";
import { safeRemoveSeries, useChart } from "@/hooks/useChart";

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
  const chart = useChart(containerRef);

  // Memoize normalized data so the effect dependency is stable by reference
  const primaryData = useMemo(() => toPercentChange(primary.data), [primary.data]);
  const secondaryData = useMemo(() => toPercentChange(secondary.data), [secondary.data]);

  useEffect(() => {
    if (!chart) return;

    const primarySeries = chart.addSeries(AreaSeries, {
      lineColor: "#3b82f6",
      topColor: "rgba(59, 130, 246, 0.2)",
      bottomColor: "rgba(59, 130, 246, 0.01)",
      lineWidth: 2,
      priceLineVisible: false,
      priceFormat: { format: "percent", precision: 2, decimals: 2 } as never,
    });
    const secondarySeries = chart.addSeries(AreaSeries, {
      lineColor: "#f59e0b",
      topColor: "rgba(245, 158, 11, 0.2)",
      bottomColor: "rgba(245, 158, 11, 0.01)",
      lineWidth: 2,
      priceLineVisible: false,
      priceFormat: { format: "percent", precision: 2, decimals: 2 } as never,
    });
    primarySeries.setData(primaryData);
    secondarySeries.setData(secondaryData);
    chart.timeScale().fitContent();

    return () => {
      safeRemoveSeries(chart, primarySeries);
      safeRemoveSeries(chart, secondarySeries);
    };
  }, [chart, primaryData, secondaryData]);

  return (
    <div>
      <div ref={containerRef} className="h-[400px] w-full" />
      <div className="flex items-center justify-center gap-6 mt-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm bg-blue-500/80" />
          {primary.symbol}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm bg-amber-500/80" />
          {secondary.symbol}
        </span>
        <span>Normalized % change from first data point of each ticker</span>
      </div>
    </div>
  );
}
