from app.database import get_db_connection, get_user_db_connection

def init_db():
    """Create strategies and saved_queries tables if they do not exist."""
    import os
    provider = os.getenv("DB_PROVIDER", "motherduck").lower()
    
    # 1. Ensure market data views exist (mapping to massive shared db or GCS)
    cur = get_db_connection()
    print(f"Checking and creating tables for DB_PROVIDER={provider}...")
    
    try:
        if provider == "gcs":
            # Clean up old ambiguous schema if it exists in users.duckdb
            try:
                cur.execute("DROP SCHEMA IF EXISTS massive CASCADE;")
            except:
                pass

            # Attaching a virtual database named 'massive' to match hardcoded queries
            try:
                cur.execute("ATTACH ':memory:' AS massive;")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    print(f"[WARN] Warning attaching massive: {e}")
            
            # In GCS mode, we create views pointing to the parquet files directly
            # Optimization: Using precise glob patterns to avoid recursive scanning overhead.
            # daily_metrics and intraday_1m are partitioned: year=*/month=*/data.parquet
            cur.execute("""
                CREATE OR REPLACE VIEW massive.daily_metrics AS 
                SELECT * EXCLUDE (pmh_gap_pct), 
                       gap_pct AS gap_at_open_pct,
                       ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) as pmh_gap_pct 
                FROM read_parquet('gs://strategybuilderbbdd/cold_storage/daily_metrics/*/*/*.parquet', hive_partitioning=true)
            """)
            cur.execute("CREATE OR REPLACE VIEW massive.intraday_1m AS SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/intraday_1m/*/*/*.parquet', hive_partitioning=true)")
            
            # tickers and splits are non-partitioned single files or flat directories
            cur.execute("CREATE OR REPLACE VIEW massive.tickers AS SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/tickers/*.parquet')")
            cur.execute("CREATE OR REPLACE VIEW massive.splits AS SELECT * FROM read_parquet('gs://strategybuilderbbdd/cold_storage/splits/*.parquet')")
            
            # Also create aliases in the main schema (of users.duckdb) for convenience
            cur.execute("CREATE OR REPLACE VIEW daily_metrics AS SELECT * FROM massive.daily_metrics")
            cur.execute("CREATE OR REPLACE VIEW intraday_1m AS SELECT * FROM massive.intraday_1m")
            cur.execute("CREATE OR REPLACE VIEW tickers AS SELECT * FROM massive.tickers")
            cur.execute("CREATE OR REPLACE VIEW splits AS SELECT * FROM massive.splits")
            
            print("[INFO] Optimized GCS views initialized (non-recursive globs)")
        elif provider == "local":
            # Local mode: create local empty tables if not exists, and create massive virtual database views
            # First, drop any existing views in main schema to avoid conflict with local tables and infinite recursion
            for table_name in ["tickers", "splits", "daily_metrics", "intraday_1m"]:
                try:
                    cur.execute(f"DROP VIEW IF EXISTS main.{table_name}")
                except Exception as e:
                    pass
            # 1. Create empty local tables in local_data.duckdb so they exist
            cur.execute("CREATE TABLE IF NOT EXISTS tickers (ticker VARCHAR PRIMARY KEY, name VARCHAR, type VARCHAR)")
            cur.execute("CREATE TABLE IF NOT EXISTS splits (ticker VARCHAR, execution_date DATE, PRIMARY KEY(ticker, execution_date))")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_metrics (
                    ticker VARCHAR,
                    timestamp TIMESTAMP,
                    year INTEGER,
                    month INTEGER,
                    gap_pct DOUBLE,
                    gap_at_open_pct DOUBLE,
                    open DOUBLE,
                    close DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    volume DOUBLE,
                    pm_volume DOUBLE,
                    pm_high DOUBLE,
                    pm_low DOUBLE,
                    pm_high_time VARCHAR,
                    pm_low_time VARCHAR,
                    rth_volume DOUBLE,
                    rth_open DOUBLE,
                    rth_high DOUBLE,
                    rth_low DOUBLE,
                    rth_close DOUBLE,
                    rth_run_pct DOUBLE,
                    day_return_pct DOUBLE,
                    rth_range_pct DOUBLE,
                    pmh_gap_pct DOUBLE,
                    pmh_fade_pct DOUBLE,
                    rth_fade_pct DOUBLE,
                    hod_time VARCHAR,
                    lod_time VARCHAR,
                    m15_return_pct DOUBLE,
                    m30_return_pct DOUBLE,
                    m60_return_pct DOUBLE,
                    m180_return_pct DOUBLE,
                    close_1559 DOUBLE,
                    last_close DOUBLE,
                    prev_close DOUBLE,
                    eod_volume DOUBLE,
                    transactions DOUBLE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS intraday_1m (
                    ticker VARCHAR,
                    date DATE,
                    timestamp TIMESTAMP,
                    open DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    close DOUBLE,
                    volume DOUBLE,
                    PRIMARY KEY (ticker, timestamp)
                )
            """)
            
            # 2. Virtualize massive db schema pointing to local tables so hardcoded massive. queries work!
            try:
                cur.execute("DROP SCHEMA IF EXISTS massive CASCADE;")
            except:
                pass
            try:
                cur.execute("ATTACH ':memory:' AS massive;")
            except Exception as e:
                if "already exists" not in str(e).lower():
                    print(f"[WARN] Warning attaching massive: {e}")
                    
            cur.execute("CREATE VIEW IF NOT EXISTS massive.tickers AS SELECT * FROM main.tickers")
            cur.execute("CREATE VIEW IF NOT EXISTS massive.splits AS SELECT * FROM main.splits")
            cur.execute("CREATE VIEW IF NOT EXISTS massive.daily_metrics AS SELECT * FROM main.daily_metrics")
            cur.execute("CREATE VIEW IF NOT EXISTS massive.intraday_1m AS SELECT * FROM main.intraday_1m")
            
            # In local mode, we do NOT create aliases in the main schema pointing to massive views,
            # because they are already tables in the main schema.
            print("[INFO] Local market data views virtualized in massive schema")
        else:
            cur.execute("""
                CREATE OR REPLACE VIEW daily_metrics AS 
                SELECT * EXCLUDE (pmh_gap_pct), 
                       ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) as pmh_gap_pct 
                FROM massive.main.daily_metrics
            """)
            cur.execute("CREATE OR REPLACE VIEW intraday_1m AS SELECT * FROM massive.main.intraday_1m")
            cur.execute("CREATE OR REPLACE VIEW tickers AS SELECT * FROM massive.main.tickers")
            cur.execute("CREATE OR REPLACE VIEW splits AS SELECT * FROM massive.main.splits")
            print("[INFO] Market data views initialized from MotherDuck")
    except Exception as e:
        print(f"[WARN] Warning: Could not initialize market data views: {e}")

    # 2. Create user tables in the default writeable database AND users.duckdb.
    # IMPORTANT: always BOTH. The old GCS-mode dedup assumed they were the same
    # connection, but get_user_db_connection() opens the users.duckdb file —
    # skipping it left users.duckdb without tables, so every SWR cache read
    # (ticker_analysis_cache) failed and ticker-analysis refetched slow sources
    # on each click until Yahoo/Finviz rate-limited us.
    db_connections = [get_db_connection(), get_user_db_connection()]

    for conn in db_connections:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS saved_queries (
                id VARCHAR PRIMARY KEY,
                name VARCHAR,
                filters JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id VARCHAR PRIMARY KEY,
                name VARCHAR,
                description VARCHAR,
                definition JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS datasets (
                id VARCHAR PRIMARY KEY,
                name VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS dataset_pairs (
                dataset_id VARCHAR,
                ticker VARCHAR,
                date DATE,
                PRIMARY KEY (dataset_id, ticker, date)
            )
        """)

        # ticker_analysis_cache: persistent stale-while-revalidate cache for the
        # Ticker Analysis endpoints (yfinance/Finviz/SEC are slow and flaky).
        # Survives restarts/deploys via the users.duckdb GCS sync cycle.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticker_analysis_cache (
                ticker VARCHAR,
                endpoint VARCHAR,
                payload JSON,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker, endpoint)
            )
        """)

        # dilution_banks_registry: histórico de agentes colocadores / bancos
        # dilusores extraídos por Edgie de los filings SEC. Cada análisis inserta
        # los bancos detectados; los conteos por banco elevan el rating de riesgo
        # de dilución en análisis posteriores. Ver routers/assistant.py.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dilution_banks_registry (
                ticker VARCHAR NOT NULL,
                bank_name VARCHAR NOT NULL,
                form_type VARCHAR,
                date_filed DATE,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # precache_state: process-shared status of dataset intraday pre-caching.
        # Survives restarts so the backtest endpoint and clients can know whether
        # a precache is still running, finished, or failed without relying on
        # in-process dicts that die with the worker.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS precache_state (
                dataset_id VARCHAR PRIMARY KEY,
                status VARCHAR,
                progress_pct DOUBLE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # backtest_results table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_results (
                id VARCHAR PRIMARY KEY,
                strategy_ids JSON,
                results_json JSON,
                total_trades INTEGER,
                win_rate DOUBLE,
                profit_factor DOUBLE,
                avg_r_multiple DOUBLE,
                total_return_r DOUBLE,
                total_return_pct DOUBLE,
                max_drawdown_pct DOUBLE,
                sharpe_ratio DOUBLE,
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                search_mode VARCHAR,
                search_space VARCHAR
            )
        """)

        # ── Feedback & feature-voting board (in-app widget) ──────────────────
        # feature_options: the single-answer list shown in the widget.
        # feature_votes:   one vote per user per release (PK round_id+user_id).
        # feature_suggestions: free-text "¿Qué echas de menos en Edgecute?".
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feature_options (
                id VARCHAR PRIMARY KEY,
                label VARCHAR,
                description VARCHAR,
                sort_order INTEGER DEFAULT 0,
                archived BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feature_votes (
                round_id VARCHAR,
                user_id VARCHAR,
                option_id VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (round_id, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feature_suggestions (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR,
                message VARCHAR,
                round_id VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed PLACEHOLDER roadmap options once. Edit/replace these freely — the
        # widget reads them live; nothing here is a product commitment.
        try:
            _seeded = conn.execute("SELECT COUNT(*) FROM feature_options").fetchone()
            if _seeded and _seeded[0] == 0:
                _opts = [
                    ("alertas_setups", "Alertas en tiempo real de setups", "Avísame cuando un ticker cumpla mi estrategia", 1),
                    ("mas_indicadores", "Más indicadores en el builder", "Ampliar el catálogo de indicadores técnicos", 2),
                    ("export_informes", "Exportar backtests a PDF/Excel", "Descargar resultados para compartir", 3),
                    ("app_movil", "App móvil", "Consultar screener y alertas desde el móvil", 4),
                    ("optim_rapida", "Optimización multi-estrategia más rápida", "Reducir el tiempo de las búsquedas", 5),
                ]
                for _oid, _label, _desc, _order in _opts:
                    conn.execute(
                        "INSERT INTO feature_options (id, label, description, sort_order, archived) "
                        "VALUES (?, ?, ?, ?, FALSE)",
                        [_oid, _label, _desc, _order],
                    )
        except Exception as e:
            print(f"[WARN] Could not seed feature_options: {e}")

        # Clerk Phase 2 migration: add nullable user_id to user-owned tables.
        # Nullable so legacy rows (and the read-only GCS parquet fallback) keep
        # working — reads use NULL-tolerant scoping (see app.auth.scope_clause).
        for table_name in ("strategies", "saved_queries", "datasets", "backtest_results"):
            try:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS user_id VARCHAR")
            except Exception as e:
                print(f"[WARN] Could not add user_id to {table_name}: {e}")

    print("[INFO] Local database tables initialized across connections")
    
    tables = cur.execute("SHOW TABLES").fetchall()
    print(f"Current tables in massive: {[t[0] for t in tables]}")

    # Mock seeding disabled — was leaking into production.
    # The seed_mock_data.py module is kept for local manual use via `python -m app.seed_mock_data`.

    # Migration: Recalculate pmh_gap_pct to use the correct Premarket High vs Prev Close formula
    try:
        cur.execute("UPDATE daily_metrics SET pmh_gap_pct = ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) WHERE prev_close IS NOT NULL AND prev_close > 0")
        print("[INFO] Successfully migrated local daily_metrics pmh_gap_pct calculation")
    except Exception as e:
        print(f"[WARN] Could not update local daily_metrics pmh_gap_pct: {e}")

if __name__ == "__main__":
    init_db()

