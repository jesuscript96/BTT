"""Pagina de Robustez: analisis de estrategias ya backtesteadas.

    GET  /api/robustness/strategies            -> listado ligero (sin trades)
    GET  /api/robustness/strategies/{id}/run   -> la corrida guardada + trades
    POST /api/robustness/montecarlo            -> bootstrap / permutacion
    POST /api/robustness/stress                -> test de estres compuesto

Gated por ROBUSTNESS_ENABLED, APAGADO por defecto (regla R7 del proyecto): en
produccion los endpoints responden 503 y el modulo no existe. La variable solo
esta puesta en el .env local.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user_id, scope_clause
from app.database import get_user_db_connection
from app.services import robustness_service as rs
from app.services.robustness_mc import run_bootstrap
from app.services.robustness_stress import run_stress

router = APIRouter()


# Se lee EN CADA PETICION, no al importar: el import puede ocurrir antes de que
# load_dotenv() haya poblado el entorno (leccion de lake_update.py).
def _enabled() -> bool:
    return os.getenv("ROBUSTNESS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _guard() -> None:
    if not _enabled():
        raise HTTPException(status_code=503, detail="Modulo de robustez desactivado (ROBUSTNESS_ENABLED)")


@router.get("/strategies")
def list_strategies_with_runs(user_id: Optional[str] = Depends(get_current_user_id)):
    """Estrategias guardadas + metadatos de su ultima corrida.

    Devuelve la `definition` entera (la usa el desplegable de condiciones) pero
    NUNCA los trades: esos se piden aparte, solo para la estrategia elegida.
    """
    _guard()
    con = get_user_db_connection(read_only=True)
    scope_sql, scope_params = scope_clause(user_id)
    try:
        rows = con.execute(
            f"SELECT id, name, description, created_at, updated_at, definition "
            f"FROM strategies WHERE 1=1{scope_sql} ORDER BY created_at DESC",
            scope_params,
        ).fetchall()

        out = []
        for r in rows:
            definition = r[5]
            if not isinstance(definition, dict):
                try:
                    definition = json.loads(definition) if definition else {}
                except (TypeError, ValueError):
                    definition = {}
            out.append({
                "id": r[0],
                "name": r[1],
                "description": r[2],
                "created_at": str(r[3]) if r[3] else None,
                "updated_at": str(r[4]) if r[4] else None,
                "definition": definition,
                "run": None,
            })

        runs = rs.list_runs_for_strategies(con, {s["id"] for s in out})
        for s in out:
            s["run"] = runs.get(s["id"])
        return out
    finally:
        con.close()


@router.get("/strategies/{strategy_id}/run")
def get_strategy_run(strategy_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    """Trades + metricas + parametros de la ultima corrida de la estrategia."""
    _guard()
    con = get_user_db_connection(read_only=True)
    scope_sql, scope_params = scope_clause(user_id)
    try:
        owned = con.execute(
            f"SELECT id FROM strategies WHERE id = ?{scope_sql}",
            [strategy_id, *scope_params],
        ).fetchone()
        if not owned:
            raise HTTPException(status_code=404, detail="Estrategia no encontrada")

        runs = rs.list_runs_for_strategies(con, {strategy_id})
        meta = runs.get(strategy_id)
        if not meta:
            raise HTTPException(
                status_code=404,
                detail="Esta estrategia no tiene ningun backtest guardado. Ejecutalo y guardalo desde el Backtester.",
            )

        payload = rs.load_run_payload(con, meta["run_id"])
        if not payload:
            raise HTTPException(status_code=404, detail="La corrida guardada ya no existe")
        return payload
    finally:
        con.close()


# ── Modelos de peticion ─────────────────────────────────────────────

class MonteCarloReq(BaseModel):
    """`values` son R-multiplos en modo compound, o PnL en $ en additive."""
    values: list[float]
    init_cash: float = 10000.0
    simulations: int = 2000
    method: str = "bootstrap"      # bootstrap | permutacion
    mode: str = "compound"         # compound | additive
    risk_pct: float = 3.0
    ruin_pct: float = 50.0
    seed: int | None = None


class StressReq(BaseModel):
    trades: list[dict]
    params: dict
    init_cash: float = 10000.0
    mode: str = "compound"
    risk_pct: float = 3.0
    seed: int | None = None


@router.post("/montecarlo")
def montecarlo(req: MonteCarloReq):
    _guard()
    try:
        return run_bootstrap(
            req.values,
            init_cash=req.init_cash,
            simulations=req.simulations,
            method=req.method,
            mode=req.mode,
            risk_pct=req.risk_pct,
            ruin_pct=req.ruin_pct,
            seed=req.seed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stress")
def stress(req: StressReq):
    _guard()
    try:
        return run_stress(
            req.trades,
            req.params,
            init_cash=req.init_cash,
            mode=req.mode,
            risk_pct=req.risk_pct,
            seed=req.seed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ──────────────────────────────────────────────────────────────────────
# Modulos pesados: re-ejecutan backtests, corren en un hilo aparte
# ──────────────────────────────────────────────────────────────────────
import threading
import time as _time
from uuid import uuid4

from app.services import robustness_grid as rg
from app.services.optimization_service import (
    cancel_optimization_task,
    get_progress,
    pop_result,
    set_progress,
    store_result,
)

# UN solo trabajo pesado a la vez. Dos barridos simultaneos se pelean por el
# disco y ninguno avanza — la misma leccion que con el actualizador del lago.
_JOB_LOCK = threading.Lock()
_ACTIVE: dict = {"task_id": None, "kind": None, "started": None}


def _job_status() -> dict:
    return {
        "busy": _ACTIVE["task_id"] is not None,
        "task_id": _ACTIVE["task_id"],
        "kind": _ACTIVE["kind"],
        "elapsed_s": round(_time.time() - _ACTIVE["started"], 1) if _ACTIVE["started"] else None,
    }


def _launch(kind: str, fn, *args, **kwargs) -> str:
    with _JOB_LOCK:
        if _ACTIVE["task_id"] is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Ya hay un trabajo pesado en marcha ({_ACTIVE['kind']}). Espera a que termine o cancelalo.",
            )
        task_id = str(uuid4())
        _ACTIVE.update({"task_id": task_id, "kind": kind, "started": _time.time()})

    set_progress(task_id, 0.5)

    def _worker():
        try:
            store_result(task_id, fn(*args, task_id=task_id, **kwargs))
            set_progress(task_id, 100.0)
        except rg.Cancelled:
            store_result(task_id, {"cancelled": True})
        except Exception as e:  # noqa: BLE001 - se devuelve al cliente
            store_result(task_id, e)
        finally:
            with _JOB_LOCK:
                _ACTIVE.update({"task_id": None, "kind": None, "started": None})

    threading.Thread(target=_worker, daemon=True, name=f"robustez-{kind}").start()
    return task_id


class LocatesCurvesReq(BaseModel):
    strategy_id: str
    locates_min: float = 0.5
    locates_max: float = 5.0
    locates_steps: int = 8
    slippage: float = 0.0
    monthly_expenses: float = 0.0
    start_date: str | None = None
    end_date: str | None = None


class LocatesMatrixReq(BaseModel):
    strategy_id: str
    locates_min: float = 1.0
    locates_max: float = 10.0
    locates_steps: int = 10
    slippage_min: float = 0.1
    slippage_max: float = 1.0
    slippage_steps: int = 10
    monthly_expenses: float = 0.0
    start_date: str | None = None
    end_date: str | None = None


def _strategy_ctx(strategy_id: str, user_id, start_date, end_date):
    """Definicion + dataset + parametros de la ultima corrida de la estrategia."""
    con = get_user_db_connection(read_only=True)
    scope_sql, scope_params = scope_clause(user_id)
    try:
        row = con.execute(
            f"SELECT definition FROM strategies WHERE id = ?{scope_sql}",
            [strategy_id, *scope_params],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Estrategia no encontrada")
        definition = row[0]
        if not isinstance(definition, dict):
            definition = json.loads(definition) if definition else {}

        runs = rs.list_runs_for_strategies(con, {strategy_id})
        meta = runs.get(strategy_id)
        params: dict = {}
        if meta:
            payload = rs.load_run_payload(con, meta["run_id"])
            params = (payload or {}).get("backtest_params") or {}
    finally:
        con.close()

    dataset_id = definition.get("dataset_id") or params.get("dataset_id")
    if not dataset_id:
        raise HTTPException(
            status_code=400,
            detail="La estrategia no tiene dataset asociado; no se puede re-ejecutar.",
        )

    uf = definition.get("universe_filters") or {}
    return {
        "definition": definition,
        "dataset_id": dataset_id,
        "backtest_params": params,
        "start_date": start_date or params.get("start_date") or uf.get("date_from"),
        "end_date": end_date or params.get("end_date") or uf.get("date_to"),
    }


@router.get("/job")
def job_status():
    """Hay algo pesado corriendo ahora mismo?"""
    _guard()
    return _job_status()


@router.get("/job/{task_id}")
def job_result(task_id: str):
    """Progreso y, si termino, el resultado."""
    _guard()
    # pop_result devuelve (encontrado, es_error, payload) — tres elementos.
    found, is_error, payload = pop_result(task_id)
    if found:
        if is_error:
            return {"status": "error", "progress": 100.0, "error": str(payload)}
        if isinstance(payload, dict) and payload.get("cancelled"):
            return {"status": "cancelled", "progress": 0.0}
        return {"status": "done", "progress": 100.0, "result": payload}

    progress = get_progress(task_id, -1.0)
    if progress is None or progress < 0:
        raise HTTPException(status_code=404, detail="Tarea desconocida")
    return {"status": "running", "progress": progress}


@router.post("/job/{task_id}/cancel")
def job_cancel(task_id: str):
    _guard()
    cancel_optimization_task(task_id)
    return {"status": "cancelling"}


@router.post("/locates/curves")
def locates_curves(req: LocatesCurvesReq, user_id: Optional[str] = Depends(get_current_user_id)):
    """Una curva de equity por cada coste de locates."""
    _guard()
    c = _strategy_ctx(req.strategy_id, user_id, req.start_date, req.end_date)
    values = rg._linspace(req.locates_min, req.locates_max, req.locates_steps)
    task_id = _launch(
        "locates_curves",
        rg.run_locates_curves,
        strategy_def=c["definition"],
        dataset_id=c["dataset_id"],
        backtest_params=c["backtest_params"],
        locates_values=values,
        slippage=req.slippage,
        monthly_expenses=req.monthly_expenses,
        start_date=c["start_date"],
        end_date=c["end_date"],
    )
    return {"task_id": task_id, "n_points": len(values)}


@router.post("/locates/matrix")
def locates_matrix(req: LocatesMatrixReq, user_id: Optional[str] = Depends(get_current_user_id)):
    """Rejilla locates x slippage: un backtest por celda."""
    _guard()
    c = _strategy_ctx(req.strategy_id, user_id, req.start_date, req.end_date)
    lv = rg._linspace(req.locates_min, req.locates_max, req.locates_steps)
    sv = rg._linspace(req.slippage_min, req.slippage_max, req.slippage_steps)
    task_id = _launch(
        "locates_matrix",
        rg.run_locates_slippage_matrix,
        strategy_def=c["definition"],
        dataset_id=c["dataset_id"],
        backtest_params=c["backtest_params"],
        locates_values=lv,
        slippage_values=sv,
        monthly_expenses=req.monthly_expenses,
        start_date=c["start_date"],
        end_date=c["end_date"],
    )
    return {"task_id": task_id, "n_points": len(lv) * len(sv)}


# ── Walk-forward ──────────────────────────────────────────────────────

from app.services import robustness_wfo as rw
from app.services.optimization_service import extract_parameters


class WfoFastReq(BaseModel):
    strategy_id: str
    n_windows: int = 6
    oos_pct: float = 30.0
    anchored: bool = False
    metric: str = "sharpe"


class WfoParamCfg(BaseModel):
    path: str
    label: str = ""
    min: float
    max: float
    steps: int = 5


class WfoFullReq(BaseModel):
    strategy_id: str
    params: list[WfoParamCfg]
    n_windows: int = 5
    oos_pct: float = 30.0
    anchored: bool = False
    metric: str = "sharpe"
    start_date: str | None = None
    end_date: str | None = None


@router.get("/strategies/{strategy_id}/parameters")
def strategy_parameters(strategy_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    """Parametros optimizables de la estrategia, para elegir cuales barre el WFO."""
    _guard()
    c = _strategy_ctx(strategy_id, user_id, None, None)
    try:
        params = extract_parameters(c["definition"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"No se pudieron extraer parametros: {e}")
    # Los de `risk_management` son los baratos: no invalidan la cache de señales.
    for p in params:
        p["cheap"] = str(p.get("path", "")).startswith("risk_management.")
    return {"parameters": params}


@router.post("/wfo/fast")
def wfo_fast(req: WfoFastReq, user_id: Optional[str] = Depends(get_current_user_id)):
    """Modo rapido: ventanas sobre los trades guardados, sin re-ejecutar nada."""
    _guard()
    con = get_user_db_connection(read_only=True)
    scope_sql, scope_params = scope_clause(user_id)
    try:
        owned = con.execute(
            f"SELECT id FROM strategies WHERE id = ?{scope_sql}",
            [req.strategy_id, *scope_params],
        ).fetchone()
        if not owned:
            raise HTTPException(status_code=404, detail="Estrategia no encontrada")
        runs = rs.list_runs_for_strategies(con, {req.strategy_id})
        meta = runs.get(req.strategy_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Esta estrategia no tiene backtest guardado")
        payload = rs.load_run_payload(con, meta["run_id"])
    finally:
        con.close()

    comp = (payload or {}).get("compounding") or {}
    try:
        return rw.run_wfo_fast(
            (payload or {}).get("trades") or [],
            n_windows=req.n_windows,
            oos_pct=req.oos_pct,
            anchored=req.anchored,
            risk_pct=comp.get("risk_pct") or 3.0,
            init_cash=comp.get("init_cash") or 10000.0,
            metric=req.metric,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/wfo/full")
def wfo_full(req: WfoFullReq, user_id: Optional[str] = Depends(get_current_user_id)):
    """Modo completo: re-optimiza en cada IS y valida en el OOS correspondiente."""
    _guard()
    if not req.params:
        raise HTTPException(status_code=400, detail="Elige al menos un parametro que optimizar")
    c = _strategy_ctx(req.strategy_id, user_id, req.start_date, req.end_date)
    task_id = _launch(
        "wfo_full",
        rw.run_wfo_full,
        strategy_def=c["definition"],
        dataset_id=c["dataset_id"],
        backtest_params=c["backtest_params"],
        param_configs=[p.model_dump() for p in req.params],
        n_windows=req.n_windows,
        oos_pct=req.oos_pct,
        anchored=req.anchored,
        metric=req.metric,
        start_date=c["start_date"],
        end_date=c["end_date"],
    )
    n = req.n_windows * (1 + int(np_prod([p.steps for p in req.params])))
    return {"task_id": task_id, "n_backtests": n}


def np_prod(vals: list[int]) -> int:
    out = 1
    for v in vals:
        out *= max(1, int(v))
    return out
