import sys
import os
import time
import pandas as pd
import numpy as np

sys.path.append(os.path.abspath('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend'))

from dotenv import load_dotenv
load_dotenv('c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/.env')

from app.services.cache_service import get_hot_daily_cache
import yfinance as yf

def safe_mean(series):
    if series is None or len(series) == 0:
        return None
    val = series.mean()
    if pd.isna(val) or np.isnan(val) or np.isinf(val):
        return None
    return float(val)

def get_gap_stats(ticker: str) -> dict:
    ticker = ticker.upper()
    
    # 1. Try GCS hot cache in memory
    df_hot = get_hot_daily_cache()
    if df_hot is not None and not df_hot.empty:
        ticker_gcs = df_hot[df_hot['ticker'] == ticker]
        if not ticker_gcs.empty:
            print(f"[{ticker}] Calculating from GCS hot cache ({len(ticker_gcs)} gap days)...")
            
            # Calculations
            high_spike = ticker_gcs['rth_run_pct']
            low_spike = (ticker_gcs['rth_open'] - ticker_gcs['rth_low']) / ticker_gcs['rth_open'] * 100
            pm_fade = ticker_gcs['pmh_fade_pct']
            rthh_fade = (ticker_gcs['rth_high'] - ticker_gcs['rth_close']) / ticker_gcs['rth_high'] * 100
            
            neg_close = (ticker_gcs['rth_close'] < ticker_gcs['prev_close']).astype(float) * 100
            close_above_pmh = (ticker_gcs['rth_close'] > ticker_gcs['pm_high']).astype(float) * 100
            
            # Midpoint proxy for VWAP
            mid_point = (ticker_gcs['rth_high'] + ticker_gcs['rth_low']) / 2.0
            close_below_vwap = (ticker_gcs['rth_close'] < mid_point).astype(float) * 100
            
            return {
                "source": "database_hot_cache",
                "gap_days_count": len(ticker_gcs),
                "high_rth_spike_avg": safe_mean(high_spike),
                "low_rth_spike_avg": safe_mean(low_spike),
                "pm_fade_avg": safe_mean(pm_fade),
                "rthh_fade_avg": safe_mean(rthh_fade),
                "neg_close_freq": safe_mean(neg_close),
                "close_above_pmh_freq": safe_mean(close_above_pmh),
                "close_below_vwap_freq": safe_mean(close_below_vwap)
            }
            
    # 2. Fallback to yfinance 1y daily history
    print(f"[{ticker}] Ticker not in hot cache. Downloading yfinance history...")
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        if not hist.empty:
            hist['prev_close'] = hist['Close'].shift(1)
            hist['gap_pct'] = (hist['Open'] - hist['prev_close']) / hist['prev_close'] * 100
            
            # Filter for gap days (abs(gap) >= 2.0%)
            gap_yf = hist[hist['gap_pct'].abs() >= 2.0].copy()
            print(f"[{ticker}] Found {len(gap_yf)} gap days (>= 2%) in yfinance daily history.")
            
            if not gap_yf.empty:
                high_spike = (gap_yf['High'] - gap_yf['Open']) / gap_yf['Open'] * 100
                low_spike = (gap_yf['Open'] - gap_yf['Low']) / gap_yf['Open'] * 100
                rthh_fade = (gap_yf['High'] - gap_yf['Close']) / gap_yf['High'] * 100
                
                neg_close = (gap_yf['Close'] < gap_yf['prev_close']).astype(float) * 100
                
                mid_point = (gap_yf['High'] + gap_yf['Low']) / 2.0
                close_below_vwap = (gap_yf['Close'] < mid_point).astype(float) * 100
                
                return {
                    "source": "yfinance_1y_history",
                    "gap_days_count": len(gap_yf),
                    "high_rth_spike_avg": safe_mean(high_spike),
                    "low_rth_spike_avg": safe_mean(low_spike),
                    "pm_fade_avg": None, # Premarket data not in yfinance daily
                    "rthh_fade_avg": safe_mean(rthh_fade),
                    "neg_close_freq": safe_mean(neg_close),
                    "close_above_pmh_freq": None, # Premarket data not in yfinance daily
                    "close_below_vwap_freq": safe_mean(close_below_vwap)
                }
    except Exception as e:
        print(f"Error calling yfinance: {e}")
        
    return {
        "source": "none",
        "gap_days_count": 0,
        "high_rth_spike_avg": None,
        "low_rth_spike_avg": None,
        "pm_fade_avg": None,
        "rthh_fade_avg": None,
        "neg_close_freq": None,
        "close_above_pmh_freq": None,
        "close_below_vwap_freq": None
    }

# Test both
# Since the script runs offline, the hot cache will load local mock data (which has AAPL).
# But let's check how the function runs.
print("--- Test AAPL ---")
t_start = time.time()
print(get_gap_stats("AAPL"))
print(f"Time: {time.time() - t_start:.4f}s\n")

print("--- Test GFAI ---")
t_start = time.time()
print(get_gap_stats("GFAI"))
print(f"Time: {time.time() - t_start:.4f}s\n")
