"""
Strategy Search API Endpoints - Database View
"""
from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks
from typing import List, Dict, Optional
from pydantic import BaseModel
from datetime import datetime
import json
import os
import uuid

from app.database import get_db_connection, get_user_db_connection, get_user_db_lock
from app.auth import get_current_user_id, scope_clause

router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────
# Auto-persistence helpers (PRD_persistir_backtests_ANTIGRAVITY — Parte A)
# ──────────────────────────────────────────────────────────────────────────
# Reused by the manual save endpoint (save_backtest_result) AND the background
# auto-save on every successful backtest (routers/backtest.py). Centralizing
# the aggregate_metrics → column mapping keeps the Baúl reading non-zero values
# regardless of who wrote the row.

AUTOSAVE_KEEP = int(os.getenv("BTT_AUTOSAVE_KEEP", "50"))


def _map_aggregate_metrics(results_json: dict) -> dict:
    """Map AggregateMetrics field names → backtest_results columns."""
    aggregate = (
        results_json.get("aggregate_metrics") or {}
        if isinstance(results_json, dict)
        else {}
    )
    return {
        "win_rate": aggregate.get("win_rate_pct", aggregate.get("win_rate", 0)) or 0,
        "profit_factor": aggregate.get("avg_profit_factor", aggregate.get("profit_factor", 0)) or 0,
        "sharpe_ratio": aggregate.get("avg_sharpe", aggregate.get("sharpe_ratio", 0)) or 0,
        "avg_r_multiple": aggregate.get("avg_r_per_day", aggregate.get("avg_r_multiple", 0)) or 0,
        "total_return_pct": aggregate.get("total_return_pct", 0) or 0,
        "total_return_r": aggregate.get("total_return_r", 0) or 0,
        "max_drawdown_pct": aggregate.get("max_drawdown_pct", 0) or 0,
        "total_trades": aggregate.get("total_trades", 0) or 0,
    }


