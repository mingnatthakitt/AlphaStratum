-- AlphaStratum Database Schema
-- PostgreSQL (Supabase). Direct psycopg connection via DATABASE_URL.
--
-- Only the tables the application actually uses are defined here:
-- model results cache, portfolio holdings, and the watchlist.
-- (An earlier version also defined stocks/prices/news/embeddings + pgvector
-- for a planned RAG pipeline that was never wired up — removed. If you ran
-- the old schema, those tables are harmless; a DROP block is provided at the
-- bottom to clean them up.)

-- ── Model Result Cache ─────────────────────────────────────────────────────
-- Expensive model outputs (markov, garch, montecarlo, screener, ...) keyed by
-- sha256(endpoint | version | params) with a 15-minute TTL enforced app-side
-- (cache.py). Best-effort: a cache miss means "recompute and write back".

CREATE TABLE IF NOT EXISTS model_cache (
    key        VARCHAR(64) PRIMARY KEY,
    endpoint   VARCHAR(100) NOT NULL,     -- e.g. 'markov', 'montecarlo', 'screener'
    payload    JSONB NOT NULL,
    cached_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_model_cache_endpoint ON model_cache(endpoint);
CREATE INDEX IF NOT EXISTS idx_model_cache_cached_at ON model_cache(cached_at);

-- ── Portfolio Holdings ─────────────────────────────────────────────────────
-- Persisted across browsers/devices. Each row is one lot (multiple lots per
-- symbol supported). user_id is a placeholder for a single-user deployment —
-- kept so a real auth layer can be added without a migration.

CREATE TABLE IF NOT EXISTS portfolio_holdings (
    id          SERIAL PRIMARY KEY,
    user_id     VARCHAR(100) NOT NULL DEFAULT 'default',
    symbol      VARCHAR(10) NOT NULL,
    shares      DECIMAL(18, 8) NOT NULL,  -- fractional shares supported
    avg_cost    DECIMAL(12, 4) NOT NULL,
    entry_date  DATE,                        -- optional YYYY-MM-DD
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_portfolio_user ON portfolio_holdings(user_id);

-- entry_date is written by the app on insert (see db.upsert_holding). It was
-- previously declared but never populated, so every row carried NULL.

-- ── Watchlist ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS watchlist (
    id          SERIAL PRIMARY KEY,
    user_id     VARCHAR(100) NOT NULL DEFAULT 'default',
    symbol      VARCHAR(10) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);

-- ── Hygiene ────────────────────────────────────────────────────────────────
-- Never store raw API keys — use env vars only.
-- All queries are parameterized (no SQL interpolation).

-- Row Level Security.
--
-- The app connects with the Supabase `postgres` role (a superuser), which
-- bypasses RLS entirely — so these statements do not change current
-- behaviour. They are here so that the DEFAULT is deny: if anyone later
-- points the browser at Supabase with the `anon` key, the tables stay
-- unreadable/unwritable until a policy is written deliberately, instead of
-- being wide open because RLS was simply never enabled.
ALTER TABLE model_cache       ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_holdings ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlist         ENABLE ROW LEVEL SECURITY;
-- No policies are defined on purpose — see the note above.

-- ── Cache retention ────────────────────────────────────────────────────────
-- The 15-minute TTL in cache.py is enforced on READ only; expired rows are
-- never deleted. model_cache would therefore grow without bound, which on a
-- free Supabase project (500 MB) eventually fills the database.
--
-- Schedule a daily purge. Requires the pg_cron extension (available on all
-- Supabase plans; enable it in the dashboard under Database → Extensions if
-- the statements below fail):
--
--   CREATE EXTENSION IF NOT EXISTS pg_cron;
--   SELECT cron.schedule(
--       'alphastratum-cache-retention',
--       '17 3 * * *',                       -- daily at 03:17 UTC
--       $$DELETE FROM model_cache WHERE cached_at < NOW() - INTERVAL '1 day'$$
--   );
--
-- One day is far longer than the 15-minute TTL, so this only removes rows no
-- reader could ever hit again. To cancel: SELECT cron.unschedule(...).

-- ── Optional cleanup for deployments that ran the old schema ───────────────
-- (tables that were never used by application code)
--
-- DROP TABLE IF EXISTS embeddings;
-- DROP TABLE IF EXISTS news;
-- DROP TABLE IF EXISTS prices;
-- DROP TABLE IF EXISTS watchlist_regime_state;
-- DROP TABLE IF EXISTS stocks;
-- DROP EXTENSION IF EXISTS vector;
