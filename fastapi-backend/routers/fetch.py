"""
Market data fetch endpoints: ticker OHLCV, news, symbol search, screener.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx
import numpy as np
from fastapi import APIRouter, HTTPException

import cache
from services import market_data, quant
from services.errors import bad_request, internal_error, not_found
from services.market_data import SymbolError, normalize_symbol

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Alpha Vantage fallback (optional — needs ALPHA_VANTAGE_KEY) ───────────────

def _fetch_alpha_vantage_ticker(symbol: str) -> list[dict] | None:
    """Daily OHLCV from Alpha Vantage. Returns None if unavailable/rate-limited."""
    key = os.getenv("ALPHA_VANTAGE_KEY")
    if not key:
        return None
    try:
        resp = httpx.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "apikey": key,
                "outputsize": "compact",
            },
            timeout=15.0,
        )
        data = resp.json()
        if "Note" in data or "Error Message" in data or "Information" in data:
            return None
        time_series = data.get("Time Series (Daily)", {})
        if not time_series:
            return None
        ohlcv = [
            {
                "date": date_str,
                "open": round(float(vals["1. open"]), 2),
                "high": round(float(vals["2. high"]), 2),
                "low": round(float(vals["3. low"]), 2),
                "close": round(float(vals["4. close"]), 2),
                "volume": int(vals["5. volume"]),
            }
            for date_str, vals in sorted(time_series.items())
        ]
        return ohlcv or None
    except Exception:
        logger.debug("Alpha Vantage fallback failed", exc_info=True, extra={"symbol": symbol})
        return None


# ── Ticker ────────────────────────────────────────────────────────────────────

@router.get("/ticker/{symbol}")
def get_ticker(symbol: str):
    """OHLCV + stock info (Yahoo primary, Alpha Vantage fallback)."""
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise bad_request(str(e))

    chart = market_data.fetch_chart(symbol)
    ohlcv = chart.ohlcv if chart else None
    meta = chart.meta if chart else {}

    if ohlcv is None:
        ohlcv = _fetch_alpha_vantage_ticker(symbol)
    if not ohlcv:
        raise not_found("No data found for this ticker")

    summary = market_data.chart_meta_summary(meta, symbol, ohlcv)
    stock_info = {
        "symbol": symbol,
        "name": summary["name"],
        "price": summary["price"],
        "change": summary["change"],
        "changePercent": summary["changePercent"],
        "volume": summary["volume"],
        "marketCap": summary["marketCap"],
        # P/E is not reliably available from the chart API — kept at 0 (see LIMITATIONS.md).
        "pe": 0.0,
        "weekHigh52": round(max(row["high"] for row in ohlcv), 2),
        "weekLow52": round(min(row["low"] for row in ohlcv), 2),
    }
    return {"info": stock_info, "ohlcv": ohlcv}


# ── News ──────────────────────────────────────────────────────────────────────

@router.get("/news/{symbol}")
async def get_news(symbol: str):
    """Latest news from NewsAPI (fallback: Yahoo company profile summary)."""
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise bad_request(str(e))

    articles: list[dict] = []
    newsapi_key = os.getenv("NEWSAPI_KEY")
    if newsapi_key:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": symbol,
                        "apiKey": newsapi_key,
                        "language": "en",
                        "sortBy": "publishedAt",
                        "pageSize": 10,
                    },
                    timeout=10.0,
                )
                data = res.json()
                for art in data.get("articles", []):
                    # NewsAPI returns `"source": null` for unattributed
                    # articles, so `.get("source", {})` is not enough — it only
                    # defaults when the key is absent, and None.get() would
                    # raise, discarding every article parsed so far.
                    src = art.get("source") or {}
                    articles.append(
                        {
                            "title": art.get("title") or "",
                            "source": src.get("name") or "Unknown",
                            "date": (art.get("publishedAt") or "")[:10],
                            "url": art.get("url") or "",
                            "snippet": (art.get("description") or "")[:300],
                        }
                    )
        except Exception:
            logger.debug("NewsAPI fetch failed for %s", symbol, exc_info=True)

    if not articles:
        try:
            import yfinance as yf

            info = await _to_thread(lambda: yf.Ticker(symbol).info)
            articles.append(
                {
                    "title": f"{symbol} — {info.get('longName', symbol)}",
                    "source": "Yahoo Finance",
                    "date": str(datetime.now().date()),
                    "url": f"https://finance.yahoo.com/quote/{symbol}",
                    "snippet": info.get("longBusinessSummary", "No summary available.")[:300],
                }
            )
        except Exception:
            logger.debug("Yahoo news fallback failed for %s", symbol, exc_info=True)

    return {"articles": articles}


def _to_thread(fn):
    import asyncio

    return asyncio.get_running_loop().run_in_executor(None, fn)


# ── Symbol search ─────────────────────────────────────────────────────────────

@router.get("/search")
def search_stock(q: str = ""):
    """Company-name/ticker autocomplete via Yahoo (equities, ETFs, indices)."""
    return {"results": market_data.search_symbols(q, limit=10)}


# ── Batch quotes ──────────────────────────────────────────────────────────────

@router.get("/quotes")
def get_quotes(symbols: str = ""):
    """
    Minimal quotes for up to 20 symbols (price/change/changePercent only).
    Uses the shared market-data cache, so polling this endpoint is far cheaper
    than fetching full OHLCV per symbol.
    """
    requested = [s.strip() for s in symbols.split(",") if s.strip()][:20]
    normalized: list[str] = []
    for raw in requested:
        try:
            normalized.append(normalize_symbol(raw))
        except SymbolError:
            continue

    with ThreadPoolExecutor(max_workers=8) as pool:
        charts = dict(zip(normalized, pool.map(market_data.fetch_chart, normalized), strict=True))

    quotes = []
    for symbol in normalized:
        chart = charts.get(symbol)
        if chart is None:
            continue
        summary = market_data.chart_meta_summary(chart.meta, symbol, chart.ohlcv)
        quotes.append(
            {
                "symbol": symbol,
                "price": summary["price"],
                "change": summary["change"],
                "changePercent": summary["changePercent"],
                "name": summary["name"],
            }
        )
    return {"quotes": quotes}


# ── Screener ──────────────────────────────────────────────────────────────────

def _score_symbol(symbol: str) -> dict | None:
    """Fetch + score one screener symbol. Returns None on any failure."""
    try:
        chart = market_data.fetch_chart(symbol)
        if chart is None or len(chart.ohlcv) < 30:
            return None

        closes = np.array([row["close"] for row in chart.ohlcv])
        returns = np.diff(np.log(closes))
        regimes = quant.threshold_regimes(returns)
        counts = quant.regime_counts(regimes)
        total = len(regimes)

        regime = quant.current_regime(regimes)
        momentum = float(returns[-20:].sum() * 100) if len(returns) >= 20 else float(returns.sum() * 100)
        volatility = (
            float(returns[-20:].std() * np.sqrt(252) * 100)
            if len(returns) >= 20
            else float(returns.std() * np.sqrt(252) * 100)
        )
        price_change_pct = (
            float((closes[-1] / closes[-2] - 1) * 100) if len(closes) >= 2 else 0.0
        )

        return {
            "symbol": symbol,
            "name": chart.meta.get("shortName") or symbol,
            "price": round(float(closes[-1]), 2),
            "change": round(price_change_pct, 2),
            "regime": regime,
            "momentum": round(momentum, 2),
            "volatility": round(volatility, 2),
            "score": quant.screener_score(regime, momentum, volatility),
            "probBull": round(counts["bull"] / total, 3),
            "probBear": round(counts["bear"] / total, 3),
            "probSideways": round(counts["sideways"] / total, 3),
        }
    except Exception:
        logger.debug("screener scoring failed for %s", symbol, exc_info=True)
        return None


@router.get("/screener/{sector}")
def get_screener(sector: str = "tech"):
    """
    Score all stocks in a sector: regime + momentum + volatility penalty.
    Symbol fetches run in parallel; results are cached for 15 minutes.
    """
    if sector not in market_data.SCREENER_SECTORS:
        raise bad_request(f"Unknown sector: {sector}. Available: {sorted(market_data.SCREENER_SECTORS)}")

    try:
        cached = cache.get_cached("screener", {"sector": sector})
        if cached is not None:
            return cached

        tickers = market_data.SECTOR_TICKERS[sector]
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = [r for r in pool.map(_score_symbol, tickers) if r is not None]

        payload = {"sector": sector, "stocks": sorted(results, key=lambda x: x["score"], reverse=True)}
        cache.set_cached("screener", {"sector": sector}, payload)
        return payload
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"screener failed for {sector}")
