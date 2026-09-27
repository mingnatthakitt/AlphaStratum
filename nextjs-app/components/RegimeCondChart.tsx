"use client";

import { useEffect, useMemo, useRef } from "react";
import type { MonteCarloRegimeCondResult } from "@/lib/api";
import {
  AMBER_FAN,
  BLUE_FAN,
  ChartLegend,
  GREEN_FAN,
  RED_FAN,
  createFanSeries,
  safeRemoveSeries,
  useChart,
} from "@/hooks/useChart";

interface Props {
  data: MonteCarloRegimeCondResult;
}

export default function RegimeCondChart({ data }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chart = useChart(containerRef);

  // Real forecast dates from the backend (fall back to fabrication in the helper).
  const forecastDates = useMemo(
    () => data.regimeProbabilities.map((r) => r.date),
    [data.regimeProbabilities],
  );

  useEffect(() => {
    if (!chart) return;

    // Blended fan is the headline; the three regime fans are faint context.
    const blended = createFanSeries(chart, forecastDates, data.blended, BLUE_FAN, true);
    const bull = createFanSeries(chart, forecastDates, data.fans.bull, GREEN_FAN);
    const bear = createFanSeries(chart, forecastDates, data.fans.bear, RED_FAN);
    const sideways = createFanSeries(chart, forecastDates, data.fans.sideways, AMBER_FAN);
    const all = [...blended, ...bull, ...bear, ...sideways];

    chart.timeScale().fitContent();
    return () => {
      for (const s of all) safeRemoveSeries(chart, s);
    };
  }, [chart, data, forecastDates]);

  return (
    <div>
      <div ref={containerRef} className="h-[400px] w-full" />
      <div className="flex justify-center mt-2">
        <ChartLegend
          items={[
            { label: "Blended", color: BLUE_FAN.median },
            { label: "Bull fan", color: GREEN_FAN.median },
            { label: "Bear fan", color: RED_FAN.median },
            { label: "Sideways fan", color: AMBER_FAN.median },
          ]}
        />
      </div>
      <p className="text-xs text-muted-foreground mt-1 text-center">
        Last price: ${data.lastPrice.toFixed(2)} · {data.horizon} day horizon · GARCH(1,1) volatility ·
        current regime: <span className="capitalize font-medium">{data.currentRegime}</span>
      </p>
      <p className="text-xs text-muted-foreground/60 text-center mt-0.5">
        Three regime-conditional GBM fans blended by Markov n-step probabilities — regime weights converge
        to the stationary distribution as the horizon grows.
      </p>
    </div>
  );
}
