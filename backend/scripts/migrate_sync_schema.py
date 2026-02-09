import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

def migrate_schema():
    print("🔄 Syncing daily_metrics schema with MotherDuck...")
    token = os.getenv("MOTHERDUCK_TOKEN")
    con = duckdb.connect(f"md:btt?motherduck_token={token}")
    
    columns_to_add = [
        ("prev_close", "DOUBLE"),
        ("pmh_gap_pct", "DOUBLE"),
        ("rth_range_pct", "DOUBLE"),
        ("day_return_pct", "DOUBLE"),
        ("pm_high_time", "VARCHAR"),
        ("pmh_fade_to_open_pct", "DOUBLE"),
        # Tier 2 - High Spikes
        ("m1_high_spike_pct", "DOUBLE"),
        ("m5_high_spike_pct", "DOUBLE"),
        ("m15_high_spike_pct", "DOUBLE"),
        ("m30_high_spike_pct", "DOUBLE"),
        ("m60_high_spike_pct", "DOUBLE"),
        ("m180_high_spike_pct", "DOUBLE"),
        # Tier 2 - Low Spikes
        ("m1_low_spike_pct", "DOUBLE"),
        ("m5_low_spike_pct", "DOUBLE"),
        ("m15_low_spike_pct", "DOUBLE"),
        ("m30_low_spike_pct", "DOUBLE"),
        ("m60_low_spike_pct", "DOUBLE"),
        ("m180_low_spike_pct", "DOUBLE"),
        # Tier 3 - Returns
        ("return_m15_to_close", "DOUBLE"),
        ("return_m30_to_close", "DOUBLE"),
        ("return_m60_to_close", "DOUBLE"),
        # Missing Core Columns
        ("low_spike_pct", "DOUBLE"),
        ("rth_fade_to_close_pct", "DOUBLE"),
        ("open_lt_vwap", "BOOLEAN"),
        ("m15_return_pct", "DOUBLE"),
        ("m30_return_pct", "DOUBLE"),
        ("m60_return_pct", "DOUBLE"),
        ("close_lt_m15", "BOOLEAN"),
        ("close_lt_m30", "BOOLEAN"),
        ("close_lt_m60", "BOOLEAN"),
        ("hod_time", "VARCHAR"),
        ("lod_time", "VARCHAR"),
        ("close_direction", "VARCHAR")
    ]
    
    for col_name, col_type in columns_to_add:
        try:
            print(f"Adding column {col_name}...")
            con.execute(f"ALTER TABLE daily_metrics ADD COLUMN {col_name} {col_type}")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"Column {col_name} already exists. Skipping.")
            else:
                print(f"Error adding {col_name}: {e}")
                
    con.close()
    print("✅ Schema sync complete!")

if __name__ == "__main__":
    migrate_schema()
