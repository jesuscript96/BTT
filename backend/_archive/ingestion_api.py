"""
Ingestion API Endpoints
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from app.ingestion import ingest_deep_history, ingest_ticker_snapshot

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


class DeepHistoryRequest(BaseModel):
    tickers: Optional[List[str]] = None  # If None, uses all active tickers
    days: int = 730  # Default: 2 years


@router.post("/deep-history")
async def trigger_deep_history(request: DeepHistoryRequest, background_tasks: BackgroundTasks):
    """
    Trigger deep history ingestion (2 years by default).
    Use this for initial data load or backfilling.
    Runs in background to avoid timeout.
    """
    background_tasks.add_task(
        ingest_deep_history,
        ticker_list=request.tickers,
        days=request.days
    )
    
    ticker_count = len(request.tickers) if request.tickers else "all active"
    
    return {
        "status": "started",
        "message": f"Deep history ingestion started for {ticker_count} tickers ({request.days} days)",
        "note": "Check server logs for progress"
    }


@router.post("/refresh-tickers")
async def refresh_ticker_list():
    """
    Refresh the master ticker list from Massive API.
    """
    try:
        ingest_ticker_snapshot()
        return {"status": "success", "message": "Ticker list refreshed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def ingestion_status():
    """
    Get current ingestion system status.
    """
    from app.database import get_db_connection
    
    con = get_db_connection()
    try:
        # Get ticker stats
        ticker_stats = con.execute("""
            SELECT 
                COUNT(*) as total_tickers,
                COUNT(CASE WHEN active THEN 1 END) as active_tickers,
                MIN(last_updated) as oldest_update,
                MAX(last_updated) as newest_update
            FROM tickers
        """).fetch_df().to_dict('records')[0]
        
        # Get data stats
        data_stats = con.execute("""
            SELECT 
                COUNT(DISTINCT ticker) as tickers_with_data,
                COUNT(*) as total_bars,
                MIN(timestamp) as earliest_data,
                MAX(timestamp) as latest_data
            FROM historical_data
        """).fetch_df().to_dict('records')[0]
        
        return {
            "tickers": ticker_stats,
            "data": data_stats,
            "pulse_config": {
                "interval_seconds": 62,
                "tickers_per_cycle": 3,
                "days_per_update": 7
            }
        }
    finally:
        con.close()
