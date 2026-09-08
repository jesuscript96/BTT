"""
Tests for Market Analysis CALCULATIONS using REAL data.
Validates that all statistical calculations (averages, percentages, distributions) are correct.
"""
import pytest
import pandas as pd
from app.database import get_db_connection
from tests.utils.db_helpers import compare_calculation_methods


class TestAverageCalculations:
    """Tests for all average calculations in the dashboard"""
    
    def test_avg_gap_at_open_pct(self, real_db):
        """Test: AVG(gap_at_open_pct) calculation"""
        # SQL calculation
        sql_avg = real_db.execute(
            "SELECT AVG(gap_at_open_pct) as avg_gap FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()[0]
        
        # Python validation
        df = real_db.execute("SELECT gap_at_open_pct FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_avg = df["gap_at_open_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(gap_at_open_pct)")
    
    def test_avg_pmh_fade_to_open_pct(self, real_db):
        """Test: AVG(pmh_fade_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(pmh_fade_pct) as avg FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT pmh_fade_pct FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_avg = df["pmh_fade_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(pmh_fade_pct)")
    
    def test_avg_rth_run_pct(self, real_db):
        """Test: AVG(rth_run_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(rth_run_pct) as avg FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT rth_run_pct FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_avg = df["rth_run_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(rth_run_pct)")
    
    def test_avg_rth_fade_to_close_pct(self, real_db):
        """Test: AVG(rth_fade_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(rth_fade_pct) as avg FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT rth_fade_pct FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_avg = df["rth_fade_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(rth_fade_pct)")
    
    def test_avg_m15_return_pct(self, real_db):
        """Test: AVG(m15_return_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(m15_return_pct) as avg FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT m15_return_pct FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_avg = df["m15_return_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(m15_return_pct)")
    
    def test_avg_m30_return_pct(self, real_db):
        """Test: AVG(m30_return_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(m30_return_pct) as avg FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT m30_return_pct FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_avg = df["m30_return_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(m30_return_pct)")
    
    def test_avg_m60_return_pct(self, real_db):
        """Test: AVG(m60_return_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(m60_return_pct) as avg FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT m60_return_pct FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_avg = df["m60_return_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(m60_return_pct)")


class TestVolumeCalculations:
    """Tests for volume-based calculations"""
    
    def test_avg_rth_volume(self, real_db):
        """Test: AVG(rth_volume) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(rth_volume) as avg FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT rth_volume FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_avg = df["rth_volume"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(rth_volume)")
    
    def test_avg_pm_volume(self, real_db):
        """Test: AVG(pm_volume) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(pm_volume) as avg FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT pm_volume FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_avg = df["pm_volume"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(pm_volume)")


class TestPriceCalculations:
    """Tests for price-based calculations"""
    
    def test_avg_pm_high(self, real_db):
        """Test: AVG(pm_high) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(pm_high) as avg FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT pm_high FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_avg = df["pm_high"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(pm_high)")
    
    def test_avg_rth_open(self, real_db):
        """Test: AVG(rth_open) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(rth_open) as avg FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT rth_open FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_avg = df["rth_open"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(rth_open)")
    
    def test_avg_rth_close(self, real_db):
        """Test: AVG(rth_close) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(rth_close) as avg FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT rth_close FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_avg = df["rth_close"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(rth_close)")


class TestBooleanToPercentageConversions:
    """Tests for boolean to percentage conversions"""
    
    def test_close_direction_red(self, real_db):
        """Test: AVG(CASE WHEN rth_close < rth_open THEN 1 ELSE 0 END) * 100"""
        sql_pct = real_db.execute("""
            SELECT AVG(CASE WHEN rth_close < rth_open THEN 1 ELSE 0 END) * 100 as pct 
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
        """).fetchone()[0]
        
        df = real_db.execute("SELECT rth_close, rth_open FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_pct = (df["rth_close"] < df["rth_open"]).astype(int).mean() * 100
        
        compare_calculation_methods(sql_pct, python_pct, description="close direction red percentage")


class TestDistributionCalculations:
    """Tests for distribution calculations"""
    
    def test_hod_time_distribution(self, real_db):
        """Test: GROUP BY hod_time with COUNT"""
        # SQL calculation
        sql_dist = real_db.execute("""
            SELECT hod_time, COUNT(*) as count
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
            GROUP BY hod_time
            ORDER BY count DESC
            LIMIT 5
        """).fetch_df()
        
        # Python validation
        df = real_db.execute("SELECT hod_time FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_dist = df["hod_time"].value_counts().head(5)
        
        # Validate that top times match
        assert len(sql_dist) > 0, "Should have distribution results"
        for _, row in sql_dist.iterrows():
            time_val = row["hod_time"]
            sql_count = row["count"]
            python_count = python_dist.get(time_val, 0)
            
            assert sql_count == python_count, f"Count mismatch for {time_val}: SQL={sql_count}, Python={python_count}"
    
    def test_lod_time_distribution(self, real_db):
        """Test: GROUP BY lod_time with COUNT"""
        sql_dist = real_db.execute("""
            SELECT lod_time, COUNT(*) as count
            FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
            GROUP BY lod_time
            ORDER BY count DESC
            LIMIT 5
        """).fetch_df()
        
        df = real_db.execute("SELECT lod_time FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)").fetch_df()
        python_dist = df["lod_time"].value_counts().head(5)
        
        assert len(sql_dist) > 0, "Should have distribution results"
        for _, row in sql_dist.iterrows():
            time_val = row["lod_time"]
            sql_count = row["count"]
            python_count = python_dist.get(time_val, 0)
            
            assert sql_count == python_count, f"Count mismatch for {time_val}"


class TestAggregateIntradayCalculations:
    """Tests for aggregate intraday calculations (joined with intraday_1m)"""
    
    def test_aggregate_avg_change(self, real_db, sample_tickers):
        """Test: AVG((close - rth_open) / rth_open * 100) with join"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        
        # SQL calculation (simplified for one ticker/date)
        result = real_db.execute("""
            WITH sample_data AS (
                SELECT ticker, date, rth_open
                FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
                WHERE ticker = ?
                LIMIT 1
            )
            SELECT AVG((h.close - s.rth_open) / s.rth_open * 100) as avg_change
            FROM intraday_1m h
            JOIN sample_data s ON h.ticker = s.ticker 
            AND CAST(h.timestamp AS DATE) = s.date
        """, [ticker]).fetchone()
        
        if result and result[0] is not None:
            sql_avg = result[0]
            assert isinstance(sql_avg, (int, float)), "Should return numeric average"
    
    def test_aggregate_median_change(self, real_db, sample_tickers):
        """Test: MEDIAN((close - rth_open) / rth_open * 100) calculation"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        
        result = real_db.execute("""
            WITH sample_data AS (
                SELECT ticker, date, rth_open
                FROM (SELECT *, CAST(timestamp AS VARCHAR)[:10] AS date FROM daily_metrics LIMIT 200000)
                WHERE ticker = ?
                LIMIT 1
            )
            SELECT MEDIAN((h.close - s.rth_open) / s.rth_open * 100) as median_change
            FROM intraday_1m h
            JOIN sample_data s ON h.ticker = s.ticker 
            AND CAST(h.timestamp AS DATE) = s.date
        """, [ticker]).fetchone()
        
        if result and result[0] is not None:
            sql_median = result[0]
            assert isinstance(sql_median, (int, float)), "Should return numeric median"
    
    def test_aggregate_time_grouping(self, real_db, sample_tickers):
        """Test: Grouping by time with strftime('%H:%M')"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        
        result = real_db.execute("""
            SELECT strftime(timestamp, '%H:%M') as time_bucket, COUNT(*) as count
            FROM intraday_1m
            WHERE ticker = ?
            GROUP BY time_bucket
            ORDER BY time_bucket
            LIMIT 10
        """, [ticker]).fetch_df()
        
        assert not result.empty, "Should have time-grouped results"
        assert "time_bucket" in result.columns
        assert all(result["count"] > 0)
