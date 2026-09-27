"""
Result cache backed by Supabase Postgres.

Stores expensive model results (Markov, GARCH, Monte Carlo, screener) keyed by
(endpoint, params) with a TTL. On a miss the caller recomputes and writes the
result back via `set_cached()`. Best-effort: cache failures never fail a
request.

Keys are versioned (CACHE_VERSION) so that deploying a changed response shape
invalidates old payloads instead of serving them stale.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv

from services.database import connection, is_configured

load_dotenv()

logger = logging.getLogger(__name__)

CACHE_VERSION = "v2"
DEFAULT_TTL_SECONDS = 15 * 60  # 15 minutes


def _hash_key(endpoint: str, params: dict) -> str:
    """Stable short hash of (endpoint, versioned params) for the cache key."""
    canonical = json.dumps(
        {"v": CACHE_VERSION, "params": params}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(f"{endpoint}|{canonical}".encode()).hexdigest()[:24]


def get_cached(endpoint: str, params: dict) -> Any | None:
    """Return the cached payload if fresh, else None."""
    if not is_configured():
        return None
    key = _hash_key(endpoint, params)
    try:
        with connection() as conn, conn.cursor() as cur:
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
            age = (datetime.now(UTC) - cached_at).total_seconds()
            if age > DEFAULT_TTL_SECONDS:
                return None
            return payload
    except Exception:
        logger.warning("cache get failed (endpoint=%s)", endpoint, exc_info=True)
        return None


def set_cached(endpoint: str, params: dict, payload: Any) -> None:
    """Upsert a result. Silent on failure."""
    if not is_configured():
        return
    key = _hash_key(endpoint, params)
    try:
        with connection() as conn, conn.cursor() as cur:
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
        logger.warning("cache set failed (endpoint=%s)", endpoint, exc_info=True)


def purge_stale(max_age_seconds: int = 24 * 3600) -> int:
    """Delete entries older than max_age. Returns row count."""
    if not is_configured():
        return 0
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM model_cache WHERE cached_at < NOW() - make_interval(secs => %s)",
                (max_age_seconds,),
            )
            return cur.rowcount
    except Exception:
        logger.warning("cache purge failed", exc_info=True)
        return 0


def stats() -> dict:
    """Cache size + per-endpoint counts. Best-effort."""
    if not is_configured():
        return {"enabled": False, "total": 0, "by_endpoint": {}}
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM model_cache")
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT endpoint, COUNT(*) FROM model_cache GROUP BY endpoint ORDER BY endpoint"
            )
            by_endpoint = {row[0]: row[1] for row in cur.fetchall()}
            return {"enabled": True, "total": total, "by_endpoint": by_endpoint}
    except Exception:
        logger.warning("cache stats failed", exc_info=True)
        return {"enabled": True, "total": 0, "by_endpoint": {}, "error": "stats failed"}
