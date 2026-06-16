import os
import sys
from dotenv import load_dotenv
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.database import get_user_db_connection, get_user_db_lock
from app.services.data_service import fetch_qualifying_data, get_intraday_stream
from app.services.backtest_service import _build_qualifying_lookup
from app.services.indicators import compute_indicator
from app.services.strategy_engine import translate_strategy
from app.services.portfolio_sim import simulate

def main():
    print("Debugging simulation for HOLO on 2024-10-01...")
    
    with get_user_db_lock():
        con = get_user_db_connection()
        queries = con.execute("SELECT id, name FROM saved_queries LIMIT 5").fetchall()
        con.close()
        
    dataset_id = queries[0][0]
    
    # We load specifically HOLO on 2024-10-01
    qualifying_df = fetch_qualifying_data(dataset_id, apply_day='gap_day')
    qualifying_df = qualifying_df[(qualifying_df['ticker'] == 'HOLO') & (pd.to_datetime(qualifying_df['timestamp']).dt.strftime('%Y-%m-%d') == '2024-10-01')]
    
    if qualifying_df.empty:
        print("HOLO on 2024-10-01 not in qualifying dataset!")
        return
        
    qualifying_df['date'] = pd.to_datetime(qualifying_df['timestamp']).dt.strftime('%Y-%m-%d')
    qual_lookup = _build_qualifying_lookup(qualifying_df)
    
    stream = get_intraday_stream(qualifying_df, '2024-10-01', '2024-10-01')
    for (date_raw, ticker_raw), day_df in stream:
        ticker = str(ticker_raw)
        date = str(date_raw)[:10]
        daily_stats = qual_lookup.get((ticker, date), {})
        
        df_bars = day_df.sort_values("timestamp").reset_index(drop=True)
        df_bars['time'] = pd.to_datetime(df_bars['timestamp']).dt.time
        
        strat_low = {
            "name": "Test RTH Low",
            "bias": "long",
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
        
        # Translate strategy
        signals = translate_strategy(df_bars, strat_low, daily_stats)
        entries_arr = signals["entries"].values
        exits_arr = signals["exits"].values
        
        # Filter to aftermarket ("post" session)
        from app.services.backtest_service import _get_market_sessions_mask
        session_mask = _get_market_sessions_mask(df_bars["timestamp"], ["post"])
        
        # Trim
        trimmed_df = df_bars[session_mask].reset_index(drop=True)
        session_mask_np = session_mask.values if hasattr(session_mask, "values") else np.asarray(session_mask)
        trimmed_entries = entries_arr[session_mask_np]
        trimmed_exits = exits_arr[session_mask_np]
        
        print(f"\nBefore simulation:")
        print(f"Trimmed DataFrame length: {len(trimmed_df)}")
        print(f"Trimmed entries sum: {trimmed_entries.sum()}")
        print(f"Trimmed exits sum: {trimmed_exits.sum()}")
        
        # Run simulate
        res = simulate(
            close=trimmed_df["close"].values.astype(np.float64),
            open_=trimmed_df["open"].values.astype(np.float64),
            high=trimmed_df["high"].values.astype(np.float64),
            low=trimmed_df["low"].values.astype(np.float64),
            entries=trimmed_entries,
            exits=trimmed_exits,
            direction="longonly",
            init_cash=10000.0,
            risk_r=100.0,
            risk_type="FIXED"
        )
        
        print("\nSimulation results:")
        print("Trades count:", len(res["trades"]))
        print("Trades list:", res["trades"])

if __name__ == "__main__":
    main()
