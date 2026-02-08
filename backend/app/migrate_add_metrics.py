"""
Database Migration Script: Add Missing Metrics Columns
Adds 20 new columns to daily_metrics table for complete metric coverage.
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)

# Load environment variables
load_dotenv()

from app.database import get_db_connection


def migrate_add_new_metrics():
    """
    Add new metric columns to daily_metrics table.
    Safe to run multiple times (uses IF NOT EXISTS).
    """
    con = get_db_connection()
    
    print("Starting migration: Adding new metric columns...")
    
    # Tier 1: Simple calculated metrics
    print("\n[1/3] Adding Tier 1 columns (simple calculations)...")
    
    con.execute("ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS prev_close DOUBLE")
    print("  ✓ prev_close")
    
    con.execute("ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS pmh_gap_pct DOUBLE")
    print("  ✓ pmh_gap_pct")
    
    con.execute("ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS rth_range_pct DOUBLE")
    print("  ✓ rth_range_pct")
    
    con.execute("ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS day_return_pct DOUBLE")
    print("  ✓ day_return_pct")
    
    con.execute("ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS pm_high_time VARCHAR")
    print("  ✓ pm_high_time")
    
    # Tier 2: M(x) High Spike metrics
    print("\n[2/3] Adding Tier 2 columns (M(x) metrics)...")
    
    mx_times = ['m1', 'm5', 'm15', 'm30', 'm60', 'm180']
    
    for mx in mx_times:
        con.execute(f"ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS {mx}_high_spike_pct DOUBLE")
        print(f"  ✓ {mx}_high_spike_pct")
    
    # Tier 2: M(x) Low Spike metrics
    for mx in mx_times:
        con.execute(f"ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS {mx}_low_spike_pct DOUBLE")
        print(f"  ✓ {mx}_low_spike_pct")
    
    # Tier 3: Return from M(x) to Close
    print("\n[3/3] Adding Tier 3 columns (Return M(x) to Close)...")
    
    con.execute("ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS return_m15_to_close DOUBLE")
    print("  ✓ return_m15_to_close")
    
    con.execute("ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS return_m30_to_close DOUBLE")
    print("  ✓ return_m30_to_close")
    
    con.execute("ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS return_m60_to_close DOUBLE")
    print("  ✓ return_m60_to_close")
    
    con.close()
    
    print("\n✅ Migration completed successfully!")
    print("   Total columns added: 20")
    print("   - Tier 1: 5 columns")
    print("   - Tier 2: 12 columns")
    print("   - Tier 3: 3 columns")


def verify_migration():
    """Verify that all new columns exist in the table"""
    con = get_db_connection(read_only=True)
    
    print("\nVerifying migration...")
    
    # Get table schema
    schema = con.execute("DESCRIBE daily_metrics").fetchall()
    column_names = [row[0] for row in schema]
    
    # Expected new columns
    expected_columns = [
        'prev_close', 'pmh_gap_pct', 'rth_range_pct', 'day_return_pct', 'pm_high_time',
        'm1_high_spike_pct', 'm5_high_spike_pct', 'm15_high_spike_pct', 
        'm30_high_spike_pct', 'm60_high_spike_pct', 'm180_high_spike_pct',
        'm1_low_spike_pct', 'm5_low_spike_pct', 'm15_low_spike_pct',
        'm30_low_spike_pct', 'm60_low_spike_pct', 'm180_low_spike_pct',
        'return_m15_to_close', 'return_m30_to_close', 'return_m60_to_close'
    ]
    
    missing = []
    for col in expected_columns:
        if col in column_names:
            print(f"  ✓ {col}")
        else:
            print(f"  ✗ {col} - MISSING")
            missing.append(col)
    
    con.close()
    
    if missing:
        print(f"\n❌ Verification failed! Missing columns: {missing}")
        return False
    else:
        print(f"\n✅ Verification passed! All 20 columns present.")
        return True


if __name__ == "__main__":
    try:
        migrate_add_new_metrics()
        verify_migration()
    except Exception as e:
        print(f"\n❌ Migration failed with error:")
        print(f"   {type(e).__name__}: {e}")
        sys.exit(1)
