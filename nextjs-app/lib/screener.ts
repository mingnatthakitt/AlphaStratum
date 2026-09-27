import type { ScreenerStock } from "./api";

/**
 * Client-side score — must stay in sync with the backend's
 * `services/quant.screener_score`. Sharpe-inspired 0-100:
 * regime (0-40) + momentum (0-40) − volatility penalty (0-20).
 */
export function screenerScore(regime: ScreenerStock["regime"], momentumPct: number, volatilityPct: number): number {
  const regimeScore = regime === "bull" ? 40 : regime === "sideways" ? 20 : 0;
  const momentumScore = Math.max(0, Math.min(40, momentumPct * 2));
  const volPenalty = Math.min(20, Math.max(0, volatilityPct) * 0.4);
  return Math.max(0, Math.round(regimeScore + momentumScore - volPenalty));
}
