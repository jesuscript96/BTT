"""
Strategy Search API Endpoints - Database View
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Optional
from pydantic import BaseModel
from datetime import datetime
import json

from app.database import get_db_connection

router = APIRouter()


class PassCriteria(BaseModel):
    """Filtering criteria for strategy search"""
    min_trades: Optional[int] = None
    min_win_rate: Optional[float] = None
    min_profit_factor: Optional[float] = None
    min_expected_value: Optional[float] = None  # avg_r_multiple
    min_net_profit: Optional[float] = None  # total_return_r


class StrategySearchFilters(BaseModel):
    """Complete search filters"""
    search_mode: Optional[str] = None
    search_space: Optional[str] = None
    dataset_id: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    pass_criteria: Optional[PassCriteria] = None


class SavedStrategyResponse(BaseModel):
    """Single saved strategy result"""
    id: str
    strategy_ids: List[str]
    strategy_names: List[str]
    total_return_pct: float
    total_return_r: float
    profit_factor: float
    win_rate: float
    max_drawdown_pct: float
    total_trades: int
    avg_r_multiple: float
    sharpe_ratio: float
    executed_at: str


@router.post("/filter")
def filter_strategies(filters: StrategySearchFilters):
    """
    Filter saved strategies using Pass Criteria
    """
    try:
        con = get_db_connection(read_only=True)
        
        # Build dynamic query
        query = """
            SELECT 
                id, strategy_ids, results_json,
                total_trades, win_rate, profit_factor,
                avg_r_multiple, total_return_r, total_return_pct,
                max_drawdown_pct, sharpe_ratio, executed_at
            FROM backtest_results
            WHERE 1=1
        """
        params = []
        
        # Apply Pass Criteria filters
        if filters.pass_criteria:
            pc = filters.pass_criteria
            
            if pc.min_trades is not None:
                query += " AND total_trades >= ?"
                params.append(pc.min_trades)
            
            if pc.min_win_rate is not None:
                query += " AND win_rate >= ?"
                params.append(pc.min_win_rate)
            
            if pc.min_profit_factor is not None:
                query += " AND profit_factor >= ?"
                params.append(pc.min_profit_factor)
            
            if pc.min_expected_value is not None:
                query += " AND avg_r_multiple >= ?"
                params.append(pc.min_expected_value)
            
            if pc.min_net_profit is not None:
                query += " AND total_return_r >= ?"
                params.append(pc.min_net_profit)
        
        # Apply metadata filters
        if filters.search_mode:
            query += " AND search_mode = ?"
            params.append(filters.search_mode)
        
        if filters.search_space:
            query += " AND search_space = ?"
            params.append(filters.search_space)
        
        if filters.date_from:
            query += " AND executed_at >= ?"
            params.append(filters.date_from)
        
        if filters.date_to:
            query += " AND executed_at <= ?"
            params.append(filters.date_to)
        
        query += " ORDER BY profit_factor DESC, total_return_pct DESC LIMIT 500"
        
        rows = con.execute(query, params).fetchall()
        
        strategies = []
        for row in rows:
            results_json = json.loads(row[2])
            strategy_names = results_json.get('strategy_names', [])
            
            strategies.append({
                "id": row[0],
                "strategy_ids": json.loads(row[1]),
                "strategy_names": strategy_names,
                "total_trades": row[3],
                "win_rate": row[4],
                "profit_factor": row[5],
                "avg_r_multiple": row[6],
                "total_return_r": row[7],
                "total_return_pct": row[8],
                "max_drawdown_pct": row[9],
                "sharpe_ratio": row[10],
                "executed_at": row[11]
            })
        
        return {
            "strategies": strategies,
            "total_count": len(strategies)
        }
        
    except Exception as e:
        print(f"Error filtering strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
def list_all_strategies(
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0)
):
    """
    Get all saved strategies with pagination
    """
    try:
        con = get_db_connection(read_only=True)
        
        rows = con.execute(
            """
            SELECT 
                id, strategy_ids, results_json,
                total_trades, win_rate, profit_factor,
                avg_r_multiple, total_return_r, total_return_pct,
                max_drawdown_pct, sharpe_ratio, executed_at
            FROM backtest_results
            ORDER BY executed_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset)
        ).fetchall()
        
        strategies = []
        for row in rows:
            results_json = json.loads(row[2])
            strategy_names = results_json.get('strategy_names', [])
            
            strategies.append({
                "id": row[0],
                "strategy_ids": json.loads(row[1]),
                "strategy_names": strategy_names,
                "total_trades": row[3],
                "win_rate": row[4],
                "profit_factor": row[5],
                "avg_r_multiple": row[6],
                "total_return_r": row[7],
                "total_return_pct": row[8],
                "max_drawdown_pct": row[9],
                "sharpe_ratio": row[10],
                "executed_at": row[11]
            })
        
        # Get total count
        total = con.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0]
        
        return {
            "strategies": strategies,
            "total_count": total,
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        print(f"Error listing strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: str):
    """
    Delete a saved strategy
    """
    try:
        con = get_db_connection()
        
        row = con.execute(
            "SELECT id FROM backtest_results WHERE id = ?",
            (strategy_id,)
        ).fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        con.execute("DELETE FROM backtest_results WHERE id = ?", (strategy_id,))
        
        return {"status": "success", "message": "Strategy deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export")
def export_strategies(strategy_ids: List[str]):
    """
    Export selected strategies to CSV format
    """
    try:
        con = get_db_connection(read_only=True)
        
        placeholders = ",".join(["?" for _ in strategy_ids])
        query = f"""
            SELECT 
                id, strategy_ids, total_trades, win_rate,
                profit_factor, avg_r_multiple, total_return_pct,
                max_drawdown_pct, sharpe_ratio, executed_at
            FROM backtest_results
            WHERE id IN ({placeholders})
        """
        
        rows = con.execute(query, strategy_ids).fetchall()
        
        csv_data = []
        csv_data.append([
            "ID", "Strategy IDs", "Total Trades", "Win Rate %",
            "Profit Factor", "Avg R-Multiple", "Total Return %",
            "Max Drawdown %", "Sharpe Ratio", "Executed At"
        ])
        
        for row in rows:
            csv_data.append([
                row[0],
                json.loads(row[1]),
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9]
            ])
        
        return {
            "csv_data": csv_data,
            "filename": f"strategies_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        }
        
    except Exception as e:
        print(f"Error exporting strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))
