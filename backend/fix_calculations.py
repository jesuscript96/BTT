#!/usr/bin/env python3
"""
Fix Calculations Script
Recalculates gap_at_open_pct, pmh_gap_pct, and rth_run_pct using correct formulas.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import get_db_connection

def main():
    print("🔧 Starting calculation fixes...")
    print()
    
    con = get_db_connection()
    
    try:
        # Part 1: Fix RTH Run %
        print("📊 Part 1: Fixing RTH Run % (using HOD instead of Close)...")
        con.execute("""
            UPDATE daily_metrics
            SET rth_run_pct = ((rth_high - rth_open) / rth_open * 100)
            WHERE rth_open > 0
        """)
        print("   ✅ RTH Run % updated")
        print()
        
        # Part 2: Fix Gap Calculations
        print("📊 Part 2: Fixing Gap Calculations (using prev_close from daily data)...")
        
        # Step 1: Create temp table
        print("   - Creating temporary table with prev_close...")
        con.execute("""
            CREATE TEMP TABLE daily_with_prev AS
            SELECT 
                curr.ticker,
                curr.date,
                curr.rth_open,
                curr.pm_high,
                prev.rth_close as prev_close_actual
            FROM daily_metrics curr
            LEFT JOIN daily_metrics prev 
                ON curr.ticker = prev.ticker 
                AND prev.date = curr.date - INTERVAL 1 DAY
        """)
        print("   ✅ Temp table created")
        
        # Step 2: Update gap_at_open_pct
        print("   - Updating gap_at_open_pct...")
        con.execute("""
            UPDATE daily_metrics
            SET gap_at_open_pct = (
                SELECT ((d.rth_open - d.prev_close_actual) / d.prev_close_actual * 100)
                FROM daily_with_prev d
                WHERE d.ticker = daily_metrics.ticker 
                AND d.date = daily_metrics.date
            )
            WHERE EXISTS (
                SELECT 1 FROM daily_with_prev d
                WHERE d.ticker = daily_metrics.ticker 
                AND d.date = daily_metrics.date
                AND d.prev_close_actual IS NOT NULL
                AND d.prev_close_actual > 0
            )
        """)
        print("   ✅ gap_at_open_pct updated")
        
        # Step 3: Update pmh_gap_pct
        print("   - Updating pmh_gap_pct...")
        con.execute("""
            UPDATE daily_metrics
            SET pmh_gap_pct = (
                SELECT ((d.pm_high - d.prev_close_actual) / d.prev_close_actual * 100)
                FROM daily_with_prev d
                WHERE d.ticker = daily_metrics.ticker 
                AND d.date = daily_metrics.date
            )
            WHERE EXISTS (
                SELECT 1 FROM daily_with_prev d
                WHERE d.ticker = daily_metrics.ticker 
                AND d.date = daily_metrics.date
                AND d.prev_close_actual IS NOT NULL
                AND d.prev_close_actual > 0
                AND d.pm_high > 0
            )
        """)
        print("   ✅ pmh_gap_pct updated")
        
        # Step 4: Update prev_close column
        print("   - Updating prev_close column...")
        con.execute("""
            UPDATE daily_metrics
            SET prev_close = (
                SELECT d.prev_close_actual
                FROM daily_with_prev d
                WHERE d.ticker = daily_metrics.ticker 
                AND d.date = daily_metrics.date
            )
            WHERE EXISTS (
                SELECT 1 FROM daily_with_prev d
                WHERE d.ticker = daily_metrics.ticker 
                AND d.date = daily_metrics.date
                AND d.prev_close_actual IS NOT NULL
            )
        """)
        print("   ✅ prev_close updated")
        
        # Clean up
        print("   - Cleaning up temp table...")
        con.execute("DROP TABLE daily_with_prev")
        print("   ✅ Cleanup complete")
        print()
        
        # Verification
        print("📊 Verification: Sample of corrected data")
        print()
        result = con.execute("""
            SELECT 
                ticker,
                date,
                rth_open,
                rth_high,
                rth_close,
                prev_close,
                gap_at_open_pct,
                rth_run_pct,
                pmh_gap_pct
            FROM daily_metrics
            WHERE ticker IN ('AAPL', 'TSLA', 'NVDA')
            ORDER BY ticker, date DESC
            LIMIT 15
        """).fetch_df()
        
        print(result.to_string())
        print()
        print("✅ All calculations fixed successfully!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        con.close()

if __name__ == "__main__":
    main()
