from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from pydantic import BaseModel
from uuid import uuid4
from datetime import datetime
import json
import threading
import time
import pandas as pd
from app.database import get_user_db_connection, get_user_db_lock
from app.auth import get_current_user_id, scope_clause

router = APIRouter()

class SavedQuery(BaseModel):
    id: Optional[str] = None
    name: str
    filters: dict
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

def _write_precache_state(dataset_id: str, status: str, progress_pct: float) -> None:
    """Persist precache progress to users.duckdb. Best-effort: never raises."""
    try:
        lock = get_user_db_lock()
        with lock:
            con = get_user_db_connection()
            try:
                con.execute(
                    "INSERT OR REPLACE INTO precache_state (dataset_id, status, progress_pct, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    [dataset_id, status, float(progress_pct)],
                )
            finally:
                con.close()
    except Exception as e:
        print(f"[PRECACHE] Could not persist state for {dataset_id}: {e}")


def get_precache_state(dataset_id: str) -> dict | None:
    """Read precache status from users.duckdb. Returns None if no row exists."""
    try:
        lock = get_user_db_lock()
        with lock:
            con = get_user_db_connection(read_only=True)
            try:
                row = con.execute(
                    "SELECT status, progress_pct FROM precache_state WHERE dataset_id = ?",
                    [dataset_id],
                ).fetchone()
            finally:
                con.close()
    except Exception as e:
        print(f"[PRECACHE] Could not read state for {dataset_id}: {e}")
        return None
    if row is None:
        return None
    return {"status": row[0], "percent": float(row[1] or 0.0)}


def _precache_dataset_intraday(pairs_df, date_from, date_to, dataset_id):
    """Pre-cache intraday data for a dataset in background thread.
    Receives pairs_df in memory — does NOT depend on caller's DB connection."""
    count = 0
    total = 0
    try:
        from app.db.gcs_cache import iter_intraday_groups_streamed

        if pairs_df is None or pairs_df.empty:
            print(f"[PRECACHE] Dataset {dataset_id}: no pairs to cache")
            _write_precache_state(dataset_id, "completed", 100.0)
            return

        total = len(pairs_df)
        print(f"[PRECACHE] Starting for dataset {dataset_id}: {total} pairs, {date_from} -> {date_to}")
        _write_precache_state(dataset_id, "running", 0.0)

        # Throttle DB writes so we don't acquire the user_db_lock per iteration
        # (that adds ~5ms per write — at 1000+ iterations it dominates the loop).
        last_percent_written = 0.0
        last_write_t = time.time()

        for _ in iter_intraday_groups_streamed(pairs_df, date_from, date_to):
            # Check if cancelled or deleted from saved_queries/precache_state to abort the thread
            if count % 10 == 0:
                state = get_precache_state(dataset_id)
                if state and state.get("status") in ("cancelled", "failed"):
                    print(f"[PRECACHE] Aborting pre-cache for dataset {dataset_id}: status is {state.get('status')}")
                    return
                
                # Check if it was deleted from saved_queries
                lock = get_user_db_lock()
                with lock:
                    con = get_user_db_connection(read_only=True)
                    try:
                        row = con.execute("SELECT 1 FROM saved_queries WHERE id = ?", [dataset_id]).fetchone()
                        if not row:
                            print(f"[PRECACHE] Aborting pre-cache for dataset {dataset_id}: query was deleted")
                            return
                    finally:
                        con.close()

            count += 1
            percent = min(100.0, round((count / total) * 100.0, 1)) if total > 0 else 100.0
            # Write at most every ~5 percentage points OR every 5 seconds — whichever comes first.
            if percent - last_percent_written >= 5.0 or (time.time() - last_write_t) >= 5.0:
                _write_precache_state(dataset_id, "running", percent)
                last_percent_written = percent
                last_write_t = time.time()

        _write_precache_state(dataset_id, "completed", 100.0)
        print(f"[PRECACHE] Completed: {count} day-groups cached for dataset {dataset_id}")
    except Exception as e:
        print(f"[PRECACHE] Error pre-caching dataset {dataset_id}: {e}")
        percent = min(100.0, round((count / total) * 100.0, 1)) if total > 0 else 0.0
        _write_precache_state(dataset_id, "failed", percent)


