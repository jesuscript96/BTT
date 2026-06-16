import duckdb
import json

def main():
    con = duckdb.connect("users.duckdb", read_only=True)
    rows = con.execute("SELECT id, name, definition FROM strategies").fetchall()
    print(f"Total strategies: {len(rows)}")
    for r_id, name, definition in rows:
        print(f"\n--- Strategy: {name} (ID: {r_id}) ---")
        if isinstance(definition, str):
            try:
                definition = json.loads(definition)
            except Exception:
                pass
        
        # print in formatted json
        print(json.dumps(definition, indent=2))

if __name__ == "__main__":
    main()
