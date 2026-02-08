"""
Tests for NEW Tier 2 Metrics using REAL data.
Tests: M(x) High Spike % and M(x) Low Spike %
"""
import pytest
import pandas as pd
from tests.utils.db_helpers import execute_and_validate_query


class TestMxHighSpike:
    """Tests for M(x) High Spike % calculations"""
    
    def test_m1_high_spike_exists(self, real_db):
        """Test: M1 high spike column is populated"""
        query = """
            SELECT m1_high_spike_pct
            FROM daily_metrics
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        
        assert not df.empty, "Should return rows"
        assert 'm1_high_spike_pct' in df.columns, "m1_high_spike_pct column should exist"
    
    def test_mx_high_spikes_increasing(self, real_db):
        """Test: M(x) high spikes should generally increase or stay same as time increases"""
        query = """
            SELECT m1_high_spike_pct, m5_high_spike_pct, m15_high_spike_pct,
                   m30_high_spike_pct, m60_high_spike_pct, m180_high_spike_pct
            FROM daily_metrics
            WHERE m1_high_spike_pct IS NOT NULL
            LIMIT 20
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            # Check that later spikes are >= earlier spikes (monotonically increasing)
            for _, row in df.iterrows():
                spikes = [
                    row['m1_high_spike_pct'],
                    row['m5_high_spike_pct'],
                    row['m15_high_spike_pct'],
                    row['m30_high_spike_pct'],
                    row['m60_high_spike_pct'],
                    row['m180_high_spike_pct']
                ]
                
                # Each subsequent spike should be >= previous (allowing for same max)
                for i in range(1, len(spikes)):
                    assert spikes[i] >= spikes[i-1] - 0.01, \
                        f"M{[1,5,15,30,60,180][i]} spike should be >= M{[1,5,15,30,60,180][i-1]} spike"
    
    def test_all_mx_high_spike_columns_exist(self, real_db):
        """Test: All M(x) high spike columns exist"""
        query = """
            SELECT m1_high_spike_pct, m5_high_spike_pct, m15_high_spike_pct,
                   m30_high_spike_pct, m60_high_spike_pct, m180_high_spike_pct
            FROM daily_metrics
            LIMIT 1
        """
        df = execute_and_validate_query(real_db, query)
        
        expected_cols = ['m1_high_spike_pct', 'm5_high_spike_pct', 'm15_high_spike_pct',
                        'm30_high_spike_pct', 'm60_high_spike_pct', 'm180_high_spike_pct']
        
        for col in expected_cols:
            assert col in df.columns, f"Column {col} should exist"


class TestMxLowSpike:
    """Tests for M(x) Low Spike % calculations"""
    
    def test_m1_low_spike_exists(self, real_db):
        """Test: M1 low spike column is populated"""
        query = """
            SELECT m1_low_spike_pct
            FROM daily_metrics
            LIMIT 10
        """
        df = execute_and_validate_query(real_db, query)
        
        assert not df.empty, "Should return rows"
        assert 'm1_low_spike_pct' in df.columns, "m1_low_spike_pct column should exist"
    
    def test_mx_low_spikes_decreasing(self, real_db):
        """Test: M(x) low spikes should generally decrease or stay same as time increases"""
        query = """
            SELECT m1_low_spike_pct, m5_low_spike_pct, m15_low_spike_pct,
                   m30_low_spike_pct, m60_low_spike_pct, m180_low_spike_pct
            FROM daily_metrics
            WHERE m1_low_spike_pct IS NOT NULL
            LIMIT 20
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            # Check that later spikes are <= earlier spikes (monotonically decreasing)
            for _, row in df.iterrows():
                spikes = [
                    row['m1_low_spike_pct'],
                    row['m5_low_spike_pct'],
                    row['m15_low_spike_pct'],
                    row['m30_low_spike_pct'],
                    row['m60_low_spike_pct'],
                    row['m180_low_spike_pct']
                ]
                
                # Each subsequent spike should be <= previous (allowing for same min)
                for i in range(1, len(spikes)):
                    assert spikes[i] <= spikes[i-1] + 0.01, \
                        f"M{[1,5,15,30,60,180][i]} low spike should be <= M{[1,5,15,30,60,180][i-1]} low spike"
    
    def test_all_mx_low_spike_columns_exist(self, real_db):
        """Test: All M(x) low spike columns exist"""
        query = """
            SELECT m1_low_spike_pct, m5_low_spike_pct, m15_low_spike_pct,
                   m30_low_spike_pct, m60_low_spike_pct, m180_low_spike_pct
            FROM daily_metrics
            LIMIT 1
        """
        df = execute_and_validate_query(real_db, query)
        
        expected_cols = ['m1_low_spike_pct', 'm5_low_spike_pct', 'm15_low_spike_pct',
                        'm30_low_spike_pct', 'm60_low_spike_pct', 'm180_low_spike_pct']
        
        for col in expected_cols:
            assert col in df.columns, f"Column {col} should exist"
    
    def test_low_spikes_usually_negative(self, real_db):
        """Test: Low spikes should typically be negative (price dropped)"""
        query = """
            SELECT m15_low_spike_pct, m30_low_spike_pct, m60_low_spike_pct
            FROM daily_metrics
            WHERE m15_low_spike_pct IS NOT NULL
            LIMIT 50
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            # Most low spikes should be <= 0 (at or below open)
            for col in ['m15_low_spike_pct', 'm30_low_spike_pct', 'm60_low_spike_pct']:
                negative_count = (df[col] <= 0).sum()
                total = len(df)
                # At least 30% should be negative (allowing for strong uptrends)
                assert negative_count / total >= 0.3, \
                    f"{col}: Expected at least 30% negative values, got {negative_count/total*100:.1f}%"


class TestMxSpikeRelationships:
    """Tests for relationships between M(x) High and Low Spikes"""
    
    def test_high_spike_greater_than_low_spike(self, real_db):
        """Test: High spike should always be >= Low spike for same time period"""
        query = """
            SELECT m15_high_spike_pct, m15_low_spike_pct,
                   m30_high_spike_pct, m30_low_spike_pct,
                   m60_high_spike_pct, m60_low_spike_pct
            FROM daily_metrics
            WHERE m15_high_spike_pct IS NOT NULL
            AND m15_low_spike_pct IS NOT NULL
            LIMIT 20
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            for _, row in df.iterrows():
                assert row['m15_high_spike_pct'] >= row['m15_low_spike_pct'], \
                    "M15 high spike should be >= M15 low spike"
                assert row['m30_high_spike_pct'] >= row['m30_low_spike_pct'], \
                    "M30 high spike should be >= M30 low spike"
                assert row['m60_high_spike_pct'] >= row['m60_low_spike_pct'], \
                    "M60 high spike should be >= M60 low spike"
    
    def test_m180_contains_hod_lod(self, real_db):
        """Test: M180 (3 hours) spikes should match or exceed high_spike_pct and low_spike_pct"""
        query = """
            SELECT high_spike_pct, low_spike_pct,
                   m180_high_spike_pct, m180_low_spike_pct
            FROM daily_metrics
            WHERE high_spike_pct IS NOT NULL
            AND m180_high_spike_pct IS NOT NULL
            AND m180_low_spike_pct IS NOT NULL
            LIMIT 20
        """
        df = execute_and_validate_query(real_db, query)
        
        if not df.empty:
            for _, row in df.iterrows():
                # M180 high should be close to or equal to daily high spike
                # (allowing larger tolerance for HOD occurring after M180)
                assert row['m180_high_spike_pct'] >= row['high_spike_pct'] - 2.0, \
                    f"M180 high spike should be close to daily high spike"
                
                # M180 low should be close to or equal to daily low spike
                assert row['m180_low_spike_pct'] <= row['low_spike_pct'] + 2.0, \
                    f"M180 low spike should be close to daily low spike"
