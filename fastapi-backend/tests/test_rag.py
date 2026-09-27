"""RAG endpoint + answer-extraction tests (no network, no LLM calls)."""
from fastapi.testclient import TestClient

import main
from routers import rag

client = TestClient(main.app, raise_server_exceptions=False)


class TestExtractAnswer:
    def test_delimited_answer(self):
        raw = "chain of thought blah\n\n<<<ANSWER>>>\nReal answer with [Source: Yahoo Finance].\n<<<END>>>"
        assert rag._extract_answer(raw) == "Real answer with [Source: Yahoo Finance]."

    def test_open_delimiter_only(self):
        raw = "<<<ANSWER>>>\nTruncated but useful answer"
        assert rag._extract_answer(raw) == "Truncated but useful answer"

    def test_fallback_prefers_last_cited_paragraph(self):
        raw = "First paragraph without sources.\n\nCited conclusion here [Source: NewsAPI 2024-01-01]."
        assert rag._extract_answer(raw) == "Cited conclusion here [Source: NewsAPI 2024-01-01]."

    def test_fallback_skips_reasoning_markers(self):
        raw = "Let me think about this.\n\nThe stock looks solid."
        assert rag._extract_answer(raw) == "The stock looks solid."

    def test_empty(self):
        assert rag._extract_answer("") == ""


class TestExtractCitations:
    def test_parses_and_strips(self):
        answer = "Apple is up. [Source: Yahoo Finance 2024-01-01] Buy side agrees. [Source: NewsAPI]"
        clean, citations = rag._extract_citations(answer)
        assert "[Source:" not in clean
        assert citations == [
            {
                "text": "Yahoo Finance 2024-01-01",
                "source": "Yahoo Finance",
                "date": "2024-01-01",
                "url": None,
            },
            {"text": "NewsAPI", "source": "NewsAPI", "date": "", "url": None},
        ]

    def test_no_citations(self):
        clean, citations = rag._extract_citations("No sources here.")
        assert clean == "No sources here."
        assert citations == []


class TestLinkCitations:
    def test_links_by_source_and_date(self):
        citations = [
            {"text": "NewsAPI 2024-01-01", "source": "NewsAPI", "date": "2024-01-01", "url": None},
            {"text": "NewsAPI 2024-02-01", "source": "NewsAPI", "date": "2024-02-01", "url": None},
        ]
        source_urls = [
            {"source": "NewsAPI", "date": "2024-02-01", "url": "https://example.com/b"},
            {"source": "NewsAPI", "date": "2024-01-01", "url": "https://example.com/a"},
        ]
        rag._link_citations(citations, source_urls)
        assert citations[0]["url"] == "https://example.com/a"
        assert citations[1]["url"] == "https://example.com/b"

    def test_links_source_without_date(self):
        citations = [{"text": "Yahoo Finance", "source": "Yahoo Finance", "date": "", "url": None}]
        source_urls = [{"source": "Yahoo Finance", "url": "https://finance.yahoo.com/quote/AAPL"}]
        rag._link_citations(citations, source_urls)
        assert citations[0]["url"] == "https://finance.yahoo.com/quote/AAPL"

    def test_leaves_unmatched_alone(self):
        citations = [{"text": "Random Blog", "source": "Random Blog", "date": "", "url": None}]
        rag._link_citations(citations, [{"source": "NewsAPI", "url": "https://example.com"}])
        assert citations[0]["url"] is None


class TestChatEndpoint:
    def test_message_too_long_422(self):
        resp = client.post("/rag/chat", json={"message": "x" * 2001})
        assert resp.status_code == 422

    def test_empty_message_422(self):
        resp = client.post("/rag/chat", json={"message": ""})
        assert resp.status_code == 422

    def test_unknown_provider_400(self):
        resp = client.post("/rag/chat", json={"message": "hi", "provider": "nope"})
        assert resp.status_code == 400

    def test_unconfigured_provider_503(self, monkeypatch):
        monkeypatch.setattr(rag, "anthropic_api_key", lambda: None)
        monkeypatch.setattr(rag, "gemini_api_key", lambda: None)
        resp = client.post("/rag/chat", json={"message": "hi", "provider": "anthropic"})
        assert resp.status_code == 503

    def test_invalid_symbol_400(self, monkeypatch):
        monkeypatch.setattr(rag, "anthropic_api_key", lambda: "fake")
        resp = client.post(
            "/rag/chat", json={"message": "hi", "symbol": "NOT VALID!", "provider": "anthropic"}
        )
        assert resp.status_code == 400


