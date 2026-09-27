"""
AI Advisor: live context injection + inline citations.

The "retrieval" here is real-time context injection — news, prices, computed
indicators, analyst consensus and SEC filings are fetched at query time and
injected into the prompt (no vector store; see LIMITATIONS.md).

Every network call is off the event loop: sync I/O runs in worker threads and
independent sources are gathered concurrently.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time

import httpx
import numpy as np
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - beautifulsoup4 is a hard dep; defensive only
    BeautifulSoup = None

from services import market_data, quant
from services.errors import bad_request
from services.market_data import SymbolError, normalize_symbol

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter()

# Provider configuration is resolved through these accessors rather than read
# once at import. Two reasons: deploying platforms (Render's `sync: false`)
# create unset env vars as EMPTY strings, which `os.getenv(name, default)`
# happily returns instead of the default; and reading per request means
# rotating a key in the dashboard takes effect without a restart.
# `or` also treats a blank value as absent, so a stray "" cannot break calls.

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"


def gemini_api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or None


def gemini_model() -> str:
    return os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL


def anthropic_api_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY") or None


def anthropic_base_url() -> str | None:
    # e.g. a MiniMax / OpenAI-compatible Anthropic proxy
    return os.getenv("ANTHROPIC_BASE_URL") or None


def anthropic_model() -> str:
    return os.getenv("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL


def newsapi_key() -> str | None:
    return os.getenv("NEWSAPI_KEY") or None


def default_provider() -> str:
    configured = os.getenv("LLM_PROVIDER")
    if configured:
        return configured.lower()
    return "anthropic" if anthropic_api_key() else "gemini"

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    symbol: str | None = Field(default=None, max_length=15)
    provider: str | None = Field(default=None, max_length=20)


# ── SEC EDGAR ─────────────────────────────────────────────────────────────────
# No API key required. Rate limit: 10 reqs/sec — enforced with a module-level
# throttle. All EDGAR functions are called from worker threads, so blocking
# sleeps here are safe.

_EDGAR_USER_AGENT = "AlphaStratum/1.0 (https://github.com/alphastratum)"
_edgar_throttle_lock = threading.Lock()
_edgar_last_call = 0.0
_EDGAR_DELAY = 0.11  # seconds between calls to stay under 10/sec

# The full company_tickers.json (~10k entries) is fetched once and cached with
# a TTL — the previous per-symbol lookup re-downloaded the whole file.
_cik_map: dict[str, str] = {}
_cik_map_loaded_at = 0.0
_CIK_MAP_TTL = 24 * 3600
_CIK_MAP_FAILURE_BACKOFF = 300  # retry a failed map download after 5 minutes
_cik_lock = threading.Lock()


def _edgar_throttle() -> None:
    """Serialize check-sleep-stamp so concurrent threads can't exceed 10 req/s."""
    global _edgar_last_call
    with _edgar_throttle_lock:
        now = time.monotonic()
        elapsed = now - _edgar_last_call
        wait = _EDGAR_DELAY - elapsed
        if wait > 0:
            time.sleep(wait)
            _edgar_last_call = time.monotonic()
        else:
            _edgar_last_call = now


def _cik_from_ticker(symbol: str) -> str | None:
    """Ticker → zero-padded CIK, via a TTL-cached in-memory map."""
    global _cik_map, _cik_map_loaded_at
    symbol = symbol.upper()
    with _cik_lock:
        fresh = (time.monotonic() - _cik_map_loaded_at) < _CIK_MAP_TTL
        if fresh and symbol in _cik_map:
            return _cik_map[symbol]

    if not fresh:
        try:
            _edgar_throttle()
            resp = httpx.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers={
                    "User-Agent": _EDGAR_USER_AGENT,
                    "Accept": "application/json",
                },
                timeout=20,
            )
            if resp.status_code == 200:
                new_map = {
                    info.get("ticker", "").upper(): str(info["cik_str"]).zfill(10)
                    for info in resp.json().values()
                    if info.get("ticker")
                }
                with _cik_lock:
                    _cik_map = new_map
                    _cik_map_loaded_at = time.monotonic()
            else:
                logger.warning("EDGAR company_tickers.json returned %s", resp.status_code)
                # Back off briefly instead of re-hitting EDGAR on every request.
                with _cik_lock:
                    _cik_map_loaded_at = time.monotonic() - _CIK_MAP_TTL + _CIK_MAP_FAILURE_BACKOFF
        except Exception:
            logger.debug("EDGAR ticker map fetch failed", exc_info=True)
            with _cik_lock:
                _cik_map_loaded_at = time.monotonic() - _CIK_MAP_TTL + _CIK_MAP_FAILURE_BACKOFF

    with _cik_lock:
        return _cik_map.get(symbol)


