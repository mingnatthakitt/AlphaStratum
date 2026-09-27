import { describe, expect, it } from "vitest";
import { screenerScore } from "@/lib/screener";
import type { ScreenerStock } from "@/lib/api";

const stock = (regime: ScreenerStock["regime"]): ScreenerStock => ({
  symbol: "TEST",
  name: "Test",
  price: 100,
  change: 0,
  regime,
  momentum: 0,
  volatility: 0,
  score: 0,
  probBull: 0,
  probBear: 0,
  probSideways: 0,
});

describe("screenerScore", () => {
  it("matches the documented formula", () => {
    // bull (40) + momentum 10 → 20 points, vol 10 → penalty 4
    expect(screenerScore("bull", 10, 10)).toBe(56);
    expect(screenerScore("sideways", 10, 10)).toBe(36);
    expect(screenerScore("bear", 10, 10)).toBe(16);
  });

  it("clamps momentum and volatility contributions", () => {
    expect(screenerScore("bull", 100, 0)).toBe(80); // momentum capped at 40
    expect(screenerScore("bull", 0, 100)).toBe(20); // vol penalty capped at 20
    expect(screenerScore("bear", -100, 100)).toBe(0); // floor 0
  });

  it("rewards low-volatility bull regimes over high-volatility bear ones", () => {
    expect(screenerScore("bull", 5, 10)).toBeGreaterThan(screenerScore("bear", 5, 40));
  });

  it("is used with the same regime type the API returns", () => {
    const s = stock("sideways");
    expect(screenerScore(s.regime, 0, 0)).toBe(20);
  });
});