class TestProviderConfig:
    """Config is read per call, and a blank env var must not shadow a default.

    Render's `sync: false` creates unset env vars as EMPTY strings, which
    `os.getenv(name, default)` returns instead of the default — that silently
    broke every Anthropic call on a fresh deploy.
    """

    def test_empty_model_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_MODEL", "")
        monkeypatch.setenv("GEMINI_MODEL", "")
        assert rag.anthropic_model() == rag.DEFAULT_ANTHROPIC_MODEL
        assert rag.gemini_model() == rag.DEFAULT_GEMINI_MODEL

    def test_blank_api_key_reads_as_unset(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("NEWSAPI_KEY", "")
        assert rag.anthropic_api_key() is None
        assert rag.gemini_api_key() is None
        assert rag.newsapi_key() is None

    def test_env_change_takes_effect_without_restart(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert rag.anthropic_api_key() is None
        monkeypatch.setenv("ANTHROPIC_API_KEY", "rotated")
        assert rag.anthropic_api_key() == "rotated"

    def test_default_provider_prefers_anthropic_when_keyed(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        assert rag.default_provider() == "anthropic"
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        monkeypatch.setenv("GEMINI_API_KEY", "key")
        assert rag.default_provider() == "gemini"

    def test_blank_llm_provider_does_not_become_the_provider(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert rag.default_provider() == "gemini"


class TestDailyIndicatorsPart:
    def test_returns_tuple_with_basic_meta_for_short_history(self, monkeypatch):
        # Regression: the early-exit path for <30-bar symbols returned a bare
        # list instead of (parts, urls), silently dropping ALL quant context
        # for recent IPOs / some ETFs.

        from services import market_data
        from services.market_data import ChartResult

        dates = [f"2024-01-{d:02d}" for d in range(2, 12)]  # 10 bars only
        ohlcv = [
            {"date": d, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1}
            for d in dates
        ]
        chart = ChartResult(ohlcv=ohlcv, meta={"shortName": "TINY"}, dates=dates)
        monkeypatch.setattr(market_data, "fetch_chart", lambda symbol, range_="1y": chart)
        monkeypatch.setattr(market_data, "fetch_intraday", lambda symbol: None)

        parts, urls = rag._daily_indicators_part("TINY")
        assert isinstance(parts, list) and isinstance(urls, list)
        assert any("Price:" in p for p in parts)
        assert not any("Regime:" in p for p in parts)  # not enough data
        assert urls and urls[0]["source"] == "Yahoo Finance"

    def test_full_history_includes_indicators(self, monkeypatch):
        import numpy as np

        from services import market_data
        from services.market_data import ChartResult

        n = 200
        dates = ["2024-01-01"] * n  # dates unused by the math
        closes = 100 * np.exp(np.linspace(0, 0.5, n))
        ohlcv = [
            {"date": d, "open": float(c), "high": float(c), "low": float(c), "close": float(c), "volume": 1}
            for d, c in zip(dates, closes, strict=True)
        ]
        chart = ChartResult(ohlcv=ohlcv, meta={"shortName": "BIG"}, dates=dates)
        monkeypatch.setattr(market_data, "fetch_chart", lambda symbol, range_="1y": chart)
        monkeypatch.setattr(market_data, "fetch_intraday", lambda symbol: None)

        parts, urls = rag._daily_indicators_part("BIG")
        assert any("Regime:" in p for p in parts)
        assert any("RSI" in p for p in parts)


class TestProvidersEndpoint:
    def test_shape(self):
        resp = client.get("/rag/providers")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"default", "available", "models"}
        assert set(body["available"]) == {"anthropic", "gemini"}
