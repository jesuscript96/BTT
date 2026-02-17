import os
import duckdb
from dotenv import load_dotenv
from app.services.query_service import build_screener_query, get_stats_sql_logic

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")
con = duckdb.connect(f"md:massive?motherduck_token={token}")

# Filters from user URL
# min_gap_at_open_pct=30&max_gap_at_open_pct=50&start_date=2025-12-03&end_date=2025-12-15&min_volume=150000000&limit=5000
filters = {
    "min_gap_at_open_pct": "30",
    "max_gap_at_open_pct": "50",
    "start_date": "2025-12-03",
    "end_date": "2025-12-15",
    "min_volume": "150000000",
    "limit": "5000"
}

print("Building screener query...")
rec_query, sql_p, where_d, where_i, where_m, where_base = build_screener_query(filters, 5000)

print(f"Executing Screener Query with {len(sql_p)} params...")
# Simulate market.py execution
try:
    cur = con.execute(rec_query, sql_p)
    rows = cur.fetchall()
    print(f"Screener returned {len(rows)} rows.")
except Exception as e:
    print(f"Screener Query FAILED: {str(e)}")
    import traceback; traceback.print_exc()

print("Building Stats Query...")
st_query = get_stats_sql_logic(where_d, where_i, where_m, where_base)

print(f"Executing Stats Query with SAME params...")
try:
    st_rows = con.execute(st_query, sql_p).fetchall()
    print("Stats Query SUCCESS.")
    print(st_rows)
except Exception as e:
    print(f"Stats Query FAILED: {str(e)}")
    import traceback; traceback.print_exc()
