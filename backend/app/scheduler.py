from apscheduler.schedulers.background import BackgroundScheduler
from app.ingestion import ingest_ticker_snapshot
import atexit

def start_scheduler():
    """
    Start the background scheduler for data ingestion.
    
    IMPORTANT: In production (Render), the pulse is DISABLED by default to prevent
    memory exhaustion. Use the API endpoints to trigger ingestion manually:
    - POST /api/ingestion/deep-history (for initial load)
    - The pulse can be enabled via environment variable if needed
    """
    # Check if we're in production (Render sets this)
    is_production = os.getenv("RENDER") == "true"
    pulse_enabled = os.getenv("ENABLE_PULSE", "false").lower() == "true"
    
    if is_production and not pulse_enabled:
        print("⚠️  Production mode detected. Pulse scheduler DISABLED to prevent memory issues.")
        print("💡 Use POST /api/ingestion/deep-history to trigger manual ingestion.")
        print("💡 To enable pulse in production, set ENABLE_PULSE=true environment variable.")
        return  # Don't start scheduler in production
    
    scheduler = BackgroundScheduler()
    
    # Lightweight Pulse Job: 3 tickers, last 7 days, every 62 seconds
    # max_instances=1 prevents overlapping executions
    from app.ingestion import pulse_ingest_cycle
    scheduler.add_job(
        func=pulse_ingest_cycle, 
        trigger="interval", 
        seconds=62,
        max_instances=1,  # Prevent overlaps
        coalesce=True,    # Skip missed runs if one is already running
        id="pulse_ingest"
    )
    
    # For deep history ingestion (2 years), use: from app.ingestion import ingest_deep_history
    # Then call manually or via API endpoint
    
    scheduler.start()
    print("✅ Scheduler started. Pulse running every 62s (3 tickers, 7-day updates).")
    
    # Shut down the scheduler when exiting the app
    atexit.register(lambda: scheduler.shutdown())
