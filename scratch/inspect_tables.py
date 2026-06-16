import duckdb

def inspect_db(path):
    print(f"\n--- Inspecting database: {path} ---")
    try:
        con = duckdb.connect(path)
        tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
        print("Tables in main schema:")
        for t in tables:
            print(f" - {t[0]}")
            # print schema / columns
            cols = con.execute(f"PRAGMA table_info('{t[0]}')").fetchall()
            col_desc = ", ".join([f"{c[1]} ({c[2]})" for c in cols])
            print(f"   Columns: {col_desc}")
            # print row count
            count = con.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
            print(f"   Row count: {count}")
        con.close()
    except Exception as e:
        print(f"Error inspecting {path}: {e}")

inspect_db('users.duckdb')
inspect_db('backend/app/market_data.db')
