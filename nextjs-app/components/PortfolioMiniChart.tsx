"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createChart, IChartApi, Time, AreaSeries } from "lightweight-charts";
import { useQuery } from "@tanstack/react-query";
import { stockApi } from "@/lib/api";
import { TrendingUp, TrendingDown } from "lucide-react";

interface Props {
  symbol: string;
  shares: number;
  avgCost: number;
}

type Period = "1mo" | "3mo" | "6mo" | "1y";
const PERIOD_DAYS: Record<Period, number> = { "1mo": 22, "3mo": 63, "6mo": 126, "1y": 252 };

export default function PortfolioMiniChart({ symbol, shares, avgCost }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [period, setPeriod] = useState<Period>("3mo");

  const tickerEnabled = !!symbol && symbol.length > 0;

  const { data: tickerData } = useQuery({
    queryKey: ["ticker", symbol],
    queryFn: () => stockApi.getTicker(symbol),
    enabled: tickerEnabled,
    staleTime: 60_000,
  });

  const ohlcv = useMemo(() => tickerData?.data?.ohlcv ?? [], [tickerData]);
  const sliced = useMemo(
    () => ohlcv.slice(-Math.min(PERIOD_DAYS[period], ohlcv.length)),
    [ohlcv, period]
  );

  const firstClose = sliced[0]?.close ?? 0;
  const lastClose = sliced[sliced.length - 1]?.close ?? 0;
  const change = lastClose - firstClose;
  const changePct = firstClose > 0 ? (change / firstClose) * 100 : 0;

  const ohlcvLength = ohlcv.length;
  const slicedSig = `${sliced[0]?.date ?? ""}-${sliced[sliced.length - 1]?.date ?? ""}`;

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: "transparent" },
        textColor: "#e5e5e5",
      },
      grid: { vertLines: { color: "transparent" }, horzLines: { color: "transparent" } },
      crosshair: { mode: 1 },
      timeScale: {
        borderVisible: true,
        borderColor: "rgba(255,255,255,0.15)",
        tickMarkDecoration: "inside",
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.1, bottom: 0.1 } },
      height: 120,
    });

    const areaSeries = chart.addSeries(AreaSeries, {
      lineColor: "#3b82f6",
      topColor: "rgba(59, 130, 246, 0.2)",
      bottomColor: "rgba(59, 130, 246, 0.0)",
      lineWidth: 1.5,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const entrySeries = chart.addSeries(AreaSeries, {
      lineColor: "rgba(251, 191, 36, 0.8)",
      topColor: "rgba(251, 191, 36, 0.0)",
      bottomColor: "rgba(251, 191, 36, 0.0)",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    if (ohlcvLength > 0) {
      const areaData = sliced.map((d) => ({ time: d.date as Time, value: d.close }));
      const entryData = sliced.map((d) => ({ time: d.date as Time, value: avgCost }));
      areaSeries.setData(areaData);
      entrySeries.setData(entryData);
      chart.timeScale().fitContent();
    }

    chartRef.current = chart;

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [avgCost, ohlcvLength, slicedSig, sliced]);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between px-1">
        <div className="flex gap-1">
          {(Object.keys(PERIOD_DAYS) as Period[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                period === p ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <div ref={containerRef} className="w-full" style={{ height: 120 }} />

      <div className="flex items-center justify-between px-1 text-[10px] text-muted-foreground">
        <span>Entry: <span className="font-medium text-amber-400">${avgCost.toFixed(2)}</span></span>
        <span className={changePct >= 0 ? "text-green-500" : "text-red-400"}>
          {changePct >= 0 ? <TrendingUp className="inline w-3 h-3" /> : <TrendingDown className="inline w-3 h-3" />}
          {" "}{changePct >= 0 ? "+" : ""}{changePct.toFixed(1)}%
        </span>
      </div>
    </div>
  );
}