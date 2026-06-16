import duckdb
import json

db_path = 'c:/Users/Famil/OneDrive/Escritorio/Jaume/Edgecute Jaume/BTT/users.duckdb'
print(f"Connecting to {db_path}...")
try:
    con = duckdb.connect(db_path, read_only=True)
    
    # Query backtest_results
    # Let's see the columns first
    cols = con.execute("DESCRIBE users.main.backtest_results").fetchall()
    print("Columns in backtest_results:")
    for col in cols:
        print(f"  {col[0]}: {col[1]}")
        
    rows = con.execute("SELECT id, strategy_ids, executed_at, CAST(results_json AS VARCHAR) FROM users.main.backtest_results ORDER BY executed_at DESC LIMIT 3").fetchall()
    print(f"\nFound {len(rows)} backtest results:")
    for row in rows:
        bt_id, strat_ids, executed_at, results_str = row
        print(f"Backtest ID: {bt_id}, Strategy IDs: {strat_ids}, Executed At: {executed_at}")
        try:
            results = json.loads(results_str)
            params = results.get("backtest_params", {})
            print("  Backtest Params:")
            print(f"    Dataset ID: {results.get('dataset_id') or params.get('dataset_id')}")
            print(f"    Market Sessions: {params.get('market_sessions')}")
            
            # Fetch the strategy definition if available
            # strat_ids is a JSON array or list, let's extract the first ID
            strat_id_list = json.loads(strat_ids) if isinstance(strat_ids, str) else strat_ids
            strat_id = strat_id_list[0] if strat_id_list else None
            if strat_id:
                strat_row = con.execute("SELECT name, CAST(definition AS VARCHAR) FROM users.main.strategies WHERE id = ?", (strat_id,)).fetchone()
                if strat_row:
                    strat_name, definition_str = strat_row
                    print(f"  Strategy Name: {strat_name}")
                    definition = json.loads(definition_str)
                    print("  Strategy Entry Time Windows:")
                    print(json.dumps(definition.get("entry_logic", {}).get("entry_time_windows", []), indent=2))
                else:
                    print(f"  Strategy {strat_id} not found in DB")
            else:
                print("  No strategy ID found")
                
            trades = results.get("trades", [])
            print(f"  Total Trades: {len(trades)}")
            if trades:
                print("  Sample Trades:")
                for t in trades[:10]:
                    print(f"    Ticker: {t.get('ticker')}, Entry: {t.get('entry_time')}, Exit: {t.get('exit_time')}, Reason: {t.get('exit_reason')}")
        except Exception as e:
            print(f"  Error parsing results: {e}")
        print("=" * 60)
        
    con.close()
except Exception as e:
    print(f"Error: {e}")