def _get_filing_document(primary_document: str, accession_number: str, cik: str) -> str | None:
    accn_clean = accession_number.replace("-", "").replace(" ", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_clean}/{primary_document}"
    try:
        _edgar_throttle()
        resp = httpx.get(url, headers={"User-Agent": _EDGAR_USER_AGENT}, timeout=20)
        return resp.text if resp.status_code == 200 else None
    except Exception:
        return None


def _extract_filing_summary(html: str, filing_type: str) -> str:
    """Pull revenue/net-income/EPS/outlook/risk highlights out of a filing HTML."""
    if not BeautifulSoup:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        text = re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True))
        highlights: list[str] = []

        m = re.search(r"Total net sales\s+\$?\s*(\d+)", text, re.IGNORECASE)
        if m:
            highlights.append(f"Revenue: ${int(m.group(1)):,}M")

        m = re.search(r"Net\s+income\s+\$?\s*(\d+)", text, re.IGNORECASE)
        if m:
            highlights.append(f"Net Income: ${int(m.group(1)):,}M")

        eps_m = re.search(r"Earnings per share: Basic \$ ([0-9.]+)", text, re.IGNORECASE)
        if eps_m:
            highlights.append(f"EPS (Basic): ${eps_m.group(1)}")

        m = re.search(r"(?:outlook|guidance|forecast|expects|anticipates)[^.]{0,200}\.", text, re.IGNORECASE)
        if m:
            highlights.append(f"Outlook: {m.group(0)[:180].strip()}")

        if filing_type == "10-K":
            risk_matches = re.findall(r"Item\s*1A[^.]{0,300}\.", text, re.IGNORECASE)
            if risk_matches:
                highlights.append(f"Key Risks: {risk_matches[-1][:180].strip()}")

        return " | ".join(highlights)
    except Exception:
        return ""


def _get_edgar_fundamentals(symbol: str) -> str:
    """Latest 10-K / 10-Q fundamentals from SEC EDGAR; '' on any failure."""
    try:
        cik = _cik_from_ticker(symbol)
        if not cik:
            return ""

        _edgar_throttle()
        resp = httpx.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers={"User-Agent": _EDGAR_USER_AGENT, "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            return ""
        recent = resp.json().get("filings", {}).get("recent", {})
    except Exception:
        logger.debug("EDGAR submissions fetch failed for %s", symbol, exc_info=True)
        return ""

    try:
        accession_numbers = recent.get("accessionNumber", [])
        filing_types = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])

        targets: dict[str, list[dict]] = {"10-K": [], "10-Q": []}
        for i, form in enumerate(filing_types):
            if form in targets and len(targets[form]) < 2:
                targets[form].append(
                    {
                        "accessionNumber": accession_numbers[i],
                        "filingDate": filing_dates[i],
                        "primaryDocument": primary_docs[i],
                    }
                )

        parts: list[str] = []
        for filing_type in ("10-K", "10-Q"):
            for candidate in targets[filing_type]:
                html = _get_filing_document(
                    candidate["primaryDocument"], candidate["accessionNumber"], cik
                )
                if html:
                    summary = _extract_filing_summary(html, filing_type)
                    if summary:
                        parts.append(f"{filing_type} ({candidate['filingDate']}): {summary}")
                        break  # one useful filing per type is enough for context
        return "\n".join(parts)
    except Exception:
        logger.debug("EDGAR fundamentals failed for %s", symbol, exc_info=True)
        return ""


