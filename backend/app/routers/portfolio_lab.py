"""Pagina de Portfolio (laboratorio local): baul, union y estudio de estrategias.

    GET  /api/portfolio-lab/strategies    -> listado ligero + cuadros + normalizacion
    POST /api/portfolio-lab/assignments   -> añadir/quitar de portfolio o incubadora
    POST /api/portfolio-lab/combine       -> imagen general lineal (F1)
    POST /api/portfolio-lab/montecarlo    -> bootstrap sobre la serie diaria combinada

Gated por PORTFOLIO_LAB_ENABLED, APAGADO por defecto (regla R7): en produccion
los endpoints responden 503 y el modulo no existe. La variable solo esta puesta
en el .env local.

OJO: el prefijo /api/portfolio (sin -lab) es del modulo de produccion del
equipo (PRD_portfolio_ANTIGRAVITY). Este modulo no lo toca ni lo reutiliza.
"""
from __future__ import annotations

import json
import math
import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user_id, scope_clause
from app.database import get_user_db_connection, get_user_db_lock
from app.services import portfolio_lab_engine as ple
from app.services import portfolio_lab_scaling as plsc
from app.services import portfolio_lab_service as pls
from app.services import robustness_service as rs
from app.services.robustness_mc import run_bootstrap

router = APIRouter()


