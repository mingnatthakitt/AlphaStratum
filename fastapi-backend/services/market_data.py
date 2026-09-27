"""
Shared market-data access layer.

All Yahoo Finance reads go through this module so that:
- there is exactly one HTTP session and retry policy,
- raw candle/closes responses are cached in-process with a short TTL
  (model *results* have their own 15-minute cache in ``cache.py``),
- multi-symbol series are aligned by **date**, never by array index —
  Yahoo histories differ in length and listing dates between symbols, so
  index-based truncation silently compares different trading days.

Dates are derived from Yahoo's bar timestamps in UTC. For US equities the
daily bar timestamp is the session start (13:30 UTC), so the UTC calendar
date is the correct trading date regardless of the server's local timezone.
"""
from __future__ import annotations

import copy
import logging
import re
import threading
import time
from datetime import UTC, datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

import numpy as np
import requests

logger = logging.getLogger(__name__)

# Intraday candle times are displayed in market time (US/Eastern) regardless
# of the server's local timezone.
ET = ZoneInfo("America/New_York")

# Ticker symbols: letters/digits plus the punctuation Yahoo uses
# (BRK.B, BF-B, ^GSPC, ...). Max 10 chars — mirrors the DB VARCHAR(10).
SYMBOL_RE = re.compile(r"^[A-Z0-9.\-^=]{1,10}$")


class SymbolError(ValueError):
    """Raised when a symbol fails normalization/validation."""


def normalize_symbol(symbol: str) -> str:
    """Uppercase/strip a symbol; raise SymbolError if it is not a plausible ticker."""
    normalized = (symbol or "").strip().upper()
    if not SYMBOL_RE.match(normalized):
        raise SymbolError(f"Invalid symbol: {symbol!r}")
    return normalized


# ── Yahoo Finance HTTP session ────────────────────────────────────────────────

_session = requests.Session()
_session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
REQUEST_TIMEOUT = 15

# ── In-process TTL cache ──────────────────────────────────────────────────────
# Keyed by (symbol, interval, range). Small bounds: entries are a few hundred
# KB at most (1y daily), and we cap the number of keys.

_CACHE_TTL_SECONDS = 300  # 5 minutes
_CACHE_MAX_ENTRIES = 512
# Keyed by (fetcher, symbol, interval, range_) so two fetchers can never
# collide on the same symbol/interval pair.
CacheKey = tuple[str, str, str, str]

