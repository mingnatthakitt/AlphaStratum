import { describe, expect, it } from "vitest";
import { computeBacktest, type BacktestResult } from "@/lib/backtest";
import type { OHLCVData } from "@/lib/api";

const ohlcv: OHLCVData[] = [
  { date: "2024-01-01", open: 100, high: 102, low: 99, close: 100, volume: 1000 },
  { date: "2024-01-02", open: 101, high: 105, low: 100, close: 110, volume: 1000 },
  { date: "2024-01-03", open: 111, high: 120, low: 110, close: 120, volume: 1000 },
];

describe("computeBacktest", () => {
  it("computes returns from the first bar on/after the entry date", () => {
    const outcome = computeBacktest("AAPL", ohlcv, "2024-01-02", 1000);
    expect(outcome.ok).toBe(true);
    if (!outcome.ok) return;
    const r: BacktestResult = outcome.result;
    expect(r.entryDate).toBe("2024-01-02");
    expect(r.entryPrice).toBe(110);
    expect(r.shares).toBeCloseTo(1000 / 110, 10);
    expect(r.exitPrice).toBe(120);
    expect(r.currentValue).toBeCloseTo((1000 / 110) * 120, 10);
    expect(r.totalReturnPct).toBeCloseTo(((120 - 110) / 110) * 100, 6);
  });

  it("rejects entry dates before and after the data range", () => {
    const early = computeBacktest("AAPL", ohlcv, "2023-12-25", 1000);
    expect(early).toEqual({ ok: false, error: "date-too-early" });
    const late = computeBacktest("AAPL", ohlcv, "2024-02-01", 1000);
    expect(late).toEqual({ ok: false, error: "date-too-late" });
  });

  it("rejects invalid inputs and empty data", () => {
    expect(computeBacktest("", ohlcv, "2024-01-02", 1000)).toEqual({ ok: false, error: "invalid-input" });
    expect(computeBacktest("AAPL", ohlcv, "2024-01-02", 0)).toEqual({ ok: false, error: "invalid-input" });
    expect(computeBacktest("AAPL", ohlcv, "2024-01-02", NaN)).toEqual({ ok: false, error: "invalid-input" });
    expect(computeBacktest("AAPL", [], "2024-01-02", 1000)).toEqual({ ok: false, error: "no-data" });
  });

  it("uses the entry-date bar itself when it is a trading day", () => {
    const outcome = computeBacktest("AAPL", ohlcv, "2024-01-01", 100);
    expect(outcome.ok && outcome.result.entryPrice).toBe(100);
  });
});
