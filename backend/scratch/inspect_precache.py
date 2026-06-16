import duckdb

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/backend/users.duckdb'
print(f"Connecting to {db_path}...")
con = duckdb.connect(db_path)

try:
    print("Checking tables...")
    tables = con.execute("SHOW TABLES").fetchall()
    print("Tables:", tables)
    
    dataset_ids = [
        'bd49cdb9-a9ff-47d1-8455-061732c1166f',
        'd75e3c62-b28e-4da5-9aa5-1229408bfb63'
    ]
    
    for ds_id in dataset_ids:
        print(f"\n=== Dataset ID: {ds_id} ===")
        # Get name
        name_row = con.execute("SELECT name, created_at FROM datasets WHERE id = ?", [ds_id]).fetchone()
        print(f"Name: {name_row}")
        
        # Check precache status
        precache_row = con.execute("SELECT status, progress_pct, updated_at FROM precache_state WHERE dataset_id = ?", [ds_id]).fetchone()
        print(f"Precache state: {precache_row}")
        
        # Check dataset_pairs
        if ('dataset_pairs',) in tables or any('dataset_pairs' in t[0] for t in tables):
            pair_count = con.execute("SELECT count(*) FROM dataset_pairs WHERE dataset_id = ?", [ds_id]).fetchone()[0]
            print(f"Number of pairs in dataset_pairs: {pair_count}")
            if pair_count > 0:
                # Show first 5 pairs
                sample_pairs = con.execute("SELECT * FROM dataset_pairs WHERE dataset_id = ? LIMIT 5", [ds_id]).fetchall()
                print("Sample pairs:", sample_pairs)
        
        # Let's count how many rows/candles are cached for this dataset, if there's any cache table
        # Let's look for tables storing intraday cache or similar.
        # Wait, how does caching work? Let's check the code where iter_intraday_groups_streamed is defined.
        
except Exception as e:
    print(f"Error: {e}")
finally:
    con.close()
