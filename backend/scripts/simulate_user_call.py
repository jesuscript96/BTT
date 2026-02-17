from app.services.query_service import build_screener_query
from datetime import date

# Simulate params from frontend
filters = {
    'min_gap_at_open_pct': '30',
    'min_volume': '150000000',
    'start_date': '2025-11-15',
    'end_date': '2026-02-16',
    'limit': '5000'
}

# Add the defaults from market.py
filters.update({
    'min_gap': 0.0,
    'max_gap': None,
    'min_run': 0.0,
    'min_volume': 150000000.0,
    'trade_date': None,
    'start_date': date(2025, 11, 15),
    'end_date': date(2026, 2, 16),
    'ticker': None
})

rec_query, sql_p, where_d, where_i, where_m, where_base = build_screener_query(filters, 5000)

print(f"WHERE_D: {where_d}")
print(f"WHERE_I: {where_i}")
print(f"WHERE_M: {where_m}")
print(f"WHERE_BASE: {where_base}")
print(f"SQL_P: {sql_p}")
# Check if gap_pct >= 30 is in where_m
if "gap_pct >= 30" in where_m:
    print("SUCCESS: Gap filter found in WHERE_M")
else:
    print("FAILURE: Gap filter MISSING from WHERE_M")
