import logging
import os
import threading
from functools import lru_cache

try:
    import psutil
except ImportError:  # optional dep — the memory guard degrades to a no-op if absent
    psutil = None

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel

from app.services.data_service import fetch_day_candles
from app.services.backtest_orchestrator import (
    BacktestRequest,
    run_backtest_orchestrator,
    generate_mock_candles,
)
from app.services import backtest_jobs
from app.services.montecarlo_service import run_montecarlo
from app.services.what_if_service import run_what_if

logger = logging.getLogger("backtester.backtest")

router = APIRouter(prefix="/api", tags=["backtest"])

backtest_progress = {}

# Minimum host memory (GB) required to START a backtest. Safety net: blocks
# piling a heavy run on top of one already in flight, or starting during the
# RAM-cache reload after a restart. NOTE: this does NOT prevent a single BROAD
# run from OOMing on its own (idle has ~19GB free → the pre-check passes, then
# the run itself allocates the memory). The real BROAD bound is fewer stream
# workers + not caching giant month frames. Env-tunable; 0 disables the guard.
_BACKTEST_MIN_AVAIL_GB = float(os.getenv("BACKTEST_MIN_AVAIL_GB", "4.0"))


def _memory_available_gb():
    """Host memory available in GB, or None if psutil is unavailable/fails."""
    if psutil is None:
        return None
    try:
        return psutil.virtual_memory().available / 1024 ** 3
    except Exception:
        return None

@router.get("/backtest/progress/{dataset_id}")
def get_backtest_progress(dataset_id: str):
    if dataset_id not in backtest_progress:
        return {"status": "not_running", "percent": 0.0, "current": 0, "total": 0}
    return backtest_progress[dataset_id]


@router.post("/backtest/cancel/{dataset_id}")
def cancel_backtest(dataset_id: str):
    # Legacy dict (sync path + the orchestrator's in-loop cancel check).
    backtest_progress[dataset_id] = {
        "status": "cancelled",
        "percent": 0.0,
        "current": 0,
        "total": 0
    }
    # Async path: flag the job for this dataset as cancelled in Redis too.
    backtest_jobs.mark_dataset_cancelled(dataset_id)
    return {"status": "success", "message": "Backtest cancellation requested"}



class MonteCarloRequest(BaseModel):
    pnls: list[float]
    init_cash: float = 10000.0
    simulations: int = 1000


class WhatIfRequest(BaseModel):
    trades: list[dict]
    init_cash: float = 10000.0
    risk_r: float = 100.0
    params: dict


def _run_backtest_in_background(req: BacktestRequest, job_id: str):
    """Background thread (F3): run the orchestrator, mirror progress into the
    job store, and persist the result to disk. Never raises — terminal states
    are written to the job store instead."""
    def on_progress(current, total, percent):
        backtest_jobs.set_job_state(
            job_id, req.dataset_id, "running",
            percent=percent, current=current, total=total,
        )

    try:
        result = run_backtest_orchestrator(req, on_progress=on_progress)
        backtest_jobs.save_job_result(job_id, result)
        n = len(result.get("day_results", []))
        backtest_jobs.set_job_state(
            job_id, req.dataset_id, "succeeded",
            percent=100.0, current=n, total=n,
        )
        logger.info(f"[JOB] {job_id} succeeded ({n} days)")
    except HTTPException as he:
        # The orchestrator raises 400 "Backtest cancelado" on cancel, 500 on error.
        detail = he.detail if isinstance(he.detail, str) else str(he.detail)
        if he.status_code == 400 and "cancel" in detail.lower():
            backtest_jobs.set_job_state(job_id, req.dataset_id, "cancelled")
            logger.info(f"[JOB] {job_id} cancelled")
        else:
            backtest_jobs.set_job_state(job_id, req.dataset_id, "failed", error=detail)
            logger.error(f"[JOB] {job_id} failed: {detail}")
    except Exception as e:  # pragma: no cover - safety net
        backtest_jobs.set_job_state(job_id, req.dataset_id, "failed", error=str(e))
        logger.error(f"[JOB] {job_id} crashed: {e}", exc_info=True)


