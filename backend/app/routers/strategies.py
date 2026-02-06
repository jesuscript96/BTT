from fastapi import APIRouter, HTTPException
from typing import List
import json
from uuid import uuid4
from datetime import datetime

from app.database import get_db_connection
from app.schemas.strategy import Strategy, StrategyCreate

router = APIRouter()

@router.post("/", response_model=Strategy)
def create_strategy(strategy: StrategyCreate):
    con = get_db_connection()
    
    new_id = str(uuid4())
    now = datetime.now()
    
    # Create full strategy object
    full_strategy = Strategy(
        **strategy.model_dump(),
        id=new_id,
        created_at=now.isoformat()
    )
    
    # Store in DB
    # We store the Pydantic model as a JSON string in the 'definition' column
    # The dedicated columns 'id', 'name', 'description' are for easy querying/indexing
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

@router.get("/", response_model=List[Strategy])
def list_strategies():
    con = get_db_connection()
    # Fetch from DB
    rows = con.execute("SELECT definition FROM strategies ORDER BY created_at DESC").fetchall()
    
    strategies = []
    for row in rows:
        # row[0] is the JSON string
        try:
            strategy_dict = json.loads(row[0])
            strategies.append(Strategy(**strategy_dict))
        except Exception as e:
            print(f"Error parsing strategy: {e}")
            continue
            
    return strategies

@router.get("/{strategy_id}", response_model=Strategy)
def get_strategy(strategy_id: str):
    con = get_db_connection()
    row = con.execute("SELECT definition FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
        
    return Strategy(**json.loads(row[0]))

@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: str):
    con = get_db_connection()
    # Check if exists
    row = con.execute("SELECT id FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
        
    con.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
    return {"status": "success", "message": "Strategy deleted"}
