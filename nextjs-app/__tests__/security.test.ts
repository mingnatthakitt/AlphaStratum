/**
 * Regression tests for the third and fourth review rounds (frontend).
 *
 * Covers: CSV formula injection, citation-URL scheme validation, partial
 * date alignment in chart data, and backend-failure diagnostics.
 */
import { describe, expect, it } from "vitest";
import { csvField, csvRow, toCsv } from "@/lib/csv";
import { safeExternalUrl, toLineData, toHistogramData, fabricateTradingDays } from "@/lib/chartData";
import { apiErrorMessage } from "@/lib/api";

describe("csv escaping", () => {
  it("defuses spreadsheet formula injection", () => {
    // The backend symbol pattern explicitly permits a leading '=', so a lot
    // named "=1+1" would otherwise be evaluated on open.
    expect(csvField("=1+1")).toBe("'=1+1");
    expect(csvField("+SUM(A1)")).toBe("'+SUM(A1)");
    expect(csvField("-2+3")).toBe("'-2+3");
    expect(csvField("@import")).toBe("'@import");
  });

  it("leaves ordinary tickers untouched", () => {
    expect(csvField("AAPL")).toBe("AAPL");
    expect(csvField("BRK-B")).toBe("BRK-B");
    expect(csvField("^GSPC")).toBe("^GSPC");
    expect(csvField("RDS.A")).toBe("RDS.A");
    expect(csvField(1234.5)).toBe("1234.5");
  });

  it("quotes fields containing delimiters, quotes or newlines", () => {
    expect(csvField("a,b")).toBe('"a,b"');
    expect(csvField('say "hi"')).toBe('"say ""hi"""');
    expect(csvField("line1\nline2")).toBe('"line1\nline2"');
  });

  it("escapes each field in a row", () => {
    expect(csvRow(["AAPL", 1.5])).toBe("AAPL,1.5");
    expect(csvRow(["=cmd", "a,b"])).toBe("'=cmd,\"a,b\"");
  });

  it("joins rows with newlines", () => {
    expect(toCsv([["A", "B"], ["1", "2"]])).toBe("A,B\n1,2");
  });
});

describe("safeExternalUrl", () => {
  it("allows http and https", () => {
    expect(safeExternalUrl("https://example.com/a")).toBe("https://example.com/a");
    expect(safeExternalUrl("http://example.com")).toBe("http://example.com/");
  });

  it("rejects javascript: URLs from prompt-injected content", () => {
    // React does not block javascript: in href — this is the whole point.
    expect(safeExternalUrl("javascript:alert(1)")).toBeNull();
    expect(safeExternalUrl("JavaScript:alert(1)")).toBeNull();
    expect(safeExternalUrl("  javascript:alert(1)")).toBeNull();
  });

  it("rejects other dangerous or non-navigable schemes", () => {
    expect(safeExternalUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeExternalUrl("vbscript:msgbox(1)")).toBeNull();
    expect(safeExternalUrl("file:///etc/passwd")).toBeNull();
  });

  it("rejects relative and empty values", () => {
    expect(safeExternalUrl("/models/AAPL")).toBeNull();
    expect(safeExternalUrl("not a url")).toBeNull();
    expect(safeExternalUrl("")).toBeNull();
    expect(safeExternalUrl(undefined)).toBeNull();
    expect(safeExternalUrl(null)).toBeNull();
  });
});

describe("chart date alignment", () => {
  const values = [1, 2, 3, 4, 5];

  it("uses real dates when the lengths match", () => {
    const dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"];
    const out = toLineData(values, dates);
    expect(out.map((d) => d.time)).toEqual(dates);
  });

  it("keeps real dates on a partial payload instead of discarding them", () => {
    // Regression: the old all-or-nothing length check threw away every real
    // date and re-anchored the axis on fabricated weekdays.
    const dates = ["2024-03-01", "2024-03-04", "2024-03-05"];
    const out = toLineData(values, dates);
    expect(out).toHaveLength(values.length);
    // The three real dates must still appear, in order, at the tail.
    const times = out.map((d) => d.time as string);
    expect(times.slice(-3)).toEqual(dates);
  });

  it("trims surplus dates from the front", () => {
    const dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"];
    const out = toLineData(values, dates);
    expect(out.map((d) => d.time as string)).toEqual(dates.slice(1));
  });

  it("falls back to fabricated weekdays when no dates are supplied", () => {
    const out = toLineData(values);
    expect(out).toHaveLength(values.length);
    const times = out.map((d) => d.time as string);
    // Ascending, and no weekends.
    expect([...times].sort()).toEqual(times);
    for (const t of times) {
      const day = new Date(`${t}T00:00:00Z`).getUTCDay();
      expect(day).not.toBe(0);
      expect(day).not.toBe(6);
    }
  });

  it("applies the same alignment to histogram data", () => {
    const out = toHistogramData([1, -1, 2], ["2024-02-01", "2024-02-02"]);
    expect(out).toHaveLength(3);
    expect(out.slice(-2).map((d) => d.time as string)).toEqual(["2024-02-01", "2024-02-02"]);
  });

  it("fabricates exactly the requested number of ascending weekdays", () => {
    const days = fabricateTradingDays(10, "2024-12-31");
    expect(days).toHaveLength(10);
    expect([...days].sort()).toEqual(days);
    expect(days[9] <= "2024-12-31").toBe(true);
  });
});

// ── backend failure diagnostics ──────────────────────────────────────────────
// The backend fails closed, so a misconfigured deploy returns 503 on every
// route. The UI has to say THAT, not "the data provider may be rate-limited"
// — otherwise the operator debugs the wrong thing entirely.
describe("apiErrorMessage", () => {
  const fallback = "Couldn't load data — the market data provider may be rate-limited.";

  const errWith = (status: number, code?: string) => {
    const e: Record<string, unknown> = { isAxiosError: true };
    if (status) e.response = { status };
    if (code) e.code = code;
    return e;
  };

  it("names the missing AUTH_PASSWORD on 503 rather than blaming the data provider", () => {
    const msg = apiErrorMessage(errWith(503), fallback);
    expect(msg).toMatch(/AUTH_PASSWORD/);
    expect(msg).not.toBe(fallback);
  });

  it("points at the key mismatch on 401", () => {
    expect(apiErrorMessage(errWith(401), fallback)).toMatch(/AUTH_KEY/);
  });

  it("explains the throttle on 429", () => {
    expect(apiErrorMessage(errWith(429), fallback)).toMatch(/Too many failed sign-in/);
  });

  it("reports 5xx as a server error with the status", () => {
    expect(apiErrorMessage(errWith(500), fallback)).toMatch(/HTTP 500/);
  });

  it("distinguishes a timeout from other network failures", () => {
    expect(apiErrorMessage(errWith(0, "ECONNABORTED"), fallback)).toMatch(/timed out/);
  });

  it("reports an unreachable backend when there is no response", () => {
    expect(apiErrorMessage(errWith(0), fallback)).toMatch(/Couldn't reach the backend/);
  });

  it("falls back for unrecognised failures and non-axios errors", () => {
    expect(apiErrorMessage(errWith(404), fallback)).toBe(fallback);
    expect(apiErrorMessage(new Error("boom"), fallback)).toBe(fallback);
    expect(apiErrorMessage(undefined, fallback)).toBe(fallback);
  });
});
