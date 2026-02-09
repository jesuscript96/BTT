import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def audit_schema():
    print("🔍 Auditing MotherDuck daily_metrics schema...")
    token = os.getenv("MOTHERDUCK_TOKEN")
    try:
        con = duckdb.connect(f"md:btt?motherduck_token={token}")
        df = con.execute("DESCRIBE daily_metrics").fetch_df()
        print("\n📊 Current Schema of daily_metrics:")
        print(df[['column_name', 'column_type']])
        
        # Check against expected columns from processor.py
        expected = [
            "ticker", "date", "rth_open", "rth_high", "rth_low", "rth_close",
            "rth_volume", "gap_at_open_pct", "rth_run_pct", "pm_high", "pm_volume",
            "high_spike_pct", "low_spike_pct", "pmh_fade_to_open_pct",
            "rth_fade_to_close_pct", "open_lt_vwap", "pm_high_break",
            "m15_return_pct", "m30_return_pct", "m60_return_pct",
            "close_lt_m15", "close_lt_m30", "close_lt_m60",
            "hod_time", "lod_time", "close_direction",
            "prev_close", "pmh_gap_pct", "rth_range_pct", "day_return_pct", "pm_high_time",
            "m1_high_spike_pct", "m5_high_spike_pct", "m15_high_spike_pct",
            "m30_high_spike_pct", "m60_high_spike_pct", "m180_high_spike_pct",
            "m1_low_spike_pct", "m5_low_spike_pct", "m15_low_spike_pct",
            "m30_low_spike_pct", "m60_low_spike_pct", "m180_low_spike_pct",
            "return_m15_to_close", "return_m30_to_close", "return_m60_to_close"
        ]
        
        current_cols = df['column_name'].tolist()
        missing = [c for c in expected if c not in current_cols]
        
        if missing:
            print(f"\n❌ MISSING COLUMNS ({len(missing)}):")
            for m in missing:
                print(f" - {m}")
        else:
            print("\n✅ All columns are present!")
            
        con.close()
    except Exception as e:
        print(f"❌ Error during audit: {e}")

if __name__ == "__main__":
    audit_schema()
