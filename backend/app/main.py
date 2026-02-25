from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from contextlib import asynccontextmanager
from fastapi import Request
from fastapi.responses import JSONResponse

from app.scheduler import start_scheduler
from app.database import get_db_connection
from app.init_db import init_db

# Lifecycle events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect to DB so first request is fast. If DB fails, app still starts (avoids 502 on cold start).
    print("Startup: Connecting to massive database...")
    try:
        con = get_db_connection()
        tables = con.execute("SHOW TABLES").fetchall()
        print(f"✅ Connected to massive. Tables: {[t[0] for t in tables]}")
        try:
            init_db()
            print("✅ Init DB: strategies and saved_queries tables verified")
        except Exception as e:
            print(f"⚠️ Init DB warning: {e}")
    except Exception as e:
        print(f"⚠️ DB not available at startup: {e}. App will start; first API request may fail or be slow.")

    start_scheduler()
    yield
    # Shutdown
    print("Shutdown: Cleaning up...")


app = FastAPI(title="Short Selling Backtester API", lifespan=lifespan)

# CORS Configuration - MUST be added BEFORE routers
# 502 from the platform (e.g. Render) has no CORS headers; ensuring our app always adds them when it responds.
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://www.mystrategybuilder.fun",
    "https://mystrategybuilder.fun",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_cors_headers_to_all_responses(request, call_next):
    """Ensure CORS headers are on every response so 4xx/5xx from our app are not reported as CORS errors."""
    response = await call_next(request)
    origin = request.headers.get("origin")
    if origin and (origin in ALLOWED_ORIGINS or origin.startswith("https://") and "vercel.app" in origin):
        response.headers["Access-Control-Allow-Origin"] = origin
    elif origin is None and request.url.path.startswith("/api/"):
        response.headers["Access-Control-Allow-Origin"] = "https://www.mystrategybuilder.fun"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

from app.routers import data, strategies, backtest, query, market, strategy_search, ticker_analysis
import logging

# ... (logging setup if needed)

app.include_router(data.router, prefix="/api/data", tags=["Data"])
app.include_router(strategies.router, prefix="/api/strategies", tags=["Strategies"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["Backtest"])
app.include_router(query.router, prefix="/api/queries", tags=["Queries"])
app.include_router(strategy_search.router, prefix="/api/strategy-search", tags=["Strategy Search"])
app.include_router(ticker_analysis.router)
app.include_router(market.router)
from app.routers import news
app.include_router(news.router, prefix="/api", tags=["News"])

@app.get("/health")
def read_health():
    return {"status": "ok"}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"GLOBAL ERROR: {exc}")
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "message": str(exc)},
        headers={
            "Access-Control-Allow-Origin": "https://www.mystrategybuilder.fun",
            "Access-Control-Allow-Credentials": "true"
        }
    )

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
