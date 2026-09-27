"""
PostgreSQL connection pool (shared by db.py and cache.py).

DATABASE_URL is read lazily so that importing this module never requires
configuration (and tests can set the env var first).
"""
from __future__ import annotations

import logging
import os
import threading

from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def is_configured() -> bool:
    return bool(os.getenv("DATABASE_URL"))


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        url = os.getenv("DATABASE_URL", "")
        if not url:
            raise RuntimeError("DATABASE_URL not set")
        with _pool_lock:
            if _pool is None:
                pool = ConnectionPool(
                    conninfo=url,
                    min_size=1,
                    max_size=5,
                    open=True,
                    kwargs={"autocommit": True},
                )
                _pool = pool
                logger.info("database connection pool opened")
    return _pool


def connection(timeout: float | None = None):
    """Check out a pooled connection (context manager)."""
    pool = get_pool()
    return pool.connection(timeout=timeout) if timeout is not None else pool.connection()


def check_connection(timeout: float = 3.0) -> str:
    """'unconfigured' | 'ok' | 'error' — for the /health endpoint."""
    if not is_configured():
        return "unconfigured"
    try:
        # Pass the timeout through to the pool. Without it, psycopg_pool waits
        # its own default of 30s — and /health is an unauthenticated public
        # endpoint, so a slow database could pin a worker thread for half a
        # minute per request.
        with connection(timeout=timeout) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return "ok"
    except Exception:
        logger.warning("database health check failed", exc_info=True)
        return "error"


def reset_pool() -> None:
    """Close and forget the pool (used by tests)."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.close()
            except Exception:
                pass
            _pool = None
