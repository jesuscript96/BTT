from apscheduler.schedulers.background import BackgroundScheduler
from app.ingestion import ingest_ticker_snapshot
import atexit

def start_scheduler():
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
