"use client";

import { useEffect, useRef } from "react";
import { createChart, IChartApi, Time, LineSeries } from "lightweight-charts";
import type { MonteCarloResult } from "@/lib/api";

interface Props {
  data: MonteCarloResult;
}

export default function MonteCarloChart({ data }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

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
      timeScale: { borderColor: "hsl(var(--border))", timeVisible: true },
      rightPriceScale: { borderColor: "hsl(var(--border))" },
    });

    const p50Series = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 2, title: "Median (50th)" });
    const p5Series = chart.addSeries(LineSeries, { color: "#94a3b8", lineWidth: 1, lineStyle: 3, title: "5th pct" });
    const p95Series = chart.addSeries(LineSeries, { color: "#94a3b8", lineWidth: 1, lineStyle: 3, title: "95th pct" });
    const p25Series = chart.addSeries(LineSeries, { color: "#60a5fa", lineWidth: 1, lineStyle: 2, title: "25th pct" });
    const p75Series = chart.addSeries(LineSeries, { color: "#60a5fa", lineWidth: 1, lineStyle: 2, title: "75th pct" });

    // Use Unix timestamps (seconds) for time axis — reliable, no string parsing issues
    const times: Time[] = data.forecastDates.map((d) => {
      const [year, month, day] = d.split("-").map(Number);
      return Math.floor(new Date(year, month - 1, day).getTime() / 1000) as Time;
    });

    p50Series.setData(data.percentiles.p50.map((v, i) => ({ time: times[i], value: v })));
    p5Series.setData(data.percentiles.p5.map((v, i) => ({ time: times[i], value: v })));
    p95Series.setData(data.percentiles.p95.map((v, i) => ({ time: times[i], value: v })));
    p25Series.setData(data.percentiles.p25.map((v, i) => ({ time: times[i], value: v })));
    p75Series.setData(data.percentiles.p75.map((v, i) => ({ time: times[i], value: v })));

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };

    window.addEventListener("resize", handleResize);
    const ro = new ResizeObserver(handleResize);
    ro.observe(containerRef.current);

    return () => {
      window.removeEventListener("resize", handleResize);
      ro.disconnect();
      chart.remove();
    };
  }, [data]);

  return (
    <div>
      <div ref={containerRef} className="h-[400px] w-full" />
      <div className="flex gap-4 justify-center mt-2 text-xs">
        {[
          { label: "95th pct", color: "#94a3b8" },
          { label: "75th pct", color: "#60a5fa" },
          { label: "Median", color: "#3b82f6" },
          { label: "25th pct", color: "#60a5fa" },
          { label: "5th pct", color: "#94a3b8" },
        ].map(({ label, color }) => (
          <span key={label} className="flex items-center gap-1">
            <span className="w-3 h-0.5 rounded" style={{ backgroundColor: color }} />
            {label}
          </span>
        ))}
      </div>
      <p className="text-xs text-muted-foreground mt-1 text-center">
        {data.paths.length.toLocaleString()} Monte Carlo paths · Last price: ${data.lastPrice.toFixed(2)}
        {data.horizon && ` · ${data.horizon} day horizon`}
        {data.currentRegime && (
          <span> · <span className="capitalize font-medium">{data.currentRegime}</span> regime{data.regimeAdjusted ? " (drift adjusted)" : ""}</span>
        )}
      </p>
      <p className="text-xs text-muted-foreground/60 text-center mt-0.5">
        Fan bands show 5th–95th percentile. Real prices can exceed p95 — a black swan can blow past it entirely.
      </p>
    </div>
  );
}