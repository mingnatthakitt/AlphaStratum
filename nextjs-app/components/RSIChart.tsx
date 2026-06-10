"use client";

import { useEffect, useRef } from "react";
import { createChart, IChartApi, Time, LineSeries } from "lightweight-charts";

interface Props {
  rsi: number;
  signal: "overbought" | "oversold" | "neutral";
  history: number[];
}

export default function RSIChart({ rsi, signal, history }: Props) {
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
      rightPriceScale: {
        borderColor: "hsl(var(--border))",
        autoScale: true,
      },
      timeScale: {
        borderColor: "hsl(var(--border))",
        timeVisible: true,
        tickMarkFormatter: (time: Time) => {
          const d = new Date(Number(time) * 1000);
          return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
        },
      },
    });

    // RSI line
    const rsiSeries = chart.addSeries(LineSeries, {
      color: "#8b5cf6",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      priceFormat: { precision: 2, decimals: 2 },
    });

    // Overbought (70) and oversold (30) reference lines
    const obSeries = chart.addSeries(LineSeries, {
      color: "rgba(239, 68, 68, 0.4)",
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const osSeries = chart.addSeries(LineSeries, {
      color: "rgba(34, 197, 94, 0.4)",
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Generate trading-day timestamps going back N days from today (skip weekends)
    const now = new Date();
    const times: Time[] = [];
    let count = 0;
    const d = new Date(now);
    while (count < history.length) {
      d.setDate(d.getDate() - 1);
      if (d.getDay() !== 0 && d.getDay() !== 6) {
        times.unshift(Math.floor(d.getTime() / 1000) as Time);
        count++;
      }
    }

    const rsiData = history.map((v, i) => ({ time: times[i], value: v }));
    const obData = history.map((_, i) => ({ time: times[i], value: 70 }));
    const osData = history.map((_, i) => ({ time: times[i], value: 30 }));

    rsiSeries.setData(rsiData);
    obSeries.setData(obData);
    osSeries.setData(osData);

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
  }, [history]);

  const signalColor = signal === "overbought" ? "text-red-500" : signal === "oversold" ? "text-green-500" : "text-yellow-500";

  return (
    <div>
      <div ref={containerRef} className="h-[250px] w-full" />
      <div className="flex items-center justify-between mt-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-2">
          <span className="font-medium">RSI(14): </span>
          <span className={`font-bold ${signalColor}`}>{rsi.toFixed(1)}</span>
          <span className={`text-xs px-1.5 py-0.5 rounded-full ${signal === "overbought" ? "bg-red-500/20 text-red-400" : signal === "oversold" ? "bg-green-500/20 text-green-400" : "bg-yellow-500/20 text-yellow-400"}`}>
            {signal}
          </span>
        </span>
        <span className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-red-400/50" />
            Overbought (70)
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-green-400/50" />
            Oversold (30)
          </span>
        </span>
      </div>
    </div>
  );
}
