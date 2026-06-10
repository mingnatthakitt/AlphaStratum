import os
import yfinance as yf
import httpx
import time
import asyncio
import numpy as np
import requests
from datetime import datetime
from fastapi import APIRouter, HTTPException
from hmmlearn import hmm

router = APIRouter()

# ── Yahoo Finance chart API (much more reliable than yf.download) ─────────────
_yf_session = requests.Session()
_yf_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
})


def _fetch_yahoo_chart(symbol: str, interval: str = "1d", range_: str = "1y") -> tuple[list[dict], dict] | None:
    """
    Fetch OHLCV + metadata directly from Yahoo Finance chart API.
    Returns (ohlcv_list, meta_dict) or None on failure.
    meta contains: currentPrice, previousClose, change, changePercent, volume, marketCap, name
    """
    try:
        resp = _yf_session.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": interval, "range": range_},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        r = result[0]
        meta = r.get("meta", {})
        timestamps = r.get("timestamp", [])
        quote = r.get("indicators", {}).get("quote", [{}])[0]

        ohlcv = []
        for i, ts in enumerate(timestamps):
            open_ = quote.get("open", [None])[i]
            high = quote.get("high", [None])[i]
            low = quote.get("low", [None])[i]
            close = quote.get("close", [None])[i]
            vol = quote.get("volume", [None])[i]
            if close is None:
                continue
            ohlcv.append({
                "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                "open": round(float(open_), 2) if open_ else 0,
                "high": round(float(high), 2) if high else 0,
                "low": round(float(low), 2) if low else 0,
                "close": round(float(close), 2),
                "volume": int(vol) if vol else 0,
            })

        if not ohlcv:
            return None

        # Extract metadata from chart meta (no extra API call needed)
        current_price = meta.get("regularMarketPrice") or (ohlcv[-1]["close"] if ohlcv else 0)
        prev_close = meta.get("regularMarketPreviousClose") or (ohlcv[-2]["close"] if len(ohlcv) >= 2 else current_price)
        market_change = float(current_price) - float(prev_close) if current_price and prev_close else 0.0
        market_change_pct = (market_change / float(prev_close) * 100) if prev_close and float(prev_close) != 0 else 0.0

        chart_meta = {
            "name": meta.get("shortName") or meta.get("symbol", symbol),
            "price": round(float(current_price), 2) if current_price else 0,
            "change": round(market_change, 2),
            "changePercent": round(market_change_pct, 2),
            "volume": meta.get("regularMarketVolume") or 0,
            "marketCap": meta.get("marketCap") or 0,
            "previousClose": prev_close,
        }

        return ohlcv, chart_meta
    except Exception:
        return None


def _get_closes_yahoo(symbol: str, range_: str = "1y") -> np.ndarray | None:
    """Fetch closing prices from Yahoo Finance chart API."""
    try:
        resp = _yf_session.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1d", "range": range_},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        closes = result[0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        return np.array(closes) if len(closes) >= 20 else None
    except Exception:
        return None


# ── In-memory TTL cache ────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 300  # 5 minutes


def _get_cache(symbol: str) -> dict | None:
    if symbol in _cache:
        ts, data = _cache[symbol]
        if time.time() - ts < _CACHE_TTL:
            return data
        del _cache[symbol]
    return None


def _set_cache(symbol: str, data: dict) -> None:
    _cache[symbol.upper()] = (time.time(), data)


# ── Retry helper ───────────────────────────────────────────────────────────────
async def _retry_httpx(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    max_retries: int = 3,
    **kwargs,
) -> httpx.Response:
    for attempt in range(max_retries):
        try:
            res = await client.request(method, url, **kwargs)
            if res.status_code == 429:
                wait = 2 ** attempt * 2
                await asyncio.sleep(wait)
                continue
            return res
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
    raise httpx.HTTPError("Max retries exceeded")


# ── Alpha Vantage helpers ──────────────────────────────────────────────────────

