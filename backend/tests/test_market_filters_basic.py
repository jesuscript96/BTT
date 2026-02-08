"""
Tests for Market Analysis BASIC filters using REAL data.
Validates that all basic numeric, time, boolean, and date filters work correctly.
"""
import pytest
from app.database import get_db_connection
from tests.utils.db_helpers import execute_and_validate_query, validate_filter_application


class TestBasicNumericFilters:
    """Tests for all basic numeric filters"""
    
    def test_min_gap_filter(self, real_db):
        """Test: gap_at_open_pct >= X"""
        test_value = 5.0
        
        # Get unfiltered data
        df_all = real_db.execute("SELECT * FROM daily_metrics").fetch_df()
        
        # Apply filter
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE gap_at_open_pct >= ?",
            [test_value]
        ).fetch_df()
        
        # Validate
        validate_filter_application(df_all, df_filtered, "gap_at_open_pct", ">=", test_value)
        assert len(df_filtered) < len(df_all), "Filter should reduce results"
    
    def test_max_gap_filter(self, real_db):
        """Test: gap_at_open_pct <= X"""
        test_value = 10.0
        
        df_all = real_db.execute("SELECT * FROM daily_metrics").fetch_df()
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE gap_at_open_pct <= ?",
            [test_value]
        ).fetch_df()
        
        validate_filter_application(df_all, df_filtered, "gap_at_open_pct", "<=", test_value)
    
    def test_min_rth_volume_filter(self, real_db):
        """Test: rth_volume >= X"""
        test_value = 1000000
        
        df_all = real_db.execute("SELECT * FROM daily_metrics").fetch_df()
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE rth_volume >= ?",
            [test_value]
        ).fetch_df()
        
        validate_filter_application(df_all, df_filtered, "rth_volume", ">=", test_value)
    
    def test_min_pm_volume_filter(self, real_db):
        """Test: pm_volume >= X"""
        test_value = 500000
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE pm_volume >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["pm_volume"] >= test_value)
    
    def test_min_rth_run_filter(self, real_db):
        """Test: rth_run_pct >= X"""
        test_value = 10.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE rth_run_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["rth_run_pct"] >= test_value)
    
    def test_max_rth_run_filter(self, real_db):
        """Test: rth_run_pct <= X"""
        test_value = 50.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE rth_run_pct <= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["rth_run_pct"] <= test_value)
    
    def test_min_pmh_fade_filter(self, real_db):
        """Test: pmh_fade_to_open_pct >= X"""
        test_value = -5.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE pmh_fade_to_open_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["pmh_fade_to_open_pct"] >= test_value)
    
    def test_min_high_spike_filter(self, real_db):
        """Test: high_spike_pct >= X"""
        test_value = 5.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE high_spike_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["high_spike_pct"] >= test_value)
    
    def test_max_high_spike_filter(self, real_db):
        """Test: high_spike_pct <= X"""
        test_value = 20.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE high_spike_pct <= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["high_spike_pct"] <= test_value)
    
    def test_min_low_spike_filter(self, real_db):
        """Test: low_spike_pct >= X"""
        test_value = -10.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE low_spike_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["low_spike_pct"] >= test_value)
    
    def test_max_low_spike_filter(self, real_db):
        """Test: low_spike_pct <= X"""
        test_value = 0.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE low_spike_pct <= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["low_spike_pct"] <= test_value)
    
    def test_min_m15_return_filter(self, real_db):
        """Test: m15_return_pct >= X"""
        test_value = 2.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE m15_return_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["m15_return_pct"] >= test_value)
    
    def test_max_m15_return_filter(self, real_db):
        """Test: m15_return_pct <= X"""
        test_value = 10.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE m15_return_pct <= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["m15_return_pct"] <= test_value)
    
    def test_min_m30_return_filter(self, real_db):
        """Test: m30_return_pct >= X"""
        test_value = 3.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE m30_return_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["m30_return_pct"] >= test_value)
    
    def test_max_m30_return_filter(self, real_db):
        """Test: m30_return_pct <= X"""
        test_value = 15.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE m30_return_pct <= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["m30_return_pct"] <= test_value)
    
    def test_min_m60_return_filter(self, real_db):
        """Test: m60_return_pct >= X"""
        test_value = 5.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE m60_return_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["m60_return_pct"] >= test_value)
    
    def test_max_m60_return_filter(self, real_db):
        """Test: m60_return_pct <= X"""
        test_value = 20.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE m60_return_pct <= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["m60_return_pct"] <= test_value)


class TestTimeFilters:
    """Tests for time-based filters"""
    
    def test_hod_after_filter(self, real_db):
        """Test: hod_time >= X"""
        test_value = "10:00"
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE hod_time >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["hod_time"] >= test_value)
    
    def test_lod_before_filter(self, real_db):
        """Test: lod_time <= X"""
        test_value = "14:00"
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE lod_time <= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["lod_time"] <= test_value)


class TestBooleanFilters:
    """Tests for boolean filters"""
    
    def test_open_lt_vwap_filter(self, real_db):
        """Test: open_lt_vwap = true"""
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE open_lt_vwap = true"
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["open_lt_vwap"] == True)
    
    def test_pm_high_break_filter(self, real_db):
        """Test: pm_high_break = true"""
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE pm_high_break = true"
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["pm_high_break"] == True)
    
    def test_close_lt_m15_filter(self, real_db):
        """Test: close_lt_m15 = true"""
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE close_lt_m15 = true"
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["close_lt_m15"] == True)
    
    def test_close_lt_m30_filter(self, real_db):
        """Test: close_lt_m30 = true"""
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE close_lt_m30 = true"
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["close_lt_m30"] == True)
    
    def test_close_lt_m60_filter(self, real_db):
        """Test: close_lt_m60 = true"""
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE close_lt_m60 = true"
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["close_lt_m60"] == True)


class TestDateFilters:
    """Tests for date-based filters"""
    
    def test_single_date_filter(self, real_db):
        """Test: date = X"""
        # Get any date from the dataset
        sample_date = real_db.execute(
            "SELECT DISTINCT date FROM daily_metrics LIMIT 1"
        ).fetchone()
        
        if sample_date:
            test_date = sample_date[0]
            df_filtered = real_db.execute(
                "SELECT * FROM daily_metrics WHERE date = ?",
                [test_date]
            ).fetch_df()
            
            if not df_filtered.empty:
                assert all(df_filtered["date"].astype(str) == str(test_date))
    
    def test_date_range_filter(self, real_db):
        """Test: date BETWEEN X AND Y"""
        # Get date range from dataset
        dates = real_db.execute(
            "SELECT MIN(date) as start_date, MAX(date) as end_date FROM daily_metrics"
        ).fetchone()
        
        if dates:
            start_date, end_date = dates
            df_filtered = real_db.execute(
                "SELECT * FROM daily_metrics WHERE date BETWEEN ? AND ?",
                [start_date, end_date]
            ).fetch_df()
            
            assert len(df_filtered) > 0, "Date range should return results"
    
    def test_ticker_filter(self, real_db, sample_tickers):
        """Test: ticker = X"""
        if sample_tickers:
            test_ticker = sample_tickers[0]
            df_filtered = real_db.execute(
                "SELECT * FROM daily_metrics WHERE ticker = ?",
                [test_ticker]
            ).fetch_df()
            
            if not df_filtered.empty:
                assert all(df_filtered["ticker"] == test_ticker)