def persist_backtest_row(
    con,
    *,
    id: str,
    strategy_ids,
    results_json: dict,
    search_mode: str,
    search_space: str,
    user_id,
):
    """INSERT OR REPLACE a backtest_results row (idempotent on `id`).

    The caller owns the connection (and the user-db lock). Maps
    results_json['aggregate_metrics'] to the typed columns so the Baúl shows
    non-zero metrics. Used by manual saves and auto-saves alike.
    """
    m = _map_aggregate_metrics(results_json or {})
    now = datetime.now()
    con.execute(
        """
        INSERT OR REPLACE INTO backtest_results (
            id, strategy_ids, results_json,
            total_trades, win_rate, profit_factor,
            avg_r_multiple, total_return_r, total_return_pct,
            max_drawdown_pct, sharpe_ratio, executed_at,
            search_mode, search_space, user_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            id,
            json.dumps(strategy_ids),
            json.dumps(results_json),
            m["total_trades"],
            m["win_rate"],
            m["profit_factor"],
            m["avg_r_multiple"],
            m["total_return_r"],
            m["total_return_pct"],
            m["max_drawdown_pct"],
            m["sharpe_ratio"],
            now,
            search_mode,
            search_space,
            user_id,
        ],
    )


def prune_autosaved(con, keep: int):
    """Keep only the `keep` most recent search_mode='auto' rows.

    Deletes the overflow (oldest by executed_at DESC) AND their on-disk
    {id}.result / {id}.equity files. Never touches 'manual' rows. Best-effort:
    any error is swallowed so it can never break a backtest.
    """
    if keep is None or keep < 0:
        return
    try:
        overflow = con.execute(
            "SELECT id FROM backtest_results WHERE search_mode = 'auto' "
            "ORDER BY executed_at DESC OFFSET ?",
            [keep],
        ).fetchall()
    except Exception as e:
        print(f"[WARN] prune_autosaved select failed: {e}")
        return

    # Lazy import to avoid a circular dependency at module load time.
    try:
        from app.services import backtest_jobs
        _path_fns = [backtest_jobs._result_path, backtest_jobs._equity_path]
    except Exception:
        _path_fns = []

    for (old_id,) in overflow:
        try:
            con.execute("DELETE FROM backtest_results WHERE id = ?", [old_id])
        except Exception:
            pass
        for path_fn in _path_fns:
            try:
                p = path_fn(old_id)
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                continue


def autosave_backtest(
    job_id: str,
    *,
    strategy_ids,
    results_json: dict,
    user_id,
    keep: int = AUTOSAVE_KEEP,
):
    """Persist a successful backtest as search_mode='auto' + prune overflow.

    Opens its own user-db connection under the lock. Intended to be called from
    the background runner wrapped in try/except (never raises out of the
    caller's success path).
    """
    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection()
        try:
            persist_backtest_row(
                con,
                id=job_id,
                strategy_ids=strategy_ids,
                results_json=results_json,
                search_mode="auto",
                search_space="auto_run",
                user_id=user_id,
            )
            prune_autosaved(con, keep)
        finally:
            con.close()


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
def save_backtest_result(data: dict, background_tasks: BackgroundTasks, user_id: Optional[str] = Depends(get_current_user_id)):
    """
    Persist a backtest run into backtest_results so it shows up in the Baul
    linked to the corresponding strategy via strategy_ids.
    """
    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection()
        try:
            new_id = str(uuid.uuid4())
            strategy_ids = data.get("strategy_ids", [])
            results_json = data.get("results_json", {})

            persist_backtest_row(
                con,
                id=new_id,
                strategy_ids=strategy_ids,
                results_json=results_json,
                search_mode="manual",
                search_space="user_save",
                user_id=user_id,
            )
        finally:
            con.close()

    try:
        from app.gcs_sync import upload_user_db
        background_tasks.add_task(upload_user_db)
        print(f"[GCS] users.duckdb upload scheduled in background after backtest save {new_id}")
    except Exception as e:
        print(f"[WARN] GCS upload background scheduling failed after save_backtest_result: {e}")

    return {"id": new_id, "status": "saved"}


@router.post("/filter")
def filter_strategies(filters: StrategySearchFilters, user_id: Optional[str] = Depends(get_current_user_id)):
    """
    Filter saved strategies using Pass Criteria
    """
    try:
        con = get_user_db_connection(read_only=True)

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


@router.get("/recent")
def list_recent_runs(
    limit: int = Query(20, ge=1, le=100),
    search_mode: Optional[str] = Query(None),
    user_id: Optional[str] = Depends(get_current_user_id),
):
    """Lista LIGERA de runs recientes para el panel 'Últimas pruebas' de Portfolio.

    /list arrastra el results_json completo de cada fila (decenas de MB con
    historial); aquí solo metadatos + métricas tipadas, con label y strategy_ids
    — nada del payload. El contenido completo se pide luego por id (GET /{id}).
    """
    con = get_user_db_connection(read_only=True)
    try:
        scope_sql, scope_params = scope_clause(user_id)
        mode_sql = " AND search_mode = ?" if search_mode else ""
        mode_params = [search_mode] if search_mode else []
        rows = con.execute(
            f"""
            SELECT
                id, executed_at, search_mode,
                json_extract_string(results_json, '$.label') AS label,
                strategy_ids,
                total_trades, win_rate, profit_factor,
                avg_r_multiple, total_return_r, total_return_pct,
                max_drawdown_pct, sharpe_ratio
            FROM backtest_results
            WHERE 1=1{scope_sql}{mode_sql}
            ORDER BY executed_at DESC
            LIMIT ?
            """,
            [*scope_params, *mode_params, limit],
        ).fetchall()
        runs = [
            {
                "id": r[0],
                "executed_at": str(r[1]),
                "search_mode": r[2],
                "label": r[3],
                "strategy_ids": json.loads(r[4]) if r[4] else [],
                "total_trades": r[5],
                "win_rate": r[6],
                "profit_factor": r[7],
                "avg_r_multiple": r[8],
                "total_return_r": r[9],
                "total_return_pct": r[10],
                "max_drawdown_pct": r[11],
                "sharpe_ratio": r[12],
            }
            for r in rows
        ]
        return {"runs": runs, "count": len(runs)}
    except Exception as e:
        print(f"Error listing recent runs: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        con.close()


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
        con = get_user_db_connection(read_only=True)

        scope_sql, scope_params = scope_clause(user_id)
        rows = con.execute(
            f"""
            SELECT
                id, strategy_ids, results_json,
                total_trades, win_rate, profit_factor,
                avg_r_multiple, total_return_r, total_return_pct,
                max_drawdown_pct, sharpe_ratio, executed_at, search_mode
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
                "search_mode": row[12],
                "label": (results_json.get("label") if isinstance(results_json, dict) else None),
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
def toggle_validation(backtest_id: str, background_tasks: BackgroundTasks, user_id: Optional[str] = Depends(get_current_user_id)):
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
        background_tasks.add_task(upload_user_db)
        print(f"[GCS] users.duckdb upload scheduled in background after toggling validation for {backtest_id}")
    except Exception as e:
        print(f"[WARN] GCS upload background scheduling failed after toggle_validation: {e}")
        
    return {"status": "success", "is_validated": new_status}



@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: str, background_tasks: BackgroundTasks, user_id: Optional[str] = Depends(get_current_user_id)):
    """
    Delete a saved strategy
    """
    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection()
        try:
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
        finally:
            con.close()

    try:
        from app.gcs_sync import upload_user_db
        background_tasks.add_task(upload_user_db)
    except Exception as e:
        print(f"[WARN] GCS upload background scheduling failed after delete_strategy: {e}")

    return {"status": "success", "message": "Strategy deleted"}


@router.get("/{backtest_id}")
def get_backtest_by_id(backtest_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    """results_json COMPLETO de un run guardado.

    Es la fuente para reabrir un run desde 'Últimas pruebas': el payload del
    autosave lleva aggregate_metrics, trades, day_results, global_equity,
    backtest_params y el snapshot de strategy_definition (patrón recuperado
    del router legacy desmontado _backtest_btt_legacy.py).
    """
    scope_sql, scope_params = scope_clause(user_id)
    con = get_user_db_connection(read_only=True)
    try:
        row = con.execute(
            f"""
            SELECT results_json, strategy_ids, executed_at, search_mode
            FROM backtest_results WHERE id = ?{scope_sql}
            """,
            [backtest_id, *scope_params],
        ).fetchone()
    finally:
        con.close()
    if not row:
        raise HTTPException(status_code=404, detail="Backtest result not found")
    try:
        payload = json.loads(row[0]) if row[0] else {}
    except Exception:
        payload = {}
    return {
        "id": backtest_id,
        "strategy_ids": json.loads(row[1]) if row[1] else [],
        "executed_at": str(row[2]),
        "search_mode": row[3],
        "results_json": payload,
    }


@router.post("/export")
def export_strategies(strategy_ids: List[str], user_id: Optional[str] = Depends(get_current_user_id)):
    """
    Export selected strategies to CSV format
    """
    try:
        con = get_user_db_connection(read_only=True)

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
