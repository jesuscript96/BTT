"""
Tests for NEW Tier 1 Metrics using REAL data.
Tests: prev_close, pmh_gap_pct, rth_range_pct, day_return_pct, pm_high_time
"""
import pytest
import pandas as pd
from tests.utils.db_helpers import execute_and_validate_query


class TestPrevClose:
    """Tests for Previous Day Close calculation"""
    
    def test_prev_close_exists(self, real_db, sample_tickers):
        """Test: prev_close column is populated"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        query = """
            SELECT date, prev_close, rth_close
            FROM daily_metrics
            WHERE ticker = ?
            AND prev_close IS NOT NULL
            ORDER BY date ASC
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query, [ticker])
        
        if not df.empty and len(df) > 1:
            # For second day onwards, prev_close should match previous day's rth_close
            for i in range(1, len(df)):
                if pd.notna(df.iloc[i]['prev_close']) and pd.notna(df.iloc[i-1]['rth_close']):
                    assert abs(df.iloc[i]['prev_close'] - df.iloc[i-1]['rth_close']) < 0.01, \
                        f"Day {i}: prev_close should match previous day's rth_close"


class TestPMHGapPct:
    """Tests for PMH Gap % calculation"""
    
    def test_pmh_gap_formula(self, real_db, sample_tickers):
        """Test: pmh_gap_pct = ((pmh - prev_close) / prev_close) * 100"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        query = """
            SELECT pm_high, prev_close, pmh_gap_pct
            FROM daily_metrics
            WHERE ticker = ?
            AND prev_close IS NOT NULL
            AND pm_high > 0
            AND pmh_gap_pct IS NOT NULL
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query, [ticker])
        
        if not df.empty:
            for _, row in df.iterrows():
                pm_high = row['pm_high']
                prev_close = row['prev_close']
                pmh_gap_pct = row['pmh_gap_pct']
                
                expected = ((pm_high - prev_close) / prev_close) * 100
                assert abs(pmh_gap_pct - expected) < 0.01, \
                    f"PMH Gap % should be {expected:.2f}%, got {pmh_gap_pct:.2f}%"
    
    def test_pmh_gap_positive_when_pm_high_above_prev_close(self, real_db):
        """Test: pmh_gap_pct > 0 when pm_high > prev_close"""
        query = """
            SELECT pmh_gap_pct, pm_high, prev_close
            FROM daily_metrics
            WHERE prev_close IS NOT NULL
            AND pm_high > prev_close
            LIMIT 5
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            assert all(df['pmh_gap_pct'] > 0), "PMH Gap % should be positive when PM High > Prev Close"


class TestRTHRangePct:
    """Tests for RTH Range % calculation"""
    
    def test_rth_range_formula(self, real_db):
        """Test: rth_range_pct = ((hod - lod) / lod) * 100"""
        query = """
            SELECT rth_high, rth_low, rth_range_pct
            FROM daily_metrics
            WHERE rth_low > 0
            AND rth_range_pct IS NOT NULL
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            for _, row in df.iterrows():
                hod = row['rth_high']
                lod = row['rth_low']
                rth_range = row['rth_range_pct']
                
                expected = ((hod - lod) / lod) * 100
                assert abs(rth_range - expected) < 0.01, \
                    f"RTH Range % should be {expected:.2f}%, got {rth_range:.2f}%"
    
    def test_rth_range_always_positive(self, real_db):
        """Test: rth_range_pct should always be >= 0 (HOD >= LOD)"""
        query = """
            SELECT rth_range_pct
            FROM daily_metrics
            WHERE rth_range_pct IS NOT NULL
            LIMIT 100
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            assert all(df['rth_range_pct'] >= 0), "RTH Range % should always be non-negative"


class TestDayReturnPct:
    """Tests for Day Return % calculation"""
    
    def test_day_return_formula(self, real_db):
        """Test: day_return_pct = ((close - open) / open) * 100"""
        query = """
            SELECT rth_open, rth_close, day_return_pct
            FROM daily_metrics
            WHERE rth_open > 0
            AND day_return_pct IS NOT NULL
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            for _, row in df.iterrows():
                rth_open = row['rth_open']
                rth_close = row['rth_close']
                day_return = row['day_return_pct']
                
                expected = ((rth_close - rth_open) / rth_open) * 100
                assert abs(day_return - expected) < 0.01, \
                    f"Day Return % should be {expected:.2f}%, got {day_return:.2f}%"
    
    def test_day_return_positive_for_green_days(self, real_db):
        """Test: day_return_pct > 0 when close > open"""
        query = """
            SELECT day_return_pct, rth_close, rth_open
            FROM daily_metrics
            WHERE rth_close > rth_open
            AND day_return_pct IS NOT NULL
            LIMIT 5
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            assert all(df['day_return_pct'] > 0), "Day Return % should be positive for green days"
    
    def test_day_return_negative_for_red_days(self, real_db):
        """Test: day_return_pct < 0 when close < open"""
        query = """
            SELECT day_return_pct, rth_close, rth_open
            FROM daily_metrics
            WHERE rth_close < rth_open
            AND day_return_pct IS NOT NULL
            LIMIT 5
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            assert all(df['day_return_pct'] < 0), "Day Return % should be negative for red days"


class TestPMHighTime:
    """Tests for PM High Time"""
    
    def test_pm_high_time_format(self, real_db):
        """Test: pm_high_time is in HH:MM format"""
        query = """
            SELECT pm_high_time
            FROM daily_metrics
            WHERE pm_high_time IS NOT NULL
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            import re
            time_pattern = re.compile(r'^\d{2}:\d{2}$')
            for time_str in df['pm_high_time']:
                assert time_pattern.match(time_str), \
                    f"PM High Time should be in HH:MM format, got {time_str}"
    
    def test_pm_high_time_in_pm_session(self, real_db):
        """Test: pm_high_time should be between 04:00 and 09:30"""
        query = """
            SELECT pm_high_time
            FROM daily_metrics
            WHERE pm_high_time IS NOT NULL
            AND pm_high_time != '00:00'
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            for time_str in df['pm_high_time']:
                hour, minute = map(int, time_str.split(':'))
                total_minutes = hour * 60 + minute
                
                # PM session: 04:00 (240 min) to 09:29 (569 min)
                assert 240 <= total_minutes <= 569, \
                    f"PM High Time {time_str} should be in PM session (04:00 - 09:29)"
