"use client";

import { useEffect, useRef } from "react";
import { createChart, IChartApi, Time, AreaSeries } from "lightweight-charts";
import type { GarchResult } from "@/lib/api";

interface Props {
  data: GarchResult;
}

export default function GarchChart({ data }: Props) {
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

    const volSeries = chart.addSeries(AreaSeries, {
      topColor: "#f59e0b",
      bottomColor: "rgba(245, 158, 11, 0.1)",
      lineColor: "#f59e0b",
      lineWidth: 2,
    });

    // Use Unix timestamps (seconds) for time axis — reliable, no string parsing issues
    const times: Time[] = data.forecastDates.map((d) => {
      const [year, month, day] = d.split("-").map(Number);
      return Math.floor(new Date(year, month - 1, day).getTime() / 1000) as Time;
    });

    volSeries.setData(data.forecast.map((v, i) => ({ time: times[i], value: v })));

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
      <p className="text-xs text-muted-foreground mt-2 text-center">
        GARCH(1,1) daily volatility forecast · Current: {(data.currentVol * 100).toFixed(2)}% annualized
      </p>
    </div>
  );
}