import sys
import os
import json
import math
from datetime import date

# Add backend to sys path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db_connection
from app.services.query_service import build_screener_query, get_stats_sql_logic, map_stats_row

def safe_float(v):
    if v is None: return 0.0
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv): return 0.0
        return fv
    except:
        return 0.0

def reproduce():
    con = get_db_connection()
    print("DB Connected.")
    
    # Filters that likely trigger data
    filters = {
        'limit': 100,
        'start_date': date(2025, 1, 1),
        'end_date': date(2026, 2, 18)
    }
    
    try:
        rec_query, sql_p, where_d, where_i, where_m, where_base = build_screener_query(filters, 100)
        
        print("\n--- executing stats query ---")
        st_query = get_stats_sql_logic(where_d, where_i, where_m, where_base)
        print(st_query)
        print(f"Params: {sql_p}")
        
        st_rows = con.execute(st_query, sql_p).fetchall()
        print(f"\nStats Rows Returned: {len(st_rows)}")
        
        stats_payload = {}
        for s_row in st_rows:
            print(f"Processing row: {s_row}")
            s_key = s_row[0]
            if s_key == 'avg':
                stats_payload['avg'] = map_stats_row(s_row)
            elif s_key in ['p25', 'p50', 'p75']:
                stats_payload[s_key] = map_stats_row(s_row)
        
        print("\n--- Attempting JSON Dump ---")
        json_str = json.dumps(stats_payload)
        print("✅ JSON Dump Success!")
        
    except Exception as e:
        print(f"❌ CRASH: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    reproduce()
