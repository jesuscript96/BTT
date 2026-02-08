"""
Recalculate script: Populate new metrics for existing data
This script re-processes historical_data to calculate new metrics
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd

# Setup
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)
load_dotenv()

from app.database import get_db_connection
from app.processor import process_daily_metrics

def recalculate_metrics_for_ticker(ticker, limit_days=30):
    """Recalculate metrics for a single ticker (last N days)"""
    con = get_db_connection()
    
    print(f"Recalculating metrics for {ticker}...")
    
    # Get historical 1-minute data for this ticker
    query = """
        SELECT *
        FROM historical_data
        WHERE ticker = ?
        ORDER BY timestamp DESC
        LIMIT ?
    """
    
    # Fetch last N days worth of 1-min data (approx 390 bars/day * N days)
    df = con.execute(query, [ticker, limit_days * 400]).fetch_df()
    
    if df.empty:
        print(f"  ⚠ No data found for {ticker}")
        return
    
    print(f"  Found {len(df)} 1-min bars")
    
    # Process to calculate daily metrics
    daily_metrics = process_daily_metrics(df)
    
    if daily_metrics.empty:
        print(f"  ⚠ No daily metrics calculated")
        return
    
    print(f"  Calculated metrics for {len(daily_metrics)} days")
    
    # Update daily_metrics table (upsert)
    for _, row in daily_metrics.iterrows():
        # Delete existing record for this ticker/date
        con.execute("""
            DELETE FROM daily_metrics
            WHERE ticker = ? AND date = ?
        """, [row['ticker'], row['date']])
        
        # Insert new record with all metrics
        cols = list(row.index)
        placeholders = ', '.join(['?'] * len(cols))
        col_names = ', '.join(cols)
        
        insert_query = f"""
            INSERT INTO daily_metrics ({col_names})
            VALUES ({placeholders})
        """
        
        con.execute(insert_query, list(row.values))
    
    con.close()
    print(f"  ✅ Updated {len(daily_metrics)} days for {ticker}")


def main():
    """Recalculate metrics for sample tickers"""
    con = get_db_connection(read_only=True)
    
    # Get list of tickers with most recent data
    query = """
        SELECT DISTINCT ticker
        FROM historical_data
        ORDER BY ticker
        LIMIT 20
    """
    
    tickers = con.execute(query).fetchall()
    con.close()
    
    if not tickers:
        print("No tickers found")
        return
    
    print(f"\\nRecalculating metrics for {len(tickers)} tickers...\\n")
    
    for (ticker,) in tickers:
        try:
            recalculate_metrics_for_ticker(ticker, limit_days=30)
        except Exception as e:
            print(f"  ❌ Error for {ticker}: {e}")
            continue
    
    print("\\n✅ Recalculation complete!")


if __name__ == "__main__":
    main()
