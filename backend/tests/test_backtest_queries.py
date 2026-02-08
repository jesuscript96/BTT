"""
Tests for Backtester SQL queries using REAL data.
Validates that queries are correctly constructed and executed.
"""
import pytest
import pandas as pd
from app.database import get_db_connection
from tests.utils.db_helpers import execute_and_validate_query


class TestSavedQueryReconstruction:
    """Tests for reconstructing saved strategy queries"""
    
    def test_saved_query_min_gap(self, real_db):
        """Test: Reconstruction of min_gap_pct filter"""
        test_value = 5.0
        
        # Simulate saved query reconstruction
        query = "SELECT * FROM daily_metrics WHERE gap_at_open_pct >= ?"
        df = execute_and_validate_query(real_db, query, [test_value])
        
        if not df.empty:
            assert all(df["gap_at_open_pct"] >= test_value)
    
    def test_saved_query_max_gap(self, real_db):
        """Test: Reconstruction of max_gap_pct filter"""
        test_value = 10.0
        
        query = "SELECT * FROM daily_metrics WHERE gap_at_open_pct <= ?"
        df = execute_and_validate_query(real_db, query, [test_value])
        
        if not df.empty:
            assert all(df["gap_at_open_pct"] <= test_value)
    
    def test_saved_query_volume(self, real_db):
        """Test: Reconstruction of min_rth_volume filter"""
        test_value = 1000000
        
        query = "SELECT * FROM daily_metrics WHERE rth_volume >= ?"
        df = execute_and_validate_query(real_db, query, [test_value])
        
        if not df.empty:
            assert all(df["rth_volume"] >= test_value)
    
    def test_saved_query_dynamic_rules(self, real_db):
        """Test: Reconstruction of dynamic rules (variable comparisons)"""
        query = "SELECT * FROM daily_metrics WHERE rth_close < rth_open"
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            assert all(df["rth_close"] < df["rth_open"])


class TestJoinLogic:
    """Tests for JOIN logic between daily_metrics and historical_data"""
    
    def test_daily_historical_join(self, real_db, sample_tickers):
        """Test: Join between daily_metrics and historical_data"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        
        query = """
            SELECT d.date, d.ticker, d.rth_open, h.timestamp, h.close
            FROM daily_metrics d
            JOIN historical_data h 
                ON d.ticker = h.ticker 
                AND CAST(d.date AS TIMESTAMP) <= h.timestamp
                AND h.timestamp < CAST(d.date AS TIMESTAMP) + INTERVAL 1 DAY
            WHERE d.ticker = ?
            LIMIT 100
        """
        
        df = execute_and_validate_query(real_db, query, [ticker])
        
        if not df.empty:
            assert "date" in df.columns
            assert "timestamp" in df.columns
            # Validate that timestamps are within the date range
            for _, row in df.iterrows():
                date_val = pd.to_datetime(row["date"])
                ts_val = pd.to_datetime(row["timestamp"])
                assert ts_val >= date_val
                assert ts_val < date_val + pd.Timedelta(days=1)
    
    def test_date_casting_in_join(self, real_db, sample_tickers):
        """Test: CAST(d.date AS TIMESTAMP) works correctly"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        
        query = """
            SELECT CAST(d.date AS TIMESTAMP) as casted_date, d.date as original_date
            FROM daily_metrics d
            WHERE d.ticker = ?
            LIMIT 10
        """
        
        df = execute_and_validate_query(real_db, query, [ticker])
        
        assert not df.empty, "Should return results"
        assert "casted_date" in df.columns
        assert "original_date" in df.columns
    
    def test_interval_calculation(self, real_db, sample_tickers):
        """Test: + INTERVAL 1 DAY calculation"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        
        query = """
            SELECT date, CAST(date AS TIMESTAMP) + INTERVAL 1 DAY as next_day
            FROM daily_metrics
            WHERE ticker = ?
            LIMIT 10
        """
        
        df = execute_and_validate_query(real_db, query, [ticker])
        
        if not df.empty:
            for _, row in df.iterrows():
                date_val = pd.to_datetime(row["date"])
                next_day_val = pd.to_datetime(row["next_day"])
                diff = (next_day_val - date_val).days
                assert diff == 1, f"Next day should be 1 day after, got {diff} days"


class TestDateFiltering:
    """Tests for date filtering in backtester queries"""
    
    def test_date_from_filter(self, real_db, sample_tickers):
        """Test: h.timestamp >= CAST(? AS TIMESTAMP)"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        test_date = "2024-01-01"
        
        query = """
            SELECT * FROM historical_data
            WHERE ticker = ?
            AND timestamp >= CAST(? AS TIMESTAMP)
            LIMIT 100
        """
        
        df = execute_and_validate_query(real_db, query, [ticker, test_date])
        
        if not df.empty:
            min_timestamp = pd.to_datetime(df["timestamp"].min())
            test_timestamp = pd.to_datetime(test_date)
            assert min_timestamp >= test_timestamp
    
    def test_date_to_filter(self, real_db, sample_tickers):
        """Test: h.timestamp <= CAST(? AS TIMESTAMP)"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        test_date = "2025-12-31"
        
        query = """
            SELECT * FROM historical_data
            WHERE ticker = ?
            AND timestamp <= CAST(? AS TIMESTAMP)
            LIMIT 100
        """
        
        df = execute_and_validate_query(real_db, query, [ticker, test_date])
        
        if not df.empty:
            max_timestamp = pd.to_datetime(df["timestamp"].max())
            test_timestamp = pd.to_datetime(test_date)
            assert max_timestamp <= test_timestamp
    
    def test_ticker_filter_in_query(self, real_db, sample_tickers):
        """Test: h.ticker = ?"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        test_ticker = sample_tickers[0]
        
        query = """
            SELECT * FROM historical_data
            WHERE ticker = ?
            LIMIT 100
        """
        
        df = execute_and_validate_query(real_db, query, [test_ticker])
        
        if not df.empty:
            assert all(df["ticker"] == test_ticker)


class TestRowLimiting:
    """Tests for LIMIT clauses in queries"""
    
    def test_max_rows_limit(self, real_db):
        """Test: LIMIT is applied correctly"""
        limit = 50
        
        query = f"SELECT * FROM daily_metrics LIMIT {limit}"
        df = execute_and_validate_query(real_db, query)
        
        assert len(df) <= limit, f"Should return at most {limit} rows"
    
    def test_no_date_range_default_limit(self, real_db, sample_tickers):
        """Test: Default limit when no date range specified"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        default_limit = 100000
        
        query = f"""
            SELECT * FROM historical_data
            WHERE ticker = ?
            LIMIT {default_limit}
        """
        
        df = execute_and_validate_query(real_db, query, [ticker])
        
        assert len(df) <= default_limit, f"Should respect default limit of {default_limit}"
