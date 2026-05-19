import atexit
import os

# v3.0 - Scheduler stub (ingestion removed from this application)

def start_scheduler():
    """
    Scheduler placeholder.
    Ingestion is now handled externally — not from this backend.
    The scheduler is kept as a no-op to avoid breaking main.py imports.
    """
    pulse_enabled = os.getenv("ENABLE_PULSE", "false").lower() == "true"
    
    if not pulse_enabled:
        print("[INFO] Scheduler disabled (ingestion handled externally).")
        return
    
    # If someone explicitly enables it, warn them
    print("[WARN] ENABLE_PULSE=true but ingestion is no longer handled by this backend.")
    print("[INFO] Data ingestion should be done through the external pipeline.")
