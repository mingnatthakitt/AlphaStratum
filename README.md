# Alpha Stratum

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/frontend-React-61DAFB.svg)](https://reactjs.org/)
[![Next.js](https://img.shields.io/badge/next.js-14-black.svg?style=flat&logo=next.js&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/typescript-5.5-blue.svg)](https://www.typescriptlang.org/)
[![Tailwind CSS](https://img.shields.io/badge/tailwind-3.4-38B2AC.svg?style=flat&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![Supabase](https://img.shields.io/badge/database-PostgreSQL-3ECF8E.svg?style=flat&logo=supabase&logoColor=white)](https://supabase.com/)
[![Anthropic](https://img.shields.io/badge/llm-Claude/MiniMax-FF6F00.svg)](https://anthropic.com)
[![AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green.svg)](https://www.gnu.org/licenses/agpl-3.0.en.html)

> AI-powered quantitative stock analysis — regime detection, Monte Carlo forecasting, technical indicators, risk models, and grounded AI chat with live source citations.

Read [LIMITATIONS.md](LIMITATIONS.md) for the honest list of what this app does not do (single-user auth model, unofficial data sources, quant approximations), and [CHANGELOG.md](CHANGELOG.md) for what changed recently.

## Screenshots

| Dashboard | Models |
|---|---|
| ![Dashboard](images/Dashboard.png) | ![Models](images/Models.png) |

| Backtest | Portfolio |
|---|---|
| ![Backtest](images/Backtest.png) | ![Portfolio](images/Portfolio.png) |

| AI Advisor | Screener |
|---|---|
| ![Advisor](images/Advisor.png) | ![Screener](images/Screener.png) |

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 14 (App Router) + TypeScript + Tailwind |
| Charts | `lightweight-charts` (TradingView) + d3-force |
| Backend | FastAPI (Python) — see `fastapi-backend/services/` for the data & math layers |
| Database | PostgreSQL (Supabase) via psycopg connection pool |
| LLM | Claude or MiniMax via the Anthropic SDK; Gemini via REST |
| AI Context | Live data injection + inline citations (not vector RAG — see LIMITATIONS.md) |
| Data | Yahoo Finance, NewsAPI, SEC EDGAR |
| Math | `arch`, `numpy`, `networkx` |
| Deploy | Vercel (frontend) + Render (backend, `render.yaml` included) |

## Features

### Dashboard (`/dashboard`)
Real-time price chart with candlestick/area view toggle. Select any model (RSI, MACD, Bollinger, GARCH, ATR, Markov, Monte Carlo) from a dropdown to pull up a synchronized comparison panel — all charts display real trading-day dates. Regime classification uses fixed daily log-return thresholds (±0.5%).

### Quantitative Models (`/models`)
All models use a shared 15-minute result cache backed by Supabase Postgres.

| Model | Endpoint | Description |
|---|---|---|
| **Monte Carlo GBM** | `GET /models/montecarlo/{symbol}` | 1,000 simulated price paths with percentile fan bands (p5–p95). Regime-aware drift adjustment. |
| **Regime-Conditional MC** | `GET /models/montecarlo/{symbol}/regime-cond` | 3 separate GBM fans (bull/bear/sideways) blended by Markov n-step probabilities at each horizon day. More accurate near-term than single-regime GBM. |
| **GARCH Volatility** | `GET /models/garch/{symbol}` | GARCH(1,1) conditional volatility forecast, 30-day horizon |
| **Markov Regime Chain** | `GET /models/markov/{symbol}` | Threshold-regime Markov chain: estimated transition matrix + 1/3/10-step probability forecast across bull/bear/sideways regimes |
| **ATR** | `GET /models/atr/{symbol}` | Average True Range (14-period default) with volatility signal (high/normal/low) and position sizing hint |
| **RSI** | `GET /models/rsi/{symbol}` | 14-day Wilder-smoothed RSI with overbought/oversold signal and 30-day history |
| **MACD** | `GET /models/macd/{symbol}` | 12/26/9 MACD with signal line and histogram history |
| **Bollinger Bands** | `GET /models/bollinger/{symbol}` | 20-day SMA ± 2σ with %B, bandwidth, and 60-bar history |
| **Correlation Network** | `GET /models/correlation-graph` | Pearson correlation MST (Minimum Spanning Tree) across sectors, color-coded by correlation strength |
| **Value at Risk (VaR)** | `POST /models/var` | 1-day Historical VaR at 95% and 99% confidence with per-symbol contributions |
| **Pairs / Beta** | `GET /models/pairs?a=NVDA&b=AMD` | Beta, Pearson correlation, and covariance between two tickers |
| **Analyst Ratings** | `GET /models/analyst/{symbol}` | Yahoo Finance buy/hold/sell consensus, mean price target, and upside/downside vs current price |

### Stock Screener (`/screener`)
Rank stocks by regime stability + momentum across 5 sector tabs (Tech, Finance, Healthcare, Energy, ETF). Portfolio stocks (starred) only appear in their actual sector category. Score = regime score (0-40) + momentum score (0-40) − volatility penalty (0-20).

### Portfolio (`/portfolio`)
Persistent multi-lot holdings backed by Supabase Postgres. Add multiple purchase instances of the same symbol at different price points. Track total value, cost basis, per-lot and aggregate P&L.

### Backtest (`/backtest`)
Hypothetical investment calculator. Enter a ticker, entry date, and dollar amount to see what the position would be worth today vs. entry price — shares bought, total return, percentage gain/loss.

### AI Advisor (`/advisor`)
Chat with live context-injected responses. Every answer is generated with news, prices, filings, and quantitative data fetched at query time and injected into the prompt — no black boxes. Each claim is cited with its source:

| Data | Source | Cited as |
|---|---|---|
| News headlines (5 latest) | NewsAPI | `[Source: NewsAPI YYYY-MM-DD]` |
| Price, market cap, P/E, 52W high/low | Yahoo Finance | `[Source: Yahoo Finance]` |
| Regime (bull/bear/sideways) + probabilities | Yahoo Finance closes (computed) | `[Source: Yahoo Finance]` |
| RSI(14) + signal | Yahoo Finance closes (computed) | `[Source: Yahoo Finance]` |
| MACD(12,26,9) + signal + histogram | Yahoo Finance closes (computed) | `[Source: Yahoo Finance]` |
| Bollinger Bands (SMA, upper/lower, %B, bandwidth) | Yahoo Finance closes (computed) | `[Source: Yahoo Finance]` |
| Intraday 1-hour candles | Yahoo Finance intraday | `[Source: Yahoo Finance]` |
| Analyst consensus (rating, price target, upside %) | Yahoo Finance (yfinance, no API key) | `[Source: Yahoo Finance analyst ratings]` |
| SEC 10-K/10-Q (revenue, net income, EPS, outlook, risks) | SEC EDGAR | `[Source: SEC EDGAR 10-K/10-Q]` |

The LLM sees the same technical indicators as the `/models` page — regime probabilities, RSI, MACD, Bollinger — plus analyst ratings and intraday prices. All inline citations let you verify every claim.

---

## Deployment

### Option A — Vercel (frontend) + Render (backend) *(recommended)*

#### 1. Fork / clone the repo

```bash
git clone https://github.com/your-username/alpha-stratum.git
cd alpha-stratum
```

#### 2. Set up Supabase

1. Create a project at [supabase.com](https://supabase.com)
2. In the **SQL Editor**, run the schema from `supabase/schema.sql`
3. Go to **Settings → Connection Pooling** and copy the **AWS pooler** connection string (format: `postgresql://postgres.xxx:xxx@aws-1-xxx.pooler.supabase.com:6543/postgres`). The direct DB host is IPv6-only — the pooler provides IPv4 access required by cloud platforms like Render.
4. Copy the pooler connection string as your `DATABASE_URL`

#### 3. Deploy the FastAPI backend on Render

Easiest: Render → **New → Blueprint** → select the repo (uses the included `render.yaml`, which sets `/health` as the health check and generates `AUTH_PASSWORD` for you). Or create a **New → Web Service** manually:

1. Create a [Render](https://render.com) account
2. Connect your GitHub repo
3. Create a **New → Web Service**
   - **Root Directory:** `fastapi-backend`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'`
4. Add environment variables from `fastapi-backend/.env.example`:
   - `DATABASE_URL` — Supabase AWS pooler connection string
   - `AUTH_PASSWORD` — strong random string (e.g. `openssl rand -base64 32`) — **required**
   - `AUTH_DEV_MODE=0` — leave at `0`. Setting `1` turns authentication off entirely
   - `CORS_ORIGINS` — your Vercel frontend URL (e.g. `https://your-app.vercel.app`)
   - `ANTHROPIC_API_KEY` (optionally `ANTHROPIC_BASE_URL` + `ANTHROPIC_MODEL`) or `GEMINI_API_KEY`
   - `NEWSAPI_KEY`
5. Deploy — wait for the service to come online at `https://your-backend.onrender.com`

> ##### ⚠️ The backend is a public URL — `AUTH_PASSWORD` is your only lock
>
> Vercel's authentication protects the **frontend pages**. It does nothing for
> `https://your-backend.onrender.com`, which anyone on the internet can call
> directly, bypassing the frontend completely. `AUTH_PASSWORD` is the only thing
> standing between that URL and your portfolio, watchlist and LLM key.
>
> The API **fails closed**: if `AUTH_PASSWORD` is missing, empty, or still the
> `.env.example` placeholder, every route returns `503` rather than serving the
> request. It will never quietly fall back to anonymous access. If the UI shows
> `503 Authentication is not configured on this server`, set a real
> `AUTH_PASSWORD` on Render **and** the matching `AUTH_KEY` on Vercel.
>
> Verify it from outside the app before you trust it:
> `curl -i https://your-backend.onrender.com/models/regime/AAPL` must return
> **401**. If it returns 200, stop and fix `AUTH_PASSWORD` — nothing else on this
> page protects that endpoint.

#### 4. Deploy the Next.js frontend on Vercel

1. Create a [Vercel](https://vercel.com) account and import the repo
2. Set **Root Directory:** `nextjs-app`
3. Add environment variables:
   - `NEXT_PUBLIC_API_URL` — your Render backend URL (e.g. `https://your-backend.onrender.com`)
   - `AUTH_KEY` — must match `AUTH_PASSWORD` you set on Render
4. Deploy

The Vercel frontend uses a server-side proxy at `/api/proxy` that attaches the auth key to every request, so the key is never exposed to the browser.

#### 5. Update Render's `DATABASE_URL`

If you change the Supabase connection string in the future, update the `DATABASE_URL` env var directly in the Render dashboard — **no redeploy needed**. `DATABASE_URL` and `AUTH_PASSWORD` are read from the environment on every request, as are the LLM/data keys, so rotating one takes effect on the next call.

> **Render's `sync: false` variables are created as empty strings, not left unset.** The code treats a blank value as "not configured" and falls back to its built-in default, so leaving `ANTHROPIC_MODEL` empty is safe (it uses the built-in default model) rather than sending an empty model name to the provider.

> **Render free tier:** free instances spin down after ~15 minutes idle and need 50s+ to wake. The first request after an idle period exceeds the frontend proxy's 25s default timeout and will appear to fail in the UI. Use an always-on instance for real use — see [LIMITATIONS.md](LIMITATIONS.md).

---

### Option B — Run everything locally

#### 1. Clone & install

```bash
git clone https://github.com/your-username/alpha-stratum.git
cd alpha-stratum
```

#### 2. Supabase (local or cloud)

```bash
# Option B1 — Supabase local (Docker)
supabase init
supabase start
# Run schema: paste contents of supabase/schema.sql into the local SQL editor
# Local connection string: postgresql://postgres:postgres@127.0.0.1:54322/postgres

# Option B2 — Supabase cloud
# Follow steps in Option A section 2, then copy pooler URL as DATABASE_URL
```

#### 3. Frontend

```bash
cd nextjs-app
cp .env.local.example .env.local
# Fill in:
#   NEXT_PUBLIC_API_URL=http://localhost:8000
#   AUTH_KEY=your_auth_password (must match AUTH_PASSWORD in fastapi-backend/.env)

npm ci        # honours package-lock.json (use `npm install` if you changed deps)
npm run dev
# → http://localhost:3000
```

#### 4. Backend

```bash
cd fastapi-backend
cp .env.example .env
# Fill in all variables — copy from .env.example and set real values:
#   DATABASE_URL=postgresql://postgres.xxx:xxx@aws-1-xxx.pooler.supabase.com:6543/postgres
#   GEMINI_API_KEY=...  (or ANTHROPIC_API_KEY + ANTHROPIC_BASE_URL)
#   NEWSAPI_KEY=...
#   AUTH_PASSWORD=...    (must match AUTH_KEY in nextjs-app/.env.local)
#   AUTH_DEV_MODE=0      (leave at 0; 1 disables auth for local experiments only)

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# → http://localhost:8000
```

> **Note:** The backend runs on port **8000** locally (not 10001). Update `NEXT_PUBLIC_API_URL` in `.env.local` to `http://localhost:8000` if you use a different port.

> **Running the backend locally with no password at all?** Set `AUTH_DEV_MODE=1` in
> `fastapi-backend/.env`. This is the *only* way to get an unauthenticated API.
> If `AUTH_PASSWORD` is missing, empty, or still the `.env.example` placeholder,
> every route returns `503` and logs an error at startup — by design, because
> the same code runs on Render where a public URL with no password is an open
> API.

---

## API Reference

All endpoints (including `/rag/chat` and `/`) require the shared secret; only `/health` is public, because Render's health check has no credential to present. `/health` deliberately reports nothing about authentication.

The secret is accepted in either of two places:

- **`X-Auth-Key: <secret>` header** — preferred. The Next.js proxy uses this so the secret never lands in an access log, a CDN log, or browser history. Calling the API directly:
  ```bash
  curl -H "X-Auth-Key: $AUTH_PASSWORD" http://localhost:8000/fetch/ticker/AAPL
  ```
- **`?key=<secret>` query parameter** — still accepted for convenience (`curl` and Swagger), but note it is written to uvicorn's access log.

### Fetch
| Method | Path | Description |
|---|---|---|
| GET | `/fetch/ticker/{symbol}` | OHLCV data + stock info |
| GET | `/fetch/quotes?symbols=AAPL,MSFT` | Minimal quotes (price/change/changePercent) for up to 20 symbols |
| GET | `/fetch/news/{symbol}` | News articles from NewsAPI |

### Models
| Method | Path | Description |
|---|---|---|
| GET | `/models/regime/{symbol}` | Threshold-based bull/bear/sideways regime |
| GET | `/models/montecarlo/{symbol}` | Monte Carlo GBM paths (days: 15/30/60/90/180) |
| GET | `/models/montecarlo/{symbol}/regime-cond` | Regime-conditional MC — 3 GBM fans blended by Markov probabilities |
| GET | `/models/garch/{symbol}` | GARCH(1,1) volatility forecast |
| GET | `/models/markov/{symbol}` | Markov regime transition matrix + 1/3/10-step forecast |
| GET | `/models/atr/{symbol}` | Average True Range with volatility signal and position sizing hint |
| GET | `/models/rsi/{symbol}` | RSI(14) with signal and 30-day history |
| GET | `/models/macd/{symbol}` | MACD(12,26,9) with histogram |
| GET | `/models/bollinger/{symbol}` | Bollinger Bands(20,2) with %B and bandwidth |
| GET | `/models/correlation-graph?sector=tech` | Sector correlation MST (sectors: tech, finance, healthcare, energy, etf) |
| POST | `/models/var` | 1-day Historical VaR (POST body below) |
| GET | `/models/pairs?a=NVDA&b=AMD` | Beta and Pearson correlation between two tickers |
| GET | `/models/analyst/{symbol}` | Analyst consensus from Yahoo Finance |

### VaR POST body
```json
{
  "positions": [
    { "symbol": "AAPL", "shares": 10, "avgCost": 150 },
    { "symbol": "NVDA", "shares": 5, "avgCost": 700 }
  ]
}
```

### Portfolio & Watchlist
| Method | Path | Description |
|---|---|---|
| GET | `/portfolio/holdings` | All holdings (supports multiple lots per symbol) |
| POST | `/portfolio/holdings` | Add a lot |
| PATCH | `/portfolio/holdings/{lot_id}` | Update shares/avgCost of a lot |
| DELETE | `/portfolio/holdings/{lot_id}` | Remove a specific lot by ID |
| GET | `/portfolio/watchlist` | All watchlist symbols |
| POST | `/portfolio/watchlist/{symbol}` | Add a symbol to watchlist |
| DELETE | `/portfolio/watchlist/{symbol}` | Remove a symbol |

### Cache Management (not exposed via the browser proxy — call the backend directly)
| Method | Path | Description |
|---|---|---|
| GET | `/models/cache/stats` | Cache size and per-endpoint counts |
| POST | `/models/cache/purge?max_age_seconds=86400` | Purge entries older than N seconds |

---

## Architecture

```
Browser (Next.js)
  └── Vercel (API Routes + Static)
        └── FastAPI Backend (Render or localhost:8000)
              ├── Yahoo Finance  ── charts, RSI, MACD, Bollinger, VaR, Pairs, ATR, Regime-Cond MC
              ├── NewsAPI / SEC EDGAR  ── context injection for AI Advisor
              ├── arch / numpy / networkx  ── GARCH, Markov, Monte Carlo
              └── PostgreSQL (Supabase)  ── portfolio, watchlist, result cache
```

---

## Quick Start (local dev)

```bash
# 1. Backend
cd fastapi-backend && cp .env.example .env  # fill in all values
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 2. Frontend (separate terminal)
cd nextjs-app && cp .env.local.example .env.local  # fill in values
npm ci && npm run dev

# → http://localhost:8000 (API)  http://localhost:3000 (app)
```

## Tests & CI

```bash
# Backend (207 tests, fully hermetic — no network or DB needed)
cd fastapi-backend
pip install -r requirements-dev.txt
ruff check .
python -m pytest

# Frontend (51 tests)
cd nextjs-app
npm test          # vitest
npm run typecheck # tsc --noEmit
npm run lint      # eslint
```

GitHub Actions runs all of the above on every push/PR (`.github/workflows/ci.yml`).

---

## Disclaimer

Nothing on this site is financial advice. All data is for informational purposes only. Always verify with official sources.