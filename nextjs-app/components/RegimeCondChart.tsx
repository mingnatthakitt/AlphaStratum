"use client";

import { useEffect, useRef } from "react";
import { createChart, IChartApi, Time, LineSeries } from "lightweight-charts";
import type { MonteCarloRegimeCondResult } from "@/lib/api";

interface Props {
  data: MonteCarloRegimeCondResult;
}

const REGIME_COLORS = {
  bull:     "#22c55e",
  bear:     "#ef4444",
  sideways: "#f59e0b",
  blended:  "#3b82f6",
};

function datesToTimes(dates: string[]): Time[] {
  return dates.map((d) => {
    const [y, m, day] = d.split("-").map(Number);
    return Math.floor(new Date(y, m - 1, day).getTime() / 1000) as Time;
  });
}

export default function RegimeCondChart({ data }: Props) {
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
      timeScale: {
        borderColor: "hsl(var(--border))",
        timeVisible: true,
        tickMarkFormatter: (time: Time) => {
          const d = new Date(Number(time) * 1000);
          return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
        },
      },
      rightPriceScale: {
        borderColor: "hsl(var(--border))",
        scaleMargins: { top: 0.05, bottom: 0.05 },
        borderVisible: true,
      },
    });

    const times = datesToTimes(data.regimeProbabilities.map((p) => p.date));

    // ── Draw each regime fan as line series ──
    for (const [regime, color] of Object.entries(REGIME_COLORS) as [keyof typeof REGIME_COLORS, string][]) {
      if (regime === "blended") continue;
      const fan = data.fans[regime as "bull" | "bear" | "sideways"];
      if (!fan) continue;

      // p95 outer bound (dashed, faint)
      const p95 = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: true,
        lastValueVisible: false,
        priceLineWidth: 0,
      });
      p95.setData(times.map((t, i) => ({ time: t, value: fan.p95[i] })));

      // p75 inner bound (dashed)
      const p75 = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        lineStyle: 3,
        priceLineVisible: true,
        lastValueVisible: false,
        priceLineWidth: 0,
      });
      p75.setData(times.map((t, i) => ({ time: t, value: fan.p75[i] })));

      // p50 median (solid, prominent)
      const p50 = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1.5,
        priceLineVisible: true,
        lastValueVisible: true,
        priceLineWidth: 0,
      });
      p50.setData(times.map((t, i) => ({ time: t, value: fan.p50[i] })));

      // p25 inner bound (dashed)
      const p25 = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        lineStyle: 3,
        priceLineVisible: true,
        lastValueVisible: false,
        priceLineWidth: 0,
      });
      p25.setData(times.map((t, i) => ({ time: t, value: fan.p25[i] })));

      // p5 outer bound (dashed, faint)
      const p05 = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: true,
        lastValueVisible: false,
        priceLineWidth: 0,
      });
      p05.setData(times.map((t, i) => ({ time: t, value: fan.p5[i] })));
    }

    // ── Blended fan on top (bold blue) ──
    const blendedP95 = chart.addSeries(LineSeries, {
      color: REGIME_COLORS.blended,
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: true,
      lastValueVisible: false,
      priceLineWidth: 0,
    });
    blendedP95.setData(times.map((t, i) => ({ time: t, value: data.blended.p95[i] })));

    const blendedP75 = chart.addSeries(LineSeries, {
      color: REGIME_COLORS.blended,
      lineWidth: 1,
      lineStyle: 3,
      priceLineVisible: true,
      lastValueVisible: false,
      priceLineWidth: 0,
    });
    blendedP75.setData(times.map((t, i) => ({ time: t, value: data.blended.p75[i] })));

    const blendedP50 = chart.addSeries(LineSeries, {
      color: REGIME_COLORS.blended,
      lineWidth: 2.5,
      priceLineVisible: true,
      lastValueVisible: true,
      priceLineWidth: 0,
    });
    blendedP50.setData(times.map((t, i) => ({ time: t, value: data.blended.p50[i] })));

    const blendedP25 = chart.addSeries(LineSeries, {
      color: REGIME_COLORS.blended,
      lineWidth: 1,
      lineStyle: 3,
      priceLineVisible: true,
      lastValueVisible: false,
      priceLineWidth: 0,
    });
    blendedP25.setData(times.map((t, i) => ({ time: t, value: data.blended.p25[i] })));

    const blendedP05 = chart.addSeries(LineSeries, {
      color: REGIME_COLORS.blended,
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: true,
      lastValueVisible: false,
      priceLineWidth: 0,
    });
    blendedP05.setData(times.map((t, i) => ({ time: t, value: data.blended.p5[i] })));

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [data]);

  return (
    <div>
      <div ref={containerRef} className="h-[400px] w-full" />
      <div className="flex flex-wrap gap-x-6 gap-y-1 justify-center mt-2 text-xs">
        {[
          { label: "Bull fan", color: REGIME_COLORS.bull, sub: "p5–p95 range" },
          { label: "Bear fan", color: REGIME_COLORS.bear, sub: "p5–p95 range" },
          { label: "Sideways fan", color: REGIME_COLORS.sideways, sub: "p5–p95 range" },
          { label: "Blended", color: REGIME_COLORS.blended, sub: "prob-weighted avg" },
        ].map(({ label, color, sub }) => (
          <span key={label} className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 rounded" style={{ backgroundColor: color }} />
            <span>
              {label} <span className="text-muted-foreground">{sub}</span>
            </span>
          </span>
        ))}
      </div>
      <p className="text-xs text-muted-foreground mt-1 text-center">
        Regime-conditional GBM · {data.horizon}d horizon · σ = {(data.sigma * 100).toFixed(2)}%/day ({data.volatilitySource === "garch" ? "GARCH" : "historical"} vol)
        {data.currentRegime && (
          <span> · Current: <span className="capitalize font-medium">{data.currentRegime}</span></span>
        )}
      </p>
      <p className="text-xs text-muted-foreground/60 text-center mt-0.5">
        Colored fans = regime-conditional paths. Blended (blue) = probability-weighted average across all regimes.
      </p>
    </div>
  );
}
