import os
import sys

sys.path.append(os.path.abspath('backend'))

from dotenv import load_dotenv
load_dotenv('backend/.env')

from app.services.backtest_orchestrator import BacktestRequest, run_backtest_orchestrator
import json

# Setup logging
import logging
logging.basicConfig(level=logging.INFO)

strategy_def = {
    "name": "Test Entry Time Windows",
    "bias": "long",
    "apply_day": "gap_day",
    "postgap_preconditions": [],
    "universe_filters": {
        "require_shortable": False,
        "exclude_dilution": False,
        "whitelist_sectors": []
    },
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
                    "target": 0.0
                }
            ]
        }
    },
    "exit_logic": {
        "timeframe": "1m",
        "root_condition": {
            "type": "group",
            "operator": "AND",
            "conditions": []
        }
    },
    "risk_management": {
        "use_hard_stop": True,
        "use_take_profit": True,
        "take_profit_mode": "Full",
        "accept_reentries": True,
        "hard_stop": {"type": "Percentage", "value": 5.0},
        "take_profit": {"type": "Percentage", "value": 5.0},
        "partial_take_profits": [],
        "trailing_stop": {"active": False, "type": "Percentage", "buffer_pct": 0.5}
    }
}

req = BacktestRequest(
    dataset_id="10358a6a-a0f4-4664-8b89-de579652dc74",
    strategy_definition=strategy_def,
    init_cash=10000.0,
    risk_r=100.0,
    start_date="2024-01-24",
    end_date="2024-01-24",
    market_sessions=["pre", "rth", "post"]
)

print("Running backtest orchestrator locally...")
res = run_backtest_orchestrator(req)
trades = res.get("trades", [])
print(f"Number of trades: {len(trades)}")
for t in trades[:10]:
    print(f"Trade: Ticker={t.get('ticker')}, EntryTime={t.get('entry_time')}, ExitTime={t.get('exit_time')}, Reason={t.get('exit_reason')}")
