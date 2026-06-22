"""HTTP endpoints for the `backtest` module.

Every handler: auth -> rate-limit -> gating hook -> work. The API is SYNCHRONOUS
with a technical ticker-days cap (docs/b2d-gateway/05 §4); async is v2 and the
contract already leaves room (`status`).
"""
from __future__ import annotations

import secrets
import time
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import ValidationError

from app.api_public.core.auth import Principal, authenticate
from app.api_public.core.errors import ApiError
from app.api_public.core import metering, ratelimit
from app.api_public.core.gating import require_access
from app.api_public.core.store import get_store
from app.api_public.facade import Facade, get_facade
from app.api_public.modules.backtest import mapper
from app.api_public.modules.backtest.catalog import build_catalog
from app.api_public.modules.backtest.models import (
    BacktestCreate,
    IndicatorCatalog,
    IntradayEquity,
    JobStatus,
    StrategyValidation,
    UniversePreview,
    UniverseSpec,
)
from app.schemas.strategy import StrategyCreate

MODULE = "backtest"

router = APIRouter(tags=["backtest"])


def authed(request: Request) -> Principal:
    """Auth + per-key rate limit. Returns the Principal."""
    principal = authenticate(request)
    ratelimit.enforce(principal)
    return principal


# ── Catalog ──────────────────────────────────────────────────────────────────
@router.get("/catalog/indicators", response_model=IndicatorCatalog)
def get_indicators(
    category: Optional[str] = Query(default=None),
    principal: Principal = Depends(authed),
):
    require_access(principal, MODULE, "read")
    entries = build_catalog()
    if category:
        entries = [e for e in entries if e["category"].lower() == category.lower()]
    return {"indicators": entries}


# ── Strategy validation (Pydantic; no engine) ────────────────────────────────
@router.post("/strategies/validate", response_model=StrategyValidation)
def validate_strategy(
    payload: dict = Body(..., description="Objeto Strategy (ver schema://strategy)"),
    principal: Principal = Depends(authed),
):
    require_access(principal, MODULE, "validate")
    try:
        StrategyCreate(**payload)
        return {"valid": True, "errors": []}
    except ValidationError as exc:
        errors = [
            {
                "path": ".".join(str(p) for p in err.get("loc", [])),
                "message": err.get("msg", "invalid"),
            }
            for err in exc.errors()
        ]
        return {"valid": False, "errors": errors}


# ── Universe preview ─────────────────────────────────────────────────────────
@router.post("/universe/preview", response_model=UniversePreview)
def preview_universe(
    spec: UniverseSpec,
    principal: Principal = Depends(authed),
    facade: Facade = Depends(get_facade),
):
    require_access(principal, MODULE, "preview")
    if not spec.dataset_ref:
        if spec.filters:
            raise ApiError(
                "not_implemented",
                "La creación de universo por filtros es v2. Usa 'dataset_ref'.",
                details={"hint": "universe.dataset_ref"},
            )
        raise ApiError("invalid_universe", "Falta 'universe.dataset_ref'.")

    preconditions = (
        [p.model_dump(mode="json") for p in spec.postgap_preconditions]
        if spec.postgap_preconditions
        else None
    )
    info = facade.preview_universe(
        spec.dataset_ref, spec.date_from, spec.date_to, preconditions, spec.apply_day
    )
    cap = principal.max_ticker_days
    td = int(info.get("ticker_days", 0))
    return {
        "ticker_days": td,
        "tickers": int(info.get("tickers", 0)),
        "within_cap": td <= cap,
        "cap": cap,
    }


