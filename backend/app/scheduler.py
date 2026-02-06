from apscheduler.schedulers.background import BackgroundScheduler
from app.ingestion import ingest_ticker_snapshot
import atexit

def start_scheduler():
    scheduler = BackgroundScheduler()
    # Schedule the Pulse Job: 5 tickers every 62 seconds (to stay under 5/min limit)
    from app.ingestion import pulse_ingest_cycle
    scheduler.add_job(func=pulse_ingest_cycle, trigger="interval", seconds=62)
    
    # Initial Snapshot update once a day if needed, but let's just start the pulse
    # scheduler.add_job(func=ingest_ticker_snapshot, trigger="interval", days=1)
    
    scheduler.start()
    print("Scheduler started. Running ingestion every hour.")
    
    # Shut down the scheduler when exiting the app
    atexit.register(lambda: scheduler.shutdown())
