"""
Backtest API Endpoints
"""
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Optional
from pydantic import BaseModel
from uuid import uuid4
from datetime import datetime
import json
import time

from app.database import get_db_connection
from app.schemas.strategy import Strategy
from app.routers.data import FilterRequest

router = APIRouter()


class BacktestRequest(BaseModel):
    """Request to run a backtest"""
    strategy_ids: List[str]
    weights: Dict[str, float]  # strategy_id -> weight % (0-100)
    dataset_filters: FilterRequest  # Reuse from Market Analysis
    query_id: Optional[str] = None  # Dynamic dataset ID
    commission_per_trade: float = 1.0
    initial_capital: float = 100000
    max_holding_minutes: int = 390  # Full RTH session


class BacktestResultResponse(BaseModel):
    """Full backtest results"""
    run_id: str
    strategy_ids: List[str]
    strategy_names: List[str]
    weights: Dict[str, float]
    initial_capital: float
    final_balance: float
    total_return_pct: float
    total_return_r: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_r_multiple: float
    max_drawdown_pct: float
    max_drawdown_value: float
    sharpe_ratio: float
    equity_curve: List[Dict]
    drawdown_series: List[Dict]
    trades: List[Dict]
    r_distribution: Dict[str, int]
    ev_by_time: Dict[str, float]
    ev_by_day: Dict[str, float]
    monthly_returns: Dict[str, float]
    correlation_matrix: Optional[Dict[str, Dict[str, float]]] = None
    monte_carlo: Optional[Dict] = None
    executed_at: str


class BacktestResponse(BaseModel):
    """Backtest execution response"""
    run_id: str
    status: str
    message: str
    results: Optional[BacktestResultResponse] = None