# ── Prompts ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a transparent, data-driven stock analysis assistant. "
    "Write thorough 5-10 sentence analysis answers. "
    "Always cite sources inline as [Source: name date]. "
    "You may use general knowledge about well-known public companies to explain what they do. "
    "Only say 'I am not certain' when the question is about a specific data point you cannot find. "
    "Never fabricate numbers, dates, or sources."
)

USER_PROMPT_TEMPLATE = (
    "Based on the data below, give a thorough stock analysis answering the user's question. "
    "Write 5-10 clear sentences. Cite sources inline as [Source: name date].\n"
    "\n"
    "IMPORTANT: Put your final answer between the delimiters <<<ANSWER>>> and <<<END>>> like this:\n"
    "\n"
    "<<<ANSWER>>>\n"
    "Your analysis here. Cite sources inline as [Source: name date].\n"
    "<<<END>>>\n"
    "\n"
    "Do not output anything outside these delimiters. "
    "No preamble, no chain-of-thought, no echoing the prompt.\n"
    "\n"
    "---\n"
    "DATA:\n"
    "{context}\n"
    "---\n"
    "QUESTION: {message}\n"
)


# ── LLM calls ─────────────────────────────────────────────────────────────────

async def _call_gemini(context: str, message: str) -> str:
    user_prompt = USER_PROMPT_TEMPLATE.format(context=context, message=message)
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model()}:generateContent",
            # The key goes in a header, not the query string: httpx embeds the
            # full request URL in HTTPStatusError's message, so a query-string
            # key would be written to our logs by logger.exception on any
            # provider-side 4xx/5xx.
            headers={"x-goog-api-key": gemini_api_key() or ""},
            json={
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": {"temperature": 0.5, "maxOutputTokens": 1024},
            },
            timeout=30.0,
        )
    res.raise_for_status()
    data = res.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def _call_anthropic(context: str, message: str) -> str:
    """Anthropic API (or any Anthropic-compatible endpoint via ANTHROPIC_BASE_URL)."""
    import anthropic

    user_prompt = USER_PROMPT_TEMPLATE.format(context=context, message=message)

    client_kwargs: dict = {"api_key": anthropic_api_key()}
    base_url = anthropic_base_url()
    if base_url:
        client_kwargs["base_url"] = base_url
    # `async with` — a bare AsyncAnthropic allocates its own httpx transport and
    # connection pool that is only reclaimed by GC (leaked sockets).
    async with anthropic.AsyncAnthropic(**client_kwargs) as client:
        response = await client.messages.create(
            model=anthropic_model(),
            max_tokens=2048,
            temperature=0.5,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    # Concatenate all text blocks — some providers return a non-text "thinking"
    # block first, and response.content[0].text would then be None/crash.
    text_parts = [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ]
    return "\n".join(text_parts)


def _extract_citations(answer: str) -> tuple[str, list[dict]]:
    """Parse [Source: name date] inline tags; returns (clean_answer, citations)."""
    found = re.findall(r"\[Source: ([^\]]+)\]", answer)
    citations = []
    for f in found:
        parts = f.strip().rsplit(" ", 1)
        # "NewsAPI 2024-01-01" → source="NewsAPI", date="2024-01-01";
        # a single-token tag keeps date empty.
        if len(parts) == 2 and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[1]):
            source, date = parts[0], parts[1]
        else:
            source, date = f.strip(), ""
        citations.append({"text": f.strip(), "source": source, "date": date, "url": None})
    answer = re.sub(r"\[Source: [^\]]+\]", "", answer).strip()
    return answer, citations


def _link_citations(citations: list[dict], source_urls: list[dict]) -> None:
    """
    Attach URLs to citations by matching (source prefix, optional date) against
    the URLs recorded while the context was built. Mutates in place.
    """
    for citation in citations:
        for entry in source_urls:
            if not citation["source"].lower().startswith(entry["source"].lower()):
                continue
            if entry.get("date") and citation["date"] and entry["date"] != citation["date"]:
                continue
            citation["url"] = entry["url"]
            break


