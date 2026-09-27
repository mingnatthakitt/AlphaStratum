"use client";

import { useEffect, useRef } from "react";
import type { MonteCarloResult } from "@/lib/api";
import { BLUE_FAN, ChartLegend, createFanSeries, safeRemoveSeries, useChart } from "@/hooks/useChart";

interface Props {
  data: MonteCarloResult;
}

export default function MonteCarloChart({ data }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chart = useChart(containerRef);

  useEffect(() => {
    if (!chart) return;
    const series = createFanSeries(chart, data.forecastDates, data.percentiles, BLUE_FAN, true);
    chart.timeScale().fitContent();
    return () => {
      for (const s of series) safeRemoveSeries(chart, s);
    };
  }, [chart, data]);

  return (
    <div>
      <div ref={containerRef} className="h-[400px] w-full" />
      <div className="flex justify-center mt-2">
        <ChartLegend
          items={[
            { label: "95th pct", color: BLUE_FAN.tail },
            { label: "75th pct", color: BLUE_FAN.quartile },
            { label: "Median", color: BLUE_FAN.median },
            { label: "25th pct", color: BLUE_FAN.quartile },
            { label: "5th pct", color: BLUE_FAN.tail },
          ]}
        />
      </div>
      <p className="text-xs text-muted-foreground mt-1 text-center">
        {data.paths.length.toLocaleString()} Monte Carlo paths · Last price: ${data.lastPrice.toFixed(2)}
        {data.horizon && ` · ${data.horizon} day horizon`}
        {data.currentRegime && (
          <span>
            {" "}
            · <span className="capitalize font-medium">{data.currentRegime}</span> regime
            {data.regimeAdjusted ? " (drift adjusted)" : ""}
          </span>
        )}
      </p>
      <p className="text-xs text-muted-foreground/60 text-center mt-0.5">
        Fan bands show 5th–95th percentile. Real prices can exceed p95 — a black swan can blow past it entirely.
      </p>
    </div>
  );
}
