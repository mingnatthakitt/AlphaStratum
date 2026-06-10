"use client";

import { useEffect, useRef } from "react";
import { createChart, IChartApi, Time, LineSeries } from "lightweight-charts";
import type { AtrResult } from "@/lib/api";

interface Props {
  data: AtrResult;
}

export default function AtrChart({ data }: Props) {
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

    // Generate trading-day timestamps going back N days from today (skip weekends)
    const now = new Date();
    const times: Time[] = [];
    let count = 0;
    const d = new Date(now);
    while (count < data.history.length) {
      d.setDate(d.getDate() - 1);
      if (d.getDay() !== 0 && d.getDay() !== 6) {
        times.unshift(Math.floor(d.getTime() / 1000) as Time);
        count++;
      }
    }

    // ATR line
    const atrSeries = chart.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 2,
      priceLineVisible: true,
      lastValueVisible: true,
      priceLineWidth: 0,
    });
    atrSeries.setData(times.map((t, i) => ({ time: t, value: data.history[i] })));

    // 3% threshold (high volatility)
    const highThresh = chart.addSeries(LineSeries, {
      color: "rgba(239,68,68,0.4)",
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: true,
      lastValueVisible: false,
      priceLineWidth: 0,
    });
    highThresh.setData(times.map((t) => ({ time: t, value: data.currentPrice * 0.03 })));

    // 1% threshold (normal/low boundary)
    const normThresh = chart.addSeries(LineSeries, {
      color: "rgba(34,197,94,0.4)",
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: true,
      lastValueVisible: false,
      priceLineWidth: 0,
    });
    normThresh.setData(times.map((t) => ({ time: t, value: data.currentPrice * 0.01 })));

    // Current ATR level line
    const currentLevel = chart.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 1,
      lineStyle: 0,
      priceLineVisible: true,
      lastValueVisible: false,
      priceLineWidth: 0,
    });
    currentLevel.setData(times.map((t) => ({ time: t, value: data.atr })));

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
      <div ref={containerRef} className="h-[300px] w-full" />
      <div className="flex gap-4 justify-center mt-2 text-xs">
        {[
          { label: "ATR", color: "#f59e0b" },
          { label: "3% threshold (high)", color: "rgba(239,68,68,0.4)" },
          { label: "1% threshold (normal)", color: "rgba(34,197,94,0.4)" },
          { label: "Current ATR", color: "#f59e0b" },
        ].map(({ label, color }) => (
          <span key={label} className="flex items-center gap-1">
            <span className="w-3 h-0.5 rounded" style={{ backgroundColor: color }} />
            {label}
          </span>
        ))}
      </div>
      <p className="text-xs text-muted-foreground mt-1 text-center">
        True Range history · {data.period}-period ATR = ${data.atr.toFixed(2)} ({data.atrPercent.toFixed(2)}% of price)
        {data.signal && ` · Signal: ${data.signal}`}
      </p>
    </div>
  );
}
