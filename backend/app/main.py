from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from contextlib import asynccontextmanager
from fastapi import Request
from fastapi.responses import JSONResponse

from app.scheduler import start_scheduler
from app.database import get_db_connection
from app.ingestion import ingest_ticker_snapshot

# Lifecycle events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Application
    print("Startup: Connecting to JAUME database...")
    
    # Verify database connection
    try:
        con = get_db_connection()
        tables = con.execute("SHOW TABLES").fetchall()
        print(f"✅ Connected to JAUME. Tables: {[t[0] for t in tables]}")
        con.close()
    except Exception as e:
        print(f"❌ Error connecting to JAUME: {e}")
        raise
        
    start_scheduler()
    yield
    # Shutdown
    print("Shutdown: Cleaning up...")


app = FastAPI(title="Short Selling Backtester API", lifespan=lifespan)

# CORS Configuration - MUST be added BEFORE routers
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://www.mystrategybuilder.fun",
    "https://mystrategybuilder.fun",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers import data, strategies, backtest, query, market, strategy_search
from app.api import ingestion
import logging

# ... (logging setup if needed)

app.include_router(data.router, prefix="/api/data", tags=["Data"])
app.include_router(strategies.router, prefix="/api/strategies", tags=["Strategies"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["Backtest"])
app.include_router(query.router, prefix="/api/queries", tags=["Queries"])
app.include_router(strategy_search.router, prefix="/api/strategy-search", tags=["Strategy Search"])
app.include_router(market.router)
app.include_router(ingestion.router)  # Deep history ingestion endpoint

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
