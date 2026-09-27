"use client";

import { useEffect, useRef } from "react";
import { AreaSeries, LineSeries, Time } from "lightweight-charts";
import type { OHLCVData } from "@/lib/api";
import { toLineData } from "@/lib/chartData";
import { safeRemoveSeries, useChart } from "@/hooks/useChart";

interface BandHistory {
  sma: number;
  upper: number;
  lower: number;
  bandwidth: number;
  percentB: number;
}

interface Props {
  sma: number;
  upper: number;
  lower: number;
  bandwidth: number;
  percentB: number;
  period: number;
  numStd: number;
  history: BandHistory[];
  priceData?: OHLCVData[];
  dates?: string[];
}

export default function BollingerChart({
  sma,
  upper,
  lower,
  bandwidth,
  percentB,
  period,
  numStd,
  history,
  priceData,
  dates,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chart = useChart(containerRef);

  useEffect(() => {
    if (!chart) return;

    const series: ReturnType<typeof chart.addSeries>[] = [];
    if (priceData && priceData.length > 0) {
      const priceSeries = chart.addSeries(AreaSeries, {
        lineColor: "#3b82f6",
        topColor: "rgba(59, 130, 246, 0.15)",
        bottomColor: "rgba(59, 130, 246, 0.02)",
        lineWidth: 1,
        priceLineVisible: false,
      });
      priceSeries.setData(priceData.map((d) => ({ time: d.date as Time, value: d.close })));
      series.push(priceSeries);
    }

    const upperSeries = chart.addSeries(LineSeries, {
      color: "rgba(148, 163, 184, 0.8)",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    upperSeries.setData(toLineData(history.map((h) => h.upper), dates));

    const smaSeries = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 2 });
    smaSeries.setData(toLineData(history.map((h) => h.sma), dates));

    const lowerSeries = chart.addSeries(LineSeries, {
      color: "rgba(148, 163, 184, 0.8)",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    lowerSeries.setData(toLineData(history.map((h) => h.lower), dates));

    series.push(upperSeries, smaSeries, lowerSeries);
    chart.timeScale().fitContent();
    return () => {
      for (const s of series) safeRemoveSeries(chart, s);
    };
  }, [chart, history, priceData, dates]);

  return (
    <div>
      <div ref={containerRef} className="h-[300px] w-full" />
      <p className="text-xs text-muted-foreground mt-2 text-center">
        BB({period},{numStd}): SMA <span className="font-semibold text-foreground">${sma.toFixed(2)}</span> ·
        bands ${lower.toFixed(2)}–${upper.toFixed(2)} · %B{" "}
        <span className={percentB > 1 ? "text-red-500" : percentB < 0 ? "text-green-500" : ""}>
          {(percentB * 100).toFixed(1)}%
        </span>{" "}
        · bandwidth {(bandwidth * 100).toFixed(2)}%
      </p>
    </div>
  );
}
