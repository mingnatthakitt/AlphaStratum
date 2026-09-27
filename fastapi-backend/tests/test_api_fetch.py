"""Endpoint tests for /fetch — ticker, search, quotes, screener (no network)."""
import pytest
from conftest import business_dates
from fastapi.testclient import TestClient

import main
from services import market_data
from services.market_data import ChartResult

client = TestClient(main.app, raise_server_exceptions=False)


def _chart(symbol: str, price: float, meta: dict | None = None) -> ChartResult:
    dates = business_dates(60)
    ohlcv = [
        {
            "date": d,
            "open": price * 0.99,
            "high": price * 1.01,
            "low": price * 0.98,
            "close": price,
            "volume": 1000,
        }
        for d in dates
    ]
    meta = meta or {"shortName": symbol, "regularMarketPrice": price}
    return ChartResult(ohlcv=ohlcv, meta=meta, dates=dates)


@pytest.fixture(autouse=True)
def _charts(monkeypatch):
    charts = {"AAAA": _chart("AAAA", 100.0), "BBBB": _chart("BBBB", 50.0)}
    monkeypatch.setattr(
        market_data,
        "fetch_chart",
        lambda symbol, interval="1d", range_="1y": charts.get(symbol.upper()),
    )
    fake_results = [{"symbol": "AAAA", "name": "Alpha", "exchange": "NASDAQ", "type": "EQUITY"}]
    monkeypatch.setattr(market_data, "search_symbols", lambda q, limit=10: fake_results if q else [])
    monkeypatch.setattr(market_data, "SCREENER_SECTORS", {"tech"})
    monkeypatch.setattr(market_data, "SECTOR_TICKERS", {"tech": ["AAAA", "BBBB"]})
    return charts


class TestTicker:
    def test_ok(self):
        resp = client.get("/fetch/ticker/AAAA")
        assert resp.status_code == 200
        body = resp.json()
        assert body["info"]["symbol"] == "AAAA"
        assert body["info"]["price"] == 100.0
        assert len(body["ohlcv"]) == 60
        assert body["info"]["weekHigh52"] == pytest.approx(101.0)

    def test_symbol_normalized(self):
        assert client.get("/fetch/ticker/aaaa").status_code == 200

    def test_invalid_symbol_400(self):
        assert client.get("/fetch/ticker/NOT%20VALID").status_code == 400

    def test_unknown_404(self):
        assert client.get("/fetch/ticker/MISSING").status_code == 404


class TestQuotes:
    def test_batch(self):
        resp = client.get("/fetch/quotes?symbols=AAAA,BBBB")
        assert resp.status_code == 200
        quotes = {q["symbol"]: q for q in resp.json()["quotes"]}
        assert quotes["AAAA"]["price"] == 100.0
        assert quotes["BBBB"]["price"] == 50.0

    def test_skips_invalid_symbols(self):
        resp = client.get("/fetch/quotes?symbols=AAAA,NOT%20VALID")
        assert resp.status_code == 200
        symbols = [q["symbol"] for q in resp.json()["quotes"]]
        assert symbols == ["AAAA"]

    def test_caps_at_20(self):
        many = ",".join(["AAAA"] * 25)
        resp = client.get(f"/fetch/quotes?symbols={many}")
        assert resp.status_code == 200
        assert len(resp.json()["quotes"]) <= 20


class TestSearch:
    def test_ok(self):
        resp = client.get("/fetch/search?q=alpha")
        assert resp.status_code == 200
        assert resp.json()["results"][0]["symbol"] == "AAAA"

    def test_empty_query(self):
        resp = client.get("/fetch/search?q=")
        assert resp.status_code == 200
        assert resp.json()["results"] == []


class TestScreener:
    def test_sorted_by_score_desc(self):
        resp = client.get("/fetch/screener/tech")
        assert resp.status_code == 200
        stocks = resp.json()["stocks"]
        assert len(stocks) == 2
        scores = [s["score"] for s in stocks]
        assert scores == sorted(scores, reverse=True)

    def test_unknown_sector_400(self):
        assert client.get("/fetch/screener/bogus").status_code == 400
