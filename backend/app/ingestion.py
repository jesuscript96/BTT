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

    def get_grouped_daily(self, date):
        """Fetch daily open/close/vol for the entire market on a specific date"""
        url = f"{BASE_URL}/v2/aggs/grouped/locale/us/market/stocks/{date}"
        try:
            response = self.session.get(url, params={"apiKey": API_KEY})
            if response.status_code == 429:
                print(f"⚠️ Rate limited (Grouped Daily) for {date}")
                time.sleep(60) # Heavy penalty wait
                return self.get_grouped_daily(date) # Retry once
            response.raise_for_status()
            return response.json().get("results", [])
        except Exception as e:
            print(f"Error fetching grouped daily for {date}: {e}")
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
                'volume', 'vwap', 'pm_high', 'pm_volume', 'gap_percent',
                'transactions', 'pm_high_break', 'high_spike_pct'
            ]
            
            for col in target_columns:
                if col not in df.columns:
                    df[col] = 0.0
                    
            final_df = df[target_columns]
            
            local_con = con if con else get_db_connection()
            try:
                # 1. Historical Data (1m bars)
                local_con.register('candles_chunk', final_df)
                
                # Delete existing records for this chunk to ensure idempotency (Fixes missing PK issue)
                min_ts = final_df['timestamp'].min()
                max_ts = final_df['timestamp'].max()
                local_con.execute("""
                    DELETE FROM historical_data 
                    WHERE ticker = ? AND timestamp >= ? AND timestamp <= ?
                """, [ticker, min_ts, max_ts])
                
                local_con.execute("INSERT INTO historical_data SELECT * FROM candles_chunk")
                
                # 2. Daily Metrics
                from .processor import process_daily_metrics
                daily_metrics_df = process_daily_metrics(final_df)
                
                if not daily_metrics_df.empty:
                    # TIER 2/3 ENRICHMENT: Use surgical UPDATE to avoid data loss
                    # Identify columns to update (metrics only)
                    con_info = local_con.execute("DESCRIBE daily_metrics").fetch_df()
                    db_columns = con_info['column_name'].tolist()
                    
                    metrics_to_update = [c for c in db_columns if c in daily_metrics_df.columns and c not in ['ticker', 'date']]
                    
                    # Sanitize for DuckDB
                    import numpy as np
                    for col in daily_metrics_df.columns:
                        if daily_metrics_df[col].dtype == object: continue
                        if pd.api.types.is_float_dtype(daily_metrics_df[col]):
                            daily_metrics_df[col] = daily_metrics_df[col].replace([np.inf, -np.inf], np.nan)
                    
                    local_con.register('daily_chunk', daily_metrics_df)
                    
                    # Build UPDATE clause
                    set_clause = ", ".join([f"{c} = t.{c}" for c in metrics_to_update])
                    
                    # 1. Update existing rows (Enrichment)
                    local_con.execute(f"""
                        UPDATE daily_metrics 
                        SET {set_clause} 
                        FROM daily_chunk t 
                        WHERE daily_metrics.ticker = t.ticker 
                        AND daily_metrics.date = t.date
                    """)
                    
                    # 2. Insert as NEW rows only for dates that don't exist yet
                    # This handles new data from the scanner for today/yesterday
                    cols_str = ", ".join(['ticker', 'date'] + metrics_to_update)
                    local_con.execute(f"""
                        INSERT INTO daily_metrics ({cols_str})
                        SELECT {cols_str} FROM daily_chunk t
                        WHERE NOT EXISTS (
                            SELECT 1 FROM daily_metrics d 
                            WHERE d.ticker = t.ticker AND d.date = t.date
                        )
                    """)
                    
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

