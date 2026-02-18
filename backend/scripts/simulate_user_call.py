from app.services.query_service import build_screener_query
from datetime import date

# Simulate params from frontend
filters = {
    'min_gap_at_open_pct': '20',
    'min_volume': '5000000',
    'start_date': '2026-02-01',
    'end_date': '2026-02-15',
    'limit': '50'
}

print("--- Filters ---")
print(filters)

rec_query, sql_p, where_d, where_i, where_m, where_base = build_screener_query(filters, 50)

print("\n--- Generated Query ---")
print(rec_query)
print("\n--- SQL Params ---")
print(sql_p)

# Basic validation
if "FROM daily_metrics" in rec_query:
    print("\n✅ Query targets daily_metrics")
else:
    print("\n❌ Query DOES NOT target daily_metrics")

if "gap_pct >= ?" in rec_query or "gap_pct > ?" in where_m:
    print("✅ Gap filter present")
else:
    print("❌ Gap filter missing")
