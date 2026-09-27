"""Shared test fixtures. Adds the backend dir to sys.path and provides
deterministic synthetic market data (no network access in tests)."""
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.market_data import ClosesSeries  # noqa: E402


def business_dates(n: int, end: str = "2024-12-31") -> list[str]:
    """n ISO business dates (weekdays only), ascending, ending on `end`."""
    d = date.fromisoformat(end)
    out: list[str] = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(out))


def make_closes(
    n: int = 100,
    start_price: float = 100.0,
    daily_log_returns: np.ndarray | float = 0.0,
    end: str = "2024-12-31",
) -> ClosesSeries:
    """Deterministic close series from a fixed daily log-return pattern."""
    if isinstance(daily_log_returns, (int, float)):
        log_rets = np.full(n - 1, float(daily_log_returns))
    else:
        log_rets = np.asarray(daily_log_returns, dtype=float)
        assert len(log_rets) == n - 1, "need exactly n-1 returns"
    closes = start_price * np.exp(np.concatenate([[0.0], np.cumsum(log_rets)]))
    return ClosesSeries(dates=business_dates(n, end), closes=closes)


@pytest.fixture(autouse=True)
def _no_database(monkeypatch):
    """Keep tests hermetic: the real DB pool is never used."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    yield


@pytest.fixture(autouse=True)
def _auth_dev_mode(monkeypatch):
    """Open the API for the endpoint tests.

    The service fails closed when AUTH_PASSWORD is missing, so without this
    every router test would just get a 503. Tests that assert on auth
    behaviour itself (tests/test_api_auth.py) override this in their own body,
    which runs after this fixture.
    """
    monkeypatch.setenv("AUTH_DEV_MODE", "1")
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    yield


@pytest.fixture(autouse=True)
def _reset_auth_throttle():
    """The failed-auth counter is process-global; don't let one test throttle
    the next."""
    import main

    main._fail_counts.clear()
    yield
    main._fail_counts.clear()


@pytest.fixture(autouse=True)
def _clear_market_cache():
    from services import market_data

    market_data.clear_cache()
    yield
    market_data.clear_cache()
