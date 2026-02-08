"""
Pytest configuration and shared fixtures for automated testing.
Uses REAL data from MotherDuck (cloud database) - no mocks.
Tests run LOCALLY but connect to REAL production database.
"""
import pytest
import sys
import duckdb
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.database import get_db_connection


@pytest.fixture(scope="session")
def real_db():
    """
    Connection to the REAL MotherDuck cloud database (read-only).
    Used for validation tests that query real data.
    
    Note: Requires MOTHERDUCK_TOKEN in .env file.
    """
    con = get_db_connection(read_only=True)
    yield con
    con.close()


@pytest.fixture(scope="session")
def test_db():
    """
    Connection to a SEPARATE local test database for write operations.
    Located at backend/test_backtester.duckdb
    This is used ONLY for tests that need to write data.
    """
    test_db_path = backend_dir / "test_backtester.duckdb"
    
    # Create fresh test database
    if test_db_path.exists():
        test_db_path.unlink()
    
    con = duckdb.connect(str(test_db_path))
    yield con
    con.close()


@pytest.fixture(scope="session")
def sample_tickers(real_db):
    """
    Get a small sample of real tickers from MotherDuck for testing.
    Returns list of ticker symbols that have data.
    """
    result = real_db.execute("""
        SELECT DISTINCT ticker 
        FROM daily_metrics 
        LIMIT 5
    """).fetchall()
    
    return [row[0] for row in result]


@pytest.fixture(scope="function")
def sample_daily_data(real_db, sample_tickers):
    """
    Get a sample of real daily_metrics data from MotherDuck.
    Returns a small but representative dataset for testing.
    """
    if not sample_tickers:
        return []
    
    placeholders = ",".join(["?" for _ in sample_tickers])
    query = f"""
        SELECT * FROM daily_metrics
        WHERE ticker IN ({placeholders})
        LIMIT 100
    """
    
    df = real_db.execute(query, sample_tickers).fetch_df()
    return df


@pytest.fixture(scope="function")
def sample_historical_data(real_db, sample_tickers):
    """
    Get a sample of real intraday historical data from MotherDuck.
    Returns 1-minute bars from real database.
    """
    if not sample_tickers:
        return []
    
    # Get one day of data for first ticker
    ticker = sample_tickers[0]
    query = """
        SELECT * FROM historical_data
        WHERE ticker = ?
        ORDER BY timestamp ASC
        LIMIT 390  -- One full RTH session
    """
    
    df = real_db.execute(query, [ticker]).fetch_df()
    return df
