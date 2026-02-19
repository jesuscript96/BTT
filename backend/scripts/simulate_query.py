import sys
import os
sys.path.append(os.getcwd())
from app.services.query_service import build_screener_query, get_stats_sql_logic

filters = {
    'min_gap_at_open_pct': 30,
    'max_gap_at_open_pct': 50,
    'start_date': '2025-11-15',
    'end_date': '2026-02-16',
}

rec_query, sql_p, where_d, where_i, where_m, where_m_stats = build_screener_query(filters, 5000)

print(f"WHERE_M_STATS: {where_m_stats}")

stats_query = get_stats_sql_logic(where_d, where_i, where_m_stats, "1=1")
print("\nSTATS QUERY:")
print(stats_query)