@router.get("/precache-status/{dataset_id}")
def get_precache_status(dataset_id: str):
    state = get_precache_state(dataset_id)
    if state is None:
        return {"status": "completed", "percent": 100.0, "current": 0, "total": 0}
    
    total_pairs = 0
    try:
        lock = get_user_db_lock()
        with lock:
            con = get_user_db_connection(read_only=True)
            try:
                row = con.execute("SELECT COUNT(*) FROM dataset_pairs WHERE dataset_id = ?", [dataset_id]).fetchone()
                if row:
                    total_pairs = row[0]
            finally:
                con.close()
    except Exception as e:
        print(f"[PRECACHE] Could not read total pairs for {dataset_id}: {e}")
        
    percent = state.get("percent", 0.0)
    current_pairs = int(round(total_pairs * (percent / 100.0)))
    
    return {
        "status": state.get("status"),
        "percent": percent,
        "current": current_pairs,
        "total": total_pairs
    }

def _populate_dataset_pairs(query_id: str, filters: dict):
    """Heavy phase of dataset creation: compute and persist ticker-day pairs.

    Runs the screener query with LEAD windows over daily_metrics (GCS reads in
    prod, can take minutes). Returns (pairs_df, date_from, date_to) for the
    intraday pre-cache. Raises on failure so the caller can mark the dataset
    creation as errored.
    """
    from app.services.query_service import build_screener_query

    _, params, _, _, _, where_m_stats = build_screener_query(filters, limit=100000)

    subquery_lagged = """
                (
                    SELECT *,
                           LEAD(rth_close, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_rth_close_1,
                           LEAD(pmh_gap_pct, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_pmh_gap_pct_1,
                           LEAD(pm_volume, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_pm_volume_1,
                           LEAD(gap_pct, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_gap_pct_1,
                           LEAD(rth_volume, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_rth_volume_1,
                           LEAD(rth_range_pct, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_rth_range_pct_1,
                           LEAD(open, 1) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_open_1,
                           
                           LEAD(rth_close, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_rth_close_2,
                           LEAD(pmh_gap_pct, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_pmh_gap_pct_2,
                           LEAD(pm_volume, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_pm_volume_2,
                           LEAD(gap_pct, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_gap_pct_2,
                           LEAD(rth_volume, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_rth_volume_2,
                           LEAD(rth_range_pct, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_rth_range_pct_2,
                           LEAD(open, 2) OVER (PARTITION BY ticker ORDER BY timestamp) as lead_open_2
                    FROM daily_metrics
                ) dm_lagged
                """
    select_sql = f"""
        SELECT ticker, CAST(CAST(timestamp AS DATE) AS VARCHAR) as date
        FROM {subquery_lagged}
        WHERE {where_m_stats.replace('daily_metrics.', 'dm_lagged.')}
    """

    # Heavy phase WITHOUT the global lock: a read-only scan over daily_metrics
    # (GCS reads, can take minutes). Holding the lock here froze /data/datasets
    # and /precache-status — the picker and progress bar hung until done.
    from app.database import get_db_connection
    con = get_db_connection()
    pairs_df = con.execute(select_sql, params).fetchdf()

    date_from = ""
    date_to = ""
    if not pairs_df.empty:
        pairs_df = pairs_df.drop_duplicates(subset=["ticker", "date"])
        date_from = pairs_df['date'].min()
        date_to = pairs_df['date'].max()

    # Fast phase WITH the lock: bulk-insert the precomputed pairs (sub-second)
    if not pairs_df.empty:
        lock = get_user_db_lock()
        with lock:
            con = get_user_db_connection()
            try:
                con.register("pairs_tmp", pairs_df)
                con.execute(
                    "INSERT INTO dataset_pairs (dataset_id, ticker, date) "
                    "SELECT ? as dataset_id, ticker, CAST(date AS DATE) FROM pairs_tmp "
                    "ON CONFLICT DO NOTHING",
                    [query_id],
                )
            finally:
                con.close()
    print(f"Saved combinations for dataset {query_id}: {len(pairs_df)} pairs")

    return pairs_df, date_from, date_to


