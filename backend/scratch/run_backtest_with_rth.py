import os
import sys
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.database import get_user_db_connection, get_user_db_lock
from app.services.backtest_orchestrator import run_backtest_orchestrator, BacktestRequest

def main():
    print("Running backtest with RTH High and RTH Low conditions...")
    
    with get_user_db_lock():
        con = get_user_db_connection()
        queries = con.execute("SELECT id, name FROM saved_queries LIMIT 5").fetchall()
        con.close()
        
    if not queries:
        print("No saved queries found in users.duckdb!")
        return
        
    dataset_id = queries[0][0]
    print(f"Using dataset_id: {dataset_id}")
    
    # 1. Strategy with RTH High condition
    strat_high = {
        "name": "Test RTH High",
        "bias": "long",
        "apply_day": "gap_1_day",
        "entry_logic": {
            "timeframe": "1m",
            "root_condition": {
                "type": "group",
                "operator": "AND",
                "conditions": [
                    {
                        "type": "indicator_comparison",
                        "source": {"name": "Bar Close"},
                        "comparator": "GREATER_THAN",
                        "target": {"name": "RTH High"}
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
    
    # 2. Strategy with RTH Low condition
    strat_low = {
        "name": "Test RTH Low",
        "bias": "long",
        "apply_day": "gap_1_day",
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
    
    # Run backtest for high
    req_high = BacktestRequest(
        dataset_id=dataset_id,
        strategy_id=None,
        strategy_definition=strat_high,
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
    
    # Run backtest for low
    req_low = BacktestRequest(
        dataset_id=dataset_id,
        strategy_id=None,
        strategy_definition=strat_low,
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
    
    print("\n--- Running Backtest with RTH High ---")
    try:
        res_high = run_backtest_orchestrator(req_high)
        trades_high = res_high.get("trades", [])
        print(f"RTH High Backtest Successful. Trades count: {len(trades_high)}")
    except Exception as e:
        print(f"RTH High Backtest Failed with error: {e}")
        import traceback
        traceback.print_exc()
        
    print("\n--- Running Backtest with RTH Low ---")
    try:
        res_low = run_backtest_orchestrator(req_low)
        trades_low = res_low.get("trades", [])
        print(f"RTH Low Backtest Successful. Trades count: {len(trades_low)}")
    except Exception as e:
        print(f"RTH Low Backtest Failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
