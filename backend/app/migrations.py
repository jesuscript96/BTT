"""
Database migrations for schema updates
"""
from app.database import get_db_connection


def migrate_backtest_results_add_missing_columns():
    """
    Add missing columns to backtest_results table if they don't exist.
    Safe to run multiple times (idempotent).
    """
    print("Running migration: Add missing columns to backtest_results...")
    
    con = get_db_connection()
    
    # Get current columns
    columns_result = con.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'backtest_results'
    """).fetchall()
    
    existing_columns = {row[0] for row in columns_result}
    print(f"Existing columns: {existing_columns}")
    
    # Define columns that should exist
    required_columns = {
        'profit_factor': 'DOUBLE',
        'total_return_pct': 'DOUBLE',
        'total_return_r': 'DOUBLE',
        'search_mode': 'VARCHAR',
        'search_space': 'VARCHAR',
        'partials_config': 'JSON',
        'trailing_stop_config': 'JSON'
    }
    
    # Add missing columns
    for col_name, col_type in required_columns.items():
        if col_name not in existing_columns:
            print(f"  Adding column: {col_name} ({col_type})")
            try:
                con.execute(f"""
                    ALTER TABLE backtest_results 
                    ADD COLUMN {col_name} {col_type}
                """)
                print(f"  ✓ Added {col_name}")
            except Exception as e:
                print(f"  ⚠️  Error adding {col_name}: {e}")
        else:
            print(f"  ✓ Column {col_name} already exists")
    
    print("Migration completed.")


def run_all_migrations():
    """Run all pending migrations"""
    print("\n" + "="*50)
    print("RUNNING DATABASE MIGRATIONS")
    print("="*50 + "\n")
    
    migrate_backtest_results_add_missing_columns()
    
    print("\n" + "="*50)
    print("ALL MIGRATIONS COMPLETED")
    print("="*50 + "\n")


if __name__ == "__main__":
    run_all_migrations()
