"""
API router for optimization surface endpoints.
"""

import logging
import threading
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.data_service import get_strategy
from app.services.optimization_service import (
    run_optimization_grid,
    extract_parameters,
    OPTIMIZATION_PROGRESS,
    OPTIMIZATION_RESULTS,
)

logger = logging.getLogger("backtester.optimization")

router = APIRouter(prefix="/api", tags=["optimization"])


class ParametersRequest(BaseModel):
    strategy_id: str | None = None
    strategy_definition: dict | None = None


class ParamConfig(BaseModel):
    id: str
    label: str = ""
    path: str
    min: float
    max: float
    steps: int = 10
    values: list[float] | None = None


class SurfaceRequest(BaseModel):
    strategy_id: str
    strategy_definition: dict | None = None
    dataset_id: str
    metric: str = "sharpe"
    param_configs: list[ParamConfig]
    init_cash: float = 10000.0
    risk_r: float = 100.0
    risk_type: str = "FIXED"
    size_by_sl: bool = False
    fees: float = 0.0
    fee_type: str = "PERCENT"
    monthly_expenses: float = 0.0
    slippage: float = 0.0
    start_date: str | None = None
    end_date: str | None = None
    market_sessions: list[str] | None = None
    custom_start_time: str | None = None
    custom_end_time: str | None = None
    locates_cost: float = 0.0
    look_ahead_prevention: bool = False
    is_percent: float = 100.0
    task_id: str | None = None


@router.post("/optimization/parameters")
def get_optimization_parameters(req: ParametersRequest):
    logger.info(f"Extracting parameters for strategy {req.strategy_id}")
    # Mock and draft strategies have no optimizable parameters
    if req.strategy_id in ("mock_strat_1", "draft") or req.strategy_id is None:
        if req.strategy_id == "draft" and req.strategy_definition:
            try:
                params = extract_parameters(req.strategy_definition)
                logger.info(f"Found {len(params)} parameters for draft strategy")
                return {"parameters": params, "strategy_name": "Draft Strategy"}
            except Exception as e:
                logger.error(f"Error extracting parameters for draft: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")
        return {"parameters": [], "strategy_name": "Draft Strategy"}
    strategy = get_strategy(req.strategy_id)
    if not strategy:
        logger.error(f"Strategy {req.strategy_id} not found")
        raise HTTPException(status_code=404, detail="Strategy not found")

    try:
        params = extract_parameters(strategy["definition"])
        logger.info(f"Found {len(params)} parameters for strategy {strategy['name']}")
        return {"parameters": params, "strategy_name": strategy["name"]}
    except Exception as e:
        logger.error(f"Error extracting parameters: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")


@router.get("/optimization/progress/{task_id}")
def get_optimization_progress(task_id: str):
    prog = OPTIMIZATION_PROGRESS.get(task_id, 0.0)
    logger.debug(f"[PROGRESS_CHECK] {task_id} = {prog}%")
    return {"progress": prog}


@router.get("/optimization/result/{task_id}")
def get_optimization_result(task_id: str):
    """Retrieve the result of a completed optimization task."""
    if task_id in OPTIMIZATION_RESULTS:
        result = OPTIMIZATION_RESULTS.pop(task_id)
        OPTIMIZATION_PROGRESS.pop(task_id, None)
        if isinstance(result, Exception):
            raise HTTPException(status_code=500, detail=str(result))
        return result
    # Still running or unknown
    prog = OPTIMIZATION_PROGRESS.get(task_id, -1)
    if prog < 0:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "running", "progress": prog}


def _run_optimization_in_background(req_data: dict, task_id: str):
    """Background thread function that runs the optimization and stores the result."""
    try:
        result = run_optimization_grid(
            strategy_id=req_data["strategy_id"],
            dataset_id=req_data["dataset_id"],
            param_configs=req_data["param_configs"],
            metric=req_data["metric"],
            backtest_params=req_data["backtest_params"],
            task_id=task_id,
            strategy_definition=req_data.get("strategy_definition"),
        )
        OPTIMIZATION_RESULTS[task_id] = result
        OPTIMIZATION_PROGRESS[task_id] = 100.0
        logger.info(f"[OPT] Background task {task_id} completed successfully")
    except Exception as e:
        logger.error(f"[OPT] Background task {task_id} failed: {e}", exc_info=True)
        OPTIMIZATION_RESULTS[task_id] = e
        OPTIMIZATION_PROGRESS[task_id] = 100.0


@router.post("/optimization/surface")
def run_surface(req: SurfaceRequest):
    # Check if dataset precache is running
    from app.routers.query import get_precache_state
    status_info = get_precache_state(req.dataset_id)
    if status_info and status_info.get("status") == "running":
        percent = status_info.get("percent", 0.0)
        raise HTTPException(
            status_code=400,
            detail=f"Espera a que se cargue el dataset (progreso: {percent}%)"
        )
    task_id = req.task_id or f"opt_{id(req)}"

    # Initialize progress tracking
    OPTIMIZATION_PROGRESS[task_id] = 0.0

    req_data = {
        "strategy_id": req.strategy_id,
        "strategy_definition": req.strategy_definition,
        "dataset_id": req.dataset_id,
        "param_configs": [pc.model_dump() for pc in req.param_configs],
        "metric": req.metric,
        "backtest_params": {
            "init_cash": req.init_cash,
            "risk_r": req.risk_r,
            "risk_type": req.risk_type,
            "size_by_sl": req.size_by_sl,
            "fees": req.fees,
            "fee_type": req.fee_type,
            "slippage": req.slippage,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "market_sessions": req.market_sessions,
            "custom_start_time": req.custom_start_time,
            "custom_end_time": req.custom_end_time,
            "locates_cost": req.locates_cost,
            "look_ahead_prevention": req.look_ahead_prevention,
            "is_percent": req.is_percent,
        },
    }

    logger.info(f"[OPT_REQUEST] strategy_id={req.strategy_id}, dataset_id={req.dataset_id}, metric={req.metric}, param_configs={req_data['param_configs']}, backtest_params={req_data['backtest_params']}")

    # Launch optimization in background thread
    thread = threading.Thread(
        target=_run_optimization_in_background,
        args=(req_data, task_id),
        daemon=True,
    )
    thread.start()

    logger.info(f"[OPT] Background task {task_id} launched")
    return {"task_id": task_id, "status": "started"}

