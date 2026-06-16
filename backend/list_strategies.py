from app.database import get_user_db_connection, get_user_db_lock

lock = get_user_db_lock()
with lock:
    con = get_user_db_connection(read_only=True)
    try:
        rows = con.execute("SELECT id, name FROM strategies").fetchall()
        print(f"Total strategies: {len(rows)}")
        for r in rows:
            print(f"- ID: {r[0]} | Name: {r[1]}")
    finally:
        con.close()
