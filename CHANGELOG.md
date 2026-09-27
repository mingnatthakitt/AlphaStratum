# Changelog

## 0.2.0 — Production-readiness pass

### Fourth review round (backend exposure on a public host)

The deployment is a Vercel frontend plus a FastAPI backend on Render. Vercel's
built-in authentication protects the frontend *pages*; the backend's own
hostname is public and bypasses it entirely. The audit of that topology found
the API's safety depended on an opt-in flag, so a single missing env var
published the whole API.

- **[P0] The API failed OPEN when no password was set.** With `AUTH_PASSWORD`
  unset, the middleware *allowed every request*; closing that door required a
  separate `AUTH_REQUIRED=1` flag to be present in the environment. Delete that
  one variable — a routine dashboard edit — and the portfolio, watchlist, model
  endpoints and the operator's LLM key are served to anyone who finds the host.
  **The default is now inverted: no usable password means every route returns
  503.** The one opt-out is an explicit `AUTH_DEV_MODE=1`, which is documented
  as local-development-only and ships as `0` in `render.yaml`.
- **[P0] The `.env.example` placeholder counted as a real password.** Copying
  the example file to Render produced an API that *looked* protected while
  using a string published in this repository. Known placeholder values are now
  treated as "no password configured" and rejected, so the failure is loud
  rather than silent.
- **[P1] The shared secret was brute-forceable without limit.** A single static
  secret on a public URL had no ceiling on guesses. Failed attempts are now
  counted per client IP (default 10 per 5 minutes) and answered with `429` and
  `Retry-After` for the rest of the window; a successful request clears the
  count. This is an in-process speed bump, not a distributed rate limiter —
  LIMITATIONS.md says so plainly, including that the window also blocks a
  legitimate client that keeps mistyping.
- **[P2] `/health` leaked whether authentication was configured.** It is the one
  route an anonymous caller can read, so `auth: configured|disabled` was a free
  open/closed oracle for anyone scanning for exposed hosts. It now reports only
  service and database status, and the auth posture goes to the startup log.
- **[P2] `/` was public** despite nothing needing it unauthenticated. Only
  `/health` is now public, so the service banner is no longer a free
  fingerprinting endpoint.
- **Client IP for throttling requires proxy headers.** The counter deliberately
  ignores the attacker-controlled `X-Forwarded-For` header and uses the peer
  address instead, which is only the real client when uvicorn runs with
  `--proxy-headers --forwarded-allow-ips '*'`. Both `render.yaml` and the
  README start command now set it; without them the throttle would key on
  Render's proxy rather than the caller.
- **Tests:** `tests/test_api_auth.py` rewritten to 41 cases pinning the new
  contract — fail-closed for missing/empty/whitespace/placeholder passwords, the
  placeholder not being a dev-mode backdoor, falsy `AUTH_DEV_MODE` spellings
  still failing closed, a stale `AUTH_REQUIRED` not reopening the API, the
  throttle and its window, the bounded failure table, and every router
  confirming it sits behind the middleware. Verified to bite: reverting the
  middleware to the old fail-open behaviour fails 15 of them.
- **Docs:** README gains a callout that the backend URL is public and
  `AUTH_PASSWORD` is the only lock, with the `curl` check that proves it (must
  return 401); LIMITATIONS.md's security model was rewritten because two of its
  claims were no longer true.

### Third review round (security + correctness audit fixes)

**Correctness — silent wrong numbers**
- **[P1] Regime-conditional Monte Carlo volatility was ~15.9× too small.** The GARCH forecast sigma was already a per-day decimal value after `/100`, and the endpoint then divided it by `sqrt(252)` again, so every fan (and the `sigma` field sent to the client) was far too narrow and disagreed with `/models/garch` for the same symbol. Removed the extra annualization; both endpoints now share one unit convention. A regression test pins sigma against realized daily volatility and asserts a plausible fan width — the previous test only checked response shape, which is why this shipped.
- **[P2] NaN parameters escaped validation.** `num_std` was guarded with `num_std <= 0`, which is False for NaN, so `?num_std=nan` reached JSON serialization and produced an unhandled 500 with a traceback (Starlette rejects NaN *after* the route's `try/except` has exited). Now `math.isfinite` is checked in both the route and `quant.bollinger`; NaN/Inf return 400.
- **[P2] `pairs` could emit NaN.** The zero-variance guard was `var_a == 0`, but `NaN != 0`, so a series containing a non-finite value fell through to the `corrcoef` branch. Now guards on `var_a > 0 and var_b > 0` and rejects non-finite history outright. Non-positive closes are dropped at the market-data layer too.
- **[P2] Partial chart dates were discarded wholesale.** `toLineData`/`toHistogramData` required `dates.length === values.length` and otherwise fabricated the *entire* axis, so a short date payload left every x-position wrong while looking plausible. Dates are now zipped against the values and only the gap is fabricated.
- **[P2] NewsAPI `null` source discarded every article.** `.get("source", {})` only defaults when the key is *absent*; NewsAPI returns `"source": null`, and the resulting `AttributeError` was swallowed by a bare `except`, silently degrading the endpoint to a single Yahoo item. Per-field `or {}` defaults now applied.

**Security / resource limits**
- **Auth key moved out of the query string.** The proxy now sends `X-Auth-Key`; the backend accepts the header and keeps `?key=` as a fallback for curl/Swagger. The long-lived shared secret no longer lands in uvicorn access logs, CDN logs or browser history. A caller-supplied `X-Auth-Key` is stripped.
- **Gemini API key no longer logged.** It was passed as a `?key=` query param, and httpx embeds the full request URL in `HTTPStatusError.__str__` — so any provider-side 4xx/5xx wrote the key to logs via `logger.exception`. Now sent as an `x-goog-api-key` header.
- **VaR request amplification bounded.** `positions` had no `max_length`, so one request could drive an unbounded number of sequential upstream fetches. Capped at 50 positions and fetched in parallel.
- **Proxy body cap.** Request bodies were buffered into memory with no limit; now rejected with 413 above 64 KB (checked against `content-length` before reading, and again after).
- **`/health` no longer blocks for 30s.** `check_connection(timeout=3.0)` accepted a timeout but never passed it to the pool, so every call waited psycopg_pool's own 30s default — on an unauthenticated public endpoint that could exhaust the threadpool.
- **Anthropic client leak.** `AsyncAnthropic` was constructed per request and never closed, leaking its httpx transport and connection pool. Now uses `async with`.
- **CSV formula injection.** The portfolio export joined fields raw, and the backend's symbol regex permits a leading `=`, so a lot named `=1+1` was evaluated as a formula on open. Fields are now RFC-4180 quoted and `=`/`+`/`-`/`@` prefixed values are defused.
- **Citation URL scheme validation.** LLM-grounded citation URLs were rendered as anchors without checking the scheme; React does not block `javascript:` in `href`, so a prompt-injected source document could produce a live link. Only `http(s)` URLs become anchors.
- **The proxy allowlist is not authentication.** Documented explicitly in LIMITATIONS.md: `/api/proxy/*` has no end-user session, so anyone who can reach the site can read/write the owner's portfolio and spend the LLM key. A real auth layer is required before public deployment.

**Concurrency / caching**
- **Cache single-flight.** Concurrent misses on a cold key each issued their own upstream request (a stampede, worst at each TTL boundary). Added per-key locks with a re-check inside.
- **Cache no longer hands out shared mutable objects.** `fetch_closes` returned the cached `ndarray` and `fetch_intraday` the cached `dict`; a caller mutating either would have corrupted every concurrent request. Cached values are now defensively copied.
- **Cache keys namespaced by fetcher**, so the `fetch_closes` sentinel can no longer collide with a real interval.
- **Regime-flip detection moved out of `useMemo`.** It mutated a ref during the render phase, so under StrictMode (and on any discarded render) the flip marker never fired. Now committed in an effect, leaving the memo pure.
- **Correlation graph** re-centres on container resize (previously sampled the width once at mount) and removes its d3-drag window listeners on unmount.
- **Chart theme colours** are read one animation frame after the theme change, so a chart is no longer painted with the previous palette.

**Reliability**
- **A failed quotes poll no longer renders as `$0.00`.** The watchlist quotes query swallowed errors and cached a *successful* empty map, so one backend hiccup made every row read 0.00 / +0.0% with no error and no retry for a minute. Errors now propagate and missing quotes render as `—`.
- **`QueryRender` no longer flashes "no data"** on the render where a gated query becomes enabled (`isLoading` is false and data undefined before the effect fires). Accepts `isPending`.
- **`.env` is loaded before the routers import it.** `routers/rag.py` snapshots LLM keys at import, so loading afterwards (or from a different CWD) left it with no provider configured.
- **Provider config is read per request** via accessors instead of module globals, and treats a blank value as unset — Render's `sync: false` creates *empty strings*, which `os.getenv(name, default)` returns instead of the default, silently breaking every Anthropic call on a fresh deploy. Rotating a key also no longer requires a restart.
- **`entry_date` is now actually written.** It was selected on every read but never inserted, so the column was permanently NULL.

**Infrastructure**
- `render.yaml` declares the missing env vars (`LOG_LEVEL`, `GEMINI_MODEL`, `LLM_PROVIDER`, `ALPHA_VANTAGE_KEY`) and no longer ships a placeholder `CORS_ORIGINS` pointing at a non-existent domain.
- `.gitignore` covers pytest/ruff caches, coverage output, virtualenvs and all `.env.*` variants, while keeping the committed `.env.example` files tracked.
- CI gains `permissions: contents: read`, concurrency cancellation, job timeouts, and advisory `pip-audit` / `npm audit` steps. Dependabot is configured for npm, pip and GitHub Actions.
- `supabase/schema.sql` enables RLS on all tables (deny-by-default, no policies — the app connects as superuser and is unaffected) and documents a ready-to-run `pg_cron` retention job for `model_cache`, which otherwise grows without bound because the only purge route is blocked by the proxy.

**Documentation**
- LIMITATIONS.md now states the Next.js risk accurately: 24 advisories with 2 critical RCE-class entries, not the single image-optimizer advisory previously claimed, plus what specifically mitigates them here and what does not.
- README documents header-based auth, the Render empty-string and cold-start behaviours, and uses `npm ci` to match CONTRIBUTING.md.

**Tests:** 174 backend (was 155) and 44 frontend (was 26), including two new regression suites (`tests/test_regressions.py`, `__tests__/security.test.ts`) that fail against each bug above.

### Second review round (fresh-eyes audit fixes)
- **[P0] Chart teardown crash**: `chart.removeSeries` ran on already-disposed chart instances during unmount and theme toggles (React runs the owning hook's cleanup first). Added `safeRemoveSeries` with disposed-instance tracking; all 10 chart components use it; CandlestickChart also stopped leaking old series on symbol change.
- **[P1] Monte Carlo units**: `gbm_percentile_fans` was integrating per-day drift/vol with an annualized `dt = 1/252`, rendering near-flat fans (the flagship charts were ~16× and ~252× too narrow). The simulator now takes per-day values (dt = 1) matching all callers; a fan-width regression test pins the convention.
- **[P1] `/models/markov` 500**: an absorbing regime (self-transition = 1.0) emitted `Infinity`, which FastAPI cannot serialize; expected duration is capped at 999.9.
- **[P1] AI advisor context loss**: the short-history early-exit in the daily-indicators builder returned a bare list instead of `(parts, urls)`, silently dropping all quantitative context for recent IPOs / some ETFs; restructured so basic quote + intraday are always included and indicators only when ≥30 bars.
- **[P2] Correlation MST** minimized |correlation| (spanning through the *weakest* pairs); now uses correlation distance (1 − |corr|) so the tree connects the strongest relationships, edges still report |corr|.
- **[P2] Proxy timeouts** are per-path: 90s for `/rag/chat`, 45s for a cold screener, 25s default (chat previously died at 25s while the backend's own LLM budget was 30–60s).
- **[P2] Watchlist polling** switched from N full OHLCV fetches/minute to a batched `GET /fetch/quotes` endpoint (≤20 symbols, cached market data).
- Watchlist add/remove use functional state updates; EDGAR throttle is lock-serialized; watchlist symbols validated by regex; `market_data.search_symbols()` exposed publicly; unused `_build_context` query parameter removed; docs drift fixed (regime description, auth wording, watchlist POST route, GARCH "annualized" claim); `.gitignore` gains `.zcode/` and `*.tsbuildinfo`.

### Security
- **Auth**: constant-time key comparison (`secrets.compare_digest`); loud warning + optional fail-closed mode (`AUTH_REQUIRED=1`) when `AUTH_PASSWORD` is unset; the previous code silently allowed all traffic.
- **CORS**: replaced `allow_origins=["*"]` + `allow_credentials=True` with an explicit origin list from `CORS_ORIGINS` (default `http://localhost:3000`); credentials disabled (auth is a query param, not cookies).
- **Error leakage**: 500 responses no longer return raw exception strings (`str(e)`); full tracebacks go to server logs via a shared `services.errors.internal_error()` helper and a global exception handler.
- **Proxy hardening** (Next.js): path allowlist (only `fetch/`, `models/`, `rag/`, `portfolio/` reachable), blocking of cache-management routes, rejection of path-traversal segments, `x-forwarded-*` header stripping. The previously forwarded client `?key=` override is still stripped.
- **Input validation**: portfolio `shares`/`avgCost` must be positive finite numbers; symbols validated by regex everywhere (backend + proxy path encoding); chat messages capped at 2,000 chars; cache-purge horizon bounded.
- **Env examples corrected**: `nextjs-app/.env.local.example` documented `NEXT_PUBLIC_AUTH_KEY` — following it would have published the shared secret into the browser bundle; it is now `AUTH_KEY` (server-only). `fastapi-backend/.env.example` now documents `DATABASE_URL`, `CORS_ORIGINS`, `LOG_LEVEL`, and model-name defaults.

### Correctness (quant)
- **VaR**: computed from value-weighted portfolio returns (was an equal-weight average that ignored position sizes); symbols aligned on common trading dates (was start-truncation, silently comparing different days); each symbol fetched once (was twice); unsupported symbols reported via `excludedSymbols`.
- **Pairs / beta**: date-aligned histories (start-truncation gave wrong numbers whenever the two tickers had different listing histories); beta now uses consistent sample covariance/variance (was ddof=1 over ddof=0, inflating β by n/(n−1)); zero-variance inputs no longer produce NaN responses.
- **Correlation graph**: date-aligned closes across tickers; unified sector universes with the screener (previously two inconsistent hardcoded lists).
- **RSI**: Wilder smoothing now seeds from the first `period` returns (the seed averaged the *last* N gains then smoothed forward, producing a wrong history); RSI/MACD/Bollinger/ATR responses include real trading `dates` from Yahoo.
- **Monte Carlo / GARCH**: forecast dates are trading days extended from the last actual trading date (were calendar days, mislabeling the x-axis); MC returns 10 real sample paths again.
- **Screeners**: backend screener fetches its universe in parallel (was 25 sequential HTTP calls) and caches results for 15 minutes; the frontend screener attributes results **by symbol** (previously, after any fetch failure, every following row displayed the wrong ticker's data) and its client-side scoring matches the backend formula.

### Architecture
- New backend `services/` layer: `market_data.py` (single Yahoo client, TTL cache, date-based alignment, unified sector lists), `quant.py` (pure, fully unit-tested math), `database.py` (psycopg connection pool — the `psycopg_pool` dependency existed but was unused), `errors.py`. Removed three copies of `_get_closes_yahoo`, two EMA/RSI implementations, four threshold-regime variants and three separate Yahoo sessions.
- **Event-loop fix**: `/rag/chat` previously ran blocking `requests` calls (including `time.sleep`-based EDGAR throttling) directly in the async handler, freezing the whole API during context building. All sync I/O now runs in worker threads and the five context sources (news, daily indicators, intraday, analyst, EDGAR) are gathered concurrently — context building drops from ~5–15s sequential to the slowest single source.
- **EDGAR**: the ~10k-entry company_tickers.json is fetched once and cached for 24h (was re-downloaded per uncached symbol), with failure backoff.
- DB access uses a pooled connection (min 1 / max 5) with lazy configuration; model-cache keys are versioned (`v2`) so deploying changed response shapes invalidates stale payloads.
- Frontend: shared `useChart` hook (single lifecycle, `autoSize` resizing, theme-aware canvas colors resolved from CSS variables, theme-reactive re-creation) replacing ~600 duplicated lines across 10 chart components; shared percentile-fan series helper; shared `QueryRender` for loading/error/empty states; hand-rolled toast system; d3 replaced with the three submodules actually used (−70 packages).
- `POST /portfolio/holdings/{id}` (PATCH) added to make lot editing possible end-to-end.

### Frontend fixes
- Watchlist rewritten: window-focus refetch no longer replaces the list and resets the selected symbol; side effects moved out of state updaters (duplicate POSTs in React StrictMode fixed); regime-flip indicator works again (previous logic could never set `lastRegime`); failure toasts.
- `/models` uses a real controlled Tabs component — inactive tabs never mount or fetch (previously a decorative component rendered all 10 sections at once and every symbol click fired ~10 request bursts). Dashboard model panels are likewise gated on the "+ Model" selector.
- Portfolio: lot editing works (was a no-op input), delete requires confirmation, mutations surface errors as toasts, initial-load skeleton fixed, division-by-zero guard, horizontal scroll for narrow screens, accessible add-lot modal (labels, Escape, backdrop).
- Backtest: routed through the shared proxy client (removed a dead client-side `process.env.AUTH_KEY` read — non-public env vars are never inlined, so it silently sent no key), explicit error messages for out-of-range dates, running state on the button, calculation extracted to a pure tested module.
- Advisor: citations are clickable when a URL exists (backend now links NewsAPI articles, Yahoo quote/analyst pages and EDGAR filings to their inline citations); retry button on failure; removed brittle client-side prompt-echo scrubbing (the backend's answer extraction covers it).
- Proxy forwards `Cache-Control` so proxied responses can be cached; charts use resolved theme colors (canvas cannot resolve `var(--x)` — most grid/text colors silently fell back to defaults before); fixed the `--secondary` light-mode token typo; theme toggle added to the navbar; responsive mobile nav.

### Tests & CI (all new)
- Backend: 155 pytest tests — quant math (RSI/MACD/Bollinger/ATR/Markov/GBM/date alignment + GBM unit conventions), market-data caching + alignment, every router (success/404/400/500-shape), auth middleware, portfolio with faked DB, model-cache round-trip/expiry/silence, citation extraction + linking, absorbing-Markov serialization, fan-width plausibility, batch quotes, screener ordering.
- Frontend: 26 vitest tests — proxy allowlist/auth/traversal/encoding, backtest calculator, screener scoring, chart-data helpers (incl. the zipSettled misattribution regression).
- `tsc --noEmit` and `next lint` are enforced during `next build` (both were disabled via `ignoreBuildErrors`/`ignoreDuringBuilds`); backend lint via ruff (pyproject config).
- GitHub Actions workflow: backend (ruff + pytest) and frontend (tsc + eslint + vitest + build).

### Dependencies & deployment
- `requirements.txt` pinned (was 18 unpinned packages); removed unused deps: hmmlearn, statsmodels, scikit-learn, sqlalchemy, pgvector, python-multipart.
- `render.yaml` blueprint (health check `/health`, `AUTH_REQUIRED=1` by default); CI workflow added.
- `package.json` renamed to `alphastratum`, `@types/d3*` moved to devDependencies, `typecheck`/`test` scripts added.

### Schema
- `supabase/schema.sql` now defines only the tables the app uses (model_cache, portfolio_holdings, watchlist). The unused `stocks`/`prices`/`news`/`embeddings`/`watchlist_regime_state` tables and the pgvector extension were removed, with an optional DROP block for existing deployments.

## 0.1.0 — Initial open-source release
