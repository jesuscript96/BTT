"""
Database helper utilities for working with REAL data in tests.
"""
import duckdb
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any


def copy_sample_data(source_con: duckdb.DuckDBPyConnection, target_con: duckdb.DuckDBPyConnection, limit: int = 1000):
    """
    Copy a sample of real data from production DB to test DB.
    
    Args:
        source_con: Connection to real database
        target_con: Connection to test database
        limit: Number of rows to copy per table
    """
    # Copy sample from daily_metrics
    daily_data = source_con.execute(f"SELECT * FROM daily_metrics LIMIT {limit}").fetch_df()
    target_con.execute("CREATE TABLE IF NOT EXISTS daily_metrics AS SELECT * FROM daily_data", {"daily_data": daily_data})
    
    # Copy sample from historical_data (just a few tickers)
    tickers = source_con.execute("SELECT DISTINCT ticker FROM historical_data LIMIT 3").fetchall()
    ticker_list = [t[0] for t in tickers]
    
    if ticker_list:
        placeholders = ",".join(["?" for _ in ticker_list])
        historical_data = source_con.execute(
            f"SELECT * FROM historical_data WHERE ticker IN ({placeholders}) LIMIT {limit}",
            ticker_list
        ).fetch_df()
        target_con.execute("CREATE TABLE IF NOT EXISTS historical_data AS SELECT * FROM hist_data", {"hist_data": historical_data})
    
    print(f"✓ Copied {len(daily_data)} daily records and sample historical data to test DB")


def execute_and_validate_query(con: duckdb.DuckDBPyConnection, query: str, params: List = None) -> pd.DataFrame:
    """
    Execute a query and validate that it returns valid results.
    
    Args:
        con: Database connection
        query: SQL query string
        params: Query parameters
        
    Returns:
        DataFrame with results
        
    Raises:
        AssertionError if query fails or returns invalid structure
    """
    try:
        if params:
            df = con.execute(query, params).fetch_df()
        else:
            df = con.execute(query).fetch_df()
        
        # Validate result structure
        assert df is not None, "Query returned None"
        assert isinstance(df, pd.DataFrame), "Query did not return DataFrame"
        
        return df
        
    except Exception as e:
        raise AssertionError(f"Query execution failed: {e}\nQuery: {query}\nParams: {params}")


def compare_calculation_methods(
    method1_result: float,
    method2_result: float,
    tolerance: float = 0.01,
    description: str = ""
) -> bool:
    """
    Compare two calculation methods to ensure they produce the same result.
    Useful for validating SQL calculations against Python calculations.
    
    Args:
        method1_result: Result from first calculation method
        method2_result: Result from second calculation method
        tolerance: Acceptable difference (default 1%)
        description: Description of what's being compared
        
    Returns:
        True if results match within tolerance
        
    Raises:
        AssertionError if results don't match
    """
    diff = abs(method1_result - method2_result)
    relative_diff = diff / abs(method1_result) if method1_result != 0 else diff
    
    assert relative_diff <= tolerance, (
        f"Calculation mismatch {description}:\n"
        f"  Method 1: {method1_result}\n"
        f"  Method 2: {method2_result}\n"
        f"  Difference: {diff} ({relative_diff*100:.2f}%)\n"
        f"  Tolerance: {tolerance*100}%"
    )
    
    return True


def validate_filter_application(
    df_before: pd.DataFrame,
    df_after: pd.DataFrame,
    filter_column: str,
    filter_operator: str,
    filter_value: Any
) -> bool:
    """
    Validate that a filter was correctly applied.
    Checks that ALL rows in df_after satisfy the filter condition.
    
    Args:
        df_before: DataFrame before filter
        df_after: DataFrame after filter
        filter_column: Column name that was filtered
        filter_operator: Operator used (>=, <=, =, !=, >, <)
        filter_value: Value used in filter
        
    Returns:
        True if filter was correctly applied
        
    Raises:
        AssertionError if any row doesn't satisfy the filter
    """
    if df_after.empty:
        # Empty result is valid if no rows matched
        return True
    
    # Check that filtered column exists
    assert filter_column in df_after.columns, f"Column {filter_column} not in results"
    
    # Validate each row
    violations = []
    for idx, row in df_after.iterrows():
        value = row[filter_column]
        
        if filter_operator == ">=":
            if value < filter_value:
                violations.append(f"Row {idx}: {value} < {filter_value}")
        elif filter_operator == "<=":
            if value > filter_value:
                violations.append(f"Row {idx}: {value} > {filter_value}")
        elif filter_operator == ">":
            if value <= filter_value:
                violations.append(f"Row {idx}: {value} <= {filter_value}")
        elif filter_operator == "<":
            if value >= filter_value:
                violations.append(f"Row {idx}: {value} >= {filter_value}")
        elif filter_operator == "=":
            if value != filter_value:
                violations.append(f"Row {idx}: {value} != {filter_value}")
        elif filter_operator == "!=":
            if value == filter_value:
                violations.append(f"Row {idx}: {value} == {filter_value}")
    
    if violations:
        raise AssertionError(
            f"Filter validation failed for {filter_column} {filter_operator} {filter_value}:\n" +
            "\n".join(violations[:10])  # Show first 10 violations
        )
    
    return True


def setup_test_database():
    """
    Setup script called by run_all_tests.sh
    Copies sample data from real DB to test DB.
    """
    import duckdb
    
    print("Setting up test database...")
    
    # Connect to real DB (local file)
    backend_dir = Path(__file__).parent.parent.parent
    real_db_path = backend_dir / "backtester.duckdb"
    
    if not real_db_path.exists():
        print(f"⚠️  Warning: Real database not found at {real_db_path}")
        print("   Skipping test database setup.")
        return
    
    real_con = duckdb.connect(str(real_db_path), read_only=True)
    
    # Connect to test DB
    test_db_path = backend_dir / "test_backtester.duckdb"
    if test_db_path.exists():
        test_db_path.unlink()
    
    test_con = duckdb.connect(str(test_db_path))
    
    # Copy sample data
    copy_sample_data(real_con, test_con, limit=5000)
    
    real_con.close()
    test_con.close()
    
    print("✓ Test database setup complete")


if __name__ == "__main__":
    setup_test_database()
