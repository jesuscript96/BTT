-- Fix Calculations Script
-- This script recalculates gap_at_open_pct, pmh_gap_pct, and rth_run_pct
-- using correct formulas from Documentacion_calculos

-- ============================================
-- PART 1: Fix RTH Run % (Use HOD, not Close)
-- ============================================

UPDATE daily_metrics
SET rth_run_pct = ((rth_high - rth_open) / rth_open * 100)
WHERE rth_open > 0;

-- ============================================
-- PART 2: Fix Gap Calculations (Use prev_close from daily data)
-- ============================================

-- Step 1: Create temporary table with prev_close from daily_metrics
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
    AND prev.date = curr.date - INTERVAL 1 DAY;

-- Step 2: Update gap_at_open_pct
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
);

-- Step 3: Update pmh_gap_pct
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
);

-- Step 4: Update prev_close column for reference
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
);

-- Clean up
DROP TABLE daily_with_prev;

-- ============================================
-- VERIFICATION QUERIES
-- ============================================

-- Check sample of corrected data
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
LIMIT 30;
