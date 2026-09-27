"""Portfolio router tests with the db module faked."""
from fastapi.testclient import TestClient

import db
import main

client = TestClient(main.app, raise_server_exceptions=False)


class TestHoldings:
    def test_list(self, monkeypatch):
        monkeypatch.setattr(
            db,
            "get_holdings",
            lambda user_id="default": [
                {"id": 1, "symbol": "AAPL", "shares": 2.0, "avgCost": 150.0, "entryDate": None}
            ],
        )
        resp = client.get("/portfolio/holdings")
        assert resp.status_code == 200
        assert resp.json()[0]["symbol"] == "AAPL"

    def test_add_valid(self, monkeypatch):
        captured = {}

        def fake_upsert(user_id, symbol, shares, avg_cost, entry_date=None):
            captured.update(symbol=symbol, shares=shares, avg_cost=avg_cost, entry_date=entry_date)
            return {
                "id": 7,
                "symbol": symbol,
                "shares": shares,
                "avgCost": avg_cost,
                "entryDate": str(entry_date) if entry_date else None,
            }

        monkeypatch.setattr(db, "upsert_holding", fake_upsert)
        resp = client.post("/portfolio/holdings", json={"symbol": "aapl", "shares": 1.5, "avgCost": 100})
        assert resp.status_code == 200
        assert captured == {"symbol": "AAPL", "shares": 1.5, "avg_cost": 100, "entry_date": None}

    def test_add_persists_entry_date(self, monkeypatch):
        """entry_date was selected on every read but never written, so the
        column was permanently NULL and the API always returned null."""
        captured = {}

        def fake_upsert(user_id, symbol, shares, avg_cost, entry_date=None):
            captured["entry_date"] = entry_date
            return {
                "id": 8,
                "symbol": symbol,
                "shares": shares,
                "avgCost": avg_cost,
                "entryDate": str(entry_date) if entry_date else None,
            }

        monkeypatch.setattr(db, "upsert_holding", fake_upsert)
        resp = client.post(
            "/portfolio/holdings",
            json={"symbol": "AAPL", "shares": 1, "avgCost": 10, "entryDate": "2024-06-01"},
        )
        assert resp.status_code == 200
        assert str(captured["entry_date"]) == "2024-06-01"
        assert resp.json()["entryDate"] == "2024-06-01"

    def test_add_bad_entry_date_422(self):
        resp = client.post(
            "/portfolio/holdings",
            json={"symbol": "AAPL", "shares": 1, "avgCost": 10, "entryDate": "not-a-date"},
        )
        assert resp.status_code == 422

    def test_add_zero_shares_422(self):
        resp = client.post("/portfolio/holdings", json={"symbol": "AAPL", "shares": 0, "avgCost": 100})
        assert resp.status_code == 422

    def test_add_nan_shares_422(self):
        resp = client.post("/portfolio/holdings", json={"symbol": "AAPL", "shares": "nan", "avgCost": 100})
        assert resp.status_code == 422

    def test_add_bad_symbol_422(self):
        resp = client.post("/portfolio/holdings", json={"symbol": "BAD SYMBOL!", "shares": 1, "avgCost": 10})
        assert resp.status_code == 422

    def test_db_error_is_500_without_leaking_details(self, monkeypatch):
        def boom(user_id="default"):
            raise RuntimeError("psycopg: connection refused at 10.0.0.1 with secret stuff")

        monkeypatch.setattr(db, "get_holdings", boom)
        resp = client.get("/portfolio/holdings")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"
        assert "psycopg" not in resp.text

    def test_delete_missing_404(self, monkeypatch):
        monkeypatch.setattr(db, "delete_holding", lambda user_id, lot_id: False)
        assert client.delete("/portfolio/holdings/999").status_code == 404

    def test_delete_ok(self, monkeypatch):
        monkeypatch.setattr(db, "delete_holding", lambda user_id, lot_id: True)
        assert client.delete("/portfolio/holdings/1").status_code == 200


class TestWatchlist:
    def test_list(self, monkeypatch):
        monkeypatch.setattr(db, "get_watchlist", lambda user_id="default": ["AAPL", "MSFT"])
        assert client.get("/portfolio/watchlist").json() == ["AAPL", "MSFT"]

    def test_add(self, monkeypatch):
        monkeypatch.setattr(db, "add_to_watchlist", lambda user_id, symbol: None)
        assert client.post("/portfolio/watchlist/GOOG").json() == {"added": True}

    def test_add_rejects_overlong_symbol(self, monkeypatch):
        monkeypatch.setattr(db, "add_to_watchlist", lambda user_id, symbol: None)
        assert client.post("/portfolio/watchlist/THISISTOOLONG").status_code == 400

    def test_remove_missing_404(self, monkeypatch):
        monkeypatch.setattr(db, "remove_from_watchlist", lambda user_id, symbol: False)
        assert client.delete("/portfolio/watchlist/NOPE").status_code == 404

    def test_remove_ok(self, monkeypatch):
        monkeypatch.setattr(db, "remove_from_watchlist", lambda user_id, symbol: True)
        assert client.delete("/portfolio/watchlist/AAPL").json() == {"deleted": True}
