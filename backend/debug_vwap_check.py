from app.database import get_db_connection
import pandas as pd

def check_vwap_logic():
    con = get_db_connection(read_only=True)
    
    ticker = 'CMCT'
    dates = ['2026-01-22', '2025-12-22', '2025-12-03', '2025-11-12']
    
    # 1. Check 08:30
    print("--- Checking 08:30:00 ---")
    query_830 = f"""
        SELECT timestamp, open, vwap, (open < vwap) as is_lower
        FROM intraday_1m
        WHERE ticker = '{ticker}'
        AND CAST(timestamp AS DATE) IN {tuple(dates)}
        AND CAST(timestamp AS TIME) = '08:30:00'
        ORDER BY timestamp
    """
    df_830 = con.execute(query_830).fetch_df()
    print(df_830)
    if not df_830.empty:
        ratio_830 = df_830['is_lower'].mean()
        print(f"Ratio 08:30: {ratio_830:.2%}")
    else:
        print("No data for 08:30")

    # 2. Check 09:30
    print("\n--- Checking 09:30:00 ---")
    query_930 = f"""
        SELECT timestamp, open, vwap, (open < vwap) as is_lower
        FROM intraday_1m
        WHERE ticker = '{ticker}'
        AND CAST(timestamp AS DATE) IN {tuple(dates)}
        AND CAST(timestamp AS TIME) = '09:30:00'
        ORDER BY timestamp
    """
    df_930 = con.execute(query_930).fetch_df()
    print(df_930)
    if not df_930.empty:
        ratio_930 = df_930['is_lower'].mean()
        print(f"Ratio 09:30: {ratio_930:.2%}")
    else:
        print("No data for 09:30")

    con.close()

if __name__ == "__main__":
    check_vwap_logic()
