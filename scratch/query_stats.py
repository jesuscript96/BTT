import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import get_db_connection
from app.init_db import init_db

init_db()
con = get_db_connection()

# 1. Total count
total = con.execute("SELECT COUNT(*) FROM massive.tickers").fetchone()[0]
print(f"Total Tickers in massive.tickers: {total}")

# 2. Count by Active / Inactive
active_counts = con.execute("SELECT active, COUNT(*) FROM massive.tickers GROUP BY active").fetchall()
print("\n--- Active Status Counts ---")
for r in active_counts:
    print(f"Active={r[0]}: {r[1]}")

# 3. Counts by Market
print("\n--- Tickers by Market (Top 25) ---")
markets = con.execute("""
    SELECT market, COUNT(*) as count 
    FROM massive.tickers 
    GROUP BY market 
    ORDER BY count DESC 
    LIMIT 25
""").fetchall()
for i, r in enumerate(markets):
    print(f"{i+1}. {r[0] or 'Unknown'}: {r[1]}")

# 4. Counts by Primary Exchange
print("\n--- Tickers by Primary Exchange (Top 25) ---")
exchanges = con.execute("""
    SELECT primary_exchange, COUNT(*) as count 
    FROM massive.tickers 
    GROUP BY primary_exchange 
    ORDER BY count DESC 
    LIMIT 25
""").fetchall()
for i, r in enumerate(exchanges):
    print(f"{i+1}. {r[0] or 'Unknown'}: {r[1]}")

# 5. Counts by Ticker Type
print("\n--- Tickers by Type (Sorted by Count DESC) ---")
types = con.execute("""
    SELECT type, COUNT(*) as count 
    FROM massive.tickers 
    GROUP BY type 
    ORDER BY count DESC
""").fetchall()
for i, r in enumerate(types):
    print(f"{i+1}. {r[0]}: {r[1]}")

# 6. Sample ADRs to see if we can identify country in name (like China, Japan, etc.)
print("\n--- Sample ADRs (type = 'ADRC') ---")
adr_samples = con.execute("""
    SELECT ticker, name, market, primary_exchange 
    FROM massive.tickers 
    WHERE type = 'ADRC'
    LIMIT 15
""").fetchdf()
print(adr_samples)

# 7. Check if there are other files in the bucket or parquet directory that might have country mapping
import os
print("\n--- Listing Parquet files in strategybuilderbbdd GCS bucket (using view path info) ---")
print("Tickers view query source path: gs://strategybuilderbbdd/cold_storage/tickers/*.parquet")
