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
            "SELECT AVG(gap_at_open_pct) as avg_gap FROM daily_metrics"
        ).fetchone()[0]
        
        # Python validation
        df = real_db.execute("SELECT gap_at_open_pct FROM daily_metrics").fetch_df()
        python_avg = df["gap_at_open_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(gap_at_open_pct)")
    
    def test_avg_pmh_fade_to_open_pct(self, real_db):
        """Test: AVG(pmh_fade_to_open_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(pmh_fade_to_open_pct) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT pmh_fade_to_open_pct FROM daily_metrics").fetch_df()
        python_avg = df["pmh_fade_to_open_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(pmh_fade_to_open_pct)")
    
    def test_avg_rth_run_pct(self, real_db):
        """Test: AVG(rth_run_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(rth_run_pct) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT rth_run_pct FROM daily_metrics").fetch_df()
        python_avg = df["rth_run_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(rth_run_pct)")
    
    def test_avg_rth_fade_to_close_pct(self, real_db):
        """Test: AVG(rth_fade_to_close_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(rth_fade_to_close_pct) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT rth_fade_to_close_pct FROM daily_metrics").fetch_df()
        python_avg = df["rth_fade_to_close_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(rth_fade_to_close_pct)")
    
    def test_avg_high_spike_pct(self, real_db):
        """Test: AVG(high_spike_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(high_spike_pct) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT high_spike_pct FROM daily_metrics").fetch_df()
        python_avg = df["high_spike_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(high_spike_pct)")
    
    def test_avg_low_spike_pct(self, real_db):
        """Test: AVG(low_spike_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(low_spike_pct) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT low_spike_pct FROM daily_metrics").fetch_df()
        python_avg = df["low_spike_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(low_spike_pct)")
    
    def test_avg_m15_return_pct(self, real_db):
        """Test: AVG(m15_return_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(m15_return_pct) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT m15_return_pct FROM daily_metrics").fetch_df()
        python_avg = df["m15_return_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(m15_return_pct)")
    
    def test_avg_m30_return_pct(self, real_db):
        """Test: AVG(m30_return_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(m30_return_pct) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT m30_return_pct FROM daily_metrics").fetch_df()
        python_avg = df["m30_return_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(m30_return_pct)")
    
    def test_avg_m60_return_pct(self, real_db):
        """Test: AVG(m60_return_pct) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(m60_return_pct) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT m60_return_pct FROM daily_metrics").fetch_df()
        python_avg = df["m60_return_pct"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(m60_return_pct)")


class TestVolumeCalculations:
    """Tests for volume-based calculations"""
    
    def test_avg_rth_volume(self, real_db):
        """Test: AVG(rth_volume) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(rth_volume) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT rth_volume FROM daily_metrics").fetch_df()
        python_avg = df["rth_volume"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(rth_volume)")
    
    def test_avg_pm_volume(self, real_db):
        """Test: AVG(pm_volume) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(pm_volume) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT pm_volume FROM daily_metrics").fetch_df()
        python_avg = df["pm_volume"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(pm_volume)")


class TestPriceCalculations:
    """Tests for price-based calculations"""
    
    def test_avg_pm_high(self, real_db):
        """Test: AVG(pm_high) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(pm_high) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT pm_high FROM daily_metrics").fetch_df()
        python_avg = df["pm_high"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(pm_high)")
    
    def test_avg_rth_open(self, real_db):
        """Test: AVG(rth_open) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(rth_open) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT rth_open FROM daily_metrics").fetch_df()
        python_avg = df["rth_open"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(rth_open)")
    
    def test_avg_rth_close(self, real_db):
        """Test: AVG(rth_close) calculation"""
        sql_avg = real_db.execute(
            "SELECT AVG(rth_close) as avg FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT rth_close FROM daily_metrics").fetch_df()
        python_avg = df["rth_close"].mean()
        
        compare_calculation_methods(sql_avg, python_avg, description="AVG(rth_close)")


class TestBooleanToPercentageConversions:
    """Tests for boolean to percentage conversions"""
    
    def test_open_lt_vwap_percentage(self, real_db):
        """Test: AVG(CAST(open_lt_vwap AS INT)) * 100"""
        sql_pct = real_db.execute(
            "SELECT AVG(CAST(open_lt_vwap AS INT)) * 100 as pct FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT open_lt_vwap FROM daily_metrics").fetch_df()
        python_pct = df["open_lt_vwap"].astype(int).mean() * 100
        
        compare_calculation_methods(sql_pct, python_pct, description="open_lt_vwap percentage")
    
    def test_pm_high_break_percentage(self, real_db):
        """Test: AVG(CAST(pm_high_break AS INT)) * 100"""
        sql_pct = real_db.execute(
            "SELECT AVG(CAST(pm_high_break AS INT)) * 100 as pct FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT pm_high_break FROM daily_metrics").fetch_df()
        python_pct = df["pm_high_break"].astype(int).mean() * 100
        
        compare_calculation_methods(sql_pct, python_pct, description="pm_high_break percentage")
    
    def test_close_lt_m15_percentage(self, real_db):
        """Test: AVG(CAST(close_lt_m15 AS INT)) * 100"""
        sql_pct = real_db.execute(
            "SELECT AVG(CAST(close_lt_m15 AS INT)) * 100 as pct FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT close_lt_m15 FROM daily_metrics").fetch_df()
        python_pct = df["close_lt_m15"].astype(int).mean() * 100
        
        compare_calculation_methods(sql_pct, python_pct, description="close_lt_m15 percentage")
    
    def test_close_lt_m30_percentage(self, real_db):
        """Test: AVG(CAST(close_lt_m30 AS INT)) * 100"""
        sql_pct = real_db.execute(
            "SELECT AVG(CAST(close_lt_m30 AS INT)) * 100 as pct FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT close_lt_m30 FROM daily_metrics").fetch_df()
        python_pct = df["close_lt_m30"].astype(int).mean() * 100
        
        compare_calculation_methods(sql_pct, python_pct, description="close_lt_m30 percentage")
    
    def test_close_lt_m60_percentage(self, real_db):
        """Test: AVG(CAST(close_lt_m60 AS INT)) * 100"""
        sql_pct = real_db.execute(
            "SELECT AVG(CAST(close_lt_m60 AS INT)) * 100 as pct FROM daily_metrics"
        ).fetchone()[0]
        
        df = real_db.execute("SELECT close_lt_m60 FROM daily_metrics").fetch_df()
        python_pct = df["close_lt_m60"].astype(int).mean() * 100
        
        compare_calculation_methods(sql_pct, python_pct, description="close_lt_m60 percentage")
    
    def test_close_direction_red(self, real_db):
        """Test: AVG(CASE WHEN rth_close < rth_open THEN 1 ELSE 0 END) * 100"""
        sql_pct = real_db.execute("""
            SELECT AVG(CASE WHEN rth_close < rth_open THEN 1 ELSE 0 END) * 100 as pct 
            FROM daily_metrics
        """).fetchone()[0]
        
        df = real_db.execute("SELECT rth_close, rth_open FROM daily_metrics").fetch_df()
        python_pct = (df["rth_close"] < df["rth_open"]).astype(int).mean() * 100
        
        compare_calculation_methods(sql_pct, python_pct, description="close direction red percentage")


class TestDistributionCalculations:
    """Tests for distribution calculations"""
    
    def test_hod_time_distribution(self, real_db):
        """Test: GROUP BY hod_time with COUNT"""
        # SQL calculation
        sql_dist = real_db.execute("""
            SELECT hod_time, COUNT(*) as count
            FROM daily_metrics
            GROUP BY hod_time
            ORDER BY count DESC
            LIMIT 5
        """).fetch_df()
        
        # Python validation
        df = real_db.execute("SELECT hod_time FROM daily_metrics").fetch_df()
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
            FROM daily_metrics
            GROUP BY lod_time
            ORDER BY count DESC
            LIMIT 5
        """).fetch_df()
        
        df = real_db.execute("SELECT lod_time FROM daily_metrics").fetch_df()
        python_dist = df["lod_time"].value_counts().head(5)
        
        assert len(sql_dist) > 0, "Should have distribution results"
        for _, row in sql_dist.iterrows():
            time_val = row["lod_time"]
            sql_count = row["count"]
            python_count = python_dist.get(time_val, 0)
            
            assert sql_count == python_count, f"Count mismatch for {time_val}"


class TestAggregateIntradayCalculations:
    """Tests for aggregate intraday calculations (joined with historical_data)"""
    
    def test_aggregate_avg_change(self, real_db, sample_tickers):
        """Test: AVG((close - rth_open) / rth_open * 100) with join"""
        if not sample_tickers:
            pytest.skip("No sample tickers available")
        
        ticker = sample_tickers[0]
        
        # SQL calculation (simplified for one ticker/date)
        result = real_db.execute("""
            WITH sample_data AS (
                SELECT ticker, date, rth_open
                FROM daily_metrics
                WHERE ticker = ?
                LIMIT 1
            )
            SELECT AVG((h.close - s.rth_open) / s.rth_open * 100) as avg_change
            FROM historical_data h
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
                FROM daily_metrics
                WHERE ticker = ?
                LIMIT 1
            )
            SELECT MEDIAN((h.close - s.rth_open) / s.rth_open * 100) as median_change
            FROM historical_data h
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
            FROM historical_data
            WHERE ticker = ?
            GROUP BY time_bucket
            ORDER BY time_bucket
            LIMIT 10
        """, [ticker]).fetch_df()
        
        assert not result.empty, "Should have time-grouped results"
        assert "time_bucket" in result.columns
        assert all(result["count"] > 0)