def _fetch_alpha_vantage_ticker(symbol: str) -> list[dict] | None:
    """Fetch daily OHLCV from Alpha Vantage. Returns None if unavailable or rate-limited."""
    key = os.getenv("ALPHA_VANTAGE_KEY")
    if not key:
        return None
    try:
        resp = httpx.get(
            "https://www.alphavantage.co/query",
            params={"function": "TIME_SERIES_DAILY", "symbol": symbol, "apikey": key, "outputsize": "compact"},
            timeout=15.0,
        )
        data = resp.json()
        if "Note" in data or "Error Message" in data or "Information" in data:
            return None
        ts = data.get("Time Series (Daily)", {})
        if not ts:
            return None
        ohlcv = []
        for date_str, vals in sorted(ts.items()):
            ohlcv.append({
                "date": date_str,
                "open": round(float(vals["1. open"]), 2),
                "high": round(float(vals["2. high"]), 2),
                "low": round(float(vals["3. low"]), 2),
                "close": round(float(vals["4. close"]), 2),
                "volume": int(vals["5. volume"]),
            })
        return ohlcv if ohlcv else None
    except Exception:
        return None


@router.get("/ticker/{symbol}")
def get_ticker(symbol: str):
    symbol = symbol.upper()
    cached = _get_cache(symbol)
    if cached is not None:
        return cached

    # Primary: Yahoo Finance chart API (returns ohlcv + metadata in one call)
    chart_result = _fetch_yahoo_chart(symbol)
    ohlcv = None
    chart_meta = {}

    if chart_result:
        ohlcv, chart_meta = chart_result

    # Fallback: Alpha Vantage (free tier — 5 calls/min, 500/day)
    if ohlcv is None:
        ohlcv = _fetch_alpha_vantage_ticker(symbol)

    if not ohlcv:
        raise HTTPException(status_code=404, detail="No data found for this ticker")

    # All metadata from chart meta (no extra API calls)
    name = chart_meta.get("name", symbol)
    price = chart_meta.get("price", ohlcv[-1]["close"])
    change = chart_meta.get("change", 0.0)
    change_pct = chart_meta.get("changePercent", 0.0)
    volume = chart_meta.get("volume", 0)
    market_cap = chart_meta.get("marketCap", 0)

    # Compute 52-week high/low from the OHLCV data we already have
    week_high = max(row["high"] for row in ohlcv)
    week_low = min(row["low"] for row in ohlcv)
    pe = 0.0  # P/E requires income statement data — not available from chart API

    stock_info = {
        "symbol": symbol,
        "name": name,
        "price": round(price, 2),
        "change": round(change, 2),
        "changePercent": round(change_pct, 2),
        "volume": volume,
        "marketCap": market_cap,
        "pe": pe,
        "weekHigh52": round(week_high, 2),
        "weekLow52": round(week_low, 2),
    }

    result = {"info": stock_info, "ohlcv": ohlcv}
    _set_cache(symbol, result)
    return result


@router.get("/news/{symbol}")
async def get_news(symbol: str):
    articles = []
    newsapi_key = os.getenv("NEWSAPI_KEY")
    if newsapi_key:
        try:
            async with httpx.AsyncClient() as client:
                res = await _retry_httpx(
                    client, "GET",
                    "https://newsapi.org/v2/everything",
                    params={"q": symbol, "apiKey": newsapi_key, "language": "en", "sortBy": "publishedAt", "pageSize": 10},
                    timeout=10.0,
                )
                data = res.json()
                for art in data.get("articles", []):
                    articles.append({
                        "title": art.get("title", ""),
                        "source": art.get("source", {}).get("name", "Unknown"),
                        "date": art.get("publishedAt", "")[:10],
                        "url": art.get("url", ""),
                        "snippet": art.get("description", "")[:300],
                    })
        except Exception:
            pass
    if not articles:
        try:
            info = yf.Ticker(symbol).info
            articles.append({
                "title": f"{symbol} — {info.get('longName', symbol)}",
                "source": "Yahoo Finance",
                "date": str(datetime.now().date()),
                "url": f"https://finance.yahoo.com/quote/{symbol}",
                "snippet": info.get("longBusinessSummary", "No summary available.")[:300],
            })
        except Exception:
            pass
    return {"articles": articles}