@router.post("/backtest")
def run_backtest_endpoint(
    req: BacktestRequest,
    response: Response,
    x_backtest_sync: str | None = Header(default=None),
):
    # Memory guard: refuse to start when the host is already critically low on
    # RAM (e.g. another heavy run in flight, or the RAM-cache reload after a
    # restart). Swap=0 on prod → an OOM-kill takes the whole backend down, so a
    # clean 503 is far better than letting a second run tip it over.
    avail = _memory_available_gb()
    if _BACKTEST_MIN_AVAIL_GB > 0 and avail is not None and avail < _BACKTEST_MIN_AVAIL_GB:
        logger.warning(f"[MEMORY GUARD] rejected backtest: {avail:.1f}GB available < {_BACKTEST_MIN_AVAIL_GB}GB")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "insufficient_memory",
                "message": f"Servidor con poca memoria disponible ({avail:.1f}GB). Intenta en unos minutos.",
                "available_gb": round(avail, 1),
            },
        )

    current = backtest_progress.get(req.dataset_id, {})

    # Guard anti-doble-run: if one is already running for this dataset, return the
    # in-progress state instead of launching a second concurrent run (two identical
    # runs compete for disk/CPU and ~2x the wall time — observed in prod).
    if current.get("status") == "running":
        existing_job = backtest_jobs.get_job_for_dataset(req.dataset_id)
        return {
            "status": "already_running",
            "dataset_id": req.dataset_id,
            "job_id": existing_job,
            "progress": current,
            "message": "Un backtest ya está corriendo para este dataset",
        }

    # Clear cancelled state if this is a fresh run
    if current.get("status") == "cancelled":
        backtest_progress.pop(req.dataset_id, None)

    # ── Retrocompat: X-Backtest-Sync: true → original blocking behaviour ──
    if x_backtest_sync and x_backtest_sync.strip().lower() == "true":
        return run_backtest_orchestrator(req)

    # ── Default: async job (202 + job_id) ──
    backtest_jobs.cleanup_old_results()
    job_id = backtest_jobs.new_job_id()
    # Seed both stores as running so the anti-double-run guard and legacy poll
    # see it immediately (before the thread's first progress tick).
    backtest_progress[req.dataset_id] = {
        "status": "running", "current": 0, "total": 0, "percent": 0.0,
    }
    backtest_jobs.set_job_state(job_id, req.dataset_id, "running")

    thread = threading.Thread(
        target=_run_backtest_in_background, args=(req, job_id), daemon=True,
    )
    thread.start()
    logger.info(f"[JOB] {job_id} launched for dataset={req.dataset_id}")

    response.status_code = status.HTTP_202_ACCEPTED
    return {"job_id": job_id, "dataset_id": req.dataset_id, "status": "running"}


@router.get("/backtest/{job_id}")
def get_backtest_job(job_id: str):
    """Async job status (no result payload)."""
    state = backtest_jobs.get_job_state(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": state.get("status"),
        "percent": state.get("percent", 0.0),
        "current": state.get("current", 0),
        "total": state.get("total", 0),
        "error": state.get("error"),
    }


