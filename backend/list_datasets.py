from app.database import get_user_db_connection, get_user_db_lock
import json

lock = get_user_db_lock()
with lock:
    con = get_user_db_connection(read_only=True)
    try:
        rows = con.execute("SELECT id, name, filters FROM saved_queries").fetchall()
        print(f"Total datasets: {len(rows)}")
        for r in rows:
            print(f"- ID: {r[0]} | Name: {r[1]}")
            try:
                filters = json.loads(r[2])
                print(f"  Start: {filters.get('start_date') or filters.get('date_from')} | End: {filters.get('end_date') or filters.get('date_to')}")
                print(f"  Rules: {filters.get('rules', [])}")
            except:
                print(f"  Filters: {r[2]}")
    finally:
        con.close()