# ── Stock search: company name → ticker ──────────────────────────────────────

@router.get("/search")
def search_stock(q: str = ""):
    """
    Search for a stock by company name or ticker.
    Uses Yahoo Finance autocomplete API.
    Returns list of { symbol, name, exchange, type }
    """
    if not q or len(q) < 1:
        return {"results": []}
    try:
        resp = _yf_session.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": q, "quotesCount": 10, "newsCount": 0, "listsCount": 0},
            timeout=10,
        )
        if resp.status_code != 200:
            return {"results": []}
        data = resp.json()
        results = []
        for item in data.get("quotes", []):
            if item.get("quoteType") in ("EQUITY", "ETF", "INDEX"):
                results.append({
                    "symbol": item.get("symbol", ""),
                    "name": item.get("shortname") or item.get("longname") or item.get("symbol", ""),
                    "exchange": item.get("exchange", ""),
                    "type": item.get("quoteType", ""),
                })
        return {"results": results[:10]}
    except Exception:
        return {"results": []}


# ── Screener: all stocks in one call ─────────────────────────────────────────
SECTOR_TICKERS = {
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
}


@router.get("/screener/{sector}")
def get_screener(sector: str = "tech"):
    """
    Returns all stocks for a sector with regime + price data in a single call.
    Uses Yahoo Finance chart API — much more reliable than yf.download.
    """
    tickers = SECTOR_TICKERS.get(sector, SECTOR_TICKERS["tech"])
    results = []

    for symbol in tickers:
        try:
            chart_result = _fetch_yahoo_chart(symbol)
            if not chart_result:
                continue
            ohlcv, chart_meta = chart_result
            if len(ohlcv) < 30:
                continue

            closes = np.array([c["close"] for c in ohlcv])
            returns = np.diff(np.log(closes))

            # Threshold-based regime (consistent with regime/markov endpoints)
            regimes = np.where(returns > 0.005, 2, np.where(returns < -0.005, 0, 1))  # 0=bear, 1=sideways, 2=bull

            regime_counts = {0: np.sum(regimes == 0), 1: np.sum(regimes == 1), 2: np.sum(regimes == 2)}
            total = len(regimes)
            prob_bull = regime_counts[2] / total
            prob_bear = regime_counts[0] / total
            prob_sideways = regime_counts[1] / total
            regime_names = {0: "bear", 1: "sideways", 2: "bull"}
            current_regime = regime_names[int(regimes[-1])]
            momentum = float(returns[-20:].sum() * 100) if len(returns) >= 20 else float(returns.sum() * 100)
            volatility = float(returns[-20:].std() * np.sqrt(252) * 100) if len(returns) >= 20 else float(returns.std() * np.sqrt(252) * 100)

            # Score: Sharpe-inspired, range 0-100 (never negative)
            # Regime (0-40): bull=40, sideways=20, bear=0
            regime_score = 40 if current_regime == "bull" else 20 if current_regime == "sideways" else 0
            # Momentum (0-40): positive 20-day return → score up to 40; no negative contribution
            momentum_score = max(0, min(40, momentum * 2))
            # Stability bonus (0-20): low vol is rewarded, high vol is penalized
            # Uses the same 0-20 penalty scale but presented as a bonus (subtracted from base 60)
            vol_penalty = min(20, volatility * 0.4)
            score = max(0, round(regime_score + momentum_score - vol_penalty))

            price = round(float(closes[-1]), 2)
            price_change_pct = round(float((closes[-1] / closes[-2] - 1) * 100), 2) if len(closes) >= 2 else 0.0

            results.append({
                "symbol": symbol,
                "name": chart_meta.get("name", symbol),
                "price": price,
                "change": price_change_pct,
                "regime": current_regime,
                "momentum": round(momentum, 2),
                "volatility": round(volatility, 2),
                "score": score,
                "probBull": round(prob_bull, 3),
                "probBear": round(prob_bear, 3),
                "probSideways": round(prob_sideways, 3),
            })
        except Exception as e:
            pass

    return {"sector": sector, "stocks": sorted(results, key=lambda x: x.get("score", 0), reverse=True)}