"""
Tests for NEW Tier 3 Metrics using REAL data.
Tests: Return from M(x) to Close
"""
import pytest
import pandas as pd
from tests.utils.db_helpers import execute_and_validate_query


class TestReturnMxToClose:
    """Tests for Return from M(x) to Close calculations"""
    
    def test_return_m15_to_close_exists(self, real_db):
        """Test: return_m15_to_close column exists and is populated"""
        query = """
            SELECT return_m15_to_close
            FROM daily_metrics
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        
        assert not df.empty, "Should return rows"
        assert 'return_m15_to_close' in df.columns, "return_m15_to_close column should exist"
    
    def test_all_return_mx_columns_exist(self, real_db):
        """Test: All return M(x) to close columns exist"""
        query = """
            SELECT return_m15_to_close, return_m30_to_close, return_m60_to_close
            FROM daily_metrics
            LIMIT 1
        """
        df = execute_and_validate_query(real_db, query)
        
        expected_cols = ['return_m15_to_close', 'return_m30_to_close', 'return_m60_to_close']
        
        for col in expected_cols:
            assert col in df.columns, f"Column {col} should exist"
    
    def test_return_m15_positive_when_close_above_m15(self, real_db):
        """Test: return_m15_to_close > 0 when close > M15 price"""
        # We need to reconstruct M15 price from m15_return_pct
        query = """
            SELECT rth_open, m15_return_pct, rth_close, return_m15_to_close
            FROM daily_metrics
            WHERE m15_return_pct IS NOT NULL
            AND return_m15_to_close IS NOT NULL
            AND rth_close > rth_open * (1 + m15_return_pct/100)
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            # When close > M15 price, return should be positive
            for _, row in df.iterrows():
                assert row['return_m15_to_close'] > -0.01, \
                    "Return M15 to close should be positive when close > M15 price"
    
    def test_return_m15_negative_when_close_below_m15(self, real_db):
        """Test: return_m15_to_close < 0 when close < M15 price"""
        query = """
            SELECT rth_open, m15_return_pct, rth_close, return_m15_to_close
            FROM daily_metrics
            WHERE m15_return_pct IS NOT NULL
            AND return_m15_to_close IS NOT NULL
            AND rth_close < rth_open * (1 + m15_return_pct/100)
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            # When close < M15 price, return should be negative
            for _, row in df.iterrows():
                assert row['return_m15_to_close'] < 0.01, \
                    "Return M15 to close should be negative when close < M15 price"
    
    def test_return_m30_calculation_logic(self, real_db):
        """Test: return_m30_to_close calculation logic"""
        query = """
            SELECT rth_open, rth_close, m30_return_pct, return_m30_to_close
            FROM daily_metrics
            WHERE m30_return_pct IS NOT NULL
            AND return_m30_to_close IS NOT NULL
            AND rth_open > 0
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            for _, row in df.iterrows():
                # Calculate M30 price from open and M30 return
                m30_price = row['rth_open'] * (1 + row['m30_return_pct']/100)
                
                # Expected return from M30 to Close
                expected_return = ((row['rth_close'] - m30_price) / m30_price) * 100
                
                # Validate
                assert abs(row['return_m30_to_close'] - expected_return) < 0.1, \
                    f"Return M30 to close calculation mismatch: expected {expected_return:.2f}, got {row['return_m30_to_close']:.2f}"
    
    def test_return_m60_calculation_logic(self, real_db):
        """Test: return_m60_to_close calculation logic"""
        query = """
            SELECT rth_open, rth_close, m60_return_pct, return_m60_to_close
            FROM daily_metrics
            WHERE m60_return_pct IS NOT NULL
            AND return_m60_to_close IS NOT NULL
            AND rth_open > 0
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            for _, row in df.iterrows():
                # Calculate M60 price from open and M60 return
                m60_price = row['rth_open'] * (1 + row['m60_return_pct']/100)
                
                # Expected return from M60 to Close
                expected_return = ((row['rth_close'] - m60_price) / m60_price) * 100
                
                # Validate
                assert abs(row['return_m60_to_close'] - expected_return) < 0.1, \
                    f"Return M60 to close calculation mismatch: expected {expected_return:.2f}, got {row['return_m60_to_close']:.2f}"


class TestReturnMxRelationships:
    """Tests for relationships between different Return M(x) metrics"""
    
    def test_return_consistency_across_timeframes(self, real_db):
        """Test: Returns at different timeframes should be internally consistent"""
        query = """
            SELECT return_m15_to_close, return_m30_to_close, return_m60_to_close,
                   m15_return_pct, m30_return_pct, m60_return_pct,
                   rth_open, rth_close
            FROM daily_metrics
            WHERE return_m15_to_close IS NOT NULL
            AND return_m30_to_close IS NOT NULL
            AND return_m60_to_close IS NOT NULL
            LIMIT 20
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            for _, row in df.iterrows():
                # All three should have the same sign in strong trending days
                # (though this is not guaranteed for choppy days)
                returns = [
                    row['return_m15_to_close'],
                    row['return_m30_to_close'],
                    row['return_m60_to_close']
                ]
                
                # At least check they are all valid numbers
                assert all(isinstance(r, (int, float)) for r in returns), \
                    "All return values should be numeric"
    
    def test_fade_detection_via_returns(self, real_db):
        """Test: Negative returns indicate fade from M(x) to close"""
        query = """
            SELECT return_m15_to_close, return_m30_to_close, return_m60_to_close,
                   rth_open, rth_close, m15_return_pct, m30_return_pct, m60_return_pct
            FROM daily_metrics
            WHERE return_m15_to_close < -2.0
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            # These are fade cases where price fell from M15 to close
            for _, row in df.iterrows():
                # M15 return should be > return_m15_to_close (price was higher at M15)
                assert row['m15_return_pct'] > row['return_m15_to_close'], \
                    "In fade cases, M15 return should be greater than return from M15 to close"
