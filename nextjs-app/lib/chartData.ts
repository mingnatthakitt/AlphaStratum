import type { Time } from "lightweight-charts";
import type { OHLCVData } from "./api";

/**
 * Chart-data helpers.
 *
 * Indicator endpoints return real trading dates alongside their values; when
 * they are missing (older cached payloads) we fall back to synthesized
 * trading-day labels. Fabricated dates skip weekends but not market holidays —
 * they are a display fallback only.
 */

export function fabricateTradingDays(count: number, endDate?: string): string[] {
  const out: string[] = [];
  const cursor = endDate ? new Date(endDate) : new Date();
  cursor.setUTCHours(0, 0, 0, 0);
  while (out.length < count) {
    cursor.setUTCDate(cursor.getUTCDate() - 1);
    const day = cursor.getUTCDay();
    if (day === 0 || day === 6) continue;
    out.push(cursor.toISOString().slice(0, 10));
  }
  return out.reverse();
}

/**
 * Align values with dates, tolerating a length mismatch.
 *
 * The previous check was all-or-nothing (`dates.length === values.length`), so a
 * partial payload — 50 real trading dates for 60 indicator values, say —
 * discarded ALL the real dates and re-anchored the whole axis onto fabricated
 * weekdays, leaving every x-position wrong while looking plausible. When the
 * backend does send real dates we now keep them and only fabricate the gap.
 */
function alignDates(values: number[], dates?: string[]): string[] {
  if (!dates || dates.length === 0) return fabricateTradingDays(values.length);
  if (dates.length === values.length) return dates;
  if (dates.length > values.length) {
    // Trim from the front: the trailing dates are the most recent.
    return dates.slice(dates.length - values.length);
  }
  // Fewer dates than values — fabricate only the missing leading labels so the
  // x-axis stays strictly ascending and the real dates still line up.
  const fabricated = fabricateTradingDays(values.length - dates.length);
  return [...fabricated, ...dates];
}

export function toLineData(
  values: number[],
  dates?: string[],
): { time: Time; value: number }[] {
  const effectiveDates = alignDates(values, dates);
  return values.map((value, i) => ({ time: effectiveDates[i] as Time, value }));
}

export function toHistogramData(
  values: number[],
  dates?: string[],
): { time: Time; value: number; color: string }[] {
  const effectiveDates = alignDates(values, dates);
  return values.map((value, i) => ({
    time: effectiveDates[i] as Time,
    value,
    color: value >= 0 ? "rgba(34, 197, 94, 0.6)" : "rgba(239, 68, 68, 0.6)",
  }));
}

/**
 * Assign each settled fetch result back to its own symbol.
 * `Promise.allSettled` preserves input order, so we must NOT re-index after
 * filtering — map results positionally instead.
 */
export function zipSettled<T, R>(
  symbols: string[],
  settled: PromiseSettledResult<T>[],
  map: (value: T, symbol: string) => R | null,
): Map<string, R> {
  const out = new Map<string, R>();
  settled.forEach((result, i) => {
    const symbol = symbols[i];
    if (result.status === "fulfilled") {
      const mapped = map(result.value, symbol);
      if (mapped !== null) out.set(symbol, mapped);
    }
  });
  return out;
}

/**
 * Return the URL only if it is a plain http(s) link, else null.
 *
 * Citation URLs are extracted from LLM output grounded in untrusted sources
 * (news headlines, SEC filings), and React does not block `javascript:` in an
 * `href` — so a prompt-injected document could otherwise yield a live link in
 * the Sources footer.
 */
export function safeExternalUrl(url: string | undefined | null): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    return parsed.toString();
  } catch {
    return null; // not an absolute URL
  }
}
