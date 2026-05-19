"""
Backtest API Endpoints
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List, Dict, Optional, Union
from pydantic import BaseModel
from uuid import uuid4
import json

from app.database import get_db_connection
from app.routers.data import FilterRequest
from app.services.backtest_service import run_backtest_task

router = APIRouter()

# Global dict for tracking backtest execution status
run_statuses = {}


class BacktestRequest(BaseModel):
    """Request to run a backtest"""
    strategy_ids: List[str]
    weights: Dict[str, float]  # strategy_id -> weight % (0-100)
    dataset_filters: FilterRequest  # Reuse from Market Analysis
    query_id: Optional[str] = None  # Dynamic dataset ID
    commission_per_trade: float = 1.0
    commission_per_share: float = 0.0
    locate_cost_per_100: float = 0.0
    slippage_pct: float = 0.0
    lookahead_prevention: bool = False
    risk_per_trade_usd: Optional[float] = None  # if set, each trade risks this amount in USD
    risk_per_trade_r: Optional[float] = None  # frontend sends this as dollar amount per trade
    market_interval: Optional[Union[str, List[str]]] = None  # PM, RTH, AM or list
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
def run_backtest(request: BacktestRequest, background_tasks: BackgroundTasks):
    """
    Start a backtest execution in the background
    """
    run_id = str(uuid4())
    run_statuses[run_id] = {"status": "processing", "message": "Backtest started"}
    
    background_tasks.add_task(run_backtest_task, run_id, request, run_statuses)
    
    return BacktestResponse(
        run_id=run_id,
        status="processing",
        message="Backtest execution started in the background",
        results=None
    )


@router.get("/status/{run_id}", response_model=BacktestResponse)
def get_backtest_status(run_id: str):
    """
    Check the status of a backtest run.
    """
    if run_id in run_statuses:
        status_info = run_statuses[run_id]
        return BacktestResponse(
            run_id=run_id,
            status=status_info["status"],
            message=status_info.get("message", ""),
            results=None
        )
    
    # If not in memory, check if it's in the DB
    try:
        con = get_db_connection(read_only=True)
        row = con.execute("SELECT id FROM backtest_results WHERE id = ?", (run_id,)).fetchone()
        if row:
            return BacktestResponse(
                run_id=run_id,
                status="completed",
                message="Backtest completed",
                results=None
            )
    except Exception:
        pass

    raise HTTPException(status_code=404, detail="Backtest run not found or expired")


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