def _extract_answer(raw: str) -> str:
    """
    Pull the final answer out of the LLM response. Models sometimes echo the
    prompt or show chain-of-thought; prefer the <<<ANSWER>>>…<<<END>>>
    delimiters, then fall back to heuristics.
    """
    if not raw:
        return raw

    m = re.search(r"<<<ANSWER>>>\s*(.*?)\s*<<<END>>>", raw, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Opening delimiter without closing — truncated by max_tokens.
    open_match = re.search(r"<<<ANSWER>>>\s*(.*)", raw, re.DOTALL)
    if open_match:
        return open_match.group(1).strip()

    end_match = list(re.finditer(r"<<<END>>>", raw))
    if end_match:
        after = raw[end_match[-1].end() :].strip()
        if after:
            return after

    # Prefer the last paragraph containing a citation (models put the answer last).
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    candidates = [p for p in paragraphs if "[Source:" in p]
    if candidates:
        return candidates[-1]

    reasoning_markers = (
        "I am not certain", "Check constraints", "Refining", "Wait,", "Let me",
        "Let's", "Draft", "Alternative", "*Refining",
    )
    for p in reversed(paragraphs):
        if not any(marker in p for marker in reasoning_markers):
            return p

    return raw.strip()


# ── Context building ──────────────────────────────────────────────────────────

def _daily_indicators_part(symbol: str) -> tuple[list[str], list[dict]]:
    """Prices, regime, RSI, MACD, Bollinger, intraday — computed in a worker thread."""
    parts: list[str] = []
    source_urls: list[dict] = []
    chart = market_data.fetch_chart(symbol, range_="1y")
    if chart is None:
        return parts, source_urls
    quote_url = f"https://finance.yahoo.com/quote/{symbol}"
    closes = np.array([row["close"] for row in chart.ohlcv])
    meta = chart.meta
    last_price = round(float(closes[-1]), 2)

    # Basic quote line — always included, even for short-history symbols.
    company_name = meta.get("shortName") or meta.get("longName") or symbol
    mc = meta.get("marketCap")
    if mc:
        if mc >= 1e12:
            market_cap_str = f"${mc / 1e12:.2f}T"
        elif mc >= 1e9:
            market_cap_str = f"${mc / 1e9:.2f}B"
        elif mc >= 1e6:
            market_cap_str = f"${mc / 1e6:.2f}M"
        else:
            market_cap_str = f"${mc:,.0f}"
    else:
        market_cap_str = ""

    pe = meta.get("trailingPE")
    pe_str = f"{pe:.1f}" if pe and pe > 0 else "N/A"

    week_high = meta.get("fiftyTwoWeekHigh")
    week_low = meta.get("fiftyTwoWeekLow")
    # Fall back to the fetched history when meta lacks 52-week levels.
    high_str = f"${week_high:.2f}" if week_high else f"${max(row['high'] for row in chart.ohlcv):.2f}"
    low_str = f"${week_low:.2f}" if week_low else f"${min(row['low'] for row in chart.ohlcv):.2f}"

    parts.append(
        f"[Source: Yahoo Finance] {company_name} ({symbol}) | "
        f"Price: ${last_price} | Market Cap: {market_cap_str or 'N/A'} | P/E: {pe_str} | "
        f"52W High: {high_str} | 52W Low: {low_str}"
    )

    # Indicator line — requires a meaningful return history.
    if len(closes) >= 30:
        returns = np.diff(np.log(closes))
        mom_20d = round(float(returns[-20:].sum() * 100), 2) if len(returns) >= 20 else 0.0
        vol_20d = round(float(returns[-20:].std() * np.sqrt(252) * 100), 2) if len(returns) >= 20 else 0.0
        avg_return = round(float(returns.mean() * 252 * 100), 2)
        parts[0] += (
            f" | 20-Day Momentum: {mom_20d:+.1f}% | Annualized Vol: {vol_20d:.1f}% | "
            f"Annualized Return: {avg_return:+.1f}%"
        )

        regimes = quant.threshold_regimes(returns)
        counts = quant.regime_counts(regimes)
        total_days = len(regimes)
        current_regime = quant.current_regime(regimes)
        prob = {name: round(counts[name] / total_days * 100, 1) for name in quant.REGIME_NAMES}

        try:
            rsi_value, _history = quant.wilder_rsi(closes, 14)
            rsi = round(rsi_value, 1)
        except ValueError:
            rsi = None
        rsi_signal = "overbought" if rsi and rsi > 70 else "oversold" if rsi and rsi < 30 else "neutral"
        rsi_str = f"{rsi} ({rsi_signal})" if rsi is not None else "N/A"

        try:
            macd = quant.macd(closes)
            macd_direction = "bullish" if macd["histogram"] > 0 else "bearish"
            macd_str = f"{macd['macd']:+.3f} / signal {macd['signal']:+.3f} ({macd_direction})"
        except ValueError:
            macd_str = None

        try:
            bb = quant.bollinger(closes)
            bb_str = (
                f"BB(20,2): SMA ${bb['sma']:.2f} | Upper ${bb['upper']:.2f} | Lower ${bb['lower']:.2f} "
                f"| %B {bb['percentB'] * 100:.1f}% | Bandwidth {bb['bandwidth'] * 100:.3f}%"
            )
        except ValueError:
            bb_str = ""

        indicators_line = (
            f"[Source: Yahoo Finance] Regime: {current_regime.upper()} "
            f"(bull {prob['bull']}% / bear {prob['bear']}% / sideways {prob['sideways']}%) | "
            f"RSI(14): {rsi_str}"
        )
        if macd_str:
            indicators_line += f" | MACD: {macd_str}"
        if bb_str:
            indicators_line += f" | {bb_str}"
        parts.append(indicators_line)

    intraday = market_data.fetch_intraday(symbol)
    if intraday and intraday["candles"]:
        recent = intraday["candles"][-8:]
        candle_str = ", ".join(f"{c['time']}:${c['close']}" for c in recent)
        parts.append(
            f"[Source: Yahoo Finance] Intraday: Open ${intraday['open']} | Current ${intraday['current']} "
            f"({intraday['change']:+.2f} / {intraday['changePercent']:+.2f}%) | "
            f"High ${intraday['high']} | Low ${intraday['low']} | Recent: {candle_str}"
        )
    source_urls.append({"source": "Yahoo Finance", "url": quote_url})
    return parts, source_urls


def _news_parts(symbol: str) -> tuple[list[str], list[dict]]:
    key = newsapi_key()
    if not key:
        return [], []
    try:
        resp = httpx.get(
            "https://newsapi.org/v2/everything",
            params={"q": symbol, "apiKey": key, "language": "en", "pageSize": 5},
            timeout=10.0,
        )
        articles = resp.json().get("articles", [])
        parts: list[str] = []
        source_urls: list[dict] = []
        for art in articles:
            date = art.get("publishedAt", "")[:10]
            parts.append(
                f"[Source: NewsAPI {date}] "
                f"{art.get('title', '')} — {art.get('description', '')[:200]}"
            )
            if art.get("url"):
                source_urls.append({"source": "NewsAPI", "date": date, "url": art["url"]})
        return parts, source_urls
    except Exception:
        logger.debug("NewsAPI context fetch failed for %s", symbol, exc_info=True)
        return [], []


def _analyst_part(symbol: str) -> tuple[list[str], list[dict]]:
    try:
        import yfinance as yf

        ticker_info = yf.Ticker(symbol).info
        rec_key = ticker_info.get("recommendationKey", "") or ""
        num_analysts = int(ticker_info.get("numberOfAnalystOpinions", 0) or 0)
        mean_target = ticker_info.get("targetMeanPrice", 0) or 0
        current_price_raw = ticker_info.get("currentPrice") or ticker_info.get("regularMarketPrice") or 0
        current_price = float(current_price_raw) if current_price_raw else 0

        if num_analysts > 0 and mean_target > 0 and current_price > 0:
            upside = round((mean_target - current_price) / current_price * 100, 1)
            return (
                [
                    f"[Source: Yahoo Finance analyst ratings] "
                    f"Analyst Consensus ({num_analysts} analysts): recommendation='{rec_key}' | "
                    f"Mean price target: ${mean_target:.2f} ({upside:+.1f}% upside) | "
                    f"Current price: ${current_price:.2f}"
                ],
                [{"source": "Yahoo Finance analyst", "url": f"https://finance.yahoo.com/quote/{symbol}/analysts"}],
            )
    except Exception:
        logger.debug("Analyst context fetch failed for %s", symbol, exc_info=True)
    return [], []


def _edgar_part(symbol: str) -> tuple[list[str], list[dict]]:
    try:
        fundamentals = _get_edgar_fundamentals(symbol)
        if fundamentals:
            cik = _cik_from_ticker(symbol)
            filing_url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K&dateb=&owner=include&count=10"
                if cik
                else "https://www.sec.gov/cgi-bin/browse-edgar"
            )
            return (
                [f"[Source: SEC EDGAR 10-K/10-Q]\n{fundamentals}"],
                [{"source": "SEC EDGAR", "url": filing_url}],
            )
    except Exception:
        logger.debug("EDGAR context fetch failed for %s", symbol, exc_info=True)
    return [], []


