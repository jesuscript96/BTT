"""
Robustness module router (thin).

Exposes the strategy-robustness endpoints described in
docs/robustez/PRD_ROBUSTEZ.md §3. All maths live in
`app.services.robustness_service`; this router only validates input, delegates,
and maps `RobustnessError` codes to HTTP responses.
"""
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.services import robustness_service
from app.services.robustness_service import RobustnessError

logger = logging.getLogger("backtester.robustness")

router = APIRouter(prefix="/api/robustness", tags=["robustness"])

# Maps the stable domain codes (PRD §3.5) to HTTP status codes.
_ERROR_STATUS = {
    "INVALID_STRATEGY": 400,
    "PARAMETER_OUT_OF_BOUNDS": 400,
    "PROCESSING_ERROR": 500,
}


def _raise_http(err: RobustnessError) -> "HTTPException":
    """Translate a domain error into an HTTPException (never leak internals)."""
    status = _ERROR_STATUS.get(err.code, 500)
    return HTTPException(status_code=status, detail={"code": err.code, "message": err.message})


@router.get("/health")
def health():
    """Liveness probe for the robustness module."""
    return {"status": "ok", "module": "robustness"}


# ─── Request models (mirror docs/robustez/PRD_ROBUSTEZ.md §3) ───────────────
# `run_id` is the saved Baúl run (= backtest_results.id). `strategy_id` is kept
# as an accepted alias so the PRD contract keeps working.

class _StrategyRef(BaseModel):
    run_id: Optional[str] = None
    strategy_id: Optional[str] = None  # alias

    def resolve_id(self) -> str:
        rid = self.run_id or self.strategy_id
        if not rid:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_STRATEGY", "message": "run_id is required."},
            )
        return rid


class MontecarloRequest(_StrategyRef):
    init_cash: float = 10000.0
    simulations: int = 1000
    ruin_pct: float = 10.0
    n_trades_limit: int = 500
    period_unit: Optional[str] = None


class LocateRange(BaseModel):
    min: float = 0.5
    max: float = 3.0
    step: float = 0.5


class SensitivityRequest(_StrategyRef):
    locate_range: LocateRange = Field(default_factory=LocateRange)
    slippage_probability: float = 0.0
    slippage_value: float = 0.0
    init_cash: float = 10000.0


class BlackSwanRequest(_StrategyRef):
    init_cash: float = 10000.0
    black_swan_count: int = 3
    severity_multiplier: float = 10.0
    ruin_pct: float = 10.0


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/montecarlo")
def montecarlo(req: MontecarloRequest):
    """Module 1 — Monte Carlo bootstrap (synchronous, <200ms)."""
    run_id = req.resolve_id()
    try:
        trades, _ = robustness_service._load_trades(run_id)
        return robustness_service.run_montecarlo_bootstrap(
            trades,
            init_cash=req.init_cash,
            simulations=req.simulations,
            ruin_pct=req.ruin_pct,
            n_trades_limit=req.n_trades_limit,
            period_unit=req.period_unit,
        )
    except RobustnessError as err:
        raise _raise_http(err)
    except Exception as exc:  # noqa: BLE001 — never leak internals
        logger.exception("montecarlo failed")
        raise HTTPException(status_code=500, detail={"code": "PROCESSING_ERROR", "message": "Internal error."}) from exc


@router.post("/sensitivity")
def sensitivity(req: SensitivityRequest):
    """Module 3 — locate/slippage sensitivity (synchronous, <200ms)."""
    run_id = req.resolve_id()
    try:
        trades, _ = robustness_service._load_trades(run_id)
        return robustness_service.run_sensitivity(
            trades,
            locate_range=req.locate_range.model_dump(),
            slippage_probability=req.slippage_probability,
            slippage_value=req.slippage_value,
            init_cash=req.init_cash,
        )
    except RobustnessError as err:
        raise _raise_http(err)
    except Exception as exc:  # noqa: BLE001
        logger.exception("sensitivity failed")
        raise HTTPException(status_code=500, detail={"code": "PROCESSING_ERROR", "message": "Internal error."}) from exc


