import duckdb
import os
import json
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add backend to path so we can import the Strategy model
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

load_dotenv("backend/.env")

def persist_strategies():
    token = os.getenv("MOTHERDUCK_TOKEN")
    if not token:
        print("MOTHERDUCK_TOKEN not found in .env.")
        return
    
    strategies_file = "backend/scripts/example_strategies.json"
    if not os.path.exists(strategies_file):
        print(f"Strategies file {strategies_file} not found.")
        return
        
    with open(strategies_file, 'r') as f:
        strategies_raw = json.load(f)

    # Validate each strategy through the Pydantic model
    from app.schemas.strategy import Strategy
    
    print(f"Connecting to MotherDuck...")
    con = duckdb.connect(f"md:massive?motherduck_token={token}")
    
    for s in strategies_raw:
        s_id = s.get('id', s['name'].lower().replace(' ', '_'))
        now = datetime.now().isoformat()
        
        # Build a complete Strategy object with required fields
        s['id'] = s_id
        s['created_at'] = now
        s['updated_at'] = now
        
        try:
            strategy = Strategy(**s)
            definition = json.dumps(strategy.model_dump())
        except Exception as e:
            print(f"⚠️  Skipping '{s.get('name')}': validation error: {e}")
            continue
        
        name = strategy.name
        description = strategy.description or ''
        
        print(f"Upserting strategy: {name} (id={s_id})")
        con.execute("DELETE FROM strategies WHERE id = ?", [s_id])
        con.execute("""
            INSERT INTO strategies (id, name, description, definition, created_at, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, [s_id, name, description, definition])
        
    print(f"Successfully persisted strategies to MotherDuck.")
    con.close()

if __name__ == "__main__":
    persist_strategies()