async def _build_context(symbol: str) -> tuple[str, list[dict]]:
    """
    Gather all context sources concurrently. Sync I/O (Yahoo sessions,
    yfinance, EDGAR) runs in worker threads so the event loop stays responsive.
    Returns (context_text, source_urls) — source_urls feed citation linking.
    """
    loop = asyncio.get_running_loop()

    news_task = loop.run_in_executor(None, _news_parts, symbol)
    daily_task = loop.run_in_executor(None, _daily_indicators_part, symbol)
    analyst_task = loop.run_in_executor(None, _analyst_part, symbol)
    edgar_task = loop.run_in_executor(None, _edgar_part, symbol)

    results = await asyncio.gather(news_task, daily_task, analyst_task, edgar_task, return_exceptions=True)
    context_parts: list[str] = []
    source_urls: list[dict] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("context source failed: %s", result)
            continue
        parts, urls = result
        context_parts.extend(parts)
        source_urls.extend(urls)

    if not context_parts:
        context_parts.append(
            f"No external data available for {symbol}. "
            f"Answer based on general knowledge, clearly state what you don't know, "
            f"and recommend consulting a financial advisor."
        )
    return "\n\n".join(context_parts), source_urls


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(req: ChatRequest):
    # Pick provider: request override → env override → auto-detect
    provider = (req.provider or default_provider()).lower()
    if provider not in ("anthropic", "gemini"):
        raise bad_request(f"Unknown provider: {provider}")
    if provider == "anthropic" and not anthropic_api_key():
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")
    if provider == "gemini" and not gemini_api_key():
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured")

    if req.symbol:
        try:
            symbol = normalize_symbol(req.symbol)
        except SymbolError as e:
            raise bad_request(str(e))
    else:
        symbol = "general"

    context, source_urls = await _build_context(symbol)

    try:
        if provider == "anthropic":
            answer = await _call_anthropic(context, req.message)
        else:
            answer = await _call_gemini(context, req.message)
    except Exception as e:
        logger.exception("LLM call failed (%s)", provider)
        raise HTTPException(status_code=502, detail=f"{provider} LLM error: {type(e).__name__}")

    answer = _extract_answer(answer)
    if not answer:
        raise HTTPException(status_code=502, detail="LLM returned empty answer")

    answer, citations = _extract_citations(answer)
    _link_citations(citations, source_urls)

    return {
        "answer": answer,
        "citations": citations,
        "provider": provider,
        "model": anthropic_model() if provider == "anthropic" else gemini_model(),
    }


@router.get("/providers")
def get_providers():
    """Which LLM providers are configured."""
    return {
        "default": default_provider(),
        "available": {
            "anthropic": bool(anthropic_api_key()),
            "gemini": bool(gemini_api_key()),
        },
        "models": {
            "anthropic": anthropic_model(),
            "gemini": gemini_model(),
        },
    }
