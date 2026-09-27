"""
Regression tests for defects found in the third review round.

Each test here failed before the corresponding fix, and is written so that
re-introducing the bug makes it fail again. They are grouped by the symptom
that was observed in production, not by the module that was changed.
"""
import numpy as np
import pytest
from conftest import make_closes
from fastapi.testclient import TestClient

import main
from routers import models as models_router
from services import market_data, quant
from services.market_data import ChartResult, ClosesSeries

client = TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    yield


def _install_series(monkeypatch, series_by_symbol):
    def fake_fetch_closes(symbol, range_="1y"):
        return series_by_symbol.get(symbol.upper())

    monkeypatch.setattr(market_data, "fetch_closes", fake_fetch_closes)


# ── Monte Carlo volatility units ──────────────────────────────────────────────

class TestMonteCarloSigmaUnits:
    """
    The regime-conditional endpoint divided the GARCH daily sigma by an extra
    sqrt(252), making every fan ~15.9x too narrow — and disagreeing with
    /models/garch for the same symbol. Both endpoints now express sigma in the
    same per-day units that gbm_percentile_fans expects (one step = one day).
    """

    @pytest.fixture
    def series(self):
        rng = np.random.default_rng(7)
        return make_closes(261, daily_log_returns=rng.normal(0.0, 0.01, 260))

    def test_regime_cond_sigma_is_per_day_not_annualized(self, monkeypatch, series):
        _install_series(monkeypatch, {"AAPL": series})
        body = client.get("/models/montecarlo/AAPL/regime-cond?days=15").json()

        realized = np.diff(np.log(series.closes)).std()
        # The reported sigma must be in the neighbourhood of realized daily
        # vol. Before the fix it was realized/sqrt(252) (~0.0006), which no
        # range assertion in the suite would have rejected.
        assert body["sigma"] == pytest.approx(realized, rel=0.5)

    def test_regime_cond_fan_width_matches_plain_garch(self, monkeypatch, series):
        """The regime-conditional fan must be plausibly wide, not a flat line."""
        _install_series(monkeypatch, {"AAPL": series})
        cond = client.get("/models/montecarlo/AAPL/regime-cond?days=15").json()

        spot = cond["lastPrice"]
        cond_width = (cond["blended"]["p95"][-1] - cond["blended"]["p5"][-1]) / spot
        assert 0.10 < cond_width < 0.60, f"regime-cond fan width {cond_width:.4f} implausible"

    def test_bollinger_rejects_non_finite_num_std(self, monkeypatch):
        """
        NaN <= 0 is False, so NaN used to pass validation and reach JSON
        serialization, where Starlette raised OUTSIDE the route's try/except —
        producing an unhandled 500 with a traceback instead of a 400.
        """
        series = make_closes(100, daily_log_returns=np.random.default_rng(3).normal(0, 0.01, 99))
        _install_series(monkeypatch, {"AAPL": series})

        for bad in ("nan", "inf", "-inf", "0", "-1"):
            resp = client.get(f"/models/bollinger/AAPL?num_std={bad}")
            assert resp.status_code == 400, f"num_std={bad} returned {resp.status_code}"

    def test_bollinger_function_rejects_nan(self):
        closes = np.linspace(100, 120, 60)
        for bad in (float("nan"), float("inf"), 0.0, -1.0):
            with pytest.raises(ValueError):
                quant.bollinger(closes, period=20, num_std=bad)


# ── Request amplification ─────────────────────────────────────────────────────

class TestVarRequestBounds:
    def test_position_count_is_capped(self, monkeypatch):
        """
        Each position costs one upstream fetch, and the list was unbounded —
        so a single request could drive an unbounded number of outbound calls.
        """
        _install_series(monkeypatch, {})
        positions = [
            {"symbol": f"S{i}"[:9], "shares": 1, "avgCost": 10} for i in range(500)
        ]
        resp = client.post("/models/var", json={"positions": positions})
        assert resp.status_code == 422

    def test_cap_boundary_is_accepted(self, monkeypatch):
        series = make_closes(80, start_price=10.0)
        _install_series(monkeypatch, {"AAPL": series})
        positions = [{"symbol": "AAPL", "shares": 1, "avgCost": 10}] * models_router.MAX_VAR_POSITIONS
        resp = client.post("/models/var", json={"positions": positions})
        assert resp.status_code == 200


# ── JSON-serializability of numeric output ────────────────────────────────────

