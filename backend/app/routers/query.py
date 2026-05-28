from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from uuid import uuid4
from datetime import datetime
import json
import threading
import pandas as pd
from app.database import get_user_db_connection, get_user_db_lock

router = APIRouter()

class SavedQuery(BaseModel):
    id: Optional[str] = None
    name: str
    filters: dict
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

def _precache_dataset_intraday(pairs_df, date_from, date_to, dataset_id):
    """Pre-cache intraday data for a dataset in background thread.
    Receives pairs_df in memory — does NOT open users.duckdb."""
    try:
        import pandas as pd
        from app.db.gcs_cache import iter_intraday_groups_streamed

        if pairs_df.empty:
            print(f"[PRECACHE] Dataset {dataset_id}: no pairs to cache")
            return
        
        print(f"[PRECACHE] Starting for dataset {dataset_id}: {len(pairs_df)} pairs, {date_from} -> {date_to}")
        
        count = 0
        for _ in iter_intraday_groups_streamed(pairs_df, date_from, date_to):
            count += 1
        
        print(f"[PRECACHE] Completed: {count} day-groups cached for dataset {dataset_id}")
    except Exception as e:
        print(f"[PRECACHE] Error pre-caching dataset {dataset_id}: {e}")

@router.post("/", response_model=SavedQuery)
def create_saved_query(query: SavedQuery):
    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection()
        try:
            query_id = str(uuid4())
            
            # 1. Save main query definition (legacy metadata)
            con.execute(
                "INSERT INTO saved_queries (id, name, filters) VALUES (?, ?, ?)",
                (query_id, query.name, json.dumps(query.filters))
            )
            
            # 2. Save to datasets metadata table
            con.execute(
                "INSERT INTO datasets (id, name) VALUES (?, ?)",
                (query_id, query.name)
            )
            
            # 3. Handle ticker-day combinations persistence
            pairs_df = pd.DataFrame()
            date_from = ""
            date_to = ""
            try:
                from app.services.query_service import build_screener_query
                
                _, params, _, _, _, where_m_stats = build_screener_query(query.filters, limit=100000)
                
                subquery_lagged = """
                (
                    SELECT *,
                           LAG(rth_close, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lag_rth_close_1,
                           LAG(pmh_gap_pct, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lag_pmh_gap_pct_1,
                           LAG(pm_volume, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lag_pm_volume_1,
                           LAG(gap_pct, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lag_gap_pct_1,
                           LAG(rth_volume, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lag_rth_volume_1,
                           LAG(rth_range_pct, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lag_rth_range_pct_1,
                           
                           LAG(rth_close, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lag_rth_close_2,
                           LAG(pmh_gap_pct, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lag_pmh_gap_pct_2,
                           LAG(pm_volume, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lag_pm_volume_2,
                           LAG(gap_pct, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lag_gap_pct_2,
                           LAG(rth_volume, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lag_rth_volume_2,
                           LAG(rth_range_pct, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lag_rth_range_pct_2
                    FROM daily_metrics
                ) dm_lagged
                """
                insert_sql = f"""
                    INSERT INTO dataset_pairs (dataset_id, ticker, date)
                    SELECT ? as dataset_id, ticker, CAST(timestamp AS DATE) as date
                    FROM {subquery_lagged}
                    WHERE {where_m_stats}
                """
                
                con.execute(insert_sql, [query_id] + params)
                print(f"Saved combinations for dataset {query_id}")
                
                # Fetch pairs in-memory BEFORE closing the connection (for pre-cache)
                pairs_df = con.execute(
                    "SELECT ticker, CAST(date AS VARCHAR) as date FROM dataset_pairs WHERE dataset_id = ?",
                    [query_id]
                ).fetchdf()
                if not pairs_df.empty:
                    date_from = pairs_df['date'].min()
                    date_to = pairs_df['date'].max()
                else:
                    date_from = ""
                    date_to = ""
                
            except Exception as e:
                print(f"Warning: Could not save dataset combinations: {e}")
            
        finally:
            con.close()
    
    # Launch intraday pre-cache in background thread (receives data in memory)
    threading.Thread(
        target=_precache_dataset_intraday,
        args=(pairs_df, date_from, date_to, query_id),
        daemon=True
    ).start()
    print(f"[PRECACHE] Background pre-cache started for dataset {query_id}")
    
    # Upload users.duckdb to GCS synchronously (ensure persistence before response)
    from app.gcs_sync import upload_user_db
    try:
        upload_user_db()
        print(f"[GCS] users.duckdb uploaded after dataset save")
    except Exception as e:
        print(f"[WARN] GCS upload failed: {e}")
    
    return {**query.dict(), "id": query_id}

def _parse_filters(raw):
    """Parse filters from DB: may be str (JSON) or already dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    return {}


@router.get("/", response_model=List[SavedQuery])
def list_saved_queries():
    con = get_user_db_connection()
    try:
        try:
            rows = con.execute("""
                SELECT id, name, filters, created_at, updated_at FROM saved_queries 
                UNION ALL 
                SELECT id, name, filters, created_at, updated_at FROM massive.main.saved_queries
                ORDER BY created_at DESC
            """).fetchall()
        except Exception as e:
            print(f"list_saved_queries error: {e}")
            try:
                rows = con.execute("SELECT id, name, filters, created_at, updated_at FROM saved_queries ORDER BY created_at DESC").fetchall()
            except Exception as e2:
                print(f"fallback list_saved_queries error: {e2}")
                return []
        return [
            {
                "id": r[0],
                "name": r[1],
                "filters": _parse_filters(r[2]),
                "created_at": str(r[3]) if r[3] is not None else None,
                "updated_at": str(r[4]) if r[4] is not None else None
            } for r in rows
        ]
    finally:
        con.close()

@router.get("/{query_id}", response_model=SavedQuery)
def get_saved_query(query_id: str):
    con = get_user_db_connection()
    try:
        row = con.execute("SELECT id, name, filters, created_at, updated_at FROM saved_queries WHERE id = ?", (query_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Query not found")
        return {
            "id": row[0],
            "name": row[1],
            "filters": _parse_filters(row[2]),
            "created_at": str(row[3]) if row[3] is not None else None,
            "updated_at": str(row[4]) if row[4] is not None else None
        }
    finally:
        con.close()

@router.delete("/{query_id}")
def delete_saved_query(query_id: str):
    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection()
        try:
            con.execute("DELETE FROM saved_queries WHERE id = ?", (query_id,))
            return {"status": "success"}
        finally:
            con.close()
