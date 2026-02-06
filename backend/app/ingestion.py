import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from .database import get_db_connection

load_dotenv()

API_KEY = os.getenv("MASSIVE_API_KEY")
BASE_URL = os.getenv("MASSIVE_API_BASE_URL", "https://api.massive.com")

class MassiveClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {API_KEY}"})

    def get_tickers(self):
        url = f"{BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers"
        try:
            response = self.session.get(url, params={"apiKey": API_KEY})
            response.raise_for_status()
            return response.json().get("tickers", [])
        except Exception as e:
            print(f"Error fetching tickers: {e}")
            return []

    def get_aggregates(self, ticker, from_date, to_date, multiplier=1, timespan="minute"):
        # Limits: 5 calls per minute on free tier. 
        # The scheduler handles the timing (62s).
        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
        try:
            response = self.session.get(url, params={"limit": 50000, "apiKey": API_KEY})
            if response.status_code == 429:
                print(f"⚠️ Rate limited by Massive API for {ticker}")
                return []
            response.raise_for_status()
            return response.json().get("results", [])
        except Exception as e:
            print(f"Error fetching aggregates for {ticker}: {e}")
            return []

def night_pulse_cycle():
    """
    Aggressive night-time data ingestion cycle.
    Runs ONLY during off-peak hours (12am-8am Mexico time).
    
    Configuration:
    - 5 tickers per cycle (more aggressive than daytime)
    - Last 30 days (expands historical coverage)
    - Memory optimized: Processes one ticker at a time
    
    This allows the backend to stay idle during the day for backtests.
    """
    from datetime import datetime
    
    current_hour = datetime.now().hour
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🌙 Night Pulse started (Hour: {current_hour})...")
    
    # Safety check: Only run during night hours (12am-8am)
    if current_hour >= 8 and current_hour < 24:
        print("⏸️  Daytime detected. Pulse skipped to preserve memory for backtests.")
        return
    
    try:
        # Get 5 oldest updated tickers
        con = get_db_connection()
        tickers = con.execute("""
            SELECT ticker FROM tickers 
            WHERE active = true 
            ORDER BY last_updated ASC 
            LIMIT 5
        """).fetch_df()['ticker'].tolist()
        con.close()
        
        if not tickers:
            print("⚠️  No tickers found to ingest.")
            return

        client = MassiveClient()
        
        # Process each ticker independently to minimize memory usage
        for ticker in tickers:
            try:
                # Pull last 30 days to expand historical coverage
                days_to_pull = 30
                to_date = datetime.now().strftime("%Y-%m-%d")
                from_date = (datetime.now() - timedelta(days=days_to_pull)).strftime("%Y-%m-%d")
                
                print(f"  🌙 Updating {ticker} (last {days_to_pull} days)...")
                
                # Use fresh connection for each ticker
                ticker_con = get_db_connection()
                ingest_ticker_history_range(client, ticker, from_date, to_date, con=ticker_con, skip_sleep=True)
                
                # Mark as updated
                ticker_con.execute("UPDATE tickers SET last_updated = ? WHERE ticker = ?", [datetime.now(), ticker])
                ticker_con.close()
                
            except Exception as ticker_error:
                print(f"  ❌ Error updating {ticker}: {ticker_error}")
                continue
            
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Night Pulse complete ({len(tickers)} tickers, 30 days each).")
    except Exception as e:
        print(f"❌ Night Pulse error: {e}")


