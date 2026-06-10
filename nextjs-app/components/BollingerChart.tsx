"use client";

import { useEffect, useRef } from "react";
import { createChart, IChartApi, Time, LineSeries, AreaSeries } from "lightweight-charts";
import type { OHLCVData } from "@/lib/api";

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
  priceData?: OHLCVData[]; // optional underlying price for context
}

export default function BollingerChart({ sma, upper, lower, bandwidth, percentB, period, numStd, history, priceData }: Props) {
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

    // Upper band
    const upperSeries = chart.addSeries(LineSeries, {
      color: "rgba(239,68,68,0.5)",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    // SMA
    const smaSeries = chart.addSeries(LineSeries, {
      color: "#3b82f6",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    // Lower band
    const lowerSeries = chart.addSeries(LineSeries, {
      color: "rgba(239,68,68,0.5)",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    // Band fill area
    const fillSeries = chart.addSeries(AreaSeries, {
      lineColor: "transparent",
      topColor: "rgba(239,68,68,0.08)",
      bottomColor: "rgba(239,68,68,0.02)",
      lineWidth: 0,
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

    const upperData = history.map((h, i) => ({ time: times[i], value: h.upper }));
    const smaData = history.map((h, i) => ({ time: times[i], value: h.sma }));
    const lowerData = history.map((h, i) => ({ time: times[i], value: h.lower }));
    const fillData = history.map((h, i) => ({ time: times[i], value: h.upper }));

    upperSeries.setData(upperData);
    smaSeries.setData(smaData);
    lowerSeries.setData(lowerData);
    fillSeries.setData(fillData);

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

  return (
    <div>
      <div ref={containerRef} className="h-[250px] w-full" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2 text-xs">
        <div className="flex justify-between">
          <span className="text-muted-foreground">SMA({period})</span>
          <span className="font-medium">${sma.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Upper ({numStd}σ)</span>
          <span className="font-medium text-red-400">${upper.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Lower ({numStd}σ)</span>
          <span className="font-medium text-red-400">${lower.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">%B</span>
          <span className="font-medium">{percentB.toFixed(3)}</span>
        </div>
      </div>
 </div>
  );
}
