from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from uuid import uuid4
from datetime import datetime
import json
from app.database import get_db_connection

router = APIRouter()

class SavedQuery(BaseModel):
    id: Optional[str] = None
    name: str
    filters: dict
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

@router.post("/", response_model=SavedQuery)
def create_saved_query(query: SavedQuery):
    con = get_db_connection()
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
    try:
        from app.services.query_service import build_screener_query
        
        # Build the query based on filters
        # Note: we need the WHERE clause and params from build_screener_query
        # We'll use backtest_no_joins=True to keep it simple and efficient for persistence
        _, params, _, _, _, where_m_stats = build_screener_query(query.filters, limit=100000)
        
        # We've got where_m_stats which contains the full filter logic.
        # Let's insert directly into dataset_pairs
        insert_sql = f"""
            INSERT INTO dataset_pairs (dataset_id, ticker, date)
            SELECT ? as dataset_id, ticker, CAST(timestamp AS DATE) as date
            FROM daily_metrics
            WHERE {where_m_stats}
        """
        
        # Execution with query_id prepended to params
        con.execute(insert_sql, [query_id] + params)
        print(f"✅ Saved combinations for dataset {query_id}")
        
    except Exception as e:
        print(f"⚠️ Warning: Could not save dataset combinations: {e}")
        # We don't fail the whole request because the primary action (saving the query) succeeded.
        # But we log it.
        
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
    con = get_db_connection(read_only=True)
    try:
        # Get queries from both local db and shared massive db
        rows = con.execute("""
            SELECT id, name, filters, created_at, updated_at FROM saved_queries 
            UNION ALL 
            SELECT id, name, filters, created_at, updated_at FROM massive.main.saved_queries
            ORDER BY created_at DESC
        """).fetchall()
    except Exception as e:
        print(f"list_saved_queries error: {e}")
        # fallback if massive.main.saved_queries doesn't exist
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

@router.get("/{query_id}", response_model=SavedQuery)
def get_saved_query(query_id: str):
    con = get_db_connection(read_only=True)
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

@router.delete("/{query_id}")
def delete_saved_query(query_id: str):
    con = get_db_connection()
    con.execute("DELETE FROM saved_queries WHERE id = ?", (query_id,))
    return {"status": "success"}