def pulse_ingest_cycle():
    """
    Lightweight incremental update cycle.
    Fetches the 3 oldest updated tickers and pulls only recent history (last 7 days).
    Designed to run every ~60s without overlapping.
    
    Memory optimized: Processes one ticker at a time and closes connection after each.
    
    NOTE: This function is now DEPRECATED in favor of night_pulse_cycle.
    Kept for backward compatibility.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📊 Pulse started...")
    
    try:
        # Get tickers in a separate connection scope
        con = get_db_connection()
        tickers = con.execute("""
            SELECT ticker FROM tickers 
            WHERE active = true 
            ORDER BY last_updated ASC 
            LIMIT 2
        """).fetch_df()['ticker'].tolist()
        con.close()
        
        if not tickers:
            print("⚠️  No tickers found to ingest.")
            return

        client = MassiveClient()
        
        # Process each ticker independently to minimize memory usage
        for ticker in tickers:
            try:
                # Only pull last 7 days for incremental updates
                days_to_pull = 7
                to_date = datetime.now().strftime("%Y-%m-%d")
                from_date = (datetime.now() - timedelta(days=days_to_pull)).strftime("%Y-%m-%d")
                
                print(f"  ✓ Updating {ticker} (last {days_to_pull} days)...")
                
                # Use fresh connection for each ticker
                ticker_con = get_db_connection()
                ingest_ticker_history_range(client, ticker, from_date, to_date, con=ticker_con, skip_sleep=True)
                
                # Mark as updated
                ticker_con.execute("UPDATE tickers SET last_updated = ? WHERE ticker = ?", [datetime.now(), ticker])
                ticker_con.close()
                
            except Exception as ticker_error:
                print(f"  ❌ Error updating {ticker}: {ticker_error}")
                continue
            
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Pulse complete ({len(tickers)} tickers updated).")
    except Exception as e:
        print(f"❌ Pulse error: {e}")


def ingest_deep_history(ticker_list=None, days=730):
    """
    Deep history ingestion for initial data load.
    Use this for first-time setup or backfilling historical data.
    
    Args:
        ticker_list: List of tickers to ingest. If None, uses all active tickers.
        days: Number of days to pull (default: 730 = 2 years)
    """
    print(f"\n🚀 Starting DEEP HISTORY ingestion ({days} days)...")
    con = get_db_connection()
    
    try:
        if ticker_list is None:
            tickers = con.execute("""
                SELECT ticker FROM tickers 
                WHERE active = true
            """).fetch_df()['ticker'].tolist()
        else:
            tickers = ticker_list
        
        if not tickers:
            print("⚠️  No tickers found.")
            return
        
        print(f"📋 Processing {len(tickers)} tickers...\n")
        client = MassiveClient()
        
        for i, ticker in enumerate(tickers, 1):
            to_date = datetime.now().strftime("%Y-%m-%d")
            from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            print(f"[{i}/{len(tickers)}] 📥 Pulling {ticker} deep history ({from_date} to {to_date})...")
            ingest_ticker_history_range(client, ticker, from_date, to_date, con=con, skip_sleep=False)
            
            # Mark as updated
            con.execute("UPDATE tickers SET last_updated = ? WHERE ticker = ?", [datetime.now(), ticker])
            print(f"  ✅ {ticker} complete\n")
            
        print(f"\n🎉 Deep history ingestion complete! ({len(tickers)} tickers processed)")
    except Exception as e:
        print(f"❌ Deep history error: {e}")
    finally:
        con.close()

def ingest_ticker_history_range(client, ticker, from_date, to_date, con=None, skip_sleep=False):
    """
    Downloads and saves history for a ticker in manageable chunks.
    
    Args:
        skip_sleep: If True, skips the rate limit sleep (use for small date ranges)
    """
    start_dt = datetime.strptime(from_date, "%Y-%m-%d")
    end_dt = datetime.strptime(to_date, "%Y-%m-%d")
    
    # 45-day chunks to stay safely under Massive 50k result limit (1m bars)
    chunk_size = 45
    current_start = start_dt
    chunk_count = 0
    
    while current_start < end_dt:
        current_end = min(current_start + timedelta(days=chunk_size), end_dt)
        fs = current_start.strftime("%Y-%m-%d")
        ts = current_end.strftime("%Y-%m-%d")
        
        print(f"    - Fetching chunk {fs} to {ts}...")
        candles = client.get_aggregates(ticker, fs, ts)
        
        if candles:
            df = pd.DataFrame(candles)
            df = df.rename(columns={
                'v': 'volume', 'o': 'open', 'c': 'close', 
                'h': 'high', 'l': 'low', 't': 'timestamp', 'vw': 'vwap'
            })
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['ticker'] = ticker
            
            target_columns = [
                'ticker', 'timestamp', 'open', 'high', 'low', 'close', 
                'volume', 'vwap', 'pm_high', 'pm_volume', 'gap_percent'
            ]
            
            for col in target_columns:
                if col not in df.columns:
                    df[col] = 0.0
                    
            final_df = df[target_columns]
            
            local_con = con if con else get_db_connection()
            try:
                local_con.register('candles_chunk', final_df)
                local_con.execute("INSERT OR IGNORE INTO historical_data SELECT * FROM candles_chunk")
                
                # Update daily metrics for this chunk
                from .processor import process_daily_metrics
                daily_metrics_df = process_daily_metrics(final_df)
                if not daily_metrics_df.empty:
                    # Enforce strict column order matching database schema to prevent misalignment
                    daily_metrics_columns = [
                        'ticker', 'date', 'rth_open', 'rth_high', 'rth_low', 'rth_close', 'rth_volume', 
                        'gap_at_open_pct', 'rth_run_pct', 'pm_high', 'pm_volume', 'high_spike_pct', 
                        'low_spike_pct', 'pmh_fade_to_open_pct', 'rth_fade_to_close_pct', 'open_lt_vwap', 
                        'pm_high_break', 'm15_return_pct', 'm30_return_pct', 'm60_return_pct', 
                        'close_lt_m15', 'close_lt_m30', 'close_lt_m60', 'hod_time', 'lod_time', 'close_direction'
                    ]
                    
                    # Reorder DataFrame to match table definition exactly
                    # Any missing columns (shouldn't happen with correct processor) would raise KeyError, which is good for safety.
                    daily_metrics_df = daily_metrics_df[daily_metrics_columns]
                    
                    local_con.register('daily_chunk', daily_metrics_df)
                    local_con.execute("INSERT OR REPLACE INTO daily_metrics SELECT * FROM daily_chunk")
                    
                print(f"      ✓ Saved {len(final_df)} bars")
            except Exception as e:
                print(f"      ❌ Chunk DB error for {ticker}: {e}")
            finally:
                if not con:
                    local_con.close()
        
        chunk_count += 1
        current_start = current_end + timedelta(days=1)
        
        # Only sleep if there are more chunks AND we're not skipping sleep
        if current_start < end_dt and not skip_sleep:
            print("    - Sleeping 12s to respect Massive API rate limit...")
            time.sleep(12)

FALLBACK_TICKERS = [
    "AAPL", "TSLA", "NVDA", "AMD", "META", "MSFT", "GOOGL", "AMZN", "NFLX", "COIN",
    "MARA", "RIOT", "PLTR", "SOFI", "NIO", "INTC", "PYPL", "SQ", "ROKU",
    "BA", "DIS", "T", "F", "GM", "XOM", "CVX", "JPM", "BAC", "WFC"
]

def ingest_ticker_snapshot():
    """Update Tickers master list"""
    client = MassiveClient()
    tickers_data = client.get_tickers()
    
    if not tickers_data:
        print("💡 Using fallback ticker list for MVP (Snapshot restricted on Free Tier).")
        tickers_data = [{"ticker": t} for t in FALLBACK_TICKERS]
    
    df = pd.DataFrame(tickers_data)
    if 'ticker' not in df.columns:
        print("Invalid data from snapshot API.")
        return

    df['name'] = df['ticker']
    df['active'] = True
    # Randomize last_updated to avoid all starting at the exact same sub-second
    df['last_updated'] = [datetime.now() - timedelta(days=365 + i) for i in range(len(df))]
    
    target_df = df[['ticker', 'name', 'active', 'last_updated']]
    con = get_db_connection()
    con.execute("DELETE FROM tickers")
    con.register('df_view', target_df)
    con.execute("INSERT INTO tickers SELECT * FROM df_view")
    con.close()
    print(f"Tickers master list updated ({len(df)} records).")

# Legacy helper, redirected to pulse logic if called manually
def ingest_history(ticker, days=30):
    client = MassiveClient()
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    ingest_ticker_history_range(client, ticker, from_date, to_date)