# ── Run backtest (synchronous) ───────────────────────────────────────────────
@router.post("/backtests", response_model=JobStatus)
def create_backtest(
    body: BacktestCreate,
    principal: Principal = Depends(authed),
    facade: Facade = Depends(get_facade),
):
    require_access(principal, MODULE, "run")
    kwargs = mapper.to_request_kwargs(body)  # raises if no dataset_ref
    dataset_ref = body.universe.dataset_ref  # type: ignore[union-attr]

    # Cap check (skip for the mock sandbox, which is always small).
    cap = principal.max_ticker_days
    ticker_days = 0
    if dataset_ref != "mock_dataset_1":
        info = facade.preview_universe(
            dataset_ref, body.universe.date_from, body.universe.date_to,  # type: ignore[union-attr]
            None, body.universe.apply_day,  # type: ignore[union-attr]
        )
        ticker_days = int(info.get("ticker_days", 0))
        if ticker_days > cap:
            raise ApiError(
                "universe_too_large",
                f"El universo ({ticker_days} ticker-días) supera el límite de tu plan ({cap}).",
                details={"ticker_days": ticker_days, "cap": cap},
            )

    t0 = time.time()
    raw = facade.run_backtest(kwargs)
    engine_ms = int((time.time() - t0) * 1000)
    trades_total = len(raw.get("trades") or [])

    # Metering (always on; real numbers from the engine).
    metering.record_run(principal, MODULE, "run", ticker_days, trades_total)

    result_dto, meta_partial = mapper.build_result(
        raw, body.include, body.trades_limit, body.trades_cursor
    )
    job_id = "bt_" + secrets.token_hex(12)
    meta = {
        "ticker_days": ticker_days,
        "trades_total": trades_total,
        "engine_ms": engine_ms,
        "downsampled": meta_partial["downsampled"],
    }
    # Persist the raw result so GET/{id} and /intraday can serve it later.
    get_store().save_result(job_id, principal.api_key_id, "succeeded", raw, meta)

    return {"job_id": job_id, "status": "succeeded", "meta": meta, "result": result_dto}


# ── Retrieve a stored backtest ───────────────────────────────────────────────
@router.get("/backtests/{job_id}", response_model=JobStatus)
def get_backtest(
    job_id: str,
    include: Optional[str] = Query(default=None, description="Coma-separado: metrics,equity,days,trades"),
    trades_limit: Optional[int] = Query(default=None, ge=1, le=5000),
    trades_cursor: Optional[str] = Query(default=None),
    principal: Principal = Depends(authed),
):
    require_access(principal, MODULE, "read")
    stored = get_store().get_result(job_id, principal.api_key_id)
    if stored is None:
        raise ApiError("job_not_found", "No existe ese backtest para tu API key.")

    sections = (
        [s.strip() for s in include.split(",") if s.strip()]
        if include
        else ["metrics", "equity", "days"]
    )
    result_dto, _ = mapper.build_result(stored["raw"], sections, trades_limit, trades_cursor)
    return {
        "job_id": job_id,
        "status": stored["status"],
        "meta": stored["meta"],
        "result": result_dto,
    }


@router.post("/backtests/{job_id}/cancel")
def cancel_backtest(job_id: str, principal: Principal = Depends(authed)):
    require_access(principal, MODULE, "run")
    stored = get_store().get_result(job_id, principal.api_key_id)
    if stored is None:
        raise ApiError("job_not_found", "No existe ese backtest para tu API key.")
    # Synchronous API: a stored job is already finished.
    raise ApiError("conflict", "El backtest ya finalizó; no se puede cancelar.")


@router.get("/backtests/{job_id}/intraday", response_model=IntradayEquity)
def get_intraday(
    job_id: str,
    ticker: str = Query(...),
    date: str = Query(...),
    principal: Principal = Depends(authed),
):
    require_access(principal, MODULE, "read")
    stored = get_store().get_result(job_id, principal.api_key_id)
    if stored is None:
        raise ApiError("job_not_found", "No existe ese backtest para tu API key.")
    series = mapper.find_intraday_series(stored["raw"], ticker, date)
    if series is None:
        raise ApiError(
            "job_not_found",
            "No hay serie intradía para ese ticker/fecha en este backtest.",
            details={"ticker": ticker, "date": date},
        )
    return series