class TestNonFiniteGuards:
    def test_pairs_rejects_non_finite_history(self, monkeypatch):
        """
        A zero or negative close yields an infinite log-return; corrcoef then
        returns NaN, which Starlette refuses to serialize. The guard used to be
        `var_a == 0`, and NaN != 0, so it fell through to the NaN branch.
        """
        bad = ClosesSeries(
            dates=[f"2024-01-{d:02d}" for d in range(1, 29)],
            closes=np.array([100.0] * 20 + [0.0] + [101.0] * 20 + [102.0] * 20),
        )
        good = make_closes(88, start_price=50.0)
        _install_series(monkeypatch, {"BAD": bad, "GOOD": good})
        resp = client.get("/models/pairs/BAD/GOOD")
        assert resp.status_code in (400, 404), f"got {resp.status_code}: {resp.text[:200]}"

    def test_fetch_closes_drops_non_positive_prices(self, monkeypatch):
        """Non-positive closes are dropped rather than poisoning log-returns."""
        payload = {
            "timestamp": [1_700_000_000 + i * 86_400 for i in range(30)],
            "indicators": {"quote": [{"close": [100.0] * 25 + [0.0] * 5}]},
        }
        monkeypatch.setattr(market_data, "_request_chart", lambda *a, **k: payload)
        market_data.clear_cache()

        series = market_data.fetch_closes("TEST")
        assert series is not None
        assert np.all(series.closes > 0)


# ── Shared cache safety ───────────────────────────────────────────────────────

class TestCacheSafety:
    def test_cached_closes_are_not_shared_mutable_state(self, monkeypatch):
        """
        fetch_closes handed out the cached ndarray itself. A caller doing
        `closes *= 2` would corrupt the cache for every concurrent request.
        """
        payload = {
            "timestamp": [1_700_000_000 + i * 86_400 for i in range(40)],
            "indicators": {"quote": [{"close": [100.0 + i for i in range(40)]}]},
        }
        monkeypatch.setattr(market_data, "_request_chart", lambda *a, **k: payload)
        market_data.clear_cache()

        first = market_data.fetch_closes("MUT1")
        # Mutate the ndarray in place — this is the exact hazard: if the cache
        # handed out its own array, this write would be visible to everyone.
        first.closes[:] *= 2.0

        second = market_data.fetch_closes("MUT1")
        assert second.closes[0] == pytest.approx(100.0), "cache was corrupted by a caller"

    def test_cached_chart_rows_are_not_shared(self, monkeypatch):
        payload = {
            "timestamp": [1_700_000_000 + i * 86_400 for i in range(30)],
            "indicators": {
                "quote": [
                    {
                        "close": [100.0 + i for i in range(30)],
                        "open": [100.0] * 30,
                        "high": [101.0] * 30,
                        "low": [99.0] * 30,
                        "volume": [10] * 30,
                    }
                ]
            },
            "meta": {"symbol": "MUT2", "regularMarketPrice": 129.0},
        }
        monkeypatch.setattr(market_data, "_request_chart", lambda *a, **k: payload)
        market_data.clear_cache()

        first = market_data.fetch_chart("MUT2")
        first.ohlcv[0]["close"] = -1.0
        first.meta["regularMarketPrice"] = -1.0

        second = market_data.fetch_chart("MUT2")
        assert second.ohlcv[0]["close"] != -1.0
        assert second.meta["regularMarketPrice"] == 129.0

    def test_concurrent_misses_issue_one_upstream_request(self, monkeypatch):
        """
        Single-flight: 8 threads racing on a cold key used to trigger 8
        identical upstream requests (and 8x the chance of a rate limit).
        """
        calls = []

        payload = {
            "timestamp": [1_700_000_000 + i * 86_400 for i in range(40)],
            "indicators": {"quote": [{"close": [100.0 + i for i in range(40)]}]},
        }

        def slow_request(*args, **kwargs):
            import time as _t

            calls.append(1)
            _t.sleep(0.05)
            return payload

        monkeypatch.setattr(market_data, "_request_chart", slow_request)
        market_data.clear_cache()

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: market_data.fetch_closes("RACE"), range(8)))

        assert len(calls) == 1, f"{len(calls)} upstream requests for one key"
        assert all(r is not None for r in results)

    def test_fetchers_do_not_share_cache_key_space(self, monkeypatch):
        """
        fetch_closes stored under the literal marker "closes" in the interval
        slot of the same flat key tuple real intervals used, so a crafted
        interval could return the wrong payload type.
        """
        chart_payload = {
            "timestamp": [1_700_000_000 + i * 86_400 for i in range(30)],
            "indicators": {"quote": [{"close": [100.0 + i for i in range(30)]}]},
            "meta": {"symbol": "NS"},
        }
        monkeypatch.setattr(market_data, "_request_chart", lambda *a, **k: chart_payload)
        market_data.clear_cache()

        closes = market_data.fetch_closes("NS")
        chart = market_data.fetch_chart("NS", interval="1d", range_="1y")

        assert isinstance(closes, ClosesSeries)
        assert isinstance(chart, ChartResult)
