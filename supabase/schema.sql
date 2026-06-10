  -- FinanceAI Database Schema
  -- PostgreSQL + pgvector for RAG semantic search

  -- Enable pgvector
  CREATE EXTENSION IF NOT EXISTS vector;

  -- ── Stocks ──────────────────────────────────────────────────────────────────

  CREATE TABLE IF NOT EXISTS stocks (
      id SERIAL PRIMARY KEY,
      symbol      VARCHAR(10) UNIQUE NOT NULL,
      name        VARCHAR(255),
      sector      VARCHAR(100),
      created_at  TIMESTAMPTZ DEFAULT NOW()
  );

  -- ── Price Cache ─────────────────────────────────────────────────────────────

  CREATE TABLE IF NOT EXISTS prices (
      id SERIAL PRIMARY KEY,
      symbol VARCHAR(10) NOT NULL REFERENCES stocks(symbol),
      date        DATE NOT NULL,
      open DECIMAL(10, 4),
      high        DECIMAL(10, 4),
      low DECIMAL(10, 4),
      close       DECIMAL(10, 4),
      volume      BIGINT,
      cached_at   TIMESTAMPTZ DEFAULT NOW(),
      UNIQUE (symbol, date)
  );

  CREATE INDEX IF NOT EXISTS idx_prices_symbol_date ON prices(symbol, date DESC);
  CREATE INDEX IF NOT EXISTS idx_prices_cached_at ON prices(cached_at);

  -- ── News& Filings ──────────────────────────────────────────────────────────

  CREATE TABLE IF NOT EXISTS news (
      id          SERIAL PRIMARY KEY,
      symbol      VARCHAR(10) NOT NULL REFERENCES stocks(symbol),
      title       TEXT NOT NULL,
      source      VARCHAR(255),
      url         TEXT,
      snippet     TEXT,
      published_at TIMESTAMPTZ,
      cached_at   TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_news_symbol ON news(symbol);
  CREATE INDEX IF NOT EXISTS idx_news_cached_at ON news(cached_at);

  -- ── RAG Embeddings ─────────────────────────────────────────────────────────

  CREATE TABLE IF NOT EXISTS embeddings (
      id          SERIAL PRIMARY KEY,
      symbol      VARCHAR(10) NOT NULL REFERENCES stocks(symbol),
      content     TEXT NOT NULL,
      source_type VARCHAR(50), -- '10k', '10q', 'news', 'transcript'
      embedding VECTOR(768),
      metadata_   JSONB,
      created_at  TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_embeddings_symbol ON embeddings(symbol);
  CREATE INDEX IF NOT EXISTS idx_embeddings_source_type ON embeddings(source_type);

  -- Exact nearest neighbor (slower build, faster query — fine for <100k rows)
  CREATE INDEX IF NOT EXISTS idx_embeddings_exact ON embeddings USING hnsw (embedding vector_cosine_ops);

  -- ── Model Result Cache ─────────────────────────────────────────────────────
  -- Stores expensive model outputs (Markov regime, GARCH, Monte Carlo) keyed by
  -- (endpoint, params_hash) with a 15-minute TTL. Best-effort: the API layer
  -- treats cache misses as "recompute and write back".

  CREATE TABLE IF NOT EXISTS model_cache (
      key        VARCHAR(64) PRIMARY KEY,   -- sha256(endpoint|params)[:24] in hex
      endpoint   VARCHAR(100) NOT NULL,     -- e.g. 'markov', 'montecarlo', 'garch'
      payload    JSONB NOT NULL,
      cached_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_model_cache_endpoint ON model_cache(endpoint);
  CREATE INDEX IF NOT EXISTS idx_model_cache_cached_at ON model_cache(cached_at);

  -- ── Portfolio Holdings ─────────────────────────────────────────────────────
  -- Persisted across browsers/devices. Each row is one position.
  -- user_id is a placeholder — for a solo internal tool, use a fixed device ID
  -- or skip the column entirely if no auth layer is needed.

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

  -- ── Watchlist ─────────────────────────────────────────────────────────────
  -- Per-user stock watchlist with regime alert tracking.

  CREATE TABLE IF NOT EXISTS watchlist (
      id          SERIAL PRIMARY KEY,
      user_id     VARCHAR(100) NOT NULL DEFAULT 'default',
      symbol      VARCHAR(10) NOT NULL,
      created_at  TIMESTAMPTZ DEFAULT NOW(),
      UNIQUE (user_id, symbol)
  );

  CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);

  -- ── Watchlist Regime Alerts ────────────────────────────────────────────────
  -- Tracks the last known regime per symbol so we can alert on bull→bear flips.
  -- Polled periodically; updated when regime changes.

  CREATE TABLE IF NOT EXISTS watchlist_regime_state (
      id          SERIAL PRIMARY KEY,
      user_id     VARCHAR(100) NOT NULL DEFAULT 'default',
      symbol      VARCHAR(10) NOT NULL,
      regime      VARCHAR(20) NOT NULL,  -- 'bull', 'bear', 'sideways'
      updated_at  TIMESTAMPTZ DEFAULT NOW(),
      UNIQUE (user_id, symbol)
  );

  CREATE INDEX IF NOT EXISTS idx_watchlist_regime_user ON watchlist_regime_state(user_id);

  -- ── Scrubbing ───────────────────────────────────────────────────────────────

  -- Never store raw API keys — use env vars only
  -- All user inputs are parameterized (no SQL interpolation)