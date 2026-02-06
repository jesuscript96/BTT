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
    con.execute(
        "INSERT INTO saved_queries (id, name, filters) VALUES (?, ?, ?)",
        (query_id, query.name, json.dumps(query.filters))
    )
    return {**query.dict(), "id": query_id}

@router.get("/", response_model=List[SavedQuery])
def list_saved_queries():
    con = get_db_connection(read_only=True)
    rows = con.execute("SELECT id, name, filters, created_at, updated_at FROM saved_queries ORDER BY created_at DESC").fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "filters": json.loads(r[2]),
            "created_at": str(r[3]),
            "updated_at": str(r[4])
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
        "filters": json.loads(row[2]),
        "created_at": str(row[3]),
        "updated_at": str(row[4])
    }

@router.delete("/{query_id}")
def delete_saved_query(query_id: str):
    con = get_db_connection()
    con.execute("DELETE FROM saved_queries WHERE id = ?", (query_id,))
    return {"status": "success"}
