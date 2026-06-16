import os
import sys
from dotenv import load_dotenv
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.database import get_user_db_connection, get_user_db_lock
from app.services.backtest_orchestrator import run_backtest_orchestrator, BacktestRequest

def main():
    print("Running short backtest with RTH Low...")
    
    with get_user_db_lock():
        con = get_user_db_connection()
        queries = con.execute("SELECT id, name FROM saved_queries LIMIT 5").fetchall()
        con.close()
        
    dataset_id = queries[0][0]
    
    strat_short_low = {
        "name": "Test Short RTH Low",
        "bias": "short",
        "apply_day": "gap_day",
        "entry_logic": {
            "timeframe": "1m",
            "root_condition": {
                "type": "group",
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Bar Close"},
                        "comparator": "LESS_THAN",
                        "target": {"name": "RTH Low"}
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
            "use_hard_stop": False,
            "use_take_profit": False,
            "take_profit_mode": "Full",
            "accept_reentries": False
        }
    }
    
    req_short = BacktestRequest(
        dataset_id=dataset_id,
        strategy_id=None,
        strategy_definition=strat_short_low,
        init_cash=10000.0,
        risk_r=100.0,
        risk_type="FIXED",
        fees=0.0,
        fee_type="PERCENT",
        slippage=0.0,
        market_sessions=["post"],  # aftermarket
        custom_start_time=None,
        custom_end_time=None,
        locates_cost=0.0,
        size_by_sl=False,
        look_ahead_prevention=False
    )
    
    res = run_backtest_orchestrator(req_short)
    trades = res.get("trades", [])
    print(f"Short RTH Low trades count: {len(trades)}")

if __name__ == "__main__":
    main()
