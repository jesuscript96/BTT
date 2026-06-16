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

def main():
    print("Inspecting why RTH Low backtest has 0 trades on gap_day...")
    
    with get_user_db_lock():
        con = get_user_db_connection()
        queries = con.execute("SELECT id, name FROM saved_queries LIMIT 5").fetchall()
        con.close()
        
    if not queries:
        return
    dataset_id = queries[0][0]
    
    qualifying_df = fetch_qualifying_data(dataset_id, apply_day='gap_day')
    qualifying_df['date'] = pd.to_datetime(qualifying_df['timestamp']).dt.strftime('%Y-%m-%d')
    
    qual_lookup = _build_qualifying_lookup(qualifying_df)
    
    date_from = qualifying_df['date'].dropna().min()
    date_to = qualifying_df['date'].dropna().max()
    
    stream = get_intraday_stream(qualifying_df, date_from, date_to)
    
    # Let's inspect the first 10 days where aftermarket price goes below rth_low
    days_checked = 0
    matches_found = 0
    
    for (date_raw, ticker_raw), day_df in stream:
        ticker = str(ticker_raw)
        date = str(date_raw)[:10]
        daily_stats = qual_lookup.get((ticker, date), {})
        if not daily_stats:
            continue
            
        rth_low = daily_stats.get('rth_low')
        if pd.isna(rth_low):
            continue
            
        df_bars = day_df.sort_values("timestamp").reset_index(drop=True)
        df_bars['time'] = pd.to_datetime(df_bars['timestamp']).dt.time
        
        # Check if any aftermarket bar close is below rth_low
        post_bars = df_bars[(df_bars['time'] >= pd.Timestamp("16:00").time()) & (df_bars['time'] < pd.Timestamp("20:00").time())]
        if post_bars.empty:
            continue
            
        lowest_post_close = post_bars['close'].min()
        if lowest_post_close < rth_low:
            matches_found += 1
            print(f"\nMatch {matches_found}: {ticker} on {date} - RTH Low: {rth_low} | Lowest Post Close: {lowest_post_close}")
            
            # Let's evaluate the strategy condition for this day
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
            entries = signals["entries"]
            
            # Check entries during aftermarket
            df_bars['entry_signal'] = entries
            post_entries = df_bars[(df_bars['time'] >= pd.Timestamp("16:00").time()) & (df_bars['time'] < pd.Timestamp("20:00").time())]
            
            entry_count = post_entries['entry_signal'].sum()
            print(f"Total entry signals in post-market: {entry_count}")
            if entry_count > 0:
                print("Post-market entry times:", post_entries[post_entries['entry_signal']]['time'].tolist())
                print("Post-market entry closes:", post_entries[post_entries['entry_signal']]['close'].tolist())
            
            # Check entries during RTH
            rth_entries = df_bars[(df_bars['time'] >= pd.Timestamp("09:30").time()) & (df_bars['time'] < pd.Timestamp("16:00").time())]
            rth_entry_count = rth_entries['entry_signal'].sum()
            print(f"Total entry signals in RTH: {rth_entry_count}")
            
            if matches_found >= 5:
                break

if __name__ == "__main__":
    main()
