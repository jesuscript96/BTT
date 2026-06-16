import os
import sys
import json
import duckdb

sys.path.append(os.path.abspath('backend'))

from dotenv import load_dotenv
load_dotenv('backend/.env')

from app.services.backtest_orchestrator import run_backtest_orchestrator, BacktestRequest

# Connect to user DB and list dataset IDs
con = duckdb.connect('users.duckdb', read_only=True)
try:
    datasets = con.execute("SELECT id, name FROM saved_queries").fetchall()
    print("Available Datasets in DB:")
    for ds in datasets:
        print(f"  ID: {ds[0]}, Name: {ds[1]}")
    if not datasets:
        print("No datasets found in DB.")
        sys.exit(0)
    dataset_id = datasets[0][0]
    print(f"Using dataset: {dataset_id}")
finally:
    con.close()

# Define the strategy definition
# Let's verify what indicator names are valid
# We will use "Bar Close" greater than "VWAP" or similar simple condition.
strategy_definition = {
    "name": "Test Entry Windows",
    "bias": "long",
    "apply_day": "gap_day",
    "entry_logic": {
        "timeframe": "1m",
        "entry_time_windows": [
            {"from_time": "09:30", "to_time": "11:30"}
        ],
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "GREATER_THAN",
                    "target": {
                        "name": "VWAP"
                    },
                    "timeframe": "1m"
                }
            ]
        }
    },
    "exit_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": [
                {
                    "type": "indicator_comparison",
                    "source": {"name": "Bar Close"},
                    "comparator": "LESS_THAN",
                    "target": {
                        "name": "VWAP"
                    },
                    "timeframe": "1m"
                }
            ]
        }
    },
    "risk_management": {
        "use_hard_stop": True,
        "hard_stop": {"type": "Percentage", "value": 2.0},
        "use_take_profit": True,
        "take_profit": {"type": "Percentage", "value": 6.0},
        "accept_reentries": True
    }
}

# Create request
req = BacktestRequest(
    dataset_id=dataset_id,
    strategy_definition=strategy_definition,
    init_cash=10000.0,
    risk_r=100.0,
    market_sessions=["pre", "rth", "post"],  # PM, RTH, AM
    look_ahead_prevention=True
)

try:
    print("\nRunning backtest...")
    results = run_backtest_orchestrator(req)
    
    trades = results.get("trades", [])
    print(f"\nExecution finished. Total trades: {len(trades)}")
    
    out_of_window_trades = []
    for t in trades:
        entry_time_str = t.get("entry_time") # format: YYYY-MM-DD HH:MM:SS
        time_part = entry_time_str.split(" ")[1][:5] # HH:MM
        h, m = map(int, time_part.split(":"))
        mins = h * 60 + m
        
        # 9:30 is 570 mins, 11:30 is 690 mins
        # If look_ahead_prevention is True, the entry is on the next open.
        # So entry can be at 11:31 if signal was at 11:30.
        # But if entry is at 05:00 or 15:00, that is way outside the window!
        if mins < 570 or mins > 691:
            out_of_window_trades.append(t)
            
    print(f"\nTrades executed OUTSIDE the 09:30 - 11:30 window (total: {len(out_of_window_trades)}):")
    for t in out_of_window_trades[:20]:
        print(f"  Ticker: {t.get('ticker')}, Entry: {t.get('entry_time')}, Exit: {t.get('exit_time')}, Exit Reason: {t.get('exit_reason')}")
        
    if not out_of_window_trades:
        print("  All entries were strictly within the 09:30 - 11:30 window!")
        
except Exception as e:
    print("Error during backtest:", e)
