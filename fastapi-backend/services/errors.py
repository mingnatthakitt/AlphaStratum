"""
Consistent error handling: full detail goes to server logs, generic messages
to clients (the old routers returned str(e), leaking internals).
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def internal_error(context: str) -> HTTPException:
    """Log the active exception with traceback and return a generic 500."""
    logger.exception("%s", context)
    return HTTPException(status_code=500, detail="Internal server error")


def not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=404, detail=detail)


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)
