import sys
import os
sys.path.append(os.getcwd())
from app.services.query_service import build_screener_query

filters = {
    'min_gap_at_open_pct': 30,
    'max_gap_at_open_pct': 50,
    'min_volume': 150000000,
    'start_date': '2025-11-15',
    'end_date': '2026-02-16',
    'min_gap': 0.0,
    'max_gap': None,
    'min_run': 0.0,
    'min_volume_explicit': 0.0 # renamed to avoid conflict
}

# Simulate the merge in market.py
# filters.update({'min_gap': 0.0, ...}) - already done above

rec_query, sql_p, where_d, where_i, where_m = build_screener_query(filters, 5000)

print(f"WHERE_D: {where_d}")
print(f"WHERE_I: {where_i}")
print(f"WHERE_M: {where_m}")
print(f"SQL_P: {sql_p}")
print("\nQUERY:")
print(rec_query)
