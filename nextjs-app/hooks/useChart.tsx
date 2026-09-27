"use client";

/**
 * Shared lightweight-charts lifecycle.
 *
 * One ResizeObserver-free chart per container (`autoSize: true` handles
 * resizing), theme-aware colors resolved from CSS custom properties, and
 * automatic re-creation when the theme changes. Series are added by callers
 * in their own effects keyed on the returned chart instance.
 */
import { useEffect, useState, type RefObject } from "react";
import {
  ISeriesApi,
  LineSeries,
  ChartOptions,
  DeepPartial,
  IChartApi,
  LineStyle,
  createChart,
  type TimeChartOptions,
} from "lightweight-charts";
import { useTheme } from "next-themes";
import { toLineData } from "@/lib/chartData";
import { cssColor } from "@/lib/chartColors";

export interface ChartColors {
  text: string;
  grid: string;
  border: string;
  background: string;
  muted: string;
  foreground: string;
  green: string;
  red: string;
}

export function resolveChartColors(): ChartColors {
  return {
    text: cssColor("--muted-foreground", "hsl(215 16% 47%)"),
    grid: cssColor("--border", "hsl(214 32% 91%)"),
    border: cssColor("--border", "hsl(214 32% 91%)"),
    background: "transparent",
    muted: cssColor("--muted", "hsl(210 40% 96%)"),
    foreground: cssColor("--foreground", "hsl(222 84% 5%)"),
    green: "rgb(34, 197, 94)",
    red: "rgb(239, 68, 68)",
  };
}

export function baseChartOptions(colors: ChartColors): DeepPartial<TimeChartOptions> {
  return {
    autoSize: true,
    background: { color: colors.background },
    layout: {
      background: { color: colors.background },
      textColor: colors.text,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: colors.grid },
      horzLines: { color: colors.grid },
    },
    crosshair: {
      mode: 1,
      vertLine: { color: colors.border, labelBackgroundColor: colors.foreground },
      horzLine: { color: colors.border, labelBackgroundColor: colors.foreground },
    },
    rightPriceScale: { borderColor: colors.border },
    timeScale: { borderColor: colors.border },
  } as DeepPartial<TimeChartOptions>;
}

/**
 * Creates and owns a chart instance bound to `containerRef`.
 * Recreates when the resolved theme changes (colors are baked into the canvas).
 * Returns the instance via state so dependent effects re-run once it exists.
 */
const disposedCharts = new WeakSet<IChartApi>();

export function useChart(
  containerRef: RefObject<HTMLDivElement | null>,
  optionsFactory: (colors: ChartColors) => DeepPartial<ChartOptions> = (colors) =>
    baseChartOptions(colors),
): IChartApi | null {
  const [chart, setChart] = useState<IChartApi | null>(null);
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // next-themes writes the `dark` class from its own provider effect, and
    // child effects run BEFORE parent effects — so sampling the DOM here can
    // read the *previous* palette and paint light-mode axis colors inside a
    // dark UI. Defer one frame so the class has been applied.
    let instance: IChartApi | null = null;
    const frame = requestAnimationFrame(() => {
      const colors = resolveChartColors();
      instance = createChart(container, {
        ...baseChartOptions(colors),
        ...optionsFactory(colors),
      });
      setChart(instance);
    });

    return () => {
      cancelAnimationFrame(frame);
      if (instance) {
        disposedCharts.add(instance);
        instance.remove();
      }
      setChart(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerRef, resolvedTheme]);

  return chart;
}

/**
 * Series cleanup that tolerates the chart being already disposed.
 *
 * React runs effect cleanups in hook-definition order: useChart's own cleanup
 * (chart removal) runs BEFORE a data-effect's cleanup that calls
 * chart.removeSeries, which throws on a disposed chart (e.g. on unmount and
 * on theme toggles).
 */
export function safeRemoveSeries(chart: IChartApi | null, series: unknown): void {
  if (!chart || disposedCharts.has(chart)) return;
  try {
    chart.removeSeries(series as never);
  } catch {
    // series already torn down with the chart — nothing to do
  }
}

/** Standard legend row for multi-series charts. */
export function ChartLegend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  );
}

export interface PercentileFan {
  p5: number[];
  p25: number[];
  p50: number[];
  p75: number[];
  p95: number[];
}

export interface FanPalette {
  median: string;
  quartile: string;
  tail: string;
}

export const BLUE_FAN: FanPalette = { median: "#3b82f6", quartile: "#60a5fa", tail: "#94a3b8" };
export const GREEN_FAN: FanPalette = { median: "#22c55e", quartile: "#4ade80", tail: "#86efac" };
export const RED_FAN: FanPalette = { median: "#ef4444", quartile: "#f87171", tail: "#fca5a5" };
export const AMBER_FAN: FanPalette = { median: "#f59e0b", quartile: "#fbbf24", tail: "#fcd34d" };

/** Adds a 5-line percentile fan (p5…p95) to a chart. Returns the series for cleanup. */
export function createFanSeries(
  chart: IChartApi,
  dates: string[] | undefined,
  fan: PercentileFan,
  palette: FanPalette = BLUE_FAN,
  titles = false,
): ISeriesApi<"Line">[] {
  const defs: { key: keyof PercentileFan; color: string; style: LineStyle; width: 1 | 2; title: string }[] = [
    { key: "p5", color: palette.tail, style: LineStyle.LargeDashed, width: 1, title: "5th" },
    { key: "p25", color: palette.quartile, style: LineStyle.Dashed, width: 1, title: "25th" },
    { key: "p50", color: palette.median, style: LineStyle.Solid, width: 2, title: "Median" },
    { key: "p75", color: palette.quartile, style: LineStyle.Dashed, width: 1, title: "75th" },
    { key: "p95", color: palette.tail, style: LineStyle.LargeDashed, width: 1, title: "95th" },
  ];
  return defs.map((def) => {
    const series = chart.addSeries(LineSeries, {
      color: def.color,
      lineWidth: def.width,
      lineStyle: def.style,
      title: titles ? def.title : undefined,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    series.setData(toLineData(fan[def.key], dates));
    return series;
  });
}