@router.post("/", response_model=SavedQuery)
def create_saved_query(query: SavedQuery, user_id: Optional[str] = Depends(get_current_user_id)):
    query_id = str(uuid4())

    # Phase A — synchronous and fast: register the dataset so it is listable
    # immediately, then return. The heavy pair computation must not block the
    # HTTP response (in prod it exceeded the frontend timeout and caused
    # duplicate saves).
    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection()
        try:
            con.execute(
                "INSERT INTO saved_queries (id, name, filters, user_id) VALUES (?, ?, ?, ?)",
                (query_id, query.name, json.dumps(query.filters), user_id)
            )
            con.execute(
                "INSERT INTO datasets (id, name, user_id) VALUES (?, ?, ?)",
                (query_id, query.name, user_id)
            )
        finally:
            con.close()

    # Outside the lock: _write_precache_state takes the same non-reentrant lock
    _write_precache_state(query_id, "pending", 0.0)

    # Phase B — background: dataset_pairs, GCS persistence, intraday pre-cache
    def _background_work():
        try:
            pairs_df, date_from, date_to = _populate_dataset_pairs(query_id, query.filters)

            from app.gcs_sync import upload_user_db
            try:
                upload_user_db()
                print(f"[GCS] users.duckdb uploaded after dataset save")
            except Exception as e:
                print(f"[WARN] GCS upload failed: {e}")

            _precache_dataset_intraday(pairs_df, date_from, date_to, query_id)
        except Exception as e:
            print(f"[ERROR] Background dataset creation failed for {query_id}: {e}")
            _write_precache_state(query_id, "error", 0.0)

    threading.Thread(target=_background_work, daemon=False).start()
    print(f"[ASYNC] Dataset {query_id} registered; pairs + pre-cache running in background")

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
def list_saved_queries(user_id: Optional[str] = Depends(get_current_user_id)):
    con = get_user_db_connection(read_only=True)
    scope_sql, scope_params = scope_clause(user_id)
    try:
        try:
            # massive.* is never attached on get_user_db_connection() connections,
            # so the old UNION with massive.main.saved_queries always threw a
            # Catalog Error and forced the fallback. users.duckdb is the only source.
            rows = con.execute(
                f"SELECT id, name, filters, created_at, updated_at FROM users.saved_queries "
                f"WHERE 1=1{scope_sql} ORDER BY created_at DESC",
                scope_params,
            ).fetchall()
        except Exception as e:
            print(f"list_saved_queries error: {e}")
            try:
                rows = con.execute(
                    f"SELECT id, name, filters, created_at, updated_at FROM saved_queries "
                    f"WHERE 1=1{scope_sql} ORDER BY created_at DESC",
                    scope_params,
                ).fetchall()
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
def get_saved_query(query_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    con = get_user_db_connection(read_only=True)
    scope_sql, scope_params = scope_clause(user_id)
    try:
        row = con.execute(
            f"SELECT id, name, filters, created_at, updated_at FROM saved_queries WHERE id = ?{scope_sql}",
            [query_id, *scope_params],
        ).fetchone()
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
def delete_saved_query(query_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    lock = get_user_db_lock()
    scope_sql, scope_params = scope_clause(user_id)
    with lock:
        con = get_user_db_connection()
        try:
            # Only cascade-delete the child rows if the caller owns the dataset.
            owned = con.execute(
                f"SELECT id FROM saved_queries WHERE id = ?{scope_sql}",
                [query_id, *scope_params],
            ).fetchone()
            if not owned:
                raise HTTPException(status_code=404, detail="Query not found")
            con.execute("DELETE FROM saved_queries WHERE id = ?", (query_id,))
            con.execute("DELETE FROM datasets WHERE id = ?", (query_id,))
            con.execute("DELETE FROM dataset_pairs WHERE dataset_id = ?", (query_id,))
            con.execute("DELETE FROM precache_state WHERE dataset_id = ?", (query_id,))
        finally:
            con.close()

    # Persist the deletion: without this, a container restart re-downloads
    # users.duckdb from GCS and resurrects the deleted dataset
    try:
        from app.gcs_sync import upload_user_db
        upload_user_db()
    except Exception as e:
        print(f"[WARN] GCS upload after delete failed: {e}")

    return {"status": "success"}
