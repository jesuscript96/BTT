import os
import pandas as pd
import numpy as np
import duckdb
import yfinance as yf
from dotenv import load_dotenv

load_dotenv('backend/.env')

ticker = "KIDZ"

def safe_float(val):
    try:
        if val is None: return None
        f = float(val)
        if np.isnan(f) or np.isinf(f): return None
        return f
    except:
        return None

def safe_mean(series):
    if series is None or len(series) == 0:
        return None
    val = series.mean()
    if pd.isna(val) or np.isnan(val) or np.isinf(val):
        return None
    return float(val)

def get_yfinance_session():
    import requests
    import urllib3
    from requests.adapters import HTTPAdapter
    
    class TimeoutHTTPAdapter(HTTPAdapter):
        def __init__(self, *args, **kwargs):
            self.timeout = kwargs.pop('timeout', 5)
            super().__init__(*args, **kwargs)
        def send(self, request, **kwargs):
            kwargs['timeout'] = kwargs.get('timeout', self.timeout)
            return super().send(request, **kwargs)
            
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    session.verify = False
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    adapter = TimeoutHTTPAdapter(timeout=5)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def _fetch_yfinance_history(ticker: str, period: str = "5y") -> pd.DataFrame:
    try:
        session = get_yfinance_session()
        stock = yf.Ticker(ticker, session=session)
        hist = stock.history(period=period)
        if not hist.empty:
            df = hist.reset_index()
            df = df.rename(columns={
                'Date': 'timestamp', 
                'Datetime': 'timestamp',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            })
            return df
    except Exception as e:
        print(f"[ERROR] yfinance history for {ticker}: {e}")
    return pd.DataFrame()

try:
    # 1. Fetch yfinance history
    yf_df = _fetch_yfinance_history(ticker)
    if yf_df.empty:
        print("YFinance returned empty")
        exit(1)
        
    yf_df['date'] = pd.to_datetime(yf_df['timestamp']).dt.strftime('%Y-%m-%d')
    
    # Calculate gap_pct on yfinance
    yf_df = yf_df.sort_values('date').reset_index(drop=True)
    yf_df['prev_close'] = yf_df['close'].shift(1)
    yf_df['gap_pct'] = (yf_df['open'] - yf_df['prev_close']) / yf_df['prev_close'] * 100
    
    # 2. Fetch daily_metrics from GCS / DuckDB
    con = duckdb.connect()
    access_key = os.getenv("GCS_HMAC_KEY")
    secret = os.getenv("GCS_HMAC_SECRET")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if access_key and secret:
        con.execute(f"CREATE OR REPLACE SECRET gcs_secret (TYPE GCS, KEY_ID '{access_key}', SECRET '{secret}');")
        
    db_df = con.execute("""
        SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
        WHERE ticker = ? ORDER BY timestamp ASC
    """, [ticker]).fetchdf()
    con.close()
    
    if not db_df.empty:
        db_df['date'] = pd.to_datetime(db_df['timestamp']).dt.strftime('%Y-%m-%d')
        # Drop columns that exist in both and would duplicate
        cols_to_drop = [c for c in ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'prev_close', 'gap_pct'] if c in db_df.columns]
        db_df = db_df.drop(columns=cols_to_drop)
        
        # Merge
        df = yf_df.merge(db_df, on='date', how='left')
    else:
        df = yf_df
        
    # Coalesce rth columns with yfinance standard columns
    for col in ['rth_open', 'rth_high', 'rth_low', 'rth_close']:
        fallback_col = col.replace('rth_', '')
        if col not in df.columns:
            df[col] = df[fallback_col]
        else:
            df[col] = df[col].fillna(df[fallback_col])
            
    # Locate gaps
    gap_indices = df[df['gap_pct'] >= 20.0].index.tolist()
    print("Gap dates identified in merged df:")
    for idx in gap_indices:
        print(f"  {df.loc[idx, 'date']} | Gap: {df.loc[idx, 'gap_pct']:.2f}% | Has DB record: {pd.notnull(df.loc[idx, 'pm_high']) if 'pm_high' in df.columns else False}")
        
    # Calculate stats
    def compute_stats_for_offset(offset):
        target_indices = [idx + offset for idx in gap_indices if idx + offset < len(df)]
        if not target_indices:
            return None
        sub_df = df.loc[target_indices].copy()
        
        o = sub_df['rth_open']
        h = sub_df['rth_high']
        l = sub_df['rth_low']
        c = sub_df['rth_close']
        
        high_spike = (h - o) / o * 100
        low_spike = (o - l) / o * 100
        rthh_fade = (h - c) / h * 100
        neg_close = (c < o).astype(float) * 100
        mid_point = (h + l) / 2.0
        close_below_vwap = (c < mid_point).astype(float) * 100
        
        pm_fade = None
        close_above_pmh = None
        if 'pm_high' in sub_df.columns:
            pm_h = sub_df['pm_high']
            pm_fade = (pm_h - o) / pm_h * 100
            pm_fade = pm_fade.mask(pm_h <= 0, None)
            close_above_pmh = (c > pm_h).astype(float) * 100
            close_above_pmh = close_above_pmh.mask(pm_h <= 0, None)
            
        return {
            "gap_days_count": len(sub_df),
            "high_rth_spike_avg": safe_mean(high_spike),
            "low_rth_spike_avg": safe_mean(low_spike),
            "pm_fade_avg": safe_mean(pm_fade),
            "rthh_fade_avg": safe_mean(rthh_fade),
            "neg_close_freq": safe_mean(neg_close),
            "close_above_pmh_freq": safe_mean(close_above_pmh),
            "close_below_vwap_freq": safe_mean(close_below_vwap)
        }
        
    print("\nStats calculated:")
    import json
    print(json.dumps(compute_stats_for_offset(0), indent=2))
    
except Exception as e:
    print("Error:", e)
