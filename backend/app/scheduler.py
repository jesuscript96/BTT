from apscheduler.schedulers.background import BackgroundScheduler
from app.ingestion import ingest_ticker_snapshot
import atexit
import os

# v2.0 - Night-time pulse with timezone support

def start_scheduler():
    """
    Start the background scheduler for data ingestion.
    
    NIGHT-TIME PULSE STRATEGY:
    - Runs ONLY during off-peak hours (12am-8am Mexico CST/CDT)
    - More aggressive loading during night (5 tickers, 30 days)
    - Completely idle during the day (8am-12am) to allow backtests
    - In production, can be disabled with ENABLE_PULSE=false
    """
    # Check if we're in production (Render sets this)
    is_production = os.getenv("RENDER") == "true"
    pulse_enabled = os.getenv("ENABLE_PULSE", "true").lower() == "true"  # Default TRUE now
    
    if is_production and not pulse_enabled:
        print("⚠️  Production mode: Pulse scheduler DISABLED via ENABLE_PULSE=false.")
        print("💡 Use POST /api/ingestion/deep-history to trigger manual ingestion.")
        return  # Don't start scheduler
    
    scheduler = BackgroundScheduler(timezone='America/Mexico_City')
    
    # Night-Time Aggressive Pulse: 5 tickers, last 30 days, every 3 minutes
    # Runs ONLY between 12:00 AM and 8:00 AM Mexico time
    from app.ingestion import night_pulse_cycle
    scheduler.add_job(
        func=night_pulse_cycle, 
        trigger="cron",
        hour='0-7',  # 12am to 7:59am (8am not included)
        minute='*/3',  # Every 3 minutes
        max_instances=1,  # Prevent overlaps
        coalesce=True,    # Skip missed runs if one is already running
        id="night_pulse"
    )
    
    scheduler.start()
    print("✅ Scheduler started: Night-Time Pulse (12am-8am CST, every 3min, 5 tickers, 30 days).")
    print("💤 Daytime: Pulse IDLE (8am-12am) - Free for backtests!")
    
    # Shut down the scheduler when exiting the app
    atexit.register(lambda: scheduler.shutdown())