# Se lee EN CADA PETICION, no al importar: el import puede ocurrir antes de que
# load_dotenv() haya poblado el entorno (leccion de lake_update.py).
def _enabled() -> bool:
    return os.getenv("PORTFOLIO_LAB_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _guard() -> None:
    if not _enabled():
        raise HTTPException(status_code=503, detail="Modulo de portfolio desactivado (PORTFOLIO_LAB_ENABLED)")


@router.get("/strategies")
def list_strategies(user_id: Optional[str] = Depends(get_current_user_id)):
    """Estrategias guardadas + su ultima corrida + cuadros + normalizacion.

    Mismo patron ligero que Robustez: columnas tipadas y `json_extract`, nunca
    el `results_json` entero (el endpoint del Baul viejo devolvia 48 MB).
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
                "buckets": [],
                "normalization": None,
            })

        runs = rs.list_runs_for_strategies(con, {s["id"] for s in out})
        assignments = pls.get_assignments(con)
        for s in out:
            s["run"] = runs.get(s["id"])
            s["buckets"] = assignments.get(s["id"], [])
            if s["run"]:
                s["normalization"] = pls.normalization_report(s["run"].get("backtest_params") or {})
        return out
    finally:
        con.close()


@router.get("/strategies/{strategy_id}/equity")
def strategy_equity(strategy_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    """Curva diaria de la ultima corrida, para el minigrafico del baul.

    Extrae SOLO `global_equity` por ruta JSON dentro de DuckDB — unos cientos
    de puntos {time, value} — sin tocar los trades. Mismo motivo que el
    listado: el payload entero de una corrida pesa varios MB.
    """
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
        metas = rs.list_runs_for_strategies(con, {strategy_id})
        meta = metas.get(strategy_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Sin backtest guardado")
        row = con.execute(
            "SELECT json_extract(results_json, '$.global_equity') FROM backtest_results WHERE id = ?",
            [meta["run_id"]],
        ).fetchone()
        return {"run_id": meta["run_id"], "equity": rs._as_list(row[0] if row else None)}
    finally:
        con.close()


class AssignmentReq(BaseModel):
    strategy_id: str
    bucket: str            # portfolio | incubadora
    present: bool          # True = añadir, False = quitar


@router.post("/assignments")
def set_assignment(req: AssignmentReq, user_id: Optional[str] = Depends(get_current_user_id)):
    _guard()
    if req.bucket not in pls.BUCKETS:
        raise HTTPException(status_code=400, detail=f"Cuadro desconocido: {req.bucket}")
    with get_user_db_lock():
        con = get_user_db_connection()
        scope_sql, scope_params = scope_clause(user_id)
        try:
            owned = con.execute(
                f"SELECT id FROM strategies WHERE id = ?{scope_sql}",
                [req.strategy_id, *scope_params],
            ).fetchone()
            if not owned:
                raise HTTPException(status_code=404, detail="Estrategia no encontrada")
            buckets = pls.set_assignment(con, req.strategy_id, req.bucket, req.present)
            return {"strategy_id": req.strategy_id, "buckets": buckets}
        finally:
            con.close()


class CombineReq(BaseModel):
    """Configuracion de ejecucion de la imagen general (unidades de la UI).

    `slippage_pct` y `risk_r` van en unidades REALES de interfaz: slippage en
    porcentaje (0.1 = 0,1%) y aqui se convierte a fraccion antes de entrar al
    motor — la trampa de la doble unidad del repo (MEMORIA §4.5) no puede
    cruzar esta frontera. `fees` es $ POR ACCION si fee_type=FLAT (fix de
    2026-08-22), o porcentaje del VALOR OPERADO por lado si PERCENT (fix de
    2026-08-21). Los dos se cobran en la entrada Y en la salida.
    """
    strategy_ids: list[str]
    init_cash: float = Field(default=10000.0, gt=0)
    # Literal, no str: el motor trata como PERCENT todo lo que no sea 'FLAT',
    # asi que un 'pct' cualquiera colaba comisiones x100 sin avisar.
    risk_type: Literal["FIXED", "PERCENT"] = "FIXED"
    risk_r: float = Field(default=100.0, ge=0)
    fees: float = Field(default=0.0, ge=0)
    fee_type: Literal["FLAT", "PERCENT"] = "FLAT"
    slippage_pct: float = Field(default=0.0, ge=0)
    locates_cost: float = Field(default=0.0, ge=0)
    monthly_expenses: float = Field(default=0.0, ge=0)
    start_date: str | None = None
    end_date: str | None = None


def _load_runs_for(req_ids: list[str], user_id) -> list[dict]:
    """Carga y normaliza la ultima corrida de cada estrategia pedida."""
    con = get_user_db_connection(read_only=True)
    scope_sql, scope_params = scope_clause(user_id)
    try:
        placeholders = ", ".join("?" for _ in req_ids)
        rows = con.execute(
            f"SELECT id, name FROM strategies WHERE id IN ({placeholders}){scope_sql}",
            [*req_ids, *scope_params],
        ).fetchall()
        names = {r[0]: r[1] for r in rows}
        missing = [sid for sid in req_ids if sid not in names]
        if missing:
            raise HTTPException(status_code=404, detail=f"Estrategias no encontradas: {missing}")

        metas = rs.list_runs_for_strategies(con, set(req_ids))
        without_run = [names[sid] for sid in req_ids if sid not in metas]
        if without_run:
            raise HTTPException(
                status_code=400,
                detail=f"Sin backtest guardado: {', '.join(without_run)}. "
                       f"Ejecutalo y guardalo desde el Backtester.",
            )

        out = []
        for sid in req_ids:
            run = pls.load_normalized_run(con, metas[sid]["run_id"], name=names[sid])
            if not run:
                raise HTTPException(status_code=404, detail=f"La corrida de {names[sid]} ya no existe")
            run["strategy_id"] = sid
            out.append(run)
        return out
    finally:
        con.close()


@router.post("/combine")
def combine(req: CombineReq, user_id: Optional[str] = Depends(get_current_user_id)):
    """Imagen general lineal: todas las estrategias con la misma configuracion."""
    _guard()
    if not req.strategy_ids:
        raise HTTPException(status_code=400, detail="Elige al menos una estrategia")
    runs = _load_runs_for(req.strategy_ids, user_id)
    try:
        result = ple.combine(runs, {
            "init_cash": req.init_cash,
            "risk_type": req.risk_type,
            "risk_r": req.risk_r,
            "fees": req.fees / 100.0 if req.fee_type.upper() == "PERCENT" else req.fees,
            "fee_type": req.fee_type,
            "slippage": req.slippage_pct / 100.0,   # % de la UI -> fraccion del motor
            "locates_cost": req.locates_cost,
            "monthly_expenses": req.monthly_expenses,
            "start_date": req.start_date,
            "end_date": req.end_date,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Nombres y normalizacion para que la interfaz no tenga que cruzar nada.
    result["strategies"] = [
        {
            "strategy_id": r["strategy_id"],
            "name": r["name"],
            "normalization": r["normalization"],
            "span": r["span"],
        }
        for r in runs
    ]
    return result


class ScalingCfg(BaseModel):
    model: Literal["fixed", "percent", "fixed_ratio", "kelly", "combinatoria"] = "fixed"
    base_risk: float = Field(default=100.0, gt=0)       # $ por trade (fixed y fixed_ratio)
    pct: float = Field(default=1.0, gt=0)               # % del capital (percent; base de kelly sin muestra)
    delta: float = Field(default=500.0, gt=0)           # delta de Ryan Jones (fixed_ratio)
    kelly_mult: float = Field(default=0.5, gt=0, le=1)  # 1 = Kelly "optima"; 0.5 / 0.25 fraccional
    threshold_equity: float = Field(default=0.0, ge=0)  # combinatoria: fix ratio hasta aqui, kelly despues


class WeightingCfg(BaseModel):
    model: Literal["equal", "hrp", "momentum", "ev", "dd"] = "equal"
    # floor > 0 obligatorio: con floor=0 y todas las estrategias en su peor DD,
    # 'dd' hacia 0/0 -> pesos NaN -> curva plana a cero sin ningun error.
    floor: float = Field(default=0.1, gt=0, le=1)
    cap_strat_pct: float = Field(default=0.0, ge=0)     # tope por estrategia, % del capital (0 = sin)


class ScalingReq(BaseModel):
    """Como CombineReq mas el eje de escalado/ponderacion. `slippage_pct` en %
    real de la UI; se convierte a fraccion aqui (MEMORIA §4.5)."""
    strategy_ids: list[str]
    init_cash: float = Field(default=10000.0, gt=0)
    fees: float = Field(default=0.0, ge=0)
    fee_type: Literal["FLAT", "PERCENT"] = "FLAT"
    slippage_pct: float = Field(default=0.0, ge=0)
    locates_cost: float = Field(default=0.0, ge=0)
    monthly_expenses: float = Field(default=0.0, ge=0)
    start_date: str | None = None
    end_date: str | None = None
    rebalance: Literal["D", "W", "M"] = "M"
    lookback_days: int = Field(default=90, ge=1)
    cap_global_pct: float = Field(default=0.0, ge=0)    # tope del riesgo por trade (0 = sin)
    scaling: ScalingCfg = ScalingCfg()
    weighting: WeightingCfg = WeightingCfg()


class ScalingVariant(BaseModel):
    label: str
    scaling: ScalingCfg | None = None
    weighting: WeightingCfg | None = None


class ScalingCompareReq(ScalingReq):
    variants: list[ScalingVariant] = []


def _scaling_cfg(req: ScalingReq) -> dict:
    return {
        "init_cash": req.init_cash,
        "fees": req.fees / 100.0 if req.fee_type.upper() == "PERCENT" else req.fees,
        "fee_type": req.fee_type,
        "slippage": req.slippage_pct / 100.0,
        "locates_cost": req.locates_cost,
        "monthly_expenses": req.monthly_expenses,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "rebalance": req.rebalance,
        "lookback_days": req.lookback_days,
        "cap_global_pct": req.cap_global_pct,
        "scaling": req.scaling.model_dump(),
        "weighting": req.weighting.model_dump(),
    }


@router.post("/scaling")
def scaling(req: ScalingReq, user_id: Optional[str] = Depends(get_current_user_id)):
    """Portfolio con escalado global y ponderacion dinamica (F2)."""
    _guard()
    if not req.strategy_ids:
        raise HTTPException(status_code=400, detail="Elige al menos una estrategia")
    runs = _load_runs_for(req.strategy_ids, user_id)
    try:
        result = plsc.run_scaling(runs, _scaling_cfg(req))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result["strategies"] = [
        {"strategy_id": r["strategy_id"], "name": r["name"],
         "normalization": r["normalization"], "span": r["span"]}
        for r in runs
    ]
    return result


@router.post("/scaling/compare")
def scaling_compare(req: ScalingCompareReq, user_id: Optional[str] = Depends(get_current_user_id)):
    """Varios modelos sobre los MISMOS datos, para enfrentarlos."""
    _guard()
    if not req.strategy_ids:
        raise HTTPException(status_code=400, detail="Elige al menos una estrategia")
    if not req.variants:
        raise HTTPException(status_code=400, detail="Elige al menos un modelo que comparar")
    runs = _load_runs_for(req.strategy_ids, user_id)
    variants = [v.model_dump(exclude_none=True) for v in req.variants]
    return {"results": plsc.run_scaling_compare(runs, _scaling_cfg(req), variants)}


# ── Monitorizacion (F3) ────────────────────────────────────────────────
# Re-ejecuta los ultimos ~6 meses de cada estrategia monitorizada con SUS
# parametros guardados (la estrategia tal y como operaria en vivo). Trabajo
# pesado: ~20-40 s por estrategia, secuencial, UN solo trabajo a la vez
# (mismo guardian 409 que Robustez — dos barridos se pelean por el disco).

import threading as _threading
import time as _time
from datetime import date as _date, timedelta as _timedelta
from uuid import uuid4 as _uuid4

from app.services.optimization_service import (
    get_progress as _get_progress,
    pop_result as _pop_result,
    set_progress as _set_progress,
    store_result as _store_result,
)

_MON_LOCK = _threading.Lock()
_MON_ACTIVE: dict = {"task_id": None, "started": None}

MONITOR_WINDOW_DAYS = 183


def _monitored_strategies(con, user_id) -> list[dict]:
    """Estrategias en portfolio o incubadora CON corrida guardada."""
    scope_sql, scope_params = scope_clause(user_id)
    rows = con.execute(
        f"SELECT id, name, definition FROM strategies WHERE 1=1{scope_sql}",
        scope_params,
    ).fetchall()
    assignments = pls.get_assignments(con)
    out = []
    for sid, name, definition in rows:
        buckets = assignments.get(sid, [])
        if not buckets:
            continue
        if not isinstance(definition, dict):
            try:
                definition = json.loads(definition) if definition else {}
            except (TypeError, ValueError):
                definition = {}
        out.append({"id": sid, "name": name, "definition": definition, "buckets": buckets})
    metas = rs.list_runs_for_strategies(con, {s["id"] for s in out})
    for s in out:
        s["run"] = metas.get(s["id"])
    return [s for s in out if s["run"]]


def _monitor_worker(task_id: str, strategies: list[dict]) -> dict:
    # Import pesado aqui a proposito: no cargar el orquestador si el modulo
    # esta apagado (mismo patron que los modulos pesados de robustness.py).
    from app.services.backtest_orchestrator import BacktestRequest, run_backtest_orchestrator

    start = (_date.today() - _timedelta(days=MONITOR_WINDOW_DAYS)).isoformat()
    done, errors = [], []
    for i, s in enumerate(strategies):
        _set_progress(task_id, max(0.5, 100.0 * i / max(1, len(strategies))))
        params = s["run"].get("backtest_params") or {}
        definition = s["definition"]
        dataset_id = definition.get("dataset_id") or params.get("dataset_id")
        if not dataset_id:
            errors.append({"strategy_id": s["id"], "error": "sin dataset asociado"})
            continue
        try:
            req = BacktestRequest(
                dataset_id=dataset_id,
                strategy_id=s["id"],
                strategy_definition=definition,
                init_cash=float(params.get("init_cash") or 10000.0),
                risk_r=float(params.get("risk_r") or 100.0),
                risk_type=str(params.get("risk_type") or "FIXED"),
                fees=float(params.get("fees") or 0.0),
                fee_type=str(params.get("fee_type") or "FLAT"),
                monthly_expenses=float(params.get("monthly_expenses") or 0.0),
                slippage=float(params.get("slippage") or 0.0),
                locates_cost=float(params.get("locates_cost") or 0.0),
                locate_type=str(params.get("locate_type") or "FLAT"),
                start_date=start,
                end_date=None,
                market_sessions=params.get("market_sessions") or definition.get("market_sessions"),
            )
            result = run_backtest_orchestrator(req)
            snap = pls.monitor_snapshot_from_result(result, start)
            with get_user_db_lock():
                con = get_user_db_connection()
                try:
                    pls.save_monitor_snapshot(con, s["id"], snap)
                finally:
                    con.close()
            done.append(s["id"])
        except Exception as e:  # noqa: BLE001 - una estrategia rota no tumba el resto
            errors.append({"strategy_id": s["id"], "error": str(e)[:300]})
    return {"done": done, "errors": errors, "window_start": start}


@router.post("/monitor/refresh")
def monitor_refresh(user_id: Optional[str] = Depends(get_current_user_id)):
    """Lanza el refresco de los ultimos 6 meses (trabajo pesado, uno a la vez)."""
    _guard()
    con = get_user_db_connection(read_only=True)
    try:
        strategies = _monitored_strategies(con, user_id)
    finally:
        con.close()
    if not strategies:
        raise HTTPException(status_code=400, detail="No hay estrategias en portfolio o incubadora con corrida guardada")

    with _MON_LOCK:
        if _MON_ACTIVE["task_id"] is not None:
            raise HTTPException(status_code=409, detail="Ya hay un refresco en marcha. Espera a que termine.")
        task_id = str(_uuid4())
        _MON_ACTIVE.update({"task_id": task_id, "started": _time.time()})

    _set_progress(task_id, 0.5)

    def _run():
        try:
            _store_result(task_id, _monitor_worker(task_id, strategies))
            _set_progress(task_id, 100.0)
        except Exception as e:  # noqa: BLE001
            _store_result(task_id, e)
        finally:
            with _MON_LOCK:
                _MON_ACTIVE.update({"task_id": None, "started": None})

    _threading.Thread(target=_run, daemon=True, name="portfolio-monitor").start()
    return {"task_id": task_id, "n_strategies": len(strategies)}


@router.get("/monitor/job/{task_id}")
def monitor_job(task_id: str):
    _guard()
    found, is_error, payload = _pop_result(task_id)
    if found:
        if is_error:
            return {"status": "error", "progress": 100.0, "error": str(payload)}
        return {"status": "done", "progress": 100.0, "result": payload}
    progress = _get_progress(task_id, -1.0)
    if progress is None or progress < 0:
        raise HTTPException(status_code=404, detail="Tarea desconocida")
    return {"status": "running", "progress": progress}


@router.get("/monitor")
def monitor_state(user_id: Optional[str] = Depends(get_current_user_id)):
    """Instantaneas guardadas + los teoricos de la corrida completa."""
    _guard()
    con = get_user_db_connection(read_only=True)
    try:
        strategies = _monitored_strategies(con, user_id)
        snaps = pls.get_monitor_snapshots(con)
    finally:
        con.close()
    return {
        "busy": _MON_ACTIVE["task_id"] is not None,
        "task_id": _MON_ACTIVE["task_id"],
        "strategies": [
            {
                "strategy_id": s["id"],
                "name": s["name"],
                "buckets": s["buckets"],
                "theoretical": {
                    "total_return_pct": s["run"].get("total_return_pct"),
                    "max_drawdown_pct": s["run"].get("max_drawdown_pct"),
                    "total_trades": s["run"].get("total_trades"),
                    "executed_at": s["run"].get("executed_at"),
                },
                "snapshot": snaps.get(s["id"]),
            }
            for s in strategies
        ],
    }


# ── Control en tiempo real: escalado sobre TU curva y pesos de AHORA ──

class RealControlReq(BaseModel):
    """Escalado aplicado a la curva REAL del usuario (portfolio_lab_real_pnl).

    `base_risk` es lo que arriesga hoy por trade en $: sirve de unidad para
    traducir su PnL diario a R (daily_R = pnl / base_risk), que es lo que
    consumen kelly y compañia.
    """
    initial_capital: float = Field(default=10000.0, gt=0)
    base_risk: float = Field(default=100.0, gt=0)
    model: Literal["compound", "fixed_ratio", "kelly", "dd"] = "compound"
    pct: float = Field(default=1.0, gt=0)               # compound: % del capital por trade
    delta: float = Field(default=500.0, gt=0)           # fixed_ratio
    kelly_mult: float = Field(default=0.5, gt=0, le=1)
    dd_floor: float = Field(default=0.25, ge=0, le=1)   # dd: suelo del multiplicador
    lookback_days: int = Field(default=90, ge=1)        # ventana de kelly
    cap_global_pct: float = Field(default=0.0, ge=0)


@router.post("/monitor/control")
def real_control(req: RealControlReq):
    """Curva real + metricas + recomendacion de size segun el modelo elegido."""
    _guard()
    con = get_user_db_connection(read_only=True)
    try:
        pls.ensure_monitor_tables(con)
        rows = con.execute(
            "SELECT fecha, pnl FROM portfolio_lab_real_pnl ORDER BY fecha"
        ).fetchall()
    finally:
        con.close()
    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="Hacen falta al menos 2 dias de PnL real importado")

    import numpy as _np
    from app.services import portfolio_lab_scaling as _plsc

    dates = [str(r[0]) for r in rows]
    pnl = _np.asarray([float(r[1]) for r in rows])
    equity = req.initial_capital + _np.cumsum(pnl)
    eq_open = _np.concatenate([[req.initial_capital], equity[:-1]])
    ret = _np.where(eq_open > 0, pnl / eq_open, 0.0)

    peak = _np.maximum.accumulate(_np.maximum(equity, 1e-9))
    dd_pct = (equity / peak - 1.0) * 100.0
    dd_now = float(dd_pct[-1])
    dd_max = float(dd_pct.min())

    wins = int((pnl > 0).sum())
    std = float(ret.std(ddof=1)) if len(ret) > 1 else 0.0
    metrics = {
        "n_days": len(dates),
        "total_pnl": round(float(pnl.sum()), 2),
        "return_pct": round(float(equity[-1] / req.initial_capital - 1) * 100, 4),
        "final_equity": round(float(equity[-1]), 2),
        "max_dd_pct": round(dd_max, 4),
        "dd_now_pct": round(dd_now, 4),
        "win_days_pct": round(100.0 * wins / len(dates), 2),
        "best_day": round(float(pnl.max()), 2),
        "worst_day": round(float(pnl.min()), 2),
        "avg_day": round(float(pnl.mean()), 2),
        "sharpe_d": round(float(ret.mean() / std * (252 ** 0.5)), 4) if std > 0 else 0.0,
    }

    # ── Recomendacion de size AHORA segun el modelo ─────────────────────
    e_now = float(equity[-1])
    note = None
    if req.model == "compound":
        x = req.pct / 100.0 * e_now
    elif req.model == "fixed_ratio":
        x = _plsc._fixed_ratio_x(e_now, req.initial_capital, req.base_risk, req.delta)
    elif req.model == "dd":
        # Menos size cuanto mas hundida este TU curva respecto a tu peor DD.
        ratio = (dd_now / dd_max) if dd_max < 0 else 0.0
        mult = max(req.dd_floor, 1.0 - ratio)
        x = req.base_risk * mult
        if mult < 1.0:
            note = f"drawdown actual al {ratio * 100:.0f}% de tu peor DD: multiplicador {mult:.2f} sobre tu riesgo base"
    elif req.model == "kelly":
        cut = dates[-1][:10]
        from datetime import date as _d, timedelta as _td
        lim = (_d.fromisoformat(cut) - _td(days=req.lookback_days)).isoformat()
        mask = [d >= lim for d in dates]
        daily_r = _np.asarray([p / req.base_risk for p, m in zip(pnl, mask) if m])
        f = _plsc._kelly_fraction(daily_r)
        if f is None:
            x = req.pct / 100.0 * e_now
            note = "sin muestra suficiente para kelly: usado el % base"
        elif f <= 0:
            x = 0.0
            note = "kelly <= 0: sin edge en tu ventana reciente, no subas size"
        else:
            raw = req.kelly_mult * f
            if raw > _plsc.KELLY_CEILING:
                x = _plsc.KELLY_CEILING * e_now
                note = f"kelly pedía {raw * 100:.0f}% del capital; aplicado el techo del {_plsc.KELLY_CEILING * 100:.0f}%"
            else:
                x = raw * e_now
    else:
        raise HTTPException(status_code=400, detail=f"Modelo desconocido: {req.model}")

    pre_cap = x
    if req.cap_global_pct > 0:
        x = min(x, req.cap_global_pct / 100.0 * e_now)
        if x < pre_cap - 1e-9:
            asked = 100.0 * pre_cap / e_now if e_now > 0 else 0.0
            note = f"el modelo pedía {asked:.1f}% del capital; aplicado {100.0 * x / e_now:.2f}% por tu tope global"

    return {
        "dates": dates,
        "equity": [round(float(v), 2) for v in equity],
        "daily_pnl": [round(float(v), 2) for v in pnl],
        "metrics": metrics,
        "recommendation": {
            "model": req.model,
            "x": round(float(x), 2),
            "x_pct": round(100.0 * x / e_now, 4) if e_now > 0 else 0.0,
            "vs_base": round(float(x) / req.base_risk, 4) if req.base_risk > 0 else None,
            "note": note,
        },
    }


class WeightsNowReq(BaseModel):
    strategy_ids: list[str]
    lookback_days: int = Field(default=90, ge=1)
    model: Literal["equal", "hrp", "momentum", "ev", "dd"] = "hrp"
    floor: float = Field(default=0.1, gt=0, le=1)


@router.post("/monitor/weights")
def weights_now_endpoint(req: WeightsNowReq, user_id: Optional[str] = Depends(get_current_user_id)):
    """Que % destinar HOY a cada estrategia, con el metodo elegido."""
    _guard()
    if len(req.strategy_ids) < 1:
        raise HTTPException(status_code=400, detail="Elige al menos una estrategia")
    runs = _load_runs_for(req.strategy_ids, user_id)
    from app.services import portfolio_lab_scaling as _plsc
    try:
        out = _plsc.weights_now(runs, req.lookback_days, req.model, req.floor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    out["strategies"] = [
        {"strategy_id": r["strategy_id"], "name": r["name"], "normalization": r["normalization"]}
        for r in runs
    ]
    return out


# ── PnL real (zona preparada; la comparacion fina llega mas adelante) ──

class RealPnlRow(BaseModel):
    # Fecha validada AQUI: la columna es DATE PRIMARY KEY, y una fila con
    # '21/08/2026' reventaba el cast a mitad del lote dejando la mitad dentro.
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    pnl: float

    @field_validator("pnl")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("pnl debe ser un numero finito")
        return v


class RealPnlReq(BaseModel):
    rows: list[RealPnlRow]


@router.get("/monitor/real")
def real_pnl_get():
    _guard()
    con = get_user_db_connection(read_only=True)
    try:
        pls.ensure_monitor_tables(con)
        rows = con.execute("SELECT fecha, pnl FROM portfolio_lab_real_pnl ORDER BY fecha").fetchall()
        return {"rows": [{"date": str(r[0]), "pnl": r[1]} for r in rows]}
    finally:
        con.close()


@router.post("/monitor/real")
def real_pnl_save(req: RealPnlReq):
    _guard()
    if not req.rows:
        raise HTTPException(status_code=400, detail="Sin filas")
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            pls.ensure_monitor_tables(con)
            # Lote ATOMICO: o entra entero o no entra nada. Antes, un fallo a
            # mitad dejaba media importacion confirmada sin forma de saberlo.
            con.execute("BEGIN TRANSACTION")
            try:
                con.executemany(
                    "INSERT OR REPLACE INTO portfolio_lab_real_pnl (fecha, pnl) VALUES (?, ?)",
                    [[r.date, r.pnl] for r in req.rows],
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            n = con.execute("SELECT COUNT(*) FROM portfolio_lab_real_pnl").fetchone()[0]
            return {"saved": len(req.rows), "total": n}
        finally:
            con.close()


@router.delete("/monitor/real")
def real_pnl_clear():
    _guard()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            pls.ensure_monitor_tables(con)
            con.execute("DELETE FROM portfolio_lab_real_pnl")
            return {"cleared": True}
        finally:
            con.close()


class PortfolioMcReq(BaseModel):
    """`values` es la serie DIARIA del portfolio (daily_r_net en compound,
    daily_pnl en additive), tal como la devuelve /combine. Se remuestrea por
    dia y no por trade a proposito: es la unidad real de composicion y los
    trades de una misma sesion van correlacionados (MEMORIA §4.4)."""
    values: list[float]
    init_cash: float = Field(default=10000.0, gt=0)
    simulations: int = Field(default=2000, ge=10, le=50_000)
    method: Literal["bootstrap", "permutacion"] = "bootstrap"
    mode: Literal["compound", "additive"] = "compound"
    risk_pct: float = Field(default=3.0, gt=0)
    ruin_pct: float = Field(default=50.0, gt=0, le=100)
    seed: int | None = None


@router.post("/montecarlo")
def montecarlo(req: PortfolioMcReq):
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
