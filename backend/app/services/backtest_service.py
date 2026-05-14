from app.database import get_db_connection
from app.schemas.strategy import Strategy
from app.routers.data import FilterRequest
from app.backtester.engine import BacktestEngine, merge_backtest_results
from app.backtester.portfolio import (
    monte_carlo_simulation,
    calculate_correlation_matrix,
    calculate_drawdown_series,
    calculate_strategy_equity_curves,
)
from app.services.query_service import build_screener_query
from app.services.cache_service import get_tickers_df, get_splits_df
import pandas as pd
import json, os, time, traceback
from datetime import datetime


# Chunked backtest: when market_data exceeds this many rows, run by month and merge (keeps memory bounded).
CHUNK_BACKTEST_ROWS = int(os.environ.get("CHUNK_BACKTEST_ROWS", "250000"))

# Eastern session bounds (minutes since midnight): PM 04:00-09:30, RTH 09:30-16:00, AM 16:00-20:00
MARKET_INTERVAL_BOUNDS = {
    "PM": (4 * 60, 9 * 60 + 30),   # 240-570
    "RTH": (9 * 60 + 30, 16 * 60),  # 570-960
    "AM": (16 * 60, 20 * 60),       # 960-1200
}


def filter_market_data_by_interval_and_dates(
    df: pd.DataFrame,
    market_interval: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> pd.DataFrame:
    """Filter market_data by date range and market interval (PM/RTH/AM)."""
    if df.empty:
        return df
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    if date_from:
        df = df[df["timestamp"].dt.date >= pd.to_datetime(date_from).date()]
    if date_to:
        df = df[df["timestamp"].dt.date <= pd.to_datetime(date_to).date()]
    if market_interval:
        minutes_since_midnight = df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute
        mask = pd.Series(False, index=df.index)
        for interval in market_interval:
            bounds = MARKET_INTERVAL_BOUNDS.get(interval.upper())
            if bounds:
                lo, hi = bounds
                mask = mask | ((minutes_since_midnight >= lo) & (minutes_since_midnight < hi))
        df = df[mask]
    return df.sort_values(["ticker", "timestamp"]).reset_index(drop=True)


def run_backtest_task(run_id: str, request, run_statuses: dict):
    """
    Execute a backtest with given strategies and dataset.

    `run_statuses` is passed in from the router module to avoid circular imports.
    """
    print("\n" + "=" * 50)
    print("BACKTEST EXECUTION STARTED")
    print("=" * 50)
    print(f"Strategy IDs: {request.strategy_ids}")
    print(f"Weights: {request.weights}")
    print(f"Dataset filters: {request.dataset_filters}")
    print(f"Initial capital: ${request.initial_capital}")

    start_total = time.time()
    try:
        con = get_db_connection()
        print("✓ Database connection established")

        # 1. Fetch strategies from database
        t0 = time.time()
        print("\n[1/5] Fetching strategies...")
        strategies: list[Strategy] = []
        strategy_names: dict[str, str] = {}

        for strategy_id in request.strategy_ids:
            row = con.execute("SELECT definition, name FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
            if not row:
                raise Exception(f"Strategy {strategy_id} not found")
            try:
                strategy_data = row[0]
                if isinstance(strategy_data, str):
                    strategy_data = json.loads(strategy_data)
                strategy = Strategy(**strategy_data)
                strategies.append(strategy)
                strategy_names[strategy_id] = row[1]
            except Exception as e:
                print(f"Error parsing strategy {strategy_id}: {e}")
                raise Exception(f"Invalid strategy format: {e}")

        print(f"  ✓ Loaded strategies in {time.time() - t0:.2f}s")

        # 2. Fetch market data based on filters
        t1 = time.time()
        print("\n[2/5] Fetching market data...")

        req_filters = {}
        dataset_summary = "Custom Filters"

        if request.query_id:
            print(f"  - Using Saved Dataset: {request.query_id}")
            sq_row = con.execute("SELECT filters, name FROM saved_queries WHERE id = ?", (request.query_id,)).fetchone()
            if not sq_row:
                req_filters = request.dataset_filters.dict() if hasattr(request.dataset_filters, "dict") else request.dataset_filters
                print(f"  ⚠️ Saved dataset {request.query_id} not found, using request filters.")
            else:
                req_filters = json.loads(sq_row[0])
                dataset_summary = sq_row[1]
        else:
            req_filters = request.dataset_filters.dict() if hasattr(request.dataset_filters, "dict") else request.dataset_filters

        print("  - Building query for universe selection...")

        universe_limit = int(os.environ.get("BACKTEST_UNIVERSE_LIMIT", "5000"))
        rec_query, sql_p, where_d, where_i, where_m, _ = build_screener_query(
            req_filters,
            limit=universe_limit,
            minimal_for_backtest=True,
            backtest_no_joins=True,
        )

        date_from_f = req_filters.get("date_from") or req_filters.get("start_date") or "2024-01-01"
        date_to_f = req_filters.get("date_to") or req_filters.get("end_date") or "2025-12-31"
        limit_per_chunk = min(200, max(100, universe_limit // 52))
        universe_chunks = []
        chunk_start = pd.Timestamp(date_from_f)
        end_ts = pd.Timestamp(date_to_f) + pd.Timedelta(days=1)
        date_filter = (
            " AND CAST(daily_metrics.timestamp AS DATE) >= CAST(? AS DATE) AND CAST(daily_metrics.timestamp AS DATE) < CAST(? AS DATE) "
        )
        rec_query_chunk = rec_query.replace("ORDER BY timestamp DESC", date_filter + "ORDER BY timestamp DESC").replace(
            f"LIMIT {universe_limit}", f"LIMIT {limit_per_chunk}"
        )

        while chunk_start < end_ts:
            chunk_end = min(chunk_start + pd.Timedelta(days=7), end_ts)
            params = list(sql_p) + [chunk_start.date().isoformat(), chunk_end.date().isoformat()]
            try:
                chunk = con.execute(rec_query_chunk, params).fetchdf()
            except Exception as e:
                err_msg = str(e)
                print(f"  Universe chunk {chunk_start.date()} failed: {err_msg[:200]}")
                if "4194304" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "larger than max" in err_msg:
                    raise Exception(
                        "Query plan too large for MotherDuck (4MB). Try a smaller date range or fewer filters. Error: "
                        + err_msg[:150]
                    )
                chunk_start = chunk_end
                continue
            if not chunk.empty:
                universe_chunks.append(chunk)
            chunk_start = chunk_end

        if not universe_chunks:
            raise Exception("No universe rows for given filters")

        universe_df = (
            pd.concat(universe_chunks, ignore_index=True)
            .drop_duplicates(subset=["ticker", "timestamp"])
            .reset_index(drop=True)
        )
        if universe_df.empty:
            raise Exception("No universe rows for given filters")
        print("  - Fetched universe to Python (minimal columns, by week).")

        universe_tickers = universe_df["ticker"].astype(str).str.upper().unique().tolist()
        TICKER_QUERY_BATCH = 150
        valid_tickers = set()
        print("  - Applying tickers (CS/ADRC/OS) filter in batches...")
        for i in range(0, len(universe_tickers), TICKER_QUERY_BATCH):
            batch = universe_tickers[i : i + TICKER_QUERY_BATCH]
            placeholders = ",".join("?" * len(batch))
            try:
                tickers_df = get_tickers_df()
                valid_df = tickers_df[tickers_df["ticker"].isin(batch)][["ticker"]]
                valid_tickers.update(valid_df["ticker"].astype(str).str.upper())
            except Exception as e:
                print(f"  Tickers batch {i // TICKER_QUERY_BATCH + 1} failed: {e}")
        valid_tickers = valid_tickers or None

        split_set = set()
        print("  - Applying splits filter in batches...")
        for i in range(0, len(universe_tickers), TICKER_QUERY_BATCH):
            batch = universe_tickers[i : i + TICKER_QUERY_BATCH]
            placeholders = ",".join("?" * len(batch))
            try:
                splits_df_all = get_splits_df()
                splits_df = splits_df_all[
                    (splits_df_all["ticker"].isin(batch)) &
                    (splits_df_all["execution_date"] >= pd.Timestamp(date_from_f).date()) &
                    (splits_df_all["execution_date"] <= pd.Timestamp(date_to_f).date())
                ].copy()
                if not splits_df.empty:
                    splits_df["execution_date"] = pd.to_datetime(splits_df["execution_date"]).dt.date
                    split_set.update(zip(splits_df["ticker"].astype(str).str.upper(), splits_df["execution_date"]))
            except Exception as e:
                print(f"  Splits batch {i // TICKER_QUERY_BATCH + 1} failed: {e}")

        universe_df["timestamp"] = pd.to_datetime(universe_df["timestamp"])
        universe_df["_date"] = universe_df["timestamp"].dt.date
        if valid_tickers is not None:
            universe_df = universe_df[universe_df["ticker"].astype(str).str.upper().isin(valid_tickers)]
        if split_set:
            universe_df = universe_df[
                ~universe_df.apply(lambda r: (str(r["ticker"]).upper(), r["_date"]) in split_set, axis=1)
            ]
        universe_df = universe_df.reset_index(drop=True)
        if universe_df.empty:
            raise Exception("No universe rows after tickers/splits filter")
        print("  - Tickers and splits filter applied.")

        universe_metrics = universe_df[
            ["ticker", "_date", "pm_high", "pm_volume", "gap_pct", "day_return_pct", "rth_run_pct"]
        ].copy()
        universe_metrics.rename(columns={"day_return_pct": "day_ret", "rth_run_pct": "rth_run"}, inplace=True)
        date_min = universe_metrics["_date"].min()
        date_max = universe_metrics["_date"].max()

        has_date_col = False
        try:
            cols = [c[0] for c in con.execute("DESCRIBE intraday_1m").fetchall()]
            has_date_col = "date" in cols
        except Exception:
            pass

        TICKER_BATCH_SIZE = int(os.environ.get("BACKTEST_INTRADAY_TICKER_BATCH", "60"))
        print(f"  - Fetching intraday by month and ticker batches (batch={TICKER_BATCH_SIZE})...")
        chunks = []
        month_start = pd.Timestamp(date_min)
        while month_start.date() <= date_max:
            month_end = month_start + pd.offsets.MonthEnd(0) + pd.Timedelta(days=1)
            ts_from = month_start.isoformat()
            ts_to = month_end.isoformat()
            month_metrics = universe_metrics[
                (universe_metrics["_date"] >= month_start.date()) & (universe_metrics["_date"] < month_end.date())
            ]
            tickers_this_month = month_metrics["ticker"].unique().tolist()
            if not tickers_this_month:
                month_start = month_end
                continue
            month_chunks = []
            for i in range(0, len(tickers_this_month), TICKER_BATCH_SIZE):
                batch = tickers_this_month[i : i + TICKER_BATCH_SIZE]
                placeholders = ",".join("?" * len(batch))
                q = (
                    "SELECT ticker, timestamp, open, high, low, close, volume "
                    "FROM intraday_1m "
                    "WHERE timestamp >= CAST(? AS TIMESTAMP) AND timestamp < CAST(? AS TIMESTAMP) "
                    f"AND ticker IN ({placeholders})"
                )
                params = [ts_from, ts_to] + batch
                try:
                    sub = con.execute(q, params).fetchdf()
                except Exception as e:
                    err_msg = str(e)
                    print(f"  Intraday chunk {ts_from} batch {i//TICKER_BATCH_SIZE + 1} failed: {err_msg[:200]}")
                    if "4194304" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "larger than max" in err_msg:
                        raise Exception(
                            "Intraday query plan too large. Set BACKTEST_INTRADAY_TICKER_BATCH=30 and retry. " + err_msg[:120]
                        )
                    continue
                if sub.empty:
                    continue
                month_chunks.append(sub)
            if not month_chunks:
                month_start = month_end
                continue
            chunk = pd.concat(month_chunks, ignore_index=True)
            chunk["timestamp"] = pd.to_datetime(chunk["timestamp"])
            chunk["_date"] = chunk["timestamp"].dt.date
            chunk = chunk.merge(universe_metrics, on=["ticker", "_date"], how="inner")
            chunk = chunk.drop(columns=["_date"], errors="ignore")
            chunks.append(chunk)
            month_start = month_end

        if not chunks:
            raise Exception("No market data found for given filters")

        market_data = (
            pd.concat(chunks, ignore_index=True)
            .sort_values(["ticker", "timestamp"])
            .reset_index(drop=True)
        )
        duration_fetch = time.time() - t1
        if market_data.empty:
            raise Exception("No market data found for given filters")

        max_rows = int(os.environ.get("BACKTEST_MAX_ROWS", "0"))
        if max_rows > 0 and len(market_data) > max_rows:
            raise Exception(
                f"Dataset too large ({len(market_data):,} rows). Max {max_rows:,}. Set BACKTEST_MAX_ROWS=0 to allow any size (uses chunked run)."
            )

        print(f"  ✓ Fetched {len(market_data):,} rows in {duration_fetch:.2f}s")

        intervals = request.market_interval
        if intervals is not None:
            intervals = [intervals] if isinstance(intervals, str) else list(intervals)
        date_from = req_filters.get("date_from") if isinstance(req_filters, dict) else getattr(request.dataset_filters, "date_from", None)
        date_to = req_filters.get("date_to") if isinstance(req_filters, dict) else getattr(request.dataset_filters, "date_to", None)
        market_data = filter_market_data_by_interval_and_dates(
            market_data,
            market_interval=intervals,
            date_from=date_from,
            date_to=date_to,
        )
        if market_data.empty:
            raise Exception("No market data left after date/interval filter")
        print(f"  ✓ After date/interval filter: {len(market_data):,} rows")

        t2 = time.time()
        risk_per_trade_usd = getattr(request, "risk_per_trade_usd", None) or getattr(request, "risk_per_trade_r", None)
        if risk_per_trade_usd is not None and risk_per_trade_usd <= 0:
            risk_per_trade_usd = None

        def run_engine_on_df(df: pd.DataFrame, initial_cap: float):
            eng = BacktestEngine(
                strategies=strategies,
                weights=request.weights,
                market_data=df,
                commission_per_trade=request.commission_per_trade,
                commission_per_share=getattr(request, "commission_per_share", 0.0),
                locate_cost_per_100=getattr(request, "locate_cost_per_100", 0.0),
                slippage_pct=getattr(request, "slippage_pct", 0.0),
                lookahead_prevention=getattr(request, "lookahead_prevention", False),
                risk_per_trade_usd=risk_per_trade_usd,
                initial_capital=initial_cap,
                max_holding_minutes=request.max_holding_minutes,
            )
            return eng.run()

        if len(market_data) > CHUNK_BACKTEST_ROWS:
            print(f"\n[3/5] Running backtest in chunks (>{CHUNK_BACKTEST_ROWS:,} rows)...")
            df = market_data.sort_values("timestamp").reset_index(drop=True)
            if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
                df["timestamp"] = pd.to_datetime(df["timestamp"])
            df["_month"] = df["timestamp"].dt.to_period("M")
            months = sorted(df["_month"].unique())
            chunk_results = []
            cap = request.initial_capital
            for i, month in enumerate(months):
                chunk = df[df["_month"] == month].drop(columns=["_month"])
                res = run_engine_on_df(chunk, cap)
                chunk_results.append(res)
                cap = res.final_balance
                print(f"  Chunk {i+1}/{len(months)} ({month}): {len(chunk):,} rows, {res.total_trades} trades, balance={cap:,.0f}")
            result = merge_backtest_results(chunk_results, request.initial_capital)
            print(f"  ✓ Merged {len(chunk_results)} chunks in {time.time() - t2:.2f}s ({result.total_trades} total trades)")
        else:
            print("\n[3/5] Running backtest engine...")
            result = run_engine_on_df(market_data, request.initial_capital)
            print(f"  ✓ Backtest execution in {time.time() - t2:.2f}s ({result.total_trades} trades)")

        t3 = time.time()
        monte_carlo_sims = min(1000, max(100, int(os.environ.get("MONTE_CARLO_SIMULATIONS", "500"))))
        monte_carlo_result = monte_carlo_simulation(result.trades, request.initial_capital, monte_carlo_sims)

        correlation_matrix = None
        if len(strategies) > 1:
            strategy_curves = calculate_strategy_equity_curves(result.trades, request.initial_capital)
            balance_curves = {sid: [point["balance"] for point in curve] for sid, curve in strategy_curves.items()}
            correlation_matrix = calculate_correlation_matrix(balance_curves)

        drawdown_series = calculate_drawdown_series(result.equity_curve)

        now = datetime.now()
        total_return_pct = (result.final_balance - request.initial_capital) / request.initial_capital * 100
        total_return_r = sum(t.get("r_multiple", 0) for t in result.trades if t.get("r_multiple") is not None)

        results_json = {
            "run_id": run_id,
            "strategy_ids": request.strategy_ids,
            "strategy_names": list(strategy_names.values()),
            "weights": request.weights,
            "initial_capital": request.initial_capital,
            "final_balance": result.final_balance,
            "total_return_pct": total_return_pct,
            "total_return_r": total_return_r,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": result.win_rate,
            "avg_r_multiple": result.avg_r_multiple,
            "max_drawdown_pct": result.max_drawdown_pct,
            "max_drawdown_value": result.max_drawdown_value,
            "sharpe_ratio": result.sharpe_ratio,
            "equity_curve": result.equity_curve,
            "drawdown_series": drawdown_series,
            "trades": result.trades,
            "r_distribution": result.r_distribution,
            "ev_by_time": result.ev_by_time,
            "ev_by_day": result.ev_by_day,
            "monthly_returns": result.monthly_returns,
            "correlation_matrix": correlation_matrix,
            "monte_carlo": {
                "worst_drawdown_pct": monte_carlo_result.worst_drawdown_pct,
                "best_final_balance": monte_carlo_result.best_final_balance,
                "worst_final_balance": monte_carlo_result.worst_final_balance,
                "median_final_balance": monte_carlo_result.median_final_balance,
                "percentile_5": monte_carlo_result.percentile_5,
                "percentile_25": monte_carlo_result.percentile_25,
                "percentile_75": monte_carlo_result.percentile_75,
                "percentile_95": monte_carlo_result.percentile_95,
                "probability_of_ruin": monte_carlo_result.probability_of_ruin,
            },
            "executed_at": now.isoformat(),
            "initial_capital": request.initial_capital,
        }

        skip_audit = os.environ.get("SKIP_BACKTEST_AUDIT", "").lower() in ("1", "true", "yes")
        if not skip_audit:
            print("\nAUDIT: Running VectorBT validation...")
            try:
                from app.backtester.backtest_validator import validate_results

                audit_report = validate_results(results_json)
                results_json["audit"] = audit_report
                print("  ✓ Audit completed")
            except Exception as audit_err:
                print(f"  ⚠️ Audit skipped or failed: {audit_err}")
        else:
            print("\n  (Audit skipped via SKIP_BACKTEST_AUDIT)")

        print("\n[5/5] Saving results to database...")
        con.execute(
            """
            INSERT INTO backtest_results (
                id, strategy_ids, dataset_summary, total_trades, win_rate,
                final_balance, max_drawdown_pct, executed_at, results_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                json.dumps(request.strategy_ids),
                dataset_summary,
                result.total_trades,
                result.win_rate,
                result.final_balance,
                result.max_drawdown_pct,
                now,
                json.dumps(results_json),
            ),
        )

        print(f"  ✓ Validated and saved run {run_id}")
        print(f"  ✓ Metrics calculated in {time.time() - t3:.2f}s")
        print(f"✓ Total Request Time: {time.time() - start_total:.2f}s")

        run_statuses[run_id] = {
            "status": "completed",
            "message": f"Backtest completed: {result.total_trades} trades, {result.win_rate:.1f}% win rate",
        }

    except Exception as e:
        print(f"Backtest execution error: {e}")
        traceback.print_exc()
        run_statuses[run_id] = {
            "status": "failed",
            "message": str(e),
        }
