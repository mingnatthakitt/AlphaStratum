import logging
import re
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import db
from services.errors import internal_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

# Single-user deployment (see LIMITATIONS.md). user_id is kept in the schema
# so a real auth layer can be dropped in without a migration.
USER_ID = "default"

# Same symbol shape as services.market_data.SYMBOL_RE.
SYMBOL_PATTERN = r"^[A-Za-z0-9.\-^=]{1,10}$"


class UpsertRequest(BaseModel):
    symbol: str = Field(pattern=SYMBOL_PATTERN, description="Ticker symbol, e.g. AAPL")
    shares: float = Field(gt=0, allow_inf_nan=False)
    avgCost: float = Field(gt=0, allow_inf_nan=False)
    entryDate: date | None = Field(default=None, description="Optional YYYY-MM-DD")


@router.get("/holdings")
def list_holdings():
    """Return all portfolio holdings for the current user."""
    try:
        return db.get_holdings(USER_ID)
    except Exception:
        raise internal_error("listing holdings failed")


@router.post("/holdings")
def upsert_holding(req: UpsertRequest):
    """Add a portfolio lot."""
    try:
        return db.upsert_holding(
            USER_ID, req.symbol.upper(), req.shares, req.avgCost, entry_date=req.entryDate
        )
    except Exception:
        raise internal_error(f"adding holding {req.symbol} failed")


@router.patch("/holdings/{lot_id}")
def update_holding(lot_id: int, req: UpsertRequest):
    """Update shares/avg_cost of an existing lot."""
    try:
        updated = db.update_holding(USER_ID, lot_id, req.shares, req.avgCost)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Lot {lot_id} not found")
        return updated
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"updating holding {lot_id} failed")


@router.delete("/holdings/{lot_id}")
def remove_holding(lot_id: int):
    """Delete a portfolio lot by its id."""
    try:
        deleted = db.delete_holding(USER_ID, lot_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Lot {lot_id} not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"deleting holding {lot_id} failed")


@router.get("/watchlist")
def list_watchlist():
    """Return watchlist symbols for the current user."""
    try:
        return db.get_watchlist(USER_ID)
    except Exception:
        raise internal_error("listing watchlist failed")


@router.post("/watchlist/{symbol}")
def add_watchlist(symbol: str):
    """Add a symbol to the watchlist."""
    try:
        symbol = symbol.strip().upper()
        if not re.fullmatch(r"[A-Z0-9.\-^=]{1,10}", symbol):
            raise HTTPException(status_code=400, detail="Invalid symbol")
        db.add_to_watchlist(USER_ID, symbol)
        return {"added": True}
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"adding watchlist symbol {symbol} failed")


@router.delete("/watchlist/{symbol}")
def remove_watchlist(symbol: str):
    """Remove a symbol from the watchlist."""
    try:
        symbol = symbol.strip().upper()
        # Same validation as add — otherwise an arbitrary caller string is
        # reflected in the 404 body below.
        if not re.fullmatch(r"[A-Z0-9.\-^=]{1,10}", symbol):
            raise HTTPException(status_code=400, detail="Invalid symbol")
        deleted = db.remove_from_watchlist(USER_ID, symbol)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"{symbol} not in watchlist")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception:
        raise internal_error(f"removing watchlist symbol {symbol} failed")
