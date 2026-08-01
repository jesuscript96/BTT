from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List, Optional
import json
from uuid import uuid4
from datetime import datetime

from app.database import get_user_db_connection, get_user_db_lock
from app.auth import get_current_user_id, scope_clause
from app.schemas.strategy import Strategy, StrategyCreate

router = APIRouter()

@router.post("/", response_model=Strategy)
def create_strategy(strategy: StrategyCreate, background_tasks: BackgroundTasks, user_id: Optional[str] = Depends(get_current_user_id)):
    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection()
        try:
            new_id = str(uuid4())
            now = datetime.now()

            full_strategy = Strategy(
                **strategy.model_dump(),
                id=new_id,
                created_at=now.isoformat()
            )

            definition_json = json.dumps({
                "bias": strategy.bias,
                "apply_day": strategy.apply_day,
                "postgap_preconditions": [p.model_dump() for p in strategy.postgap_preconditions] if strategy.postgap_preconditions else None,
                "universe_filters": strategy.universe_filters.model_dump() if strategy.universe_filters else None,
                "entry_logic": strategy.entry_logic.model_dump() if strategy.entry_logic else None,
                "exit_logic": strategy.exit_logic.model_dump() if strategy.exit_logic else None,
                "risk_management": strategy.risk_management.model_dump() if strategy.risk_management else None,
                "is_wizard": strategy.is_wizard,
                "dataset_id": strategy.dataset_id,
                "market_sessions": strategy.market_sessions,
                "custom_start_time": strategy.custom_start_time,
                "custom_end_time": strategy.custom_end_time,
            })

            con.execute(
                """
                INSERT INTO strategies (id, name, description, created_at, updated_at, definition, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id,
                    strategy.name,
                    strategy.description,
                    now,
                    now,
                    definition_json,
                    user_id,
                )
            )
        finally:
            con.close()

    try:
        from app.gcs_sync import upload_user_db
        background_tasks.add_task(upload_user_db)
        print("[GCS] users.duckdb upload scheduled in background after strategy save")
    except Exception as e:
        print(f"[WARN] GCS upload background scheduling failed: {e}")

    return full_strategy

@router.put("/{strategy_id}", response_model=Strategy)
def update_strategy(strategy_id: str, strategy: StrategyCreate, background_tasks: BackgroundTasks, user_id: Optional[str] = Depends(get_current_user_id)):
    lock = get_user_db_lock()
    scope_sql, scope_params = scope_clause(user_id)
    with lock:
        con = get_user_db_connection()
        try:
            # Ownership check: without the scope filter any authenticated user
            # could overwrite another user's strategy by guessing its id (IDOR).
            row = con.execute(
                f"SELECT created_at FROM strategies WHERE id = ?{scope_sql}",
                [strategy_id, *scope_params],
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Strategy not found")
            created_at = row[0]
            now = datetime.now()

            definition_json = json.dumps({
                "bias": strategy.bias,
                "apply_day": strategy.apply_day,
                "postgap_preconditions": [p.model_dump() for p in strategy.postgap_preconditions] if strategy.postgap_preconditions else None,
                "universe_filters": strategy.universe_filters.model_dump() if strategy.universe_filters else None,
                "entry_logic": strategy.entry_logic.model_dump() if strategy.entry_logic else None,
                "exit_logic": strategy.exit_logic.model_dump() if strategy.exit_logic else None,
                "risk_management": strategy.risk_management.model_dump() if strategy.risk_management else None,
                "is_wizard": strategy.is_wizard,
                "dataset_id": strategy.dataset_id,
                "market_sessions": strategy.market_sessions,
                "custom_start_time": strategy.custom_start_time,
                "custom_end_time": strategy.custom_end_time,
            })

            con.execute(
                f"""
                UPDATE strategies
                SET name = ?, description = ?, updated_at = ?, definition = ?
                WHERE id = ?{scope_sql}
                """,
                (
                    strategy.name,
                    strategy.description,
                    now,
                    definition_json,
                    strategy_id,
                    *scope_params,
                )
            )
        finally:
            con.close()

    try:
        from app.gcs_sync import upload_user_db
        background_tasks.add_task(upload_user_db)
        print("[GCS] users.duckdb upload scheduled in background after strategy update")
    except Exception as e:
        print(f"[WARN] GCS upload background scheduling failed: {e}")

    return Strategy(
        **strategy.model_dump(),
        id=strategy_id,
        created_at=str(created_at),
        updated_at=now.isoformat()
    )

@router.get("/")
def list_strategies(user_id: Optional[str] = Depends(get_current_user_id)):
    con = get_user_db_connection(read_only=True)
    scope_sql, scope_params = scope_clause(user_id)
    try:
        rows = con.execute(
            f"SELECT id, name, description, created_at, updated_at, definition "
            f"FROM strategies WHERE 1=1{scope_sql} ORDER BY created_at DESC",
            scope_params,
        ).fetchall()
    except Exception as e:
        print(f"list_strategies DB error: {e}")
        return []
    finally:
        con.close()
    strategies = []
    for row in rows:
        if not row or row[5] is None:
            continue
        raw = row[5]
        if isinstance(raw, dict):
            strategy_dict = raw
        else:
            try:
                strategy_dict = json.loads(raw)
            except (TypeError, ValueError) as e:
                print(f"Error parsing strategy JSON: {e}")
                continue
        try:
            strategy_dict["id"] = row[0]
            strategy_dict["name"] = row[1]
            strategy_dict["description"] = row[2]
            strategy_dict["created_at"] = str(row[3]) if row[3] else None
            strategy_dict["updated_at"] = str(row[4]) if row[4] else None
            strategies.append(Strategy(**strategy_dict))
        except Exception as e:
            print(f"Error building Strategy: {e}")
            continue

    # El respaldo a GCS se ha quitado: ese parquet es una foto congelada de marzo de
    # 2026, SIN columna de dueño, y se servía a todo el mundo sin filtrar (33 estrategias
    # tipo "Test V17"/"asgfasdg"). Con varios usuarios en la app eso es una fuga y ensucia
    # el Baúl de todos. El parquet sigue en GCS por si hiciera falta; simplemente no se lista.
    return [s.model_dump() if hasattr(s, "model_dump") else s for s in strategies]

@router.get("/{strategy_id}")
def get_strategy(strategy_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    con = get_user_db_connection(read_only=True)
    scope_sql, scope_params = scope_clause(user_id)
    try:
        row = con.execute(
            f"SELECT id, name, description, created_at, updated_at, definition "
            f"FROM strategies WHERE id = ?{scope_sql}",
            [strategy_id, *scope_params],
        ).fetchone()
        if row:
            strategy_dict = json.loads(row[5]) if isinstance(row[5], str) else (row[5] or {})
            strategy_dict["id"] = row[0]
            strategy_dict["name"] = row[1]
            strategy_dict["description"] = row[2]
            strategy_dict["created_at"] = str(row[3]) if row[3] else None
            strategy_dict["updated_at"] = str(row[4]) if row[4] else None
            return strategy_dict
    finally:
        con.close()

    # Sin respaldo a GCS: servía cualquier estrategia del parquet legacy por id, sin mirar
    # dueño — bastaba conocer el id para leer la de otro. Ver list_strategies.
    raise HTTPException(status_code=404, detail="Strategy not found")

@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: str, background_tasks: BackgroundTasks, user_id: Optional[str] = Depends(get_current_user_id)):
    # NOTE: DELETE only works for local strategies.
    # Strategies that only exist in GCS parquet cannot be deleted from here.
    # GCS parquet is read-only from the backend.
    lock = get_user_db_lock()
    scope_sql, scope_params = scope_clause(user_id)
    with lock:
        con = get_user_db_connection()
        try:
            row = con.execute(
                f"SELECT id FROM strategies WHERE id = ?{scope_sql}",
                [strategy_id, *scope_params],
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Strategy not found")
            con.execute(
                f"DELETE FROM strategies WHERE id = ?{scope_sql}",
                [strategy_id, *scope_params],
            )
        finally:
            con.close()

    try:
        from app.gcs_sync import upload_user_db
        background_tasks.add_task(upload_user_db)
        print("[GCS] users.duckdb upload scheduled in background after strategy delete")
    except Exception as e:
        print(f"[WARN] GCS upload background scheduling failed: {e}")

    return {"status": "success", "message": "Strategy deleted"}
