import os
import re
import httpx
import requests
import time
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

load_dotenv()

router = APIRouter()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemma-4-31b-it")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL")  # e.g. https://api.minimax.io/anthropic for MiniMax
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "MiniMax-M2.5")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

# ── LLM provider selection ──────────────────────────────────────────────────
# Priority: Anthropic (Claude) if configured, else Gemini.
# Override with LLM_PROVIDER=gemini or LLM_PROVIDER=anthropic in .env.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic" if ANTHROPIC_API_KEY else "gemini").lower()

# ── Yahoo Finance chart API session ──────────────────────────────────────────
_yf_session = requests.Session()
_yf_session.headers.update({
    "User-Agent": "FinanceAI/1.0 (contact@financeai.app; https://financeai.app) (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
})


class ChatRequest(BaseModel):
    message: str
    symbol: str | None = None
    provider: str | None = None  # override provider per-request ("anthropic" or "gemini")


class Citation(BaseModel):
    text: str
    source: str
    url: str | None = None


def _get_closes_yahoo(symbol: str, range_: str = "1y") -> tuple[list[float], dict] | None:
    """
    Fetch closing prices and meta from Yahoo Finance chart API.
    Returns (closes, meta) tuple or None on failure.
    """
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
        r = result[0]
        closes = [c for c in r["indicators"]["quote"][0]["close"] if c is not None]
        meta = r.get("meta", {})
        return closes, meta
    except Exception:
        return None


def _get_intraday_yahoo(symbol: str) -> dict | None:
    """
    Fetch 1-hour interval data for the current trading day.
    Returns {open, high, low, close, change, changePercent, candles} or None.
    """
    try:
        resp = _yf_session.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1h", "range": "1d"},
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

        candles = []
        for i, ts in enumerate(timestamps):
            close = quote.get("close", [None])[i]
            high = quote.get("high", [None])[i]
            low = quote.get("low", [None])[i]
            if close is None:
                continue
            candles.append({
                "time": datetime.fromtimestamp(ts).strftime("%H:%M"),
                "close": round(float(close), 2),
                "high": round(float(high), 2) if high else None,
                "low": round(float(low), 2) if low else None,
            })

        if not candles:
            return None

        current_price = float(meta.get("regularMarketPrice", candles[-1]["close"]))
        prev_price = float(meta.get("previousClose", candles[0]["close"])) if len(candles) > 1 else current_price
        day_open = float(meta.get("regularMarketOpen", candles[0]["close"]))
        day_change = current_price - prev_price
        day_change_pct = (day_change / prev_price * 100) if prev_price else 0.0

        valid_highs = [c["high"] for c in candles if c["high"] is not None]
        valid_lows = [c["low"] for c in candles if c["low"] is not None]
        return {
            "open": round(day_open, 2),
            "current": round(current_price, 2),
            "high": round(max(valid_highs), 2) if valid_highs else None,
            "low": round(min(valid_lows), 2) if valid_lows else None,
            "change": round(day_change, 2),
            "changePercent": round(day_change_pct, 2),
            "candles": candles,
        }
    except Exception:
        return None


# ── SEC EDGAR10-K / 10-Q Fetcher ─────────────────────────────────────────────
# No API key required. Respects SEC rate limits: 10 reqs/sec per IP.
# Throttle is enforced via a module-level cooldown variable.

_edgar_last_call = 0.0
_EDGAR_DELAY = 0.11  # seconds between calls to stay under 10/sec
_edgar_cik_cache: dict[str, str] = {}  # symbol → zero-padded CIK, cached for session


def _edgar_throttle():
    """Wait if needed to respect SEC EDGAR rate limits."""
    global _edgar_last_call
    elapsed = time.time() - _edgar_last_call
    if elapsed < _EDGAR_DELAY:
        time.sleep(_EDGAR_DELAY - elapsed)
    _edgar_last_call = time.time()