@router.post("/black-swan")
def black_swan(req: BlackSwanRequest):
    """Module 4 — Black Swan simulator (synchronous, <200ms)."""
    run_id = req.resolve_id()
    try:
        trades, _ = robustness_service._load_trades(run_id)
        return robustness_service.run_black_swan(
            trades,
            init_cash=req.init_cash,
            black_swan_count=req.black_swan_count,
            severity_multiplier=req.severity_multiplier,
            ruin_pct=req.ruin_pct,
        )
    except RobustnessError as err:
        raise _raise_http(err)
    except Exception as exc:  # noqa: BLE001
        logger.exception("black-swan failed")
        raise HTTPException(status_code=500, detail={"code": "PROCESSING_ERROR", "message": "Internal error."}) from exc


# ─── Module 2 — Walk-Forward (heavy → background + polling) ──────────────────
# Reuses the optimization task store (set_progress/store_result/pop_result).

class WfoParamConfig(BaseModel):
    id: str
    path: str
    min: Optional[float] = None
    max: Optional[float] = None
    steps: Optional[int] = 5
    values: Optional[list[float]] = None


class WalkForwardRequest(_StrategyRef):
    dataset_id: str
    is_pct: float = 70.0
    oos_pct: float = 30.0
    step_pct: float = 30.0
    metric: str = "sharpe"
    init_cash: float = 10000.0
    param_configs: list[WfoParamConfig] = Field(default_factory=list)


def _run_wfo_in_background(task_id: str, payload: dict) -> None:
    """Background worker: run WFO, stream progress, store the result/error."""
    from app.services.optimization_service import set_progress, store_result
    try:
        set_progress(task_id, 1.0)
        result = robustness_service.run_walk_forward(
            run_id=payload["run_id"],
            dataset_id=payload["dataset_id"],
            is_pct=payload["is_pct"],
            oos_pct=payload["oos_pct"],
            step_pct=payload["step_pct"],
            metric=payload["metric"],
            param_configs=payload["param_configs"],
            init_cash=payload["init_cash"],
            progress_cb=lambda pct: set_progress(task_id, pct),
        )
        store_result(task_id, result)
        set_progress(task_id, 100.0)
    except RobustnessError as err:
        store_result(task_id, {"status": "error", "code": err.code, "message": err.message})
        set_progress(task_id, 100.0)
    except Exception as exc:  # noqa: BLE001
        logger.exception("WFO background task %s failed", task_id)
        store_result(task_id, {"status": "error", "code": "PROCESSING_ERROR", "message": "Internal error."})
        set_progress(task_id, 100.0)


@router.post("/walk-forward")
def walk_forward(req: WalkForwardRequest, background_tasks: BackgroundTasks):
    """Module 2 — enqueue a Walk-Forward analysis; returns a task_id to poll."""
    run_id = req.resolve_id()
    task_id = f"wfo_task_{uuid.uuid4().hex[:10]}"
    payload = {
        "run_id": run_id,
        "dataset_id": req.dataset_id,
        "is_pct": req.is_pct,
        "oos_pct": req.oos_pct,
        "step_pct": req.step_pct,
        "metric": req.metric,
        "init_cash": req.init_cash,
        "param_configs": [pc.model_dump() for pc in req.param_configs],
    }
    background_tasks.add_task(_run_wfo_in_background, task_id, payload)
    return {"task_id": task_id, "status": "running", "progress": 0.0}


@router.get("/walk-forward/progress/{task_id}")
def walk_forward_progress(task_id: str):
    from app.services.optimization_service import get_progress
    return {"progress": get_progress(task_id, 0.0)}


@router.get("/walk-forward/result/{task_id}")
def walk_forward_result(task_id: str):
    from app.services.optimization_service import pop_result, get_progress
    found, is_error, payload = pop_result(task_id)
    if found:
        if is_error:
            raise HTTPException(status_code=500, detail={"code": "PROCESSING_ERROR", "message": str(payload)})
        return payload
    prog = get_progress(task_id, -1)
    if prog == -1:
        raise HTTPException(status_code=404, detail={"code": "INVALID_STRATEGY", "message": "Task not found"})
    return {"status": "running", "progress": prog}
