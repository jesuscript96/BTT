from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from contextlib import asynccontextmanager

from app.scheduler import start_scheduler
from app.database import init_db, get_db_connection
from app.ingestion import ingest_ticker_snapshot

# Lifecycle events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize data, scheduler etc.
    print("Startup: Initializing Application...")
    init_db()
    
    # Check if we need to fetch initial tickers
    try:
        con = get_db_connection()
        ticker_count = con.execute("SELECT COUNT(*) FROM tickers").fetchone()[0]
        con.close()
        
        if ticker_count == 0:
            print("No tickers found in database. Triggering initial ingestion...")
            ingest_ticker_snapshot()
        else:
            print(f"Found {ticker_count} tickers in database.")
    except Exception as e:
        print(f"Error checking/seeding tickers on startup: {e}")
        
    start_scheduler()
    yield
    # Shutdown
    print("Shutdown: Cleaning up...")


app = FastAPI(title="Short Selling Backtester API", lifespan=lifespan)

from app.routers import data

app.include_router(data.router, prefix="/api", tags=["Data"])

# CORS Configuration - Allow all origins for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (Vercel, localhost, etc.)
    allow_credentials=False,  # Must be False when using allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def read_health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