_cache: dict[CacheKey, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _cache_get(key: CacheKey):
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > _CACHE_TTL_SECONDS:
            del _cache[key]
            return None
        return value


def _cache_set(key: CacheKey, value) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            # Drop the oldest half rather than growing without bound.
            for k in sorted(_cache, key=lambda k: _cache[k][0])[: _CACHE_MAX_ENTRIES // 2]:
                del _cache[k]
        _cache[key] = (time.monotonic(), value)


# Per-key locks for single-flight: without these, every concurrent miss on a
# cold (or just-expired) key issues its own upstream request. The lock is held
# only around the load, never the network call, so different symbols still
# fetch in parallel.
_key_locks: dict[CacheKey, threading.Lock] = {}


def _key_lock(key: CacheKey) -> threading.Lock:
    with _cache_lock:
        lock = _key_locks.get(key)
        if lock is None:
            if len(_key_locks) >= _CACHE_MAX_ENTRIES:
                _key_locks.clear()
            lock = threading.Lock()
            _key_locks[key] = lock
        return lock


def _copy_value(value):
    """
    Defensive copy of a cached value.

    Cached objects are shared by every concurrent caller; a caller that mutates
    one in place (e.g. `row["close"] = x` or `closes *= 2`) would corrupt the
    cache for everyone else. Handing out copies makes that impossible.
    """
    if isinstance(value, ChartResult):
        return ChartResult(
            ohlcv=[dict(row) for row in value.ohlcv],
            meta=dict(value.meta),
            dates=list(value.dates),
        )
    if isinstance(value, ClosesSeries):
        return ClosesSeries(dates=list(value.dates), closes=value.closes.copy())
    if isinstance(value, dict):
        return copy.deepcopy(value)
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
        _key_locks.clear()


# ── Result types ──────────────────────────────────────────────────────────────

class ChartResult(NamedTuple):
    """Daily (or intraday) OHLCV rows plus per-row dates and Yahoo meta."""
    ohlcv: list[dict]
    meta: dict
    dates: list[str]  # ISO yyyy-mm-dd, aligned with ohlcv


class ClosesSeries(NamedTuple):
    """Closing prices with their trading dates (None closes dropped in tandem)."""
    dates: list[str]
    closes: np.ndarray


# ── Fetchers ──────────────────────────────────────────────────────────────────

def _request_chart(symbol: str, interval: str, range_: str) -> dict | None:
    """Call the Yahoo chart API and return the raw `result[0]` dict, or None."""
    try:
        resp = _session.get(
            CHART_URL.format(symbol=symbol),
            params={"interval": interval, "range": range_},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        results = resp.json().get("chart", {}).get("result")
        if not results:
            return None
        return results[0]
    except Exception:
        logger.debug("Yahoo chart request failed", exc_info=True, extra={"symbol": symbol})
        return None


def _iso_date(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d")


def fetch_chart(symbol: str, interval: str = "1d", range_: str = "1y") -> ChartResult | None:
    """
    Fetch OHLCV rows + metadata for a symbol. Returns None on any failure
    (network, bad symbol, no data). Rows with a missing close are dropped;
    `dates` stays aligned with `ohlcv`.
    """
    symbol = normalize_symbol(symbol)
    # Namespace by fetcher: fetch_closes uses its own "closes" marker, and
    # sharing the flat key space with real intervals would let one function's
    # payload satisfy another's cache lookup.
    key = ("chart", symbol, interval, range_)
    cached = _cache_get(key)
    if cached is not None:
        return _copy_value(cached)

    with _key_lock(key):
        # Re-check: another thread may have populated the cache while we
        # waited on the lock.
        cached = _cache_get(key)
        if cached is not None:
            return _copy_value(cached)

        result = _request_chart(symbol, interval, range_)
        if result is None:
            return None

        meta = result.get("meta", {})
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        opens = quote.get("open", []) or []
        highs = quote.get("high", []) or []
        lows = quote.get("low", []) or []
        closes = quote.get("close", []) or []
        volumes = quote.get("volume", []) or []

        ohlcv: list[dict] = []
        dates: list[str] = []
        for i, ts in enumerate(timestamps):
            close = closes[i] if i < len(closes) else None
            # A non-positive close makes log-returns NaN/-inf downstream, which
            # Starlette refuses to serialize. Drop the row instead.
            if close is None or not np.isfinite(close) or close <= 0:
                continue
            open_ = opens[i] if i < len(opens) else None
            high = highs[i] if i < len(highs) else None
            low = lows[i] if i < len(lows) else None
            vol = volumes[i] if i < len(volumes) else None
            ohlcv.append(
                {
                    "date": _iso_date(ts),
                    "open": round(float(open_), 2) if open_ else 0.0,
                    "high": round(float(high), 2) if high else 0.0,
                    "low": round(float(low), 2) if low else 0.0,
                    "close": round(float(close), 2),
                    "volume": int(vol) if vol else 0,
                }
            )
            dates.append(_iso_date(ts))

        if not ohlcv:
            return None

        chart = ChartResult(ohlcv=ohlcv, meta=meta, dates=dates)
        _cache_set(key, chart)
        return _copy_value(chart)


def chart_meta_summary(meta: dict, symbol: str, ohlcv: list[dict]) -> dict:
    """Flatten Yahoo chart `meta` into the ticker-info summary the API returns."""
    current_price = meta.get("regularMarketPrice") or (ohlcv[-1]["close"] if ohlcv else 0)
    prev_close = meta.get("regularMarketPreviousClose") or (
        ohlcv[-2]["close"] if len(ohlcv) >= 2 else current_price
    )
    try:
        change = float(current_price) - float(prev_close)
        change_pct = (change / float(prev_close) * 100) if float(prev_close) != 0 else 0.0
    except (TypeError, ValueError):
        change, change_pct = 0.0, 0.0
    return {
        "name": meta.get("shortName") or meta.get("longName") or meta.get("symbol", symbol),
        "price": round(float(current_price), 2) if current_price else 0,
        "change": round(change, 2),
        "changePercent": round(change_pct, 2),
        "volume": meta.get("regularMarketVolume") or 0,
        "marketCap": meta.get("marketCap") or 0,
        "previousClose": prev_close,
    }


def fetch_intraday(symbol: str) -> dict | None:
    """
    1-hour candles for the current trading day (times in US/Eastern).
    Returns {open, current, high, low, change, changePercent, candles} or None.
    """
    symbol = normalize_symbol(symbol)
    key = ("intraday", symbol, "1h", "1d")
    cached = _cache_get(key)
    if cached is not None:
        return _copy_value(cached)

    with _key_lock(key):
        cached = _cache_get(key)
        if cached is not None:
            return _copy_value(cached)

        result = _request_chart(symbol, "1h", "1d")
        if result is None:
            return None
        meta = result.get("meta", {})
        timestamps = result.get("timestamp", []) or []
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        closes_raw = quote.get("close", []) or []
        highs_raw = quote.get("high", []) or []
        lows_raw = quote.get("low", []) or []

        candles = []
        for i, ts in enumerate(timestamps):
            close = closes_raw[i] if i < len(closes_raw) else None
            if close is None or not np.isfinite(close) or close <= 0:
                continue
            high = highs_raw[i] if i < len(highs_raw) else None
            low = lows_raw[i] if i < len(lows_raw) else None
            candle_time = datetime.fromtimestamp(ts, tz=UTC).astimezone(ET)
            candles.append(
                {
                    "time": candle_time.strftime("%H:%M"),
                    "close": round(float(close), 2),
                    "high": round(float(high), 2) if high else None,
                    "low": round(float(low), 2) if low else None,
                }
            )
        if not candles:
            return None

        current_price = float(meta.get("regularMarketPrice", candles[-1]["close"]))
        prev_price = float(
            meta.get("chartPreviousClose", meta.get("previousClose", candles[0]["close"]))
        )
        day_open = float(meta.get("regularMarketOpen", candles[0]["close"]))
        day_change = current_price - prev_price
        day_change_pct = (day_change / prev_price * 100) if prev_price else 0.0

        valid_highs = [c["high"] for c in candles if c["high"] is not None]
        valid_lows = [c["low"] for c in candles if c["low"] is not None]
        intraday = {
            "open": round(day_open, 2),
            "current": round(current_price, 2),
            "high": round(max(valid_highs), 2) if valid_highs else None,
            "low": round(min(valid_lows), 2) if valid_lows else None,
            "change": round(day_change, 2),
            "changePercent": round(day_change_pct, 2),
            "candles": candles,
        }
        _cache_set(key, intraday)
        return _copy_value(intraday)


def fetch_closes(symbol: str, range_: str = "1y") -> ClosesSeries | None:
    """
    Fetch closing prices + trading dates. Returns None if fewer than 20
    non-null closes are available (callers treat that as "not enough data").
    """
    symbol = normalize_symbol(symbol)
    key = ("closes", symbol, "1d", range_)
    cached = _cache_get(key)
    if cached is not None:
        return _copy_value(cached)

    with _key_lock(key):
        cached = _cache_get(key)
        if cached is not None:
            return _copy_value(cached)

        result = _request_chart(symbol, "1d", range_)
        if result is None:
            return None
        raw_closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", []) or []
        timestamps = result.get("timestamp", []) or []

        dates: list[str] = []
        closes: list[float] = []
        for i, close in enumerate(raw_closes):
            if close is None or i >= len(timestamps):
                continue
            value = float(close)
            # Non-positive/non-finite closes would make log-returns NaN or
            # -inf, which cannot be serialized to JSON.
            if not np.isfinite(value) or value <= 0:
                continue
            dates.append(_iso_date(timestamps[i]))
            closes.append(value)

        if len(closes) < 20:
            return None

        series = ClosesSeries(dates=dates, closes=np.array(closes))
        _cache_set(key, series)
        return _copy_value(series)


# ── Cross-symbol date alignment ───────────────────────────────────────────────

def align_closes(series_by_symbol: dict[str, ClosesSeries]) -> tuple[list[str], dict[str, np.ndarray]]:
    """
    Align close series across symbols on their **common trading dates**
    (intersection), preserving chronological order. Raises ValueError when
    the intersection is empty or has fewer than 2 points.
    """
    if not series_by_symbol:
        raise ValueError("no series to align")
    symbols = list(series_by_symbol)
    common: set[str] = set(series_by_symbol[symbols[0]].dates)
    for sym in symbols[1:]:
        common &= set(series_by_symbol[sym].dates)
    if len(common) < 2:
        raise ValueError("series have no overlapping trading dates")

    ordered = sorted(common)
    aligned: dict[str, np.ndarray] = {}
    for sym in symbols:
        series = series_by_symbol[sym]
        if len(series.dates) != len(series.closes):
            raise ValueError(f"dates/closes length mismatch for {sym}")
        date_to_close = dict(zip(series.dates, series.closes, strict=True))
        aligned[sym] = np.array([date_to_close[d] for d in ordered])
    return ordered, aligned


# ── Symbol search ─────────────────────────────────────────────────────────────

def search_symbols(q: str, limit: int = 10) -> list[dict]:
    """Company-name/ticker autocomplete via Yahoo (equities, ETFs, indices)."""
    if not q:
        return []
    try:
        resp = _session.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": q, "quotesCount": limit, "newsCount": 0, "listsCount": 0},
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        quotes = resp.json().get("quotes", [])
        return [
            {
                "symbol": item.get("symbol", ""),
                "name": item.get("shortname") or item.get("longname") or item.get("symbol", ""),
                "exchange": item.get("exchange", ""),
                "type": item.get("quoteType", ""),
            }
            for item in quotes
            if item.get("quoteType") in ("EQUITY", "ETF", "INDEX")
        ][:limit]
    except Exception:
        logger.debug("symbol search failed", exc_info=True)
        return []


# ── Sector universes ──────────────────────────────────────────────────────────

SECTOR_TICKERS: dict[str, list[str]] = {
    "tech": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "NFLX",
        "AMD", "INTC", "ORCL", "CRM", "ADBE", "CSCO", "ACN", "QCOM",
        "AVGO", "TXN", "MU", "PANW", "NOW", "INTU", "SNOW", "UBER", "SQ",
    ],
    "finance": ["JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "AXP", "COF", "USB"],
    "healthcare": ["UNH", "JNJ", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT", "DHR", "AMGN"],
    "energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC", "VLO", "PSX", "OXY", "HAL"],
    "etf": [
        "SPY", "QQQ", "VOO", "VTI", "IVV", "VEA", "VWO", "IWM", "EFA", "EEM",
        "TLT", "GLD", "SLV", "XLF", "XLE", "XLK", "XLV", "XLY", "XLI", "XLRE",
        "QQQM", "VOT", "VO", "VB", "VNQ", "BND", "AGG", "SCHD", "DIA", "JEPQ",
    ],
    "broad": ["SPY", "QQQ", "IWM", "DIA", "VTI", "VEA", "VWO", "BND", "GLD", "TLT"],
    "dividends": ["JEPI", "JEPQ", "SCHD", "VYM", "HDV", "DGRO", "DVY", "VIG", "SPHD", "HYLG"],
    "semiconductors": [
        "NVDA", "AMD", "INTC", "QCOM", "AVGO", "TXN", "MU", "AMAT",
        "LRCX", "ASML", "KLAC", "AMKR",
    ],
}

# Sectors exposed by the screener UI (the others are correlation-graph only).
SCREENER_SECTORS = {"tech", "finance", "healthcare", "energy", "etf"}
