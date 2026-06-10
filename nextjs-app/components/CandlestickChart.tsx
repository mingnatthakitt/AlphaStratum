"use client";

import { useEffect, useRef } from "react";
import { createChart, IChartApi, Time, CandlestickSeries, AreaSeries } from "lightweight-charts";
import type { OHLCVData } from "@/lib/api";

interface Props {
  data: OHLCVData[];
  symbol: string;
  view?: "candle" | "area";
}

export default function CandlestickChart({ data, symbol, view = "candle" }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<{ candle: any; area: any } | null>(null);

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
      lastValueVisible: true,
    });

    const chartData = data.map((d) => ({
      time: d.date as Time,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }));
    const areaData = data.map((d) => ({ time: d.date as Time, value: d.close }));

    candlestickSeries.setData(chartData);
    areaSeries.setData(areaData);

    candleSeriesRef.current = { candle: candlestickSeries, area: areaSeries };

    if (view === "area") {
      candlestickSeries.applyOptions({ visible: false });
    } else {
      areaSeries.applyOptions({ visible: false });
    }

    chart.timeScale().fitContent();
    chartRef.current = chart;

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
  }, [data]);

  // Toggle candlestick vs area view
  useEffect(() => {
    if (!chartRef.current) return;
    const refs = candleSeriesRef.current as { candle: any; area: any } | null;
    if (!refs) return;
    const { candle, area } = refs;
    if (view === "area") {
      candle.applyOptions({ visible: false });
      area.applyOptions({ visible: true });
    } else {
      candle.applyOptions({ visible: true });
      area.applyOptions({ visible: false });
    }
  }, [view]);

  return (
    <div>
      <div ref={containerRef} className="h-[400px] w-full" />
      <p className="text-xs text-muted-foreground mt-2 text-center">
        Data sourced from Yahoo Finance — {data.length} trading days shown
      </p>
    </div>
  );
}