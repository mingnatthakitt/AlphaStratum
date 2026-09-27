# Known Limitations

Honest documentation of what this application does *not* do. Read this before
deploying it anywhere public.

## Security model
- **The backend is a public URL.** Vercel's authentication protects the
  *frontend pages* only. `https://your-backend.onrender.com` is reachable by
  anyone on the internet and bypasses the frontend completely, so
  `AUTH_PASSWORD` is the only credential protecting the API — no IP allowlist,
  no second factor, no per-user identity behind it. If that secret leaks, the
  API is fully open. It is compared with `secrets.compare_digest` and sent as a
  header rather than a query param, so it does not land in access logs, CDN
  logs or browser history.
- **The API fails closed.** If `AUTH_PASSWORD` is missing, empty, or still the
  `.env.example` placeholder, every route returns `503` — it never falls back
  to serving anonymously. This inverts the previous behaviour, where an unset
  password meant "allow everyone" and safety depended on a *separate*
  `AUTH_REQUIRED=1` flag happening to be present in the environment — one
  deleted env var away from a fully public API. The single opt-out is
  `AUTH_DEV_MODE=1`, which is local-development-only and ships as `0` in
  `render.yaml`.
- **`/health` is the only unauthenticated route** (Render's health check has no
  credential to present). It reports service and database status and
  deliberately says nothing about authentication, so it cannot be used to probe
  whether a host is open.
- **Failed auth attempts are throttled** per client IP (10 per 5 minutes by
  default, then `429` for the rest of the window) so the shared secret is not
  brute-forceable without limit. This is an in-process counter: it resets on
  deploy or restart, and each uvicorn worker keeps its own, so it is a speed
  bump against a determined attacker rather than a real rate limiter. The
  window also blocks a legitimate client that fails repeatedly — a deliberate
  trade-off, since continuing to guess after the limit is useless to an
  attacker. Put Cloudflare or a platform-level rate limit in front of it if the
  deployment is genuinely public.
- **The proxy has no end-user authentication.** `/api/proxy/*` is gated only by
  a path allowlist — there is no session, cookie or per-user check, because the
  app is single-user by design. Anyone who can reach the deployed frontend can
  read and write the owner's portfolio, delete watchlist entries, and call
  `/rag/chat` repeatedly against the operator's LLM key. The allowlist limits
  *which* backend routes are reachable (it does block `/models/cache/purge`),
  but it is not an authorization boundary. Keeping Vercel's built-in
  authentication (or Cloudflare Access) enabled on the frontend is what keeps
  the proxy from being an open door — but remember it protects the proxy only,
  never the backend URL behind it.
- **All data lives under a single `user_id="default"`** with no per-user
  isolation. There is no signup/login/authorization. Do not store sensitive data.
- Beyond authentication there is no rate limiting on the API itself; the other
  bounds are the EDGAR-mandated 10 req/s, per-request payload caps (50 VaR
  positions, 64 KB proxy body, 2000-char chat message) and whatever the
  platform enforces.

## Data sources
- **Yahoo Finance chart API is unofficial.** Endpoints, rate limits and crumbs
  can change without notice; heavy polling (watchlist prices + regimes every
  60s per symbol) may get rate-limited. The 404/503 fallbacks degrade
  gracefully but there is no alternative provider wired for models (the Alpha
  Vantage fallback covers only the ticker endpoint and needs `ALPHA_VANTAGE_KEY`).
- Prices are delayed 15–20 minutes; fundamentals fields such as P/E are
  often unavailable from the chart API and reported as `pe: 0` / "N/A".
- **Market holidays are not modeled.** Forecast dates extend from the last
  real trading date over weekdays only, so forecast x-axes drift from real
  sessions across holidays. The same approximation exists in the fabricated
  dates the frontend uses only when a cached payload predates server-side dates.

## Quant models
- Regime classification is a **fixed ±0.5% daily-return threshold rule**, not a
  fitted HMM (the HMM implementation was removed after proving unreliable).
  "Probabilities" are historical day-count frequencies, not forecasts.
- Monte Carlo assumes **GBM with GARCH(1,1) variance** (regime-cond mode) —
  no jumps, no fat tails beyond what the sample volatility captures; percentile
  bands routinely understate tail risk.
- Historical VaR uses a one-year window and date-aligned daily log-returns;
  per-symbol "contributions" are standalone VaRs and do not sum to the
  portfolio VaR (diversification is not decomposed).
- The screener score is a heuristic (regime + momentum − volatility penalty),
  not a validated factor model.

## AI advisor
- **Context injection, not RAG.** News/prices/filings are fetched live and
  stuffed into the prompt; there is no vector store, embedding pipeline, or
  document chunking (a pgvector schema existed but was never wired up and has
  been removed). This was a deliberate decision for the Render/Vercel scale.
- SEC filings are summarized with **regex heuristics over filing HTML** — the
  extraction ("Revenue: $X M", outlook sentence, first risk-factor paragraph)
  is brittle across companies and filing formats, and units are not verified.
- LLM output is wrapped in `<<<ANSWER>>>` delimiters and recovered
  heuristically; provider "thinking" blocks are stripped. Answers can still be
  wrong, stale, or missing citations — every claim must be verified.
- No conversation memory: each question is answered from a fresh context.

## Platform
- **Vercel serverless timeouts.** The proxy allows 25s upstream time (90s for
  chat, 45s for a cold screener), but Vercel's function timeout (10s on Hobby)
  cuts requests earlier; long calls can be killed mid-flight on Hobby.
- The backend is single-process (uvicorn default) — heavy model fits
  (GARCH/Monte Carlo) block the endpoint's worker thread but not the event
  loop; scale workers (`--workers`) or threads for concurrent load.
- No streaming: chat responses arrive as a single JSON payload.
- **Next.js 14 carries 24 open advisories, 2 of them critical (RCE-class), and
  no 14.x release patches them.** This is the most significant known risk in
  the project and it is *not* limited to the image optimizer, as an earlier
  revision of this file claimed. The two criticals are unauthenticated RCE in
  the Image Optimization API (AVIF path) and on Windows-hosted servers.
  Mitigating for this specific deployment: the app makes **no `next/image`
  calls** and has no `images.remotePatterns` configured, which removes the
  AVIF path entirely; and it is deployed to Vercel (Linux), not self-hosted on
  Windows. The remaining advisories are DoS (Server Components, Server
  Actions), SSRF via rewrites/WebSocket upgrades, request smuggling, and RSC
  cache poisoning — none of the code paths exercised here (a single
  `/api/proxy/[...path]` catch-all route plus static App Router pages) touch
  rewrites, Server Actions, or WebSocket upgrades.
  **The real remediation is upgrading to Next 15/16**, which is a migration
  this project has not yet undertaken. `npm audit` runs in CI (advisory, not
  blocking) and Dependabot is configured so the upgrade gets proposed.
- Other audit findings (postcss, glob, eslint-config-next) are build-time or
  dev-dependency only.

## Database
- **`model_cache` needs a retention job.** The 15-minute TTL in `cache.py` is
  enforced on read only — expired rows are never deleted, and the only purge
  endpoint (`POST /models/cache/purge`) is deliberately blocked by the frontend
  proxy. `supabase/schema.sql` now contains a ready-to-run `pg_cron` schedule
  that deletes rows older than a day; **it is commented out**, so you must
  enable the `pg_cron` extension and run those two statements, or the table
  grows without bound until it fills the project.
- Row Level Security is now *enabled* on all three tables with **no policies**,
  which means deny-by-default for any non-superuser connection. The app itself
  connects as the Supabase `postgres` role (a superuser) and bypasses RLS, so
  current behaviour is unchanged. If you switch to a non-superuser role you
  will need to write policies.

## Testing
- Backend tests are hermetic (no network/DB); they validate logic and response
  shapes, not live Yahoo/LLM behavior. The EDGAR parser, yfinance integration
  and LLM providers are exercised only against the real services.
- Frontend tests cover pure logic and the proxy handler; components are not
  mounted in tests. `WatchlistContext` — the highest-risk module, with a
  polling effect and optimistic mutations — still has no render test, so a
  regression there would not be caught by CI.
