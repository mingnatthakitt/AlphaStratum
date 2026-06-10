import os
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from routers.fetch import router as fetch_router
from routers.models import router as models_router
from routers.rag import router as rag_router
from routers.portfolio import router as portfolio_router

# Load .env from the same directory as main.py
load_dotenv(Path(__file__).parent / ".env")

AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")
PUBLIC_PATHS = {"/", "/health"}

app = FastAPI(title="Alpha Stratum API", version="0.1.0")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    if not AUTH_PASSWORD:
        # No password configured — allow all (dev mode)
        return await call_next(request)
    # Accept password via ?key= query param (never in browser JS bundle when using NEXT_PUBLIC_ vars is avoided)
    provided = request.query_params.get("key", "")
    if provided != AUTH_PASSWORD:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fetch_router, prefix="/fetch", tags=["fetch"])
app.include_router(models_router, prefix="/models", tags=["models"])
app.include_router(rag_router, prefix="/rag", tags=["rag"])
app.include_router(portfolio_router, tags=["portfolio"])


@app.get("/")
def root():
    return {"status": "ok", "service": "Alpha Stratum API"}


@app.get("/health")
def health():
    return {"status": "healthy"}
