import sys
import os
import json
import duckdb

# Connect directly to BTT/backend/users.duckdb
db_path = r"c:\Users\Famil\OneDrive\Escritorio\Jaume\Edgecute Jaume\BTT\backend\users.duckdb"
print("Connecting to:", db_path)
conn = duckdb.connect(db_path)

rows = conn.execute("SELECT name, description, definition FROM strategies").fetchall()
print(f"Total strategies: {len(rows)}")
for i, row in enumerate(rows):
    name = row[0]
    description = row[1]
    definition = json.loads(row[2]) if isinstance(row[2], str) else row[2]
    
    print(f"{i+1}: Name: '{name}', Description: '{description}'")
    if "V4" in name or "v4" in name or "V4" in str(description) or "v4" in str(description):
        print("=" * 60)
        print("Strategy Name:", name)
        print("Description:", description)
        print("Definition:")
        print(json.dumps(definition, indent=2))
        print("=" * 60)
