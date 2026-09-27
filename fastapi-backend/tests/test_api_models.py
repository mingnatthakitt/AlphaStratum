"""Endpoint tests for /models — with market data monkeypatched (no network)."""
import sys
import types

import numpy as np
import pytest
from conftest import business_dates, make_closes
from fastapi.testclient import TestClient

import main
from services import market_data
from services.market_data import ClosesSeries

client = TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):

    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    yield


def _install_series(monkeypatch, series_by_symbol: dict[str, ClosesSeries]):
    def fake_fetch_closes(symbol, range_="1y"):
        return series_by_symbol.get(symbol.upper())

    monkeypatch.setattr(market_data, "fetch_closes", fake_fetch_closes)


def _install_charts(monkeypatch, charts: dict[str, object]):
    def fake_fetch_chart(symbol, interval="1d", range_="1y"):
        return charts.get(symbol.upper())

    monkeypatch.setattr(market_data, "fetch_chart", fake_fetch_chart)


class TestRegime:
    def test_ok(self, monkeypatch):
        series = make_closes(100, daily_log_returns=0.006)  # every day > +0.5% → bull
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.get("/models/regime/AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert body["currentRegime"] == "bull"
        assert set(body["probabilities"]) == {"bull", "bear", "sideways"}
        assert sum(body["probabilities"].values()) == pytest.approx(1.0)

    def test_symbol_lowercased(self, monkeypatch):
        series = make_closes(100)
        _install_series(monkeypatch, {"AAPL": series})
        assert client.get("/models/regime/aapl").status_code == 200

    def test_invalid_symbol_400(self, monkeypatch):
        resp = client.get("/models/regime/NOT%20VALID")
        assert resp.status_code == 400

    def test_no_data_404(self, monkeypatch):
        _install_series(monkeypatch, {})
        assert client.get("/models/regime/AAPL").status_code == 404


class TestMonteCarlo:
    @pytest.fixture
    def series(self):
        rng = np.random.default_rng(3)
        returns = rng.normal(0.0002, 0.012, 130)
        return make_closes(131, daily_log_returns=returns)

    def test_ok(self, monkeypatch, series):
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.get("/models/montecarlo/AAPL?days=30")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["paths"]) == 10
        assert all(len(path) == 30 for path in body["paths"])
        assert len(body["forecastDates"]) == 30
        assert body["percentiles"]["p5"][0] <= body["percentiles"]["p95"][0]
        # forecast dates skip weekends
        from datetime import date

        for d in body["forecastDates"]:
            assert date.fromisoformat(d).weekday() < 5

    def test_invalid_horizon_400(self, monkeypatch, series):
        _install_series(monkeypatch, {"AAPL": series})
        assert client.get("/models/montecarlo/AAPL?days=45").status_code == 400

    def test_fan_width_plausible(self, monkeypatch):
        # Pins the per-day GBM convention: daily vol 1% over 30 trading days
        # must give a 30-day p5–p95 width of ≈ ±1.645·σ·√30 ≈ 18% of spot.
        # (The pre-refactor code passed daily σ into an annualized-dt GBM,
        # producing visually flat fans.)
        returns = np.full(130, 0.0)  # zero drift; volatility-only
        series = make_closes(131, daily_log_returns=returns)
        # make_closes with constant returns gives constant prices — inject vol:
        rng = np.random.default_rng(5)
        returns = rng.normal(0.0, 0.01, 130)
        series = make_closes(131, daily_log_returns=returns)
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.get("/models/montecarlo/AAPL?days=30")
        assert resp.status_code == 200
        body = resp.json()
        spot = body["lastPrice"]
        width_pct = (body["percentiles"]["p95"][-1] - body["percentiles"]["p5"][-1]) / spot
        assert 0.10 < width_pct < 0.30, f"fan width {width_pct:.4f} implausible for daily vol 1%"

    def test_regime_cond_ok(self, monkeypatch, series):
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.get("/models/montecarlo/AAPL/regime-cond?days=15")
        assert resp.status_code == 200
        body = resp.json()
        assert body["volatilitySource"] == "garch"
        assert set(body["fans"]) == {"bull", "bear", "sideways"}
        assert len(body["blended"]["p50"]) == 15
        assert len(body["regimeProbabilities"]) == 15
        # regime probabilities sum to 1 each day
        for row in body["regimeProbabilities"]:
            assert row["bull"] + row["bear"] + row["sideways"] == pytest.approx(1.0, abs=1e-6)


