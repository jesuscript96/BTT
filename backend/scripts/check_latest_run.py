import duckdb
import os
import json
from dotenv import load_dotenv

load_dotenv('backend/.env')
token = os.getenv("MOTHERDUCK_TOKEN")
if token:
    try:
        con = duckdb.connect(f"md:massive?motherduck_token={token}")
        res = con.execute("SELECT id, executed_at, results_json FROM backtest_results ORDER BY executed_at DESC LIMIT 1").fetchone()
        if res:
            print(f"Latest Run: {res[0]} at {res[1]}")
            data = json.loads(res[2])
            print(f"Total Trades: {len(data['trades'])}")
            for t in data['trades'][:5]:
                print(f"{t['ticker']} | Entry: {t['entry_time']} | Exit: {t['exit_time']} | Reason: {t.get('exit_reason')}")
        else:
            print("No results")
    except Exception as e:
        print("Error:", e)
else:
    print("No token")
