"""
Portfolio and watchlist persistence (Supabase Postgres via the shared pool).
"""
from __future__ import annotations

from services.database import connection


def get_holdings(user_id: str = "default") -> list[dict]:
    """Fetch all portfolio holdings for a user."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, symbol, shares, avg_cost, entry_date
            FROM portfolio_holdings
            WHERE user_id = %s
            ORDER BY created_at ASC
            """,
            (user_id,),
        )
        return [
            {
                "id": row[0],
                "symbol": row[1],
                "shares": float(row[2]),
                "avgCost": float(row[3]),
                "entryDate": str(row[4]) if row[4] else None,
            }
            for row in cur.fetchall()
        ]


def upsert_holding(
    user_id: str,
    symbol: str,
    shares: float,
    avg_cost: float,
    entry_date=None,
) -> dict:
    """Insert a new portfolio lot. Always inserts — caller manages duplicates."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO portfolio_holdings (user_id, symbol, shares, avg_cost, entry_date)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, symbol, shares, avg_cost, entry_date
            """,
            (user_id, symbol.upper(), shares, avg_cost, entry_date),
        )
        row = cur.fetchone()
        return {
            "id": row[0],
            "symbol": row[1],
            "shares": float(row[2]),
            "avgCost": float(row[3]),
            "entryDate": str(row[4]) if row[4] else None,
        }


def delete_holding(user_id: str, lot_id: int) -> bool:
    """Delete a portfolio lot by its id. Returns True if deleted."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM portfolio_holdings WHERE user_id = %s AND id = %s",
            (user_id, lot_id),
        )
        return cur.rowcount > 0


def update_holding(user_id: str, lot_id: int, shares: float, avg_cost: float) -> dict | None:
    """Update shares/avg_cost of a lot. Returns the updated row or None."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE portfolio_holdings
            SET shares = %s, avg_cost = %s, updated_at = NOW()
            WHERE user_id = %s AND id = %s
            RETURNING id, symbol, shares, avg_cost, entry_date
            """,
            (shares, avg_cost, user_id, lot_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "symbol": row[1],
            "shares": float(row[2]),
            "avgCost": float(row[3]),
            "entryDate": str(row[4]) if row[4] else None,
        }


def get_watchlist(user_id: str = "default") -> list[str]:
    """Fetch watchlist symbols for a user."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM watchlist WHERE user_id = %s ORDER BY created_at ASC",
            (user_id,),
        )
        return [row[0] for row in cur.fetchall()]


def add_to_watchlist(user_id: str, symbol: str) -> None:
    """Add a symbol to the watchlist. Idempotent (ON CONFLICT DO NOTHING)."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO watchlist (user_id, symbol) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (user_id, symbol.upper()),
        )


def remove_from_watchlist(user_id: str, symbol: str) -> bool:
    """Remove a symbol from the watchlist. Returns True if deleted."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM watchlist WHERE user_id = %s AND symbol = %s",
            (user_id, symbol.upper()),
        )
        return cur.rowcount > 0
