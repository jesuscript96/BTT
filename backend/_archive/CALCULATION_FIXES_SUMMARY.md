# Calculation Corrections Summary

## Changes Implemented

### ✅ Code Changes

1. **`processor.py` (Line 133)** - Fixed RTH Run calculation:
   ```python
   # BEFORE: 'rth_run_pct': float(((rth_close - rth_open) / rth_open) * 100)
   # AFTER:  'rth_run_pct': float(((rth_high - rth_open) / rth_open) * 100)
   ```

2. **`processor.py` (Lines 5-11, 40-56)** - Fixed gap calculation:
   - Updated function signature to accept database connection
   - Modified gap calculation to query `prev_close` from `daily_metrics` table
   - Removed loop-based `prev_close` inference

3. **`ingestion.py` (Line 289)** - Pass connection to processor:
   ```python
   daily_metrics_df = process_daily_metrics(final_df, con=local_con)
   ```

### 📝 Scripts Created

1. **`fix_calculations.sql`** - SQL script for recalculation
2. **`fix_calculations.py`** - Python wrapper to execute SQL

---

## Next Steps

### To Recalculate Existing Data:

**Option 1: Using Python script (RECOMMENDED)**
```bash
cd /Users/jvch/Desktop/AutomatoWebs/BTT/backend
# Activate your Python environment first, then:
python3 fix_calculations.py
```

**Option 2: Manual SQL execution**
```bash
# Execute the SQL file directly against MotherDuck
```

---

## What Was Fixed

### 🔴 RTH Run %
- **Before**: Measured open-to-close (same as Day Return)
- **After**: Measures open-to-HOD (maximum upside)
- **Impact**: Now correctly captures volatility/spike potential

### 🔴 Gap Calculations
- **Before**: Inferred `prev_close` from loop (unreliable)
- **After**: Queries `prev_close` from `daily_metrics` table
- **Impact**: Accurate gaps even with missing data

---

## Verification

After running the recalculation script, verify with:

```sql
SELECT 
    ticker,
    date,
    rth_open,
    rth_high,
    rth_close,
    prev_close,
    gap_at_open_pct,
    rth_run_pct
FROM daily_metrics
WHERE ticker = 'AAPL'
ORDER BY date DESC
LIMIT 10;
```

Check that:
- `rth_run_pct` = `((rth_high - rth_open) / rth_open) * 100`
- `gap_at_open_pct` = `((rth_open - prev_close) / prev_close) * 100`
