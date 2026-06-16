import duckdb
import os

paths = ['users.duckdb', 'backend/users.duckdb']
for p in paths:
    if os.path.exists(p):
        print(f"\nChecking database: {p}")
        try:
            con = duckdb.connect(p, read_only=True)
            tables = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
            print("  Tables:", [t[0] for t in tables])
            if ('datasets',) in tables:
                ds = con.execute("SELECT id, name FROM datasets").fetchall()
                print("  Datasets (datasets table):")
                for d in ds:
                    print(f"    {d[0]} | {d[1]}")
            if ('saved_queries',) in tables:
                sq = con.execute("SELECT id, name FROM saved_queries").fetchall()
                print("  Datasets (saved_queries table):")
                for s in sq:
                    print(f"    {s[0]} | {s[1]}")
            con.close()
        except Exception as e:
            print("  Error:", e)
    else:
        print(f"\nPath does not exist: {p}")
