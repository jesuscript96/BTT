import duckdb

db_path = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\users.duckdb"
con = duckdb.connect(db_path, read_only=True)
try:
    print("Datasets pair counts:")
    res = con.execute("""
        SELECT q.id, q.name, COUNT(p.ticker) as pair_count 
        FROM saved_queries q
        LEFT JOIN dataset_pairs p ON q.id = p.dataset_id
        GROUP BY q.id, q.name
        ORDER BY pair_count ASC
    """).fetchall()
    for row in res:
        print(f"ID: {row[0]} | Name: {row[1]} | Pairs: {row[2]}")
finally:
    con.close()
