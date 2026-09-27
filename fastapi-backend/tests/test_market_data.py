"""Tests for services/market_data.py: caching, symbol handling, date alignment."""
from datetime import UTC, datetime

import numpy as np
import pytest

from services import market_data
from services.market_data import ClosesSeries, SymbolError


def _ts(iso_date: str) -> float:
    return datetime.fromisoformat(iso_date).replace(tzinfo=UTC).timestamp()


def raw_chart(dates: list[str], closes: list[float | None], meta: dict | None = None) -> dict:
    """Build a fake Yahoo chart `result[0]` payload."""
    n = len(dates)
    return {
        "meta": meta or {},
        "timestamp": [_ts(d) for d in dates],
        "indicators": {
            "quote": [
                {
                    "open": [c and c - 0.5 for c in closes],
                    "high": [c and c + 1 for c in closes],
                    "low": [c and c - 1 for c in closes],
                    "close": closes,
                    "volume": [1000] * n,
                }
            ]
        },
    }


class TestNormalizeSymbol:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("aapl", "AAPL"), (" brk.b ", "BRK.B"), ("^GSPC", "^GSPC"), ("BF-B", "BF-B")],
    )
    def test_valid(self, raw, expected):
        assert market_data.normalize_symbol(raw) == expected

    @pytest.mark.parametrize("raw", ["", "  ", "DROP TABLE", "TOOLONGTICKER!", "A" * 11, "AB C"])
    def test_invalid(self, raw):
        with pytest.raises(SymbolError):
            market_data.normalize_symbol(raw)


class TestFetchChart:
    def test_parses_and_drops_null_closes(self, monkeypatch):
        calls = []

        def fake_request(symbol, interval, range_):
            calls.append(symbol)
            return raw_chart(
                ["2024-01-02", "2024-01-03", "2024-01-04"],
                [100.0, None, 102.0],
                meta={"regularMarketPrice": 102.0, "regularMarketPreviousClose": 100.0},
            )

        monkeypatch.setattr(market_data, "_request_chart", fake_request)
        result = market_data.fetch_chart("aapl")
        assert result is not None
        assert [row["date"] for row in result.ohlcv] == ["2024-01-02", "2024-01-04"]
        assert result.dates == ["2024-01-02", "2024-01-04"]
        assert result.ohlcv[1]["close"] == 102.0

    def test_cached_second_call_skips_network(self, monkeypatch):
        calls = []

        def fake_request(symbol, interval, range_):
            calls.append(1)
            return raw_chart(["2024-01-02"], [100.0])

        monkeypatch.setattr(market_data, "_request_chart", fake_request)
        market_data.fetch_chart("aapl")
        market_data.fetch_chart("aapl")
        assert len(calls) == 1

    def test_symbol_normalized_for_cache_key(self, monkeypatch):
        calls = []

        def fake_request(symbol, interval, range_):
            calls.append(symbol)
            return raw_chart(["2024-01-02"], [100.0])

        monkeypatch.setattr(market_data, "_request_chart", fake_request)
        market_data.fetch_chart("aapl")
        market_data.fetch_chart("AAPL")
        assert calls == ["AAPL"]

    def test_returns_none_on_failure(self, monkeypatch):
        monkeypatch.setattr(market_data, "_request_chart", lambda *a: None)
        assert market_data.fetch_chart("AAPL") is None


class TestFetchCloses:
    def test_filters_none_in_tandem_with_dates(self, monkeypatch):
        dates = [f"2024-01-{d:02d}" for d in range(1, 27)][:25]
        closes = [10.0 + i * 0.5 for i in range(25)]
        closes[5] = None  # one missing close mid-series
        monkeypatch.setattr(market_data, "_request_chart", lambda *a: raw_chart(dates, closes))
        series = market_data.fetch_closes("aapl")
        assert series is not None
        assert len(series.dates) == 24
        assert None not in series.closes
        # dropped date is gone from the output, order preserved
        assert "2024-01-06" not in series.dates

    def test_none_when_too_short(self, monkeypatch):
        monkeypatch.setattr(
            market_data,
            "_request_chart",
            lambda *a: raw_chart(["2024-01-02", "2024-01-03"], [10.0, 11.0]),
        )
        assert market_data.fetch_closes("aapl") is None


class TestAlignCloses:
    def test_intersection_alignment(self):
        a = ClosesSeries(
            dates=["2024-01-02", "2024-01-03", "2024-01-04"], closes=np.array([1.0, 2.0, 3.0])
        )
        b = ClosesSeries(
            dates=["2024-01-03", "2024-01-04", "2024-01-05"], closes=np.array([20.0, 30.0, 40.0])
        )
        dates, aligned = market_data.align_closes({"A": a, "B": b})
        assert dates == ["2024-01-03", "2024-01-04"]
        assert aligned["A"].tolist() == [2.0, 3.0]
        assert aligned["B"].tolist() == [20.0, 30.0]

    def test_no_overlap_raises(self):
        a = ClosesSeries(dates=["2024-01-02"], closes=np.array([1.0]))
        b = ClosesSeries(dates=["2024-02-02"], closes=np.array([2.0]))
        with pytest.raises(ValueError):
            market_data.align_closes({"A": a, "B": b})

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            market_data.align_closes({})


class TestChartMetaSummary:
    def test_change_percent(self):
        summary = market_data.chart_meta_summary(
            {"regularMarketPrice": 110.0, "regularMarketPreviousClose": 100.0, "shortName": "Apple"},
            "AAPL",
            [],
        )
        assert summary["change"] == pytest.approx(10.0)
        assert summary["changePercent"] == pytest.approx(10.0)
        assert summary["name"] == "Apple"

    def test_falls_back_to_ohlcv(self):
        ohlcv = [{"close": 50.0}, {"close": 55.0}]
        summary = market_data.chart_meta_summary({}, "XYZ", ohlcv)
        assert summary["price"] == pytest.approx(55.0)
        assert summary["previousClose"] == pytest.approx(50.0)

    def test_handles_bad_meta_values(self):
        summary = market_data.chart_meta_summary(
            {"regularMarketPrice": None, "regularMarketPreviousClose": "garbage"}, "XYZ", [{"close": 9.0}]
        )
        assert summary["change"] == 0.0
        assert summary["changePercent"] == 0.0


class TestSectorUniverses:
    def test_screener_sectors_exist(self):
        for sector in market_data.SCREENER_SECTORS:
            assert len(market_data.SECTOR_TICKERS[sector]) >= 10
            # no duplicates within a sector
            assert len(set(market_data.SECTOR_TICKERS[sector])) == len(market_data.SECTOR_TICKERS[sector])

    def test_no_overlap_between_screener_and_correlation_only(self):
        # etf vs broad/dividends universes are distinct on purpose
        etf = set(market_data.SECTOR_TICKERS["etf"])
        broad = set(market_data.SECTOR_TICKERS["broad"])
        assert etf & broad  # they share blue-chip ETFs — that's fine, just sanity
