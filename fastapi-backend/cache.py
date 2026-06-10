"""
Result cache backed by Supabase Postgres.

Stores expensive model results (Markov, GARCH, Monte Carlo) keyed by
(symbol, params) with a TTL. Returns cached data when fresh, otherwise
lets the caller recompute and the caller writes the result back via
`set_cached()`.

This is intentionally simple — a single key/value table with JSONB.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
DEFAULT_TTL_SECONDS = 15 * 60  # 15 minutes


def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set — cache disabled")
    return psycopg.connect(DATABASE_URL, autocommit=True)


def _hash_key(endpoint: str, params: dict) -> str:
    """Stable short hash of (endpoint, params) for the cache key column."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(f"{endpoint}|{canonical}".encode()).hexdigest()[:24]
    return h


def get_cached(endpoint: str, params: dict) -> Optional[Any]:
    """Return cached payload if fresh, else None. Caller decides fallback."""
    if not DATABASE_URL:
        return None
    key = _hash_key(endpoint, params)
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT payload, cached_at
                FROM model_cache
                WHERE key = %s AND endpoint = %s
                """,
                (key, endpoint),
            )
            row = cur.fetchone()
            if not row:
                return None
            payload, cached_at = row
            age = (datetime.now(timezone.utc) - cached_at).total_seconds()
            if age > DEFAULT_TTL_SECONDS:
                return None
            return payload
    except Exception:
        # Cache is best-effort. Never fail a request because the cache is down.
        return None


def set_cached(endpoint: str, params: dict, payload: Any) -> None:
    """Upsert a result. Silent on failure."""
    if not DATABASE_URL:
        return
    key = _hash_key(endpoint, params)
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_cache (key, endpoint, payload, cached_at)
                VALUES (%s, %s, %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                  SET payload = EXCLUDED.payload,
                      cached_at = NOW()
                """,
                (key, endpoint, json.dumps(payload, default=str)),
            )
    except Exception:
        pass


def purge_stale(max_age_seconds: int = 24 * 3600) -> int:
    """Optional: delete entries older than max_age. Returns row count."""
    if not DATABASE_URL:
        return 0
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM model_cache WHERE cached_at < NOW() - (%s || ' seconds')::interval",
                (str(max_age_seconds),),
            )
            return cur.rowcount
    except Exception:
        return 0


def stats() -> dict:
    """Return cache size + per-endpoint counts. Best-effort."""
    if not DATABASE_URL:
        return {"enabled": False, "total": 0, "by_endpoint": {}}
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM model_cache")
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT endpoint, COUNT(*) FROM model_cache GROUP BY endpoint ORDER BY endpoint"
            )
            by_endpoint = {row[0]: row[1] for row in cur.fetchall()}
            return {"enabled": True, "total": total, "by_endpoint": by_endpoint}
    except Exception:
        return {"enabled": True, "total": 0, "by_endpoint": {}, "error": "stats failed"}
