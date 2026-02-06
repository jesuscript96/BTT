import sys
import os
import json
from app.database import get_db_connection

# Connect
con = get_db_connection()

# Fetch all strategies
strategies = con.execute("SELECT id, definition FROM strategies").fetchall()

print(f"Found {len(strategies)} strategies. Checking for 'Price > 0'...")

for row in strategies:
    sid = row[0]
    definition = json.loads(row[1])
    
    modified = False
    
    # Check entry logic
    if 'entry_logic' in definition:
        for group in definition['entry_logic']:
            for cond in group.get('conditions', []):
                # If Price > 0, make it Price > 1000 (so it rarely hits) or something sensible
                if cond.get('indicator') == 'Price' and cond.get('operator') == '>' and cond.get('value') == 0:
                    print(f"Fixing spam condition in strategy {definition.get('name')} ({sid})")
                    cond['value'] = 999999 # Make it impossible to hit for now
                    modified = True
                
                # Also fix Price > 0.0
                if cond.get('indicator') == 'Price' and cond.get('operator') == '>' and cond.get('value') == 0.0:
                    print(f"Fixing spam condition in strategy {definition.get('name')} ({sid})")
                    cond['value'] = 999999
                    modified = True

    if modified:
        new_def_json = json.dumps(definition)
        con.execute("UPDATE strategies SET definition = ? WHERE id = ?", (new_def_json, sid))
        print("✓ Updated.")
    else:
        print(f"- Strategy {definition.get('name')} looks ok.")

print("Done.")