def _cik_from_ticker(symbol: str) -> str | None:
    """
    Look up CIK for a ticker symbol using the SEC company tickers JSON.
    Returns the CIK as a zero-padded string, or None if not found.
    Cached in module-level _edgar_cik_cache to avoid repeated fetches.
    """
    if symbol.upper() in _edgar_cik_cache:
        return _edgar_cik_cache[symbol.upper()]

    try:
        _edgar_throttle()
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "FinanceAI/1.0 (contact@financeai.app; https://financeai.app) (compatible; FinanceAI/1.0)", "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        companies = resp.json()
        # The JSON is a dict keyed by a sequential index; each entry has a cik_str field
        for _, info in companies.items():
            if info.get("ticker", "").upper() == symbol.upper():
                cik = str(info["cik_str"]).zfill(10)
                _edgar_cik_cache[symbol.upper()] = cik
                return cik
        return None
    except Exception:
        return None


def _get_filing_document(primary_document: str, accession_number: str, cik: str) -> str | None:
    """
    Fetch the raw HTML of a filing given its document name, accession number, and CIK.
    Constructs URL: https://www.sec.gov/Archives/edgar/data/{cik}/{accn_clean}/{doc}
    Returns HTML text or None.
    """
    try:
        accn_clean = accession_number.replace("-", "").replace(" ", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_clean}/{primary_document}"
        _edgar_throttle()
        resp = requests.get(url, headers={"User-Agent": "FinanceAI/1.0 (contact@financeai.app; https://financeai.app)"}, timeout=20)
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception:
        return None