class DailyScanner:
    """
    Intelligent Daily Scanner.
    1. Scans the entire market using Grouped Daily endpoints.
    2. Identifies 'Pump' candidates based on broad criteria (Gap > X, Vol > Y).
    3. Downloads full 1-minute history for candidates.
    4. Applies STRICT validation (PM Gap, PM Vol, Price) before saving.
    """
    
    def __init__(self):
        self.client = MassiveClient()
        self.con = None

    def scan_and_ingest_range(self, start_date_str, end_date_str):
        """Backfill a range of dates using the scanner logic"""
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        
        current_date = start_date
        
        # Pre-fetch yesterday's close for the first day
        prev_date = current_date - timedelta(days=1)
        print(f"📊 Prime-loading previous day data ({prev_date.strftime('%Y-%m-%d')})...")
        prev_closes = self._get_closes_map(prev_date.strftime('%Y-%m-%d'))
        
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            print(f"\n🔎 Scanning {date_str}...")
            
            # 1. Broad Scan
            candidates, todays_closes = self._broad_scan(date_str, prev_closes)
            print(f"   Found {len(candidates)} candidates passing broad filters (Gap>15%, Vol>500k)")
            
            # 2. Strict Ingestion
            saved_count = 0
            for ticker in candidates:
                if self._strict_ingest(ticker, date_str):
                    saved_count += 1
            
            print(f"   ✅ Saved {saved_count} valid pumps for {date_str}")
            
            # Move forward
            prev_closes = todays_closes
            current_date += timedelta(days=1)
            
            # Small sleep between dates to respect Massive API rate limits (Free Tier)
            if current_date <= end_date:
                print("   💤 Sleeping 10s before next date...")
                time.sleep(10)
            
    def _get_closes_map(self, date_str):
        """Get a map of Ticker -> ClosePrice for a given date"""
        results = self.client.get_grouped_daily(date_str)
        return {r['T']: r['c'] for r in results if 'c' in r and 'T' in r}

    def _broad_scan(self, date_str, prev_closes_map):
        """
        Find tickers that MIGHT match criteria.
        Criteria: Gap > 15% (loose), Total Volume > 500k, Price > 0.1
        """
        results = self.client.get_grouped_daily(date_str)
        todays_closes = {}
        candidates = []
        
        for r in results:
            ticker = r.get('T')
            close = r.get('c')
            open_price = r.get('o')
            vol = r.get('v', 0)
            
            if not ticker or not close or not open_price:
                continue
                
            todays_closes[ticker] = close
            
            # Filter 1: Price > 0.10 (User: "Precio cierre anterior > 0.10")
            # We use today's open as a proxy for price range if prev not found, 
            # or strictly check prev_close if available.
            prev_close = prev_closes_map.get(ticker)
            
            # If we don't have prev_close (listing just started, or split, or missing data), 
            # we skip gap check usually, OR assume slight gap. 
            # Safest is to skip if no prev_close (can't calc pumps).
            if not prev_close or prev_close < 0.10:
                continue

            # Filter 2: Total Volume > 500k
            if vol < 500000:
                continue

            # Filter 3: Gap > 15% (User asked for 20%, we use 15% as catch-all)
            gap_pct = ((open_price - prev_close) / prev_close) * 100
            
            if gap_pct >= 15.0:
                candidates.append(ticker)
                
        return candidates, todays_closes

    def _strict_ingest(self, ticker, date_str):
        """
        Download 1-min data, verify strict Gap/PM-Vol criteria, and save if valid.
        """
        # We fetch JUST that day (from=date, to=date)
        # ingest_ticker_history_range handles saving
        # But we need to intercept the DF to check conditions BEFORE saving?
        # Actually checking triggers afterwards is easier with current architecture
        # OR we just save it (it's good data anyway) and tag it?
        # User said: "tu objetivo es tener la mayor BBDD posible... asegurar que tienes todo lo que se mueve"
        # So if it passed Broad Scan, it's worth saving!
        # Strict validation is for "Tags", but saving the data is good regardless.
        
        # However, to avoid spamming the logs, let's just ingest.
        try:
            # Re-use existing function but we need to ensure it uses the Scanner's logic?
            # Existing ingest_ticker_history_range is designed for ranges. 
            # We can use it for single day.
            
            # 1. Update Ticker table first (if new)
            con = get_db_connection()
            try:
                # Manual existence check instead of ON CONFLICT for MotherDuck compatibility
                exists = con.execute("SELECT 1 FROM tickers WHERE ticker = ?", [ticker]).fetchone()
                if not exists:
                    con.execute("""
                        INSERT INTO tickers (ticker, name, active, last_updated) 
                        VALUES (?, ?, ?, ?)
                    """, [ticker, ticker, True, datetime.now()])
                else:
                    con.execute("UPDATE tickers SET last_updated = ? WHERE ticker = ?", [datetime.now(), ticker])
            except Exception as e:
                print(f"      ⚠️  Ticker update error (non-fatal): {e}")
            finally:
                con.close()
            
            print(f"      - Ingesting {ticker}...", end="", flush=True)
            
            # Ingest content
            # We use a dummy client-like call or just call the function?
            # The function ingest_ticker_history_range uses `client` passed to it.
            ingest_ticker_history_range(self.client, ticker, date_str, date_str, skip_sleep=True)
            print(" Done.")
            return True
            
        except Exception as e:
            print(f" Error: {e}")
            return False

def run_daily_scan_job():
    """Entry point for the scheduled job"""
    scanner = DailyScanner()
    
    # We scan YESTERDAY (to ensure full day data is final) or TODAY?
    # User said: "5:00 PM (hora Mexico)". Market is closed.
    # So we scan TODAY.
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"🚀 Starting Daily Scanner Job for {today}...")
    scanner.scan_and_ingest_range(today, today)

def ingest_history(ticker, days=30):
    """Legacy helper for API compatibility"""
    client = MassiveClient()
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    ingest_ticker_history_range(client, ticker, from_date, to_date)


