import sys
import os
import traceback
import threading
import time

# Set up path so we can import app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.backtest_orchestrator import BacktestRequest, run_backtest_orchestrator

def dump_stacks_periodically():
    while True:
        time.sleep(5)
        print("\n=== THREAD STACKS ===")
        for thread_id, frame in sys._current_frames().items():
            print(f"\nThread {thread_id}:")
            traceback.print_stack(frame)
        print("=====================\n")

def run():
    # Start thread monitor
    t = threading.Thread(target=dump_stacks_periodically, daemon=True)
    t.start()
    
    req = BacktestRequest(
        dataset_id="49b9d03d-a487-4fa7-b292-3e4f28194db2",
        strategy_id="569bc862-0a1e-4f05-b5eb-29cccd5493f6"
    )
    
    print("Starting backtest orchestrator run...")
    try:
        res = run_backtest_orchestrator(req)
        print("Backtest orchestrator run completed successfully!")
        print("Keys in result:", res.keys())
    except Exception as e:
        print("Error in run_backtest_orchestrator:")
        traceback.print_exc()

if __name__ == "__main__":
    run()
