"use client";

import { useEffect, useRef } from "react";
import { createChart, IChartApi, Time, HistogramSeries, LineSeries } from "lightweight-charts";

interface Props {
  macd: number;
  signal: number;
  histogram: number;
  macdHistory: number[];
  signalHistory: number[];
  histogramHistory: number[];
}

export default function MACDBarChart({ macd, signal, histogram, macdHistory, signalHistory, histogramHistory }: Props) {
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
      rightPriceScale: { borderColor: "hsl(var(--border))" },
      timeScale: {
        borderColor: "hsl(var(--border))",
        timeVisible: true,
        tickMarkFormatter: (time: Time) => {
          const d = new Date(Number(time) * 1000);
          return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
        },
      },
    });

    // Generate trading-day timestamps going back N days from today (skip weekends)
    const now = new Date();
    const times: Time[] = [];
    let count = 0;
    const d = new Date(now);
    while (count < macdHistory.length) {
      d.setDate(d.getDate() - 1);
      if (d.getDay() !== 0 && d.getDay() !== 6) {
        times.unshift(Math.floor(d.getTime() / 1000) as Time);
        count++;
      }
    }

    const histData = histogramHistory.map((v, i) => ({ time: times[i], value: v, color: v >= 0 ? "#22c55e" : "#ef4444" }));

    // Histogram
    const histSeries = chart.addSeries(HistogramSeries, {
      color: (v: number) => v >= 0 ? "rgba(34,197,94,0.7)" : "rgba(239,68,68,0.7)",
      priceLineVisible: false,
      lastValueVisible: false,
      priceFormat: { precision: 4, decimals: 4 },
    });
    histSeries.setData(histData as any);

    // MACD line
    const macdSeries = chart.addSeries(LineSeries, {
      color: "#3b82f6",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      priceFormat: { precision: 4, decimals: 4 },
    });
    macdSeries.setData(macdHistory.map((v, i) => ({ time: times[i], value: v })));

    // Signal line
    const sigSeries = chart.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: true,
      priceFormat: { precision: 4, decimals: 4 },
    });
    sigSeries.setData(signalHistory.map((v, i) => ({ time: times[i], value: v })));

    chartRef.current = chart;
    chart.timeScale().fitContent();

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
  }, [macdHistory, signalHistory, histogramHistory]);

  const histColor = histogram >= 0 ? "text-green-500" : "text-red-500";

  return (
    <div>
      <div ref={containerRef} className="h-[250px] w-full" />
      <div className="flex items-center justify-between mt-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 rounded-sm bg-blue-500" />
            MACD: <span className="font-medium">{macd.toFixed(3)}</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-amber-500" />
            Signal: <span className="font-medium">{signal.toFixed(3)}</span>
          </span>
          <span className={`flex items-center gap-1 ${histColor}`}>
            <span className="inline-block w-3 h-3 rounded-sm bg-current opacity-70" />
            Histogram: <span className="font-medium">{histogram.toFixed(3)}</span>
          </span>
        </span>
        <span className="text-muted-foreground/60">60-day history</span>
      </div>
    </div>
  );
}
