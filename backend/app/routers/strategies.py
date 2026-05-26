from fastapi import APIRouter, HTTPException
from typing import List
import json
from uuid import uuid4
from datetime import datetime

from app.database import get_user_db_connection, get_user_db_lock
from app.schemas.strategy import Strategy, StrategyCreate

router = APIRouter()

@router.post("/", response_model=Strategy)
def create_strategy(strategy: StrategyCreate):
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
            
            con.execute(
                """
                INSERT INTO strategies (id, name, description, created_at, updated_at, definition)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id, 
                    strategy.name, 
                    strategy.description, 
                    now, 
                    now, 
                    json.dumps(full_strategy.model_dump())
                )
            )
            
            return full_strategy
        finally:
            con.close()
    
    # Upload users.duckdb to GCS synchronously (ensure persistence before response)
    from app.gcs_sync import upload_user_db
    try:
        upload_user_db()
        print(f"[GCS] users.duckdb uploaded after strategy save")
    except Exception as e:
        print(f"[WARN] GCS upload failed: {e}")

@router.get("/", response_model=List[Strategy])
def list_strategies():
    con = get_user_db_connection()
    try:
        rows = con.execute("SELECT definition FROM strategies ORDER BY created_at DESC").fetchall()
    except Exception as e:
        print(f"list_strategies DB error: {e}")
        return []
    finally:
        con.close()
    strategies = []
    for row in rows:
        if not row or row[0] is None:
            continue
        raw = row[0]
        if isinstance(raw, dict):
            strategy_dict = raw
        else:
            try:
                strategy_dict = json.loads(raw)
            except (TypeError, ValueError) as e:
                print(f"Error parsing strategy JSON: {e}")
                continue
        try:
            strategies.append(Strategy(**strategy_dict))
        except Exception as e:
            print(f"Error building Strategy: {e}")
            continue
    return strategies

@router.get("/{strategy_id}", response_model=Strategy)
def get_strategy(strategy_id: str):
    con = get_user_db_connection()
    try:
        row = con.execute("SELECT definition FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return Strategy(**json.loads(row[0]))
    finally:
        con.close()

@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: str):
    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection()
        try:
            row = con.execute("SELECT id FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Strategy not found")
            con.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
            return {"status": "success", "message": "Strategy deleted"}
        finally:
            con.close()
    
    # Upload users.duckdb to GCS synchronously (ensure persistence before response)
    from app.gcs_sync import upload_user_db
    try:
        upload_user_db()
        print(f"[GCS] users.duckdb uploaded after strategy save")
    except Exception as e:
        print(f"[WARN] GCS upload failed: {e}")