@router.post("/run", response_model=BacktestResponse)
def run_backtest(request: BacktestRequest):
    """
    Execute a backtest with given strategies and dataset
    """
    # Lazy imports to save memory on startup (Numba/Pandas ~100MB RAM)
    from app.backtester.engine import BacktestEngine
    from app.backtester.portfolio import (
        monte_carlo_simulation,
        calculate_correlation_matrix,
        calculate_drawdown_series,
        calculate_strategy_equity_curves
    )

    print("\n" + "="*50)
    print("BACKTEST EXECUTION STARTED")
    print("="*50)
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
        strategies = []
        strategy_names = {}
        
        for strategy_id in request.strategy_ids:
            # Check if strategy exists
            row = con.execute("SELECT definition, name FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
            if not row: raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
            try:
                # Handle possible JSON/Dict format issues
                strategy_data = row[0]
                if isinstance(strategy_data, str):
                    strategy_data = json.loads(strategy_data)
                
                strategy = Strategy(**strategy_data)
                strategies.append(strategy)
                strategy_names[strategy_id] = row[1]
            except Exception as e:
                print(f"Error parsing strategy {strategy_id}: {e}")
                raise HTTPException(status_code=500, detail=f"Invalid strategy format: {e}")
            
        print(f"  ✓ Loaded strategies in {time.time() - t0:.2f}s")
        
        # 2. Fetch market data based on filters
        t1 = time.time()
        print("\n[2/5] Fetching market data...")
        
        req_filters = {}
        dataset_summary = "Custom Filters"
        
        if request.query_id:
            logger_prefix = f"  - Using Saved Dataset: {request.query_id}"
            print(logger_prefix)
            sq_row = con.execute("SELECT filters, name FROM saved_queries WHERE id = ?", (request.query_id,)).fetchone()
            if not sq_row:
                req_filters = request.dataset_filters.dict() if hasattr(request.dataset_filters, 'dict') else request.dataset_filters
                print(f"  ⚠️ Saved dataset {request.query_id} not found, using request filters.")
            else:
                req_filters = json.loads(sq_row[0])
                dataset_summary = sq_row[1]
        else:
            req_filters = request.dataset_filters.dict() if hasattr(request.dataset_filters, 'dict') else request.dataset_filters
            
        print(f"  - Building query for universe selection...")
        from app.services.query_service import build_screener_query
        
        # Get universe of (Ticker, Date) using shared logic
        # We limit the universe to 3000 days/tickers to stay within memory limits for now
        rec_query, sql_p, where_d, where_i, where_m, _ = build_screener_query(req_filters, limit=3000)
        
        # OPTIMIZED FETCHING STRATEGY
        # 1. Create a temporary table with the universe (Ticker, Date, Metrics)
        print("  - Materializing universe to temporary table...")
        try:
            con.execute("CREATE OR REPLACE TEMPORARY TABLE temp_universe AS " + rec_query, sql_p)
        except Exception as e:
             # Fallback if params issue
             print(f"Temp table creation failed: {e}")
             raise
        
        # 2. Fetch Intraday 1m data by joining strictly on Ticker AND Date
        
        # Check if 'date' column exists in intraday_1m
        has_date_col = False
        try:
             # DuckDB describe
             cols = [c[0] for c in con.execute("DESCRIBE intraday_1m").fetchall()]
             if 'date' in cols: has_date_col = True
        except: pass
        
        join_condition = "i.ticker = u.ticker AND i.date = u.timestamp::DATE"
        if not has_date_col:
             join_condition = "i.ticker = u.ticker AND CAST(i.timestamp AS DATE) = CAST(u.timestamp AS DATE)"
        
        print(f"  - Fetching Intraday Data (Join optimize: {has_date_col})...")
        
        final_query = f"""
            WITH intraday_clean AS (
                SELECT 
                    i.ticker,
                    i.timestamp,
                    i.open, i.high, i.low, i.close,
                    i.volume,
                    u.pm_high, u.pm_volume,
                    u.gap_pct, u.day_return_pct as day_ret, u.rth_run_pct as rth_run
                FROM intraday_1m i
                INNER JOIN temp_universe u ON {join_condition}
            )
            SELECT * FROM intraday_clean
            ORDER BY ticker, timestamp ASC
        """
        
        market_data = con.execute(final_query).fetchdf()
        duration_fetch = time.time() - t1
        
        con.execute("DROP TABLE IF EXISTS temp_universe")
        
        if market_data.empty:
             raise HTTPException(status_code=400, detail="No market data found for given filters")
             
        
        print(f"  ✓ Fetched {len(market_data):,} rows in {duration_fetch:.2f}s")
        
        # 3. Run backtest
        t2 = time.time()
        print("\n[3/5] Running backtest engine...")
        engine = BacktestEngine(
            strategies=strategies,
            weights=request.weights,
            market_data=market_data,
            commission_per_trade=request.commission_per_trade,
            initial_capital=request.initial_capital,
            max_holding_minutes=request.max_holding_minutes
        )
        
        result = engine.run()
        print(f"  ✓ Backtest execution in {time.time() - t2:.2f}s ({result.total_trades} trades)")
        
        # 4. Calculate additional metrics
        t3 = time.time()
        
        monte_carlo_result = monte_carlo_simulation(result.trades, request.initial_capital, 1000)
        
        correlation_matrix = None
        if len(strategies) > 1:
            strategy_curves = calculate_strategy_equity_curves(result.trades, request.initial_capital)
            balance_curves = {sid: [point['balance'] for point in curve] for sid, curve in strategy_curves.items()}
            correlation_matrix = calculate_correlation_matrix(balance_curves)
        
        drawdown_series = calculate_drawdown_series(result.equity_curve)
        
        # 5. Prepare Result Object
        run_id = str(uuid4())
        now = datetime.now()
        total_return_pct = ((result.final_balance - request.initial_capital) / request.initial_capital * 100)
        total_return_r = sum(t.get('r_multiple', 0) for t in result.trades if t.get('r_multiple') is not None)
        
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
                 "probability_of_ruin": monte_carlo_result.probability_of_ruin
             },
             "executed_at": now.isoformat(),
             "initial_capital": request.initial_capital
        }
        
        # 5.5 CROSS-VALIDATION (Double Audit)
        print(f"\nAUDIT: Running VectorBT validation...")
        try:
            from app.backtester.backtest_validator import validate_results
            audit_report = validate_results(results_json)
            results_json['audit'] = audit_report
            print("  ✓ Audit completed")
        except Exception as audit_err:
            print(f"  ⚠️ Audit skipped or failed: {audit_err}")
        
        # 6. SAVE RESULTS TO DATABASE
        print("\n[5/5] Saving results to database...")
        con.execute("""
            INSERT INTO backtest_results (
                id, strategy_ids, dataset_summary, total_trades, win_rate, 
                final_balance, max_drawdown_pct, executed_at, results_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            json.dumps(request.strategy_ids),
            dataset_summary,
            result.total_trades,
            result.win_rate,
            result.final_balance,
            result.max_drawdown_pct,
            now,
            json.dumps(results_json)
        ))
        
        print(f"  ✓ Validated and saved run {run_id}")
        
        print(f"  ✓ Metrics calculated in {time.time() - t3:.2f}s")
        print(f"✓ Total Request Time: {time.time() - start_total:.2f}s")
        
        return BacktestResponse(
            run_id=run_id,
            status="success",
            message=f"Backtest completed: {result.total_trades} trades, {result.win_rate:.1f}% win rate",
            results=BacktestResultResponse(**results_json)
        )
        
    except Exception as e:
        print(f"Backtest execution error: {e}")
        # traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/results/{run_id}", response_model=BacktestResultResponse)
def get_backtest_results(run_id: str):
    """
    Get full results for a backtest run
    """
    try:
        con = get_db_connection(read_only=True)
        
        row = con.execute(
            "SELECT results_json FROM backtest_results WHERE id = ?",
            (run_id,)
        ).fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Backtest run not found")
        
        results = json.loads(row[0])
        
        return BacktestResultResponse(**results)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching backtest results: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
def get_backtest_history():
    """
    Get list of all backtest runs
    """
    try:
        con = get_db_connection(read_only=True)
        
        rows = con.execute(
            """
            SELECT 
                id, strategy_ids, dataset_summary,
                total_trades, win_rate, final_balance,
                max_drawdown_pct, executed_at
            FROM backtest_results
            ORDER BY executed_at DESC
            LIMIT 50
            """
        ).fetchall()
        
        history = []
        for row in rows:
            history.append({
                "run_id": row[0],
                # strategy_ids might be stored as string if json encoding used
                "strategy_ids": json.loads(row[1]) if isinstance(row[1], str) else row[1],
                "dataset_summary": row[2],
                "total_trades": row[3],
                "win_rate": row[4],
                "final_balance": row[5],
                "max_drawdown_pct": row[6],
                "executed_at": row[7]
            })
        
        return {"history": history}
        
    except Exception as e:
        print(f"Error fetching backtest history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{run_id}")
def delete_backtest(run_id: str):
    """
    Delete a backtest run
    """
    try:
        con = get_db_connection()
        
        row = con.execute(
            "SELECT id FROM backtest_results WHERE id = ?",
            (run_id,)
        ).fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Backtest run not found")
        
        con.execute("DELETE FROM backtest_results WHERE id = ?", (run_id,))
        
        return {"status": "success", "message": "Backtest deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting backtest: {e}")
        raise HTTPException(status_code=500, detail=str(e))
