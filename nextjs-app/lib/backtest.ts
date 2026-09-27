import type { OHLCVData } from "./api";

export interface BacktestResult {
  symbol: string;
  entryDate: string;
  exitDate: string;
  investment: number;
  shares: number;
  entryPrice: number;
  exitPrice: number;
  currentValue: number;
  totalReturn: number;
  totalReturnPct: number;
  priceChangePct: number;
}

export type BacktestError = "no-data" | "date-too-early" | "date-too-late" | "invalid-input";

/**
 * Hypothetical investment calculator over daily OHLCV.
 * Pure function so the UI only handles fetching and display.
 */
export function computeBacktest(
  symbol: string,
  ohlcv: OHLCVData[],
  entryDate: string,
  investment: number,
): { ok: true; result: BacktestResult } | { ok: false; error: BacktestError } {
  if (!symbol || !entryDate || !Number.isFinite(investment) || investment <= 0) {
    return { ok: false, error: "invalid-input" };
  }
  if (ohlcv.length === 0) return { ok: false, error: "no-data" };

  const first = ohlcv[0].date;
  const last = ohlcv[ohlcv.length - 1].date;
  if (entryDate < first) return { ok: false, error: "date-too-early" };
  if (entryDate > last) return { ok: false, error: "date-too-late" };

  // First trading day on or after the requested entry date.
  const entryBar = ohlcv.find((d) => d.date >= entryDate);
  if (!entryBar || entryBar.close <= 0) return { ok: false, error: "no-data" };

  const exitBar = ohlcv[ohlcv.length - 1];
  const shares = investment / entryBar.close;
  const currentValue = shares * exitBar.close;
  const totalReturn = currentValue - investment;

  return {
    ok: true,
    result: {
      symbol,
      entryDate: entryBar.date,
      exitDate: last,
      investment,
      shares,
      entryPrice: entryBar.close,
      exitPrice: exitBar.close,
      currentValue,
      totalReturn,
      totalReturnPct: (totalReturn / investment) * 100,
      priceChangePct: ((exitBar.close - entryBar.close) / entryBar.close) * 100,
    },
  };
}
