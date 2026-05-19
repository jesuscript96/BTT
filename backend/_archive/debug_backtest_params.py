import duckdb
import json
import os
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("MOTHERDUCK_TOKEN")
con = duckdb.connect(f"md:btt?motherduck_token={token}")

# Mock saved query filters
saved_filters = {
    "min_gap_pct": 5.0,
    "rules": [
        {"metric": "RVOL", "operator": ">", "value": "2.0", "valueType": "static"}
    ]
}

METRIC_MAP = {
    "RVOL": "rth_volume", # Assuming mapping
}

sub_query = "SELECT ticker, date FROM daily_metrics WHERE 1=1"
sub_params = []

f = saved_filters
if f.get('min_gap_pct') is not None:
    sub_query += " AND gap_at_open_pct >= ?"
    sub_params.append(f['min_gap_pct'])

rules = f.get('rules', [])
for rule_dict in rules:
    col = METRIC_MAP.get(rule_dict.get('metric'))
    op = rule_dict.get('operator')
    val = rule_dict.get('value')
    v_type = rule_dict.get('valueType')
    
    if col and op in ["=", "!=", ">", ">=", "<", "<="] and val:
        if v_type == "static":
            try:
                sub_query += f" AND {col} {op} ?"
                sub_params.append(float(val))
            except ValueError:
                sub_query += f" AND {col} {op} ?"
                sub_params.append(val)

query = f"""
    SELECT h.* 
    FROM historical_data h
    INNER JOIN ({sub_query}) d 
    ON h.ticker = d.ticker 
    AND h.timestamp >= CAST(d.date AS TIMESTAMP)
    AND h.timestamp < CAST(d.date AS TIMESTAMP) + INTERVAL 1 DAY
    WHERE 1=1
"""
params = sub_params

# Mock manual filters
date_from = "2023-01-01"
date_to = "2023-12-31"

if date_from:
    query += " AND h.timestamp >= CAST(? AS TIMESTAMP)"
    params.append(date_from)

if date_to:
    query += " AND h.timestamp <= CAST(? AS TIMESTAMP)"
    params.append(date_to)

print("Query:")
print(query)
print("\nParams:")
print(params)
print("\nParam count in query:", query.count('?'))
print("Param count in list:", len(params))

try:
    df = con.execute(query, params).fetch_df()
    print("\nSuccess! Rows:", len(df))
except Exception as e:
    print("\nError recorded:", e)