class TestIndicators:
    @pytest.fixture
    def series(self):
        rng = np.random.default_rng(5)
        returns = rng.normal(0.0, 0.01, 260)
        return make_closes(261, daily_log_returns=returns)

    def test_rsi(self, monkeypatch, series):
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.get("/models/rsi/AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert 0 <= body["rsi"] <= 100
        assert len(body["history"]) == 30
        assert len(body["dates"]) == len(body["history"])
        assert body["dates"][-1] == series.dates[-1]

    def test_rsi_bad_period_400(self, monkeypatch, series):
        _install_series(monkeypatch, {"AAPL": series})
        assert client.get("/models/rsi/AAPL?period=1").status_code == 400

    def test_macd(self, monkeypatch, series):
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.get("/models/macd/AAPL")
        assert resp.status_code == 200
        body = resp.json()
        n = len(body["dates"])
        assert n == 60
        assert len(body["macdHistory"]) == n
        assert len(body["signalHistory"]) == n
        assert len(body["histogramHistory"]) == n

    def test_bollinger(self, monkeypatch, series):
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.get("/models/bollinger/AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert body["upper"] > body["lower"]
        assert len(body["history"]) == 60
        assert len(body["dates"]) == 60

    def test_bollinger_negative_std_400(self, monkeypatch, series):
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.get("/models/bollinger/AAPL?num_std=-1")
        assert resp.status_code == 400

    def test_atr(self, monkeypatch, series):
        from services.market_data import ChartResult

        ohlcv = [
            {
                "date": series.dates[i],
                "open": float(series.closes[i]),
                "high": float(series.closes[i]) + 1,
                "low": float(series.closes[i]) - 1,
                "close": float(series.closes[i]),
                "volume": 1000,
            }
            for i in range(len(series.dates))
        ]
        _install_charts(monkeypatch, {"AAPL": ChartResult(ohlcv=ohlcv, meta={}, dates=series.dates)})
        resp = client.get("/models/atr/AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert body["atr"] > 0  # TR is 2.0 on every bar (±1 around close)
        assert len(body["history"]) == 30
        assert len(body["dates"]) == 30

    def test_garch(self, monkeypatch, series):
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.get("/models/garch/AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["forecast"]) == 30
        assert len(body["forecastDates"]) == 30
        assert body["currentVol"] > 0

    def test_markov(self, monkeypatch, series):
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.get("/models/markov/AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert body["currentRegime"] in ("bull", "bear", "sideways")
        rows = body["transitionMatrix"].values()
        for row in rows:
            # 4-decimal rounding in the response drifts the sum slightly
            assert sum(row.values()) == pytest.approx(1.0, abs=1e-3)

    def test_markov_absorbing_state_is_serializable(self, monkeypatch):
        # 100 closes with the same daily return → absorbing regime → the old
        # code emitted float("inf"), which is not JSON-serializable (500).
        series = make_closes(101, daily_log_returns=0.006)
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.get("/models/markov/AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert body["expectedDuration"]["bull"] == 999.9
        assert "Infinity" not in resp.text


class TestVar:
    def test_value_weighted(self, monkeypatch):
        n = 100
        # A: constant price → zero returns; B: deterministic ramp returns
        series_a = make_closes(n, start_price=100.0, daily_log_returns=0.0)
        rb = np.linspace(-0.02, 0.02, n - 1)
        series_b = make_closes(n, start_price=200.0, daily_log_returns=rb)
        _install_series(monkeypatch, {"AAAA": series_a, "BBBB": series_b})

        resp = client.post(
            "/models/var",
            json={
                "positions": [
                    {"symbol": "AAAA", "shares": 1, "avgCost": 100},
                    {"symbol": "BBBB", "shares": 1, "avgCost": 200},
                ]
            },
        )
        assert resp.status_code == 200
        body = resp.json()

        total = float(series_a.closes[-1]) + float(series_b.closes[-1])
        expected_port = (float(series_b.closes[-1]) / total) * rb  # A contributes zero
        expected_var95 = round(float(-np.percentile(expected_port, 5) * total), 2)
        assert body["portfolioValue"] == pytest.approx(round(total, 2))
        assert body["var95"] == expected_var95
        assert body["var99"] >= body["var95"]

    def test_duplicate_symbols_aggregated(self, monkeypatch):
        series = make_closes(100, start_price=50.0)
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.post(
            "/models/var",
            json={
                "positions": [
                    {"symbol": "AAPL", "shares": 1, "avgCost": 50},
                    {"symbol": "AAPL", "shares": 2, "avgCost": 50},
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["portfolioValue"] == pytest.approx(150.0)

    def test_missing_symbol_reported_as_excluded(self, monkeypatch):
        series = make_closes(100)
        _install_series(monkeypatch, {"AAPL": series})
        resp = client.post(
            "/models/var",
            json={
                "positions": [
                    {"symbol": "AAPL", "shares": 1, "avgCost": 50},
                    {"symbol": "GONE", "shares": 1, "avgCost": 50},
                ]
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["excludedSymbols"] == ["GONE"]
        assert [c["symbol"] for c in body["contributions"]] == ["AAPL"]

    def test_empty_positions_400(self):
        assert client.post("/models/var", json={"positions": []}).status_code == 400

    def test_negative_shares_422(self):
        resp = client.post(
            "/models/var", json={"positions": [{"symbol": "AAPL", "shares": -5, "avgCost": 10}]}
        )
        assert resp.status_code == 422

    def test_no_data_404(self, monkeypatch):
        _install_series(monkeypatch, {})
        resp = client.post("/models/var", json={"positions": [{"symbol": "AAPL", "shares": 1, "avgCost": 1}]})
        assert resp.status_code == 404


class TestPairs:
    def test_identical_series(self, monkeypatch):
        series = make_closes(100, daily_log_returns=0.001)  # non-constant
        _install_series(monkeypatch, {"AAAA": series, "BBBB": series})
        resp = client.get("/models/pairs?a=AAAA&b=BBBB")
        assert resp.status_code == 200
        body = resp.json()
        assert body["beta"] == pytest.approx(1.0)
        assert body["correlation"] == pytest.approx(1.0)
        assert body["nObservations"] == 99

    def test_constant_series_no_nan(self, monkeypatch):
        # zero-variance returns would make corrcoef NaN (not JSON-serializable)
        series = make_closes(100, daily_log_returns=0.0)
        _install_series(monkeypatch, {"AAAA": series, "BBBB": series})
        resp = client.get("/models/pairs?a=AAAA&b=BBBB")
        assert resp.status_code == 200
        body = resp.json()
        assert body["beta"] == 0.0
        assert body["correlation"] == 1.0  # identical constant series
        assert "nan" not in resp.text.lower()

    def test_date_alignment(self, monkeypatch):
        # B starts 10 days later — alignment must use common dates, not index.
        series_a = make_closes(100)
        shifted = ClosesSeries(dates=series_a.dates[10:], closes=series_a.closes[10:])
        _install_series(monkeypatch, {"AAAA": series_a, "BBBB": shifted})
        resp = client.get("/models/pairs?a=AAAA&b=BBBB")
        assert resp.status_code == 200
        body = resp.json()
        # identical prices over the common window → correlation 1, 89 observations
        assert body["nObservations"] == 89
        assert body["correlation"] == pytest.approx(1.0)

    def test_same_symbol_400(self):
        assert client.get("/models/pairs?a=AAPL&b=AAPL").status_code == 400


class TestAnalyst:
    @staticmethod
    def _fake_yfinance(info, recommendations):
        class FakeRecs(list):
            """Mimics enough of a pandas DataFrame for the endpoint."""

            @property
            def iloc(self):
                return self

        class FakeTicker:
            def __init__(self, symbol):
                self.info = info
                self.recommendations = recommendations

        fake_yf = types.ModuleType("yfinance")
        fake_yf.Ticker = FakeTicker
        return fake_yf

    def test_with_recommendations(self, monkeypatch):
        fake_yf = self._fake_yfinance(
            {
                "currentPrice": 100.0,
                "targetMeanPrice": 150.0,
                "recommendationKey": "buy",
                "numberOfAnalystOpinions": 10,
            },
            self._recs_frame([{"strongBuy": 5, "buy": 3, "hold": 1, "sell": 1, "strongSell": 0}]),
        )
        monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

        resp = client.get("/models/analyst/AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert body["numberOfAnalysts"] == 10
        assert body["strongBuy"] == 5
        assert body["buy"] == 3

    @staticmethod
    def _recs_frame(rows):
        class FakeRecs(list):
            """Mimics enough of a pandas DataFrame for the endpoint."""

            @property
            def iloc(self):
                return self

        return FakeRecs(rows)

    def test_fallback_to_info(self, monkeypatch):
        fake_yf = self._fake_yfinance(
            {
                "currentPrice": 100.0,
                "targetMeanPrice": 150.0,
                "recommendationKey": "buy",
                "numberOfAnalystOpinions": 10,
            },
            None,
        )
        monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

        resp = client.get("/models/analyst/AAPL")
        assert resp.status_code == 200
        assert resp.json()["buy"] == 1  # mapped from recommendationKey "buy"


class TestCorrelationGraph:
    def test_graph_built(self, monkeypatch):
        base = np.linspace(100, 110, 60)
        series = {}
        for i, sym in enumerate(["AAA", "BBB", "CCC", "DDD"]):
            noise = 0.01 * i * np.arange(60)  # different trends → different correlations
            series[sym] = ClosesSeries(dates=business_dates(60), closes=base + noise)
        _install_series(monkeypatch, series)
        monkeypatch.setattr(market_data, "SECTOR_TICKERS", {"tech": ["AAA", "BBB", "CCC", "DDD"]})
        resp = client.get("/models/correlation-graph?sector=tech")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["nodes"]) == 4
        # MST on 4 nodes has 3 edges
        assert len(body["edges"]) == 3

    def test_unknown_sector_400(self):
        assert client.get("/models/correlation-graph?sector=bogus").status_code == 400

    def test_insufficient_data_503(self, monkeypatch):
        _install_series(monkeypatch, {})
        assert client.get("/models/correlation-graph?sector=tech").status_code == 503


class TestCacheAdmin:
    def test_purge_bounds(self):
        assert client.post("/models/cache/purge?max_age_seconds=-1").status_code == 400
        assert client.post("/models/cache/purge?max_age_seconds=99999999").status_code == 400
        assert client.post("/models/cache/purge").status_code == 200

    def test_stats_without_db(self):
        resp = client.get("/models/cache/stats")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
