from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

USER_ID = "default"


class Holding(BaseModel):
    id: int
    symbol: str
    shares: float
    avgCost: float
    entryDate: str | None = None


class UpsertRequest(BaseModel):
    symbol: str
    shares: float
    avgCost: float


@router.get("/holdings")
def list_holdings():
    """Return all portfolio holdings for the current user."""
    try:
        return db.get_holdings(USER_ID)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/holdings")
def upsert_holding(req: UpsertRequest):
    """Add or update a portfolio position."""
    if req.shares <= 0 or req.avgCost <= 0:
        raise HTTPException(status_code=400, detail="shares and avgCost must be positive")
    try:
        return db.upsert_holding(USER_ID, req.symbol, req.shares, req.avgCost)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/watchlist")
def list_watchlist():
    """Return watchlist symbols for the current user."""
    try:
        return db.get_watchlist(USER_ID)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/watchlist/{symbol}")
def add_watchlist(symbol: str):
    """Add a symbol to the watchlist."""
    try:
        db.add_to_watchlist(USER_ID, symbol)
        return {"added": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/watchlist/{symbol}")
def remove_watchlist(symbol: str):
    """Remove a symbol from the watchlist."""
    try:
        deleted = db.remove_from_watchlist(USER_ID, symbol)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"{symbol} not in watchlist")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))