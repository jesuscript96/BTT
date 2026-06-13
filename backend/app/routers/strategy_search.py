"""
Strategy Search API Endpoints - Database View
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Dict, Optional
from pydantic import BaseModel
from datetime import datetime
import json
import uuid

from app.database import get_db_connection, get_user_db_connection, get_user_db_lock
from app.auth import get_current_user_id, scope_clause

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


@router.post("/", response_model=dict)
def save_backtest_result(data: dict, user_id: Optional[str] = Depends(get_current_user_id)):
    """
    Persist a backtest run into backtest_results so it shows up in the Baul
    linked to the corresponding strategy via strategy_ids.
    """
    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection()
        try:
            new_id = str(uuid.uuid4())
            now = datetime.now()

            strategy_ids = data.get("strategy_ids", [])
            results_json = data.get("results_json", {})

            # AggregateMetrics uses different field names than backtest_results columns;
            # map carefully so the Baul reads non-zero values.
            aggregate = results_json.get("aggregate_metrics", {}) or {}

            win_rate = aggregate.get("win_rate_pct", aggregate.get("win_rate", 0)) or 0
            profit_factor = aggregate.get("avg_profit_factor", aggregate.get("profit_factor", 0)) or 0
            sharpe = aggregate.get("avg_sharpe", aggregate.get("sharpe_ratio", 0)) or 0
            avg_r = aggregate.get("avg_r_per_day", aggregate.get("avg_r_multiple", 0)) or 0
            total_return_pct = aggregate.get("total_return_pct", 0) or 0
            total_return_r = aggregate.get("total_return_r", 0) or 0
            max_dd = aggregate.get("max_drawdown_pct", 0) or 0
            total_trades = aggregate.get("total_trades", 0) or 0

            con.execute("""
                INSERT INTO backtest_results (
                    id, strategy_ids, results_json,
                    total_trades, win_rate, profit_factor,
                    avg_r_multiple, total_return_r, total_return_pct,
                    max_drawdown_pct, sharpe_ratio, executed_at,
                    search_mode, search_space, user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                new_id,
                json.dumps(strategy_ids),
                json.dumps(results_json),
                total_trades,
                win_rate,
                profit_factor,
                avg_r,
                total_return_r,
                total_return_pct,
                max_dd,
                sharpe,
                now,
                "manual",
                "user_save",
                user_id,
            ])
        finally:
            con.close()

    try:
        from app.gcs_sync import upload_user_db
        upload_user_db()
        print(f"[GCS] users.duckdb uploaded after backtest save {new_id}")
    except Exception as e:
        print(f"[WARN] GCS upload failed after save_backtest_result: {e}")

    return {"id": new_id, "status": "saved"}


@router.post("/filter")
def filter_strategies(filters: StrategySearchFilters, user_id: Optional[str] = Depends(get_current_user_id)):
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

        # Restrict to the caller's own results (plus legacy NULL-owner rows).
        scope_sql, scope_params = scope_clause(user_id)
        query += scope_sql
        params.extend(scope_params)
        
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
            is_validated = results_json.get('is_validated', None)
            
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
                "executed_at": row[11],
                "results_json": results_json,
                "is_validated": is_validated
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
    offset: int = Query(0, ge=0),
    user_id: Optional[str] = Depends(get_current_user_id),
):
    """
    Get all saved strategies with pagination
    """
    try:
        con = get_db_connection(read_only=True)

        scope_sql, scope_params = scope_clause(user_id)
        rows = con.execute(
            f"""
            SELECT
                id, strategy_ids, results_json,
                total_trades, win_rate, profit_factor,
                avg_r_multiple, total_return_r, total_return_pct,
                max_drawdown_pct, sharpe_ratio, executed_at
            FROM backtest_results
            WHERE 1=1{scope_sql}
            ORDER BY executed_at DESC
            LIMIT ? OFFSET ?
            """,
            [*scope_params, limit, offset],
        ).fetchall()
        
        strategies = []
        for row in rows:
            results_json = json.loads(row[2])
            strategy_names = results_json.get('strategy_names', [])
            is_validated = results_json.get('is_validated', None)
            
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
                "executed_at": row[11],
                "results_json": results_json,
                "is_validated": is_validated
            })
        
        # Get total count
        total = con.execute(
            f"SELECT COUNT(*) FROM backtest_results WHERE 1=1{scope_sql}",
            scope_params,
        ).fetchone()[0]
        
        return {
            "strategies": strategies,
            "total_count": total,
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        print(f"Error listing strategies: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{backtest_id}/toggle-validation")
def toggle_validation(backtest_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    """
    Toggle the is_validated flag inside results_json for a backtest result.
    """
    lock = get_user_db_lock()
    scope_sql, scope_params = scope_clause(user_id)
    with lock:
        con = get_user_db_connection()
        try:
            row = con.execute(
                f"SELECT results_json FROM backtest_results WHERE id = ?{scope_sql}",
                [backtest_id, *scope_params],
            ).fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Backtest result not found")
            
            results_json = json.loads(row[0]) if row[0] else {}
            current_status = results_json.get("is_validated", None)
            
            # If not set, let's toggle based on default logic (win_rate >= 50 and sharpe_ratio > 1.5)
            if current_status is None:
                # We can load the parent row details to match the client logic
                parent_row = con.execute(
                    "SELECT win_rate, sharpe_ratio FROM backtest_results WHERE id = ?",
                    (backtest_id,)
                ).fetchone()
                win_rate = parent_row[0] if parent_row else 0
                sharpe = parent_row[1] if parent_row else 0
                current_status = (win_rate >= 50 and sharpe > 1.5)
                
            new_status = not current_status
            results_json["is_validated"] = new_status
            
            con.execute(
                "UPDATE backtest_results SET results_json = ? WHERE id = ?",
                (json.dumps(results_json), backtest_id)
            )
        finally:
            con.close()
            
    try:
        from app.gcs_sync import upload_user_db
        upload_user_db()
        print(f"[GCS] users.duckdb uploaded after toggling validation for {backtest_id}")
    except Exception as e:
        print(f"[WARN] GCS upload failed after toggle_validation: {e}")
        
    return {"status": "success", "is_validated": new_status}



@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    """
    Delete a saved strategy
    """
    try:
        con = get_db_connection()

        scope_sql, scope_params = scope_clause(user_id)
        row = con.execute(
            f"SELECT id FROM backtest_results WHERE id = ?{scope_sql}",
            [strategy_id, *scope_params],
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Strategy not found")

        con.execute(
            f"DELETE FROM backtest_results WHERE id = ?{scope_sql}",
            [strategy_id, *scope_params],
        )

        return {"status": "success", "message": "Strategy deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export")
def export_strategies(strategy_ids: List[str], user_id: Optional[str] = Depends(get_current_user_id)):
    """
    Export selected strategies to CSV format
    """
    try:
        con = get_db_connection(read_only=True)

        placeholders = ",".join(["?" for _ in strategy_ids])
        scope_sql, scope_params = scope_clause(user_id)
        query = f"""
            SELECT
                id, strategy_ids, total_trades, win_rate,
                profit_factor, avg_r_multiple, total_return_pct,
                max_drawdown_pct, sharpe_ratio, executed_at
            FROM backtest_results
            WHERE id IN ({placeholders}){scope_sql}
        """

        rows = con.execute(query, [*strategy_ids, *scope_params]).fetchall()
        
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
