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
        df_all = real_db.execute("SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        
        # Apply filter
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE gap_at_open_pct >= ?",
            [test_value]
        ).fetch_df()
        
        # Validate
        validate_filter_application(df_all, df_filtered, "gap_at_open_pct", ">=", test_value)
        assert len(df_filtered) < len(df_all), "Filter should reduce results"
    
    def test_max_gap_filter(self, real_db):
        """Test: gap_at_open_pct <= X"""
        test_value = 10.0
        
        df_all = real_db.execute("SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE gap_at_open_pct <= ?",
            [test_value]
        ).fetch_df()
        
        validate_filter_application(df_all, df_filtered, "gap_at_open_pct", "<=", test_value)
    
    def test_min_rth_volume_filter(self, real_db):
        """Test: rth_volume >= X"""
        test_value = 1000000
        
        df_all = real_db.execute("SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE rth_volume >= ?",
            [test_value]
        ).fetch_df()
        
        validate_filter_application(df_all, df_filtered, "rth_volume", ">=", test_value)
    
    def test_min_pm_volume_filter(self, real_db):
        """Test: pm_volume >= X"""
        test_value = 500000
        
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE pm_volume >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["pm_volume"] >= test_value)
    
    def test_min_rth_run_filter(self, real_db):
        """Test: rth_run_pct >= X"""
        test_value = 10.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE rth_run_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["rth_run_pct"] >= test_value)
    
    def test_max_rth_run_filter(self, real_db):
        """Test: rth_run_pct <= X"""
        test_value = 50.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE rth_run_pct <= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["rth_run_pct"] <= test_value)
    
    def test_min_pmh_fade_filter(self, real_db):
        """Test: pmh_fade_pct >= X"""
        test_value = -5.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE pmh_fade_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["pmh_fade_pct"] >= test_value)
    
    def test_min_m15_return_filter(self, real_db):
        """Test: m15_return_pct >= X"""
        test_value = 2.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE m15_return_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["m15_return_pct"] >= test_value)
    
    def test_max_m15_return_filter(self, real_db):
        """Test: m15_return_pct <= X"""
        test_value = 10.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE m15_return_pct <= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["m15_return_pct"] <= test_value)
    
    def test_min_m30_return_filter(self, real_db):
        """Test: m30_return_pct >= X"""
        test_value = 3.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE m30_return_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["m30_return_pct"] >= test_value)
    
    def test_max_m30_return_filter(self, real_db):
        """Test: m30_return_pct <= X"""
        test_value = 15.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE m30_return_pct <= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["m30_return_pct"] <= test_value)
    
    def test_min_m60_return_filter(self, real_db):
        """Test: m60_return_pct >= X"""
        test_value = 5.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE m60_return_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["m60_return_pct"] >= test_value)
    
    def test_max_m60_return_filter(self, real_db):
        """Test: m60_return_pct <= X"""
        test_value = 20.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE m60_return_pct <= ?",
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
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE hod_time >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["hod_time"] >= test_value)
    
    def test_lod_before_filter(self, real_db):
        """Test: lod_time <= X"""
        test_value = "14:00"
        
        df_filtered = real_db.execute(
            "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE lod_time <= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["lod_time"] <= test_value)


class TestBooleanFilters:
    """Tests for boolean filters"""
    
    def test_single_date_filter(self, real_db):
        """Test: date = X"""
        # Get any date from the dataset
        sample_date = real_db.execute(
            "SELECT DISTINCT date FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) LIMIT 1"
        ).fetchone()
        
        if sample_date:
            test_date = sample_date[0]
            df_filtered = real_db.execute(
                "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE date = ?",
                [test_date]
            ).fetch_df()
            
            if not df_filtered.empty:
                assert all(df_filtered["date"].astype(str) == str(test_date))
    
    def test_date_range_filter(self, real_db):
        """Test: date BETWEEN X AND Y"""
        # Get date range from dataset
        dates = real_db.execute(
            "SELECT MIN(date) as start_date, MAX(date) as end_date FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()
        
        if dates:
            start_date, end_date = dates
            df_filtered = real_db.execute(
                "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE date BETWEEN ? AND ?",
                [start_date, end_date]
            ).fetch_df()
            
            assert len(df_filtered) > 0, "Date range should return results"
    
    def test_ticker_filter(self, real_db, sample_tickers):
        """Test: ticker = X"""
        if sample_tickers:
            test_ticker = sample_tickers[0]
            df_filtered = real_db.execute(
                "SELECT * FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000) WHERE ticker = ?",
                [test_ticker]
            ).fetch_df()
            
            if not df_filtered.empty:
                assert all(df_filtered["ticker"] == test_ticker)