def _extract_filing_summary(html: str, filing_type: str) -> str:
    """
    Parse a10-K or 10-Q HTML filing and extract key financial highlights.
    Returns a compact multi-line string.
    """
    if not BeautifulSoup:
        return ""

    try:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)

        highlights = []

        # ── Revenue ────────────────────────────────────────────────────────────
        # 10-K/10-Q tables: "Total net sales $ 416,161" or "Total net sales 416,161" (in millions)
        # Use \d+ to avoid non-greedy matching issues with commas in the number
        m = re.search(r"Total net sales\s+\$?\s*(\d+)", text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            highlights.append(f"Revenue: ${val:,}M")

        # ── Net Income ─────────────────────────────────────────────────────────
        # Table format: "Net income $ 112,010" (in millions)
        m = re.search(r"Net\s+income\s+\$?\s*(\d+)", text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            highlights.append(f"Net Income: ${val:,}M")

        # ── EPS ────────────────────────────────────────────────────────────────
        eps_m = re.search(r"Earnings per share: Basic \$ ([0-9.]+)", text, re.IGNORECASE)
        if eps_m:
            highlights.append(f"EPS (Basic): ${eps_m.group(1)}")

        # ── Forward Guidance / Outlook ─────────────────────────────────────────
        # Item 7 in 10-K contains Management's Discussion — look for outlook/guidance
        for pat in [
            r"(?:outlook|guidance|forecast|expects|anticipates)[^.]{0,200}\.",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                highlights.append(f"Outlook: {m.group(0)[:180].strip()}")
                break

        # ── Key Risk Factors (10-K only) ────────────────────────────────────────
        # Use findall + pop() to get the LAST occurrence — the TOC entry "Item 1A. Risk Factors"
        # appears first in document order; the actual Risk Factors section is later.
        if filing_type == "10-K":
            risk_matches = re.findall(r"Item\s*1A[^.]{0,300}\.", text, re.IGNORECASE)
            if risk_matches:
                last_risk = risk_matches[-1]
                highlights.append(f"Key Risks: {last_risk[:180].strip()}")

        return " | ".join(highlights) if highlights else ""

    except Exception:
        return ""


def _get_edgar_fundamentals(symbol: str) -> str:
    """
    Fetch latest10-K and 10-Q filings from SEC EDGAR and return a compact
    fundamental summary string. Returns empty string on failure.
    """
    cik = _cik_from_ticker(symbol)
    if not cik:
        return ""

    try:
        _edgar_throttle()
        resp = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers={"User-Agent": "FinanceAI/1.0 (contact@financeai.app; https://financeai.app)", "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            return ""
        data = resp.json()
    except Exception:
        return ""

    try:
        filings_recent = data.get("filings", {}).get("recent", {})
        accession_numbers = filings_recent.get("accessionNumber", [])
        filing_types = filings_recent.get("form", [])
        filing_dates = filings_recent.get("filingDate", [])
        primary_docs = filings_recent.get("primaryDocument", [])

        # Collect latest 10-K and 10-Q (up to 2 of each)
        targets = {"10-K": [], "10-Q": []}
        for i, form in enumerate(filing_types):
            if form in targets and len(targets[form]) < 2:
                targets[form].append({
                    "accessionNumber": accession_numbers[i],
                    "filingDate": filing_dates[i],
                    "primaryDocument": primary_docs[i],
                })

        parts = []
        # Always try 10-K first (annual fundamentals most useful for context)
        for filing_type, candidates in targets.items():
            for candidate in candidates:
                html = _get_filing_document(candidate["primaryDocument"], candidate["accessionNumber"], cik)
                if html:
                    summary = _extract_filing_summary(html, filing_type)
                    if summary:
                        parts.append(
                            f"{filing_type} ({candidate['filingDate']}): {summary}"
                        )
                        break  # Got a useful summary, move to next filing type
            # Early termination: if we got a 10-K summary, skip 10-Q fetches
            # (10-K annual fundamentals are sufficient for RAG context)
            if parts and parts[-1].startswith("10-K"):
                break

        return "\n".join(parts)
    except Exception:
        return ""


SYSTEM_PROMPT = (
    "You are a transparent, data-driven stock analysis assistant. "
    "Write thorough 5-10 sentence analysis answers. "
    "Always cite sources inline as [Source: name date]. "
    "You may use general knowledge about well-known public companies to explain what they do. "
    "Only say 'I am not certain' when the question is about a specific data point you cannot find. "
    "Never fabricate numbers, dates, or sources."
)

USER_PROMPT_TEMPLATE = """Based on the data below, give a thorough stock analysis answering the user's question. Write 5-10 clear sentences. Cite sources inline as [Source: name date].

IMPORTANT: Put your final answer between the delimiters <<<ANSWER>>> and <<<END>>> like this:

<<<ANSWER>>>
Your analysis here. Cite sources inline as [Source: name date].
<<<END>>>

Do not output anything outside these delimiters. No preamble, no chain-of-thought, no echoing the prompt.

---
DATA:
{context}
---
QUESTION: {message}
"""


async def _call_gemini(context: str, message: str) -> str:
    """Call Google Gemini via REST."""
    user_prompt = USER_PROMPT_TEMPLATE.format(context=context, message=message)
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            params={"key": GEMINI_API_KEY},
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
    """Call Anthropic Claude via the official SDK (or any Anthropic-compatible endpoint)."""
    import anthropic

    user_prompt = USER_PROMPT_TEMPLATE.format(context=context, message=message)

    # Lazy client — created on first use to avoid init errors when key missing
    # ANTHROPIC_BASE_URL lets you point at MiniMax / any Anthropic-compatible proxy
    client_kwargs = {"api_key": ANTHROPIC_API_KEY}
    if ANTHROPIC_BASE_URL:
        client_kwargs["base_url"] = ANTHROPIC_BASE_URL
    client = anthropic.AsyncAnthropic(**client_kwargs)
    response = await client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2048,
        temperature=0.5,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    # Concatenate all text-type content blocks. Some providers (MiniMax M2.7)
    # return a "thinking" block (text=None) followed by the actual "text" block.
    # The default `response.content[0].text` grabs the thinking block and crashes.
    text_parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text" and getattr(block, "text", None):
            text_parts.append(block.text)
    if not text_parts:
        # Fallback: try the first block's text defensively.
        if response.content and getattr(response.content[0], "text", None):
            text_parts.append(response.content[0].text)
    return "\n".join(text_parts)


def _extract_citations(answer: str) -> tuple[str, list[dict]]:
    """Parse [Source: name date] inline tags from the answer text."""
    found = re.findall(r'\[Source: ([^\]]+)\]', answer)
    citations = []
    for f in found:
        parts = f.rsplit(" ", 1)
        src = parts[0] if parts else f
        date = parts[1] if len(parts) > 1 else ""
        citations.append({"text": f.strip(), "source": src.strip(), "url": None})
    answer = re.sub(r'\[Source: [^\]]+\]', '', answer).strip()
    return answer, citations


def _extract_answer(raw: str) -> str:
    """
    Pull the actual answer out of the LLM response. The model sometimes echoes
    the system prompt or shows chain-of-thought; we asked it to wrap the final
    answer in <<<ANSWER>>>...<<<END>>>, so prefer that. Fall back to the last
    non-empty paragraph if the delimiters are missing.
    """
    if not raw:
        return raw

    m = re.search(r"<<<ANSWER>>>\s*(.*?)\s*<<<END>>>", raw, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Opening delimiter without closing — model was truncated by max_tokens.
    # Take everything after the opening delimiter.
    open_match = re.search(r"<<<ANSWER>>>\s*(.*)", raw, re.DOTALL)
    if open_match:
        return open_match.group(1).strip()

    # Fallback: take everything after the last "<<<END>>>" if it appears, or
    # after the last "*Sentence N:*" line, or just the last non-empty paragraph.
    end_match = list(re.finditer(r"<<<END>>>", raw))
    if end_match:
        after = raw[end_match[-1].end():].strip()
        if after:
            return after

    # Heuristic: find the last *-bulleted paragraph that contains a [Source: ...]
    # citation and looks like a final answer (declarative, short-ish, has substance).
    # The model wraps its CoT in * bullets and the actual answer is the LAST such
    # bullet that cites a source.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    candidates = [p for p in paragraphs if "[Source:" in p]
    if candidates:
        # Prefer the LAST cited paragraph (the model puts its final answer last).
        return candidates[-1]

    # Otherwise pick the LAST paragraph that doesn't look like internal reasoning
    # (reasoning lines typically have these markers).
    reasoning_markers = ("I am not certain", "Check constraints", "Refining", "Wait,", "Let me", "Let's", "Draft", "Alternative", "*Refining")
    for p in reversed(paragraphs):
        if not any(marker in p for marker in reasoning_markers):
            return p

    return raw.strip()


@router.post("/chat")
async def chat(req: ChatRequest):
    # Pick provider: request override → env override → auto-detect
    provider = (req.provider or LLM_PROVIDER).lower()
    if provider == "anthropic" and not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")
    if provider == "gemini" and not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
    if provider not in ("anthropic", "gemini"):
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    symbol = req.symbol or "general"
    context = await _build_context(symbol, req.message)

    try:
        if provider == "anthropic":
            answer = await _call_anthropic(context, req.message)
        else:
            answer = await _call_gemini(context, req.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{provider} LLM error: {str(e)}")

    # Strip prompt-echo / chain-of-thought, keep only the final answer.
    answer = _extract_answer(answer)
    if not answer:
        raise HTTPException(status_code=502, detail="LLM returned empty answer")

    answer, citations = _extract_citations(answer)

    # Include the actual model name so the UI can show "via MiniMax-M2.7" etc.
    model = ANTHROPIC_MODEL if provider == "anthropic" else GEMINI_MODEL

    return {
        "answer": answer,
        "citations": citations,
        "provider": provider,
        "model": model,
    }


@router.get("/providers")
def get_providers():
    """Return which LLM providers are available."""
    return {
        "default": LLM_PROVIDER,
        "available": {
            "anthropic": bool(ANTHROPIC_API_KEY),
            "gemini": bool(GEMINI_API_KEY),
        },
        "models": {
            "anthropic": ANTHROPIC_MODEL,
            "gemini": GEMINI_MODEL,
        },
    }


async def _build_context(symbol: str, query: str) -> str:
    import numpy as np

    context_parts = []

    # ── NewsAPI ───────────────────────────────────────────────────────────────
    if NEWSAPI_KEY:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(
                    "https://newsapi.org/v2/everything",
                    params={"q": symbol, "apiKey": NEWSAPI_KEY, "language": "en", "pageSize": 5},
                    timeout=10.0,
                )
                articles = res.json().get("articles", [])
                for art in articles:
                    context_parts.append(
                        f"[Source: NewsAPI {art.get('publishedAt', '')[:10]}] {art.get('title', '')} — {art.get('description', '')[:200]}"
                    )
        except Exception:
            pass

    # ── Yahoo Finance — price, regime, volatility, RSI, Bollinger, analyst ─────
    try:
        result = _get_closes_yahoo(symbol, range_="1y")
        if result:
            closes, meta = result
        else:
            closes, meta = None, {}

        if closes and len(closes) >= 30:
            closes = np.array(closes)
            returns = np.diff(np.log(closes))
            last_price = round(float(closes[-1]), 2)
            mom_20d = round(float(returns[-20:].sum() * 100), 2) if len(returns) >= 20 else 0.0
            vol_20d = round(float(returns[-20:].std() * np.sqrt(252) * 100), 2) if len(returns) >= 20 else 0.0
            avg_return = round(float(returns.mean() * 252 * 100), 2)

            # Regime: same threshold logic as models router
            regimes = np.where(returns > 0.005, 2, np.where(returns < -0.005, 0, 1))
            regime_names = {0: "bear", 1: "sideways", 2: "bull"}
            current_regime = regime_names[int(regimes[-1])]
            regime_counts = {regime_names[k]: int(np.sum(regimes == k)) for k in range(3)}
            total_days = len(regimes)
            prob_bull = round(regime_counts["bull"] / total_days * 100, 1)
            prob_bear = round(regime_counts["bear"] / total_days * 100, 1)
            prob_sideways = round(regime_counts["sideways"] / total_days * 100, 1)

            # RSI(14) — Wilder's method
            gains = np.where(returns > 0, returns, 0.0)
            losses = np.where(returns < 0, -returns, 0.0)
            avg_gain = gains[-14:].mean()
            avg_loss = losses[-14:].mean()
            for i in range(14, len(closes)):
                avg_gain = (avg_gain * (14 - 1) + gains[i - 1]) / 14
                avg_loss = (avg_loss * (14 - 1) + losses[i - 1]) / 14
            rs = avg_gain / avg_loss if avg_loss > 0 else 0
            rsi = round(100 - 100 / (1 + rs), 1)
            rsi_signal = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"

            # Bollinger Bands (20, 2)
            period = 20
            num_std = 2.0
            if len(closes) >= period:
                window = closes[-period:]
                sma = window.mean()
                std = window.std()
                upper = sma + num_std * std
                lower = sma - num_std * std
                bandwidth = round((upper - lower) / sma * 100, 3) if sma != 0 else 0
                pct_b = round((closes[-1] - lower) / (upper - lower) * 100, 1) if (upper - lower) != 0 else 0
                bb_str = f"BB(20,2): SMA ${sma:.2f} | Upper ${upper:.2f} | Lower ${lower:.2f} | %B {pct_b:.1f}% | Bandwidth {bandwidth:.3f}%"
            else:
                bb_str = ""

            # MACD (12,26,9)
            def _ema(values, span):
                ema = np.zeros(len(values))
                ema[0] = values[0]
                alpha = 2 / (span + 1)
                for i in range(1, len(values)):
                    ema[i] = alpha * values[i] + (1 - alpha) * ema[i - 1]
                return ema

            ema_fast = _ema(closes, 12)
            ema_slow = _ema(closes, 26)
            macd_line = ema_fast - ema_slow
            signal_line = _ema(macd_line, 9)
            macd_current = round(float(macd_line[-1]), 3)
            signal_current = round(float(signal_line[-1]), 3)
            histogram = round(float(macd_line[-1] - signal_line[-1]), 3)
            macd_signal = "bullish" if histogram > 0 else "bearish"

            # Company meta
            company_name = meta.get("shortName") or meta.get("longName") or symbol
            market_cap_str = ""
            mc = meta.get("marketCap")
            if mc:
                if mc >= 1e12: market_cap_str = f"${mc / 1e12:.2f}T"
                elif mc >= 1e9: market_cap_str = f"${mc / 1e9:.2f}B"
                elif mc >= 1e6: market_cap_str = f"${mc / 1e6:.2f}M"
                else: market_cap_str = f"${mc:,.0f}"

            pe = meta.get("trailingPE")
            pe_str = f"{pe:.1f}" if pe and pe > 0 else "N/A"
            week_high = meta.get("fiftyTwoWeekHigh")
            week_low = meta.get("fiftyTwoWeekLow")
            high_str = f"${week_high:.2f}" if week_high else "N/A"
            low_str = f"${week_low:.2f}" if week_low else "N/A"

            context_parts.append(
                f"[Source: Yahoo Finance] {company_name} ({symbol}) | "
                f"Price: ${last_price} | Market Cap: {market_cap_str or 'N/A'} | P/E: {pe_str} | "
                f"52W High: {high_str} | 52W Low: {low_str} | "
                f"20-Day Momentum: {mom_20d:+.1f}% | Annualized Vol: {vol_20d:.1f}% | "
                f"Annualized Return: {avg_return:+.1f}%"
            )

            context_parts.append(
                f"[Source: Yahoo Finance] Regime: {current_regime.upper()} (bull {prob_bull}% / "
                f"bear {prob_bear}% / sideways {prob_sideways}%) | "
                f"RSI(14): {rsi} ({rsi_signal}) | MACD: {macd_current:+.3f} / signal {signal_current:+.3f} ({macd_signal})"
                + (f" | {bb_str}" if bb_str else "")
            )

            # Intraday
            intraday = _get_intraday_yahoo(symbol)
            if intraday and intraday["candles"]:
                open_p = intraday["open"]
                current_p = intraday["current"]
                high_p = intraday["high"]
                low_p = intraday["low"]
                chg = intraday["change"]
                chg_pct = intraday["changePercent"]
                recent = intraday["candles"][-8:]
                candle_str = ", ".join(f"{c['time']}:${c['close']}" for c in recent)
                context_parts.append(
                    f"[Source: Yahoo Finance] Intraday: Open ${open_p} | Current ${current_p} "
                    f"({chg:+.2f} / {chg_pct:+.2f}%) | High ${high_p} | Low ${low_p} | "
                    f"Recent: {candle_str}"
                )
    except Exception:
        pass

    # ── Analyst consensus from Yahoo Finance (via yfinance, no API key needed) ─
    try:
        import yfinance as yf
        ticker_info = yf.Ticker(symbol).info
        rec_key = ticker_info.get("recommendationKey", "") or ""
        num_analysts = int(ticker_info.get("numberOfAnalystOpinions", 0) or 0)
        mean_target = ticker_info.get("targetMeanPrice", 0) or 0
        current_price_raw = ticker_info.get("currentPrice") or ticker_info.get("regularMarketPrice") or 0
        current_price_yf = float(current_price_raw) if current_price_raw else 0

        if num_analysts > 0 and mean_target > 0 and current_price_yf > 0:
            upside = round((mean_target - current_price_yf) / current_price_yf * 100, 1)
            rec_summary = (
                f"Analyst Consensus ({num_analysts} analysts): recommendation='{rec_key}' | "
                f"Mean price target: ${mean_target:.2f} ({upside:+.1f}% upside) | "
                f"Current price: ${current_price_yf:.2f}"
            )
            context_parts.append(f"[Source: Yahoo Finance analyst ratings] {rec_summary}")
    except Exception:
        pass

    # ── SEC EDGAR fundamentals ─────────────────────────────────────────────────
    try:
        fundamentals = _get_edgar_fundamentals(symbol)
        if fundamentals:
            context_parts.append(f"[Source: SEC EDGAR 10-K/10-Q]\n{fundamentals}")
    except Exception:
        pass

    if not context_parts:
        context_parts.append(
            f"No external data available for {symbol}. "
            f"Answer based on general knowledge, clearly state what you don't know, and recommend consulting a financial advisor."
        )

    return "\n\n".join(context_parts)
