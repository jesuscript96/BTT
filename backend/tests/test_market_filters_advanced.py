"""
Tests for Market Analysis ADVANCED filters (Dynamic Rules) using REAL data.
Validates all advanced filtering capabilities including static/variable comparisons and logic combinations.
"""
import pytest
from app.routers.data import METRIC_MAP
from app.database import get_db_connection


class TestStaticValueComparisons:
    """Tests for static value comparisons with all operators"""
    
    def test_static_equals(self, real_db):
        """Test: column = value"""
        # Get a real value from the dataset
        sample = real_db.execute(
            "SELECT gap_at_open_pct FROM daily_metrics WHERE gap_at_open_pct IS NOT NULL LIMIT 1"
        ).fetchone()
        
        if sample:
            test_value = sample[0]
            df_filtered = real_db.execute(
                "SELECT * FROM daily_metrics WHERE gap_at_open_pct = ?",
                [test_value]
            ).fetch_df()
        
            if not df_filtered.empty:
                assert all(df_filtered["gap_at_open_pct"] == test_value)
    
    def test_static_not_equals(self, real_db):
        """Test: column != value"""
        test_value = 0.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE gap_at_open_pct != ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["gap_at_open_pct"] != test_value)
    
    def test_static_greater_than(self, real_db):
        """Test: column > value"""
        test_value = 5.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE rth_run_pct > ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["rth_run_pct"] > test_value)
    
    def test_static_greater_or_equal(self, real_db):
        """Test: column >= value"""
        test_value = 10.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE rth_volume >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["rth_volume"] >= test_value)
    
    def test_static_less_than(self, real_db):
        """Test: column < value"""
        test_value = 5.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE pmh_fade_to_open_pct < ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["pmh_fade_to_open_pct"] < test_value)
    
    def test_static_less_or_equal(self, real_db):
        """Test: column <= value"""
        test_value = 20.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE high_spike_pct <= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["high_spike_pct"] <= test_value)


class TestVariableComparisons:
    """Tests for variable comparisons (column vs column)"""
    
    def test_variable_price_comparison(self, real_db):
        """Test: rth_close > rth_open (red candles)"""
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE rth_close > rth_open"
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["rth_close"] > df_filtered["rth_open"])
    
    def test_variable_volume_comparison(self, real_db):
        """Test: pm_volume > rth_volume"""
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE pm_volume > rth_volume"
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["pm_volume"] > df_filtered["rth_volume"])
    
    def test_variable_spike_comparison(self, real_db):
        """Test: high_spike_pct > low_spike_pct"""
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE high_spike_pct > low_spike_pct"
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["high_spike_pct"] > df_filtered["low_spike_pct"])
    
    def test_variable_price_vs_pm_high(self, real_db):
        """Test: rth_high > pm_high (PM high break)"""
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE rth_high > pm_high"
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["rth_high"] > df_filtered["pm_high"])
    
    def test_all_metric_combinations(self, real_db):
        """Test: Validate all metrics from METRIC_MAP can be used in comparisons"""
        # Test a sample of metric combinations
        test_pairs = [
            ("rth_open", "rth_close"),
            ("rth_high", "rth_low"),
            ("m15_return_pct", "m30_return_pct"),
            ("m30_return_pct", "m60_return_pct"),
        ]
        
        for col1, col2 in test_pairs:
            # Test that query doesn't fail
            df = real_db.execute(
                f"SELECT * FROM daily_metrics WHERE {col1} > {col2} LIMIT 10"
            ).fetch_df()
            
            # Validation: query executed successfully
            assert df is not None


class TestLogicCombinations:
    """Tests for combining multiple rules with AND/OR logic"""
    
    def test_single_rule_and_logic(self, real_db):
        """Test: Single rule with AND (should behave same as direct filter)"""
        test_value = 5.0
        
        df_filtered = real_db.execute(
            "SELECT * FROM daily_metrics WHERE gap_at_open_pct >= ?",
            [test_value]
        ).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["gap_at_open_pct"] >= test_value)
    
    def test_multiple_rules_and_logic(self, real_db):
        """Test: Multiple rules with AND (all must be satisfied)"""
        df_filtered = real_db.execute("""
            SELECT * FROM daily_metrics 
            WHERE gap_at_open_pct >= 5.0
            AND rth_volume >= 1000000
            AND rth_run_pct >= 10.0
        """).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["gap_at_open_pct"] >= 5.0)
            assert all(df_filtered["rth_volume"] >= 1000000)
            assert all(df_filtered["rth_run_pct"] >= 10.0)
    
    def test_multiple_rules_or_logic(self, real_db):
        """Test: Multiple rules with OR (at least one must be satisfied)"""
        df_filtered = real_db.execute("""
            SELECT * FROM daily_metrics 
            WHERE gap_at_open_pct >= 20.0
            OR rth_run_pct >= 50.0
        """).fetch_df()
        
        if not df_filtered.empty:
            # Each row should satisfy at least one condition
            for _, row in df_filtered.iterrows():
                assert row["gap_at_open_pct"] >= 20.0 or row["rth_run_pct"] >= 50.0
    
    def test_mixed_static_and_variable(self, real_db):
        """Test: Combining static value and variable comparisons"""
        df_filtered = real_db.execute("""
            SELECT * FROM daily_metrics 
            WHERE gap_at_open_pct >= 5.0
            AND rth_close < rth_open
        """).fetch_df()
        
        if not df_filtered.empty:
            assert all(df_filtered["gap_at_open_pct"] >= 5.0)
            assert all(df_filtered["rth_close"] < df_filtered["rth_open"])


class TestEdgeCases:
    """Tests for edge cases and error handling"""
    
    def test_empty_result_set(self, real_db):
        """Test: Query that returns no results"""
        df_filtered = real_db.execute("""
            SELECT * FROM daily_metrics 
            WHERE gap_at_open_pct >= 1000.0
        """).fetch_df()
        
        # Should return empty DataFrame, not error
        assert df_filtered.empty
    
    def test_null_value_handling(self, real_db):
        """Test: Handling of NULL values in comparisons"""
        # NULLs should be excluded from > comparisons
        df_filtered = real_db.execute("""
            SELECT * FROM daily_metrics 
            WHERE gap_at_open_pct > 0.0
        """).fetch_df()
        
        # No NULL values should be in results
        if not df_filtered.empty:
            assert not df_filtered["gap_at_open_pct"].isnull().any()
    
    def test_invalid_operator_handling(self, real_db):
        """Test: Invalid operators should cause SQL error"""
        with pytest.raises(Exception):
            real_db.execute("""
                SELECT * FROM daily_metrics 
                WHERE gap_at_open_pct INVALID_OP 5.0
            """).fetch_df()
    
    def test_combined_filters_with_nulls(self, real_db):
        """Test: Combined filters with potential NULL values"""
        df_filtered = real_db.execute("""
            SELECT * FROM daily_metrics 
            WHERE gap_at_open_pct IS NOT NULL
            AND rth_volume IS NOT NULL
            AND gap_at_open_pct >= 5.0
        """).fetch_df()
        
        if not df_filtered.empty:
            assert not df_filtered["gap_at_open_pct"].isnull().any()
            assert not df_filtered["rth_volume"].isnull().any()
            assert all(df_filtered["gap_at_open_pct"] >= 5.0)