@router.get("/backtest/{job_id}/result")
def get_backtest_job_result(job_id: str):
    """Completed result WITHOUT equity_curves (served per-day via /equity)."""
    state = backtest_jobs.get_job_state(job_id)
    if state is not None and state.get("status") in ("running", None):
        return {"status": "running", "percent": state.get("percent", 0.0)}
    if state is not None and state.get("status") == "failed":
        raise HTTPException(status_code=500, detail=state.get("error") or "Backtest failed")
    if state is not None and state.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Backtest cancelado")

    result = backtest_jobs.load_job_result_light(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found or expired")
    return result


@router.get("/backtest/{job_id}/equity/{date}")
def get_backtest_job_equity(job_id: str, date: str, ticker: str | None = None):
    """Equity curve for a single day, loaded on demand."""
    equity = backtest_jobs.load_job_equity(job_id, date, ticker)
    if equity is None:
        # No equity for this day (e.g. a no-trade day) → empty, not an error.
        return {"date": date, "ticker": ticker, "equity": []}
    return equity


@router.get("/candles")
def get_candles(dataset_id: str, ticker: str, date: str):
    if dataset_id == "mock_dataset_1":
        return generate_mock_candles(ticker, date)

    candles = fetch_day_candles(dataset_id, ticker, date)
    if not candles:
        raise HTTPException(status_code=404, detail="No candle data found")
    return {"ticker": ticker, "date": date, "candles": candles}


def _ym_window(date_str: str, back: int, fwd: int) -> list[tuple[int, int]]:
    """Pares (year, month) desde `back` meses atrás hasta `fwd` adelante."""
    from datetime import datetime
    base = datetime.strptime(date_str, "%Y-%m-%d")
    out = []
    for delta in range(-back, fwd + 1):
        mm = base.month + delta
        yy = base.year + (mm - 1) // 12
        out.append((yy, (mm - 1) % 12 + 1))
    return out


@lru_cache(maxsize=4096)
def _adjacent_trading_dates(ticker: str, date: str, direction: str, limit: int) -> tuple[str, ...]:
    """Días de trading adyacentes de un ticker vía daily_metrics.

    daily_metrics es una vista sobre parquets remotos en GCS: sin poda de
    particiones cada consulta escanea TODO el histórico (~7-15s medidos en
    prod). Podamos a mes actual ± 1 (year/month son columnas hive), lo que
    baja a ~2s, y cacheamos en proceso para que repetir un trade sea
    instantáneo. Un ticker con un halt > 1 mes devuelve menos días y el chart
    simplemente muestra menos contexto.
    """
    from app.database import get_db_connection
    con = get_db_connection()
    if direction == "succ":
        pairs = _ym_window(date, 0, 1)
        cmp_op, order = ">", "ASC"
    else:
        pairs = _ym_window(date, 1, 0)
        cmp_op, order = "<", "DESC"
    ym_pred = " OR ".join(f"(year = {y} AND month = {m})" for y, m in pairs)
    query = f"""
        SELECT DISTINCT CAST("timestamp" AS DATE) AS d
        FROM daily_metrics
        WHERE ({ym_pred}) AND ticker = ?
          AND CAST("timestamp" AS DATE) {cmp_op} CAST(? AS DATE)
        ORDER BY d {order}
        LIMIT {int(limit)}
    """
    rows = con.execute(query, [ticker, date]).fetchall()
    return tuple(str(r[0]) for r in rows)


@router.get("/candles/multi")
def get_multi_candles(
    dataset_id: str,
    ticker: str,
    date: str,
    apply_day: str = "gap_day",
    swing_active: bool = False,
    swing_target_day: str = "gap_1_day"
):
    count = 1
    if apply_day == "gap_1_day":
        count = 2
    elif apply_day == "gap_2_day":
        count = 3

    if swing_active:
        if swing_target_day == "gap_2_day":
            count = max(count, 3)
        elif swing_target_day == "gap_1_day":
            count = max(count, 2)

    if dataset_id == "mock_dataset_1":
        from datetime import datetime, timedelta
        try:
            base_dt = datetime.strptime(date, "%Y-%m-%d")
        except Exception:
            base_dt = datetime.now()
        
        if apply_day == "gap_day":
            dates = [
                date,
                (base_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                (base_dt + timedelta(days=2)).strftime("%Y-%m-%d")
            ]
        elif apply_day == "gap_1_day":
            dates = [
                (base_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
                date,
                (base_dt + timedelta(days=1)).strftime("%Y-%m-%d")
            ]
        else: # gap_2_day
            dates = [
                (base_dt - timedelta(days=2)).strftime("%Y-%m-%d"),
                (base_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
                date
            ]
        dates = dates[:count]
    elif count == 1:
        # Solo se muestra el propio día: no hace falta consultar días adyacentes.
        # (Antes se lanzaba igualmente la query a daily_metrics —vista remota
        # sobre GCS, 7-15s— y se descartaba el resultado.)
        dates = [date]
    else:
        try:
            if apply_day == "gap_day":
                succeeding = list(_adjacent_trading_dates(ticker, date, "succ", 2))
                dates = [date] + succeeding
            elif apply_day == "gap_1_day":
                preceding = _adjacent_trading_dates(ticker, date, "prec", 1)
                gap_day = preceding[0] if preceding else date
                succeeding = _adjacent_trading_dates(ticker, date, "succ", 1)
                dates = [gap_day, date]
                if succeeding:
                    dates.append(succeeding[0])
            else: # gap_2_day
                preceding = list(_adjacent_trading_dates(ticker, date, "prec", 2))
                if len(preceding) == 2:
                    dates = [preceding[1], preceding[0], date]
                elif len(preceding) == 1:
                    dates = [preceding[0], date]
                else:
                    dates = [date]

            dates = dates[:count]
        except Exception as e:
            logger.warning(f"/candles/multi: fallo obteniendo días adyacentes {ticker} {date}: {e}")
            # Fallback
            from app.services.data_service import fetch_preceding_trading_dates
            dates = fetch_preceding_trading_dates(ticker, date, count)
            if not dates:
                dates = [date]

    result = {}
    day_labels = []
    if len(dates) == 1:
        day_labels = ["gap_day"]
    elif len(dates) == 2:
        day_labels = ["gap_day", "gap_1_day"]
    elif len(dates) == 3:
        day_labels = ["gap_day", "gap_1_day", "gap_2_day"]
    else:
        day_labels = [f"day_{i}" for i in range(len(dates))]

    for idx, d in enumerate(dates):
        label = day_labels[idx] if idx < len(day_labels) else f"day_{idx}"
        if dataset_id == "mock_dataset_1":
            candles = generate_mock_candles(ticker, d)
        else:
            candles = fetch_day_candles(dataset_id, ticker, d)
        result[label] = {
            "date": d,
            "candles": candles
        }
    return result




@router.post("/montecarlo")
def run_montecarlo_endpoint(req: MonteCarloRequest):
    if not req.pnls:
        raise HTTPException(status_code=400, detail="No trades provided")
    if req.simulations < 100 or req.simulations > 10000:
        raise HTTPException(
            status_code=400, detail="Simulations must be between 100 and 10000"
        )
    try:
        return run_montecarlo(req.pnls, req.init_cash, req.simulations)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error en Monte Carlo: {str(e)}"
        )


@router.post("/what-if")
def run_what_if_endpoint(req: WhatIfRequest):
    if not req.trades:
        raise HTTPException(status_code=400, detail="No trades provided for simulation")
    try:
        return run_what_if(req.trades, req.params, req.init_cash, req.risk_r)
    except Exception as e:
        logger.error(f"  what-if FAILED: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en simulación What-if: {str(e)}")
