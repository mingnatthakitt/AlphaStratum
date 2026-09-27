import { describe, expect, it } from "vitest";
import { fabricateTradingDays, toLineData, toHistogramData, zipSettled } from "@/lib/chartData";

describe("fabricateTradingDays", () => {
  it("skips weekends walking backwards", () => {
    // 2024-01-08 is a Monday → previous trading days: Fri 05, Thu 04
    const dates = fabricateTradingDays(2, "2024-01-08");
    expect(dates).toEqual(["2024-01-04", "2024-01-05"]);
  });

  it("returns ascending order and the requested count", () => {
    const dates = fabricateTradingDays(10, "2024-01-31");
    expect(dates).toHaveLength(10);
    for (let i = 1; i < dates.length; i++) {
      expect(dates[i] > dates[i - 1]).toBe(true);
      const day = new Date(dates[i]).getUTCDay();
      expect(day).not.toBe(0);
      expect(day).not.toBe(6);
    }
  });
});

describe("toLineData", () => {
  it("pairs values with provided dates when lengths match", () => {
    const data = toLineData([1, 2], ["2024-01-01", "2024-01-02"]);
    expect(data).toEqual([
      { time: "2024-01-01", value: 1 },
      { time: "2024-01-02", value: 2 },
    ]);
  });

  it("falls back to fabricated dates on length mismatch", () => {
    const data = toLineData([1, 2, 3], ["2024-01-01"]);
    expect(data).toHaveLength(3);
    expect(data[0].time).toBeDefined();
  });
});

describe("toHistogramData", () => {
  it("colors positive and negative values", () => {
    const data = toHistogramData([2, -3], ["2024-01-01", "2024-01-02"]);
    expect(data[0].color).toContain("34, 197, 94");
    expect(data[1].color).toContain("239, 68, 68");
  });
});

describe("zipSettled", () => {
  it("attributes results to their own symbol even after failures", () => {
    // The regression this guards against: re-indexing after filtering
    // attributed B's data to C when A failed.
    const settled = [
      { status: "rejected" as const, reason: new Error("boom") },
      { status: "fulfilled" as const, value: { name: "B-data" } },
      { status: "fulfilled" as const, value: { name: "C-data" } },
    ];
    const map = zipSettled(["A", "B", "C"], settled, (value) => value);
    expect(map.has("A")).toBe(false);
    expect(map.get("B")).toEqual({ name: "B-data" });
    expect(map.get("C")).toEqual({ name: "C-data" });
  });

  it("drops null mappings", () => {
    const settled = [{ status: "fulfilled" as const, value: null }];
    const map = zipSettled(["A"], settled, () => null);
    expect(map.size).toBe(0);
  });
});
