"""Model-result cache tests with a fake DB connection."""
import json
from datetime import UTC, datetime, timedelta

import pytest

import cache
from services import database


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.db.last_sql = sql
        self.db.last_params = params
        if "INSERT" in sql:
            key, endpoint, payload = params[0], params[1], params[2]
            self.db.rows[key] = (endpoint, json.loads(payload), datetime.now(UTC))
            self.rowcount = 1
        elif "DELETE" in sql:
            self.rowcount = len(self.db.rows)
            self.db.rows.clear()
        elif "COUNT(*)" in sql:
            self._count = len(self.db.rows)

    def fetchone(self):
        if "SELECT payload" in self.db.last_sql:
            key = self.db.last_params[0]
            row = self.db.rows.get(key)
            if row is None:
                return None
            endpoint, payload, cached_at = row
            return (payload, cached_at)  # psycopg returns jsonb as dict
        if "COUNT(*)" in self.db.last_sql:
            return (self._count,)
        return None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return FakeCursor(self.db)


class FakeDB:
    def __init__(self):
        self.rows = {}
        self.last_sql = ""
        self.last_params = None

    def connection(self):
        return FakeConnection(self)


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(cache, "is_configured", lambda: True)
    monkeypatch.setattr(cache, "connection", db.connection)
    return db


class TestCacheKey:
    def test_deterministic(self):
        assert cache._hash_key("ep", {"a": 1}) == cache._hash_key("ep", {"a": 1})

    def test_param_order_irrelevant(self):
        assert cache._hash_key("ep", {"a": 1, "b": 2}) == cache._hash_key("ep", {"b": 2, "a": 1})

    def test_different_params_differ(self):
        assert cache._hash_key("ep", {"a": 1}) != cache._hash_key("ep", {"a": 2})

    def test_version_busts_cache(self, monkeypatch):
        before = cache._hash_key("ep", {"a": 1})
        monkeypatch.setattr(cache, "CACHE_VERSION", "v3")
        assert cache._hash_key("ep", {"a": 1}) != before


class TestRoundTrip:
    def test_set_then_get(self, fake_db):
        cache.set_cached("markov", {"symbol": "AAPL"}, {"hello": [1, 2, 3]})
        assert cache.get_cached("markov", {"symbol": "AAPL"}) == {"hello": [1, 2, 3]}

    def test_overwrite(self, fake_db):
        cache.set_cached("markov", {"symbol": "AAPL"}, {"v": 1})
        cache.set_cached("markov", {"symbol": "AAPL"}, {"v": 2})
        assert cache.get_cached("markov", {"symbol": "AAPL"}) == {"v": 2}

    def test_miss_returns_none(self, fake_db):
        assert cache.get_cached("markov", {"symbol": "MISSING"}) is None


class TestExpiry:
    def test_stale_entry_ignored(self, fake_db, monkeypatch):
        cache.set_cached("markov", {"symbol": "AAPL"}, {"v": 1})
        # Rewind the stored timestamp past the TTL.
        key = cache._hash_key("markov", {"symbol": "AAPL"})
        endpoint, payload, _ = fake_db.rows[key]
        fake_db.rows[key] = (
            endpoint,
            payload,
            datetime.now(UTC) - timedelta(seconds=cache.DEFAULT_TTL_SECONDS + 1),
        )
        assert cache.get_cached("markov", {"symbol": "AAPL"}) is None


class TestFailuresAreSilent:
    def test_broken_connection_returns_none(self, monkeypatch):
        def broken():
            raise RuntimeError("db down")

        monkeypatch.setattr(cache, "is_configured", lambda: True)
        monkeypatch.setattr(cache, "connection", broken)
        assert cache.get_cached("ep", {}) is None

    def test_set_failure_does_not_raise(self, monkeypatch):
        def broken():
            raise RuntimeError("db down")

        monkeypatch.setattr(cache, "is_configured", lambda: True)
        monkeypatch.setattr(cache, "connection", broken)
        cache.set_cached("ep", {}, {"a": 1})  # must not raise

    def test_stats_error_is_reported(self, monkeypatch):
        def broken():
            raise RuntimeError("db down")

        monkeypatch.setattr(cache, "is_configured", lambda: True)
        monkeypatch.setattr(cache, "connection", broken)
        stats = cache.stats()
        assert stats["enabled"] is True
        assert stats["error"] == "stats failed"


class TestUnconfigured:
    def test_no_database_url(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(database, "is_configured", lambda: False)
        monkeypatch.setattr(cache, "is_configured", lambda: False)
        assert cache.get_cached("ep", {}) is None
        assert cache.stats() == {"enabled": False, "total": 0, "by_endpoint": {}}

    def test_purge_without_db_returns_zero(self, monkeypatch):
        monkeypatch.setattr(cache, "is_configured", lambda: False)
        assert cache.purge_stale(60) == 0
