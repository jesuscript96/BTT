"""
Portfolio de estrategias — endpoints (PRD_portfolio_ANTIGRAVITY §4).

  POST /api/portfolio/run        → corre (o usa cache) cada estrategia + combina.
                                    Síncrono si todo está cacheado; async (202 +
                                    job_id) si hay que correr alguna.
  POST /api/portfolio/recombine  → solo re-combina trades cacheados con pesos
                                    nuevos (instantáneo, para los sliders).
  GET  /api/portfolio/{job_id}          → estado del job async.
  GET  /api/portfolio/{job_id}/result   → resultado combinado (sin equity pesada).
  POST /api/portfolio/save       → persiste el portfolio en backtest_results
                                    (search_mode='portfolio') → aparece en el Baúl.

Reutiliza el job store de backtest (backtest_jobs) y persist_backtest_row.
Toda persistencia en try/except log-only. (El viejo BacktestEngine, que este
modulo nunca tocaba, se borro el 2026-08-31 por ser codigo muerto.)
"""
import logging
import threading
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.services import backtest_jobs, portfolio_service

logger = logging.getLogger("backtester.portfolio")

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ──────────────────────────────────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────────────────────────────────
class PortfolioItem(BaseModel):
    strategy_id: str | None = None
    strategy_definition: dict | None = None
    # Weight of this strategy. Interpretation depends on `weight_unit`:
    #   'pct'      (default) → percent of equity (5 = 5%, 0.05 = 5%).
    #   'usd'      → a fixed DOLLAR amount for this strategy (e.g. 10000):
    #                fraction = amount / init_cash.
    #   'fraction' → already a fraction (0.05).
    pct_equity: float
    weight_unit: str = "pct"


class PortfolioRunRequest(BaseModel):
    # Where each strategy's curve comes from (2026-08-14):
    #   'saved' (default) → the LATEST backtest saved in the Baúl for each
    #     strategy. Nothing is re-run: the portfolio is just the SUM of the
    #     saved daily PnL curves. Instant, no async job.
    #   'rerun' → legacy: re-run each strategy through the live orchestrator
    #     over date_from/date_to with portfolio-level costs.
    source: str = "saved"
    # Optional: each strategy runs over its OWN universe (sdef["dataset_id"]);
    # this is only a fallback for inline drafts without one.
    # PRD §2 corrección 2026-08-11.
    dataset_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    items: list[PortfolioItem]
    init_cash: float = 10000.0
    max_total_exposure_pct: float = 100.0
    # R3 T1: sizing base. 'fixed' (default) = init_cash always (linear, see R);
    # 'daily_compound' = equity at the start of each session day.
    sizing_mode: str = "fixed"
    # R3 T4: portfolio-level costs (broker costs, not strategy params) applied
    # to every strategy via the orchestrator. Only used by source='rerun' —
    # saved trades already embed their run's costs. Defaults explicit (0).
    fees: float = 0.0
    fee_type: str = "PERCENT"
    slippage: float = 0.0
    locates_cost: float = 0.0
    locate_type: str = "FLAT"
    # Tope de locates (0 = sin tope). Ver portfolio_sim.simulate.
    max_locates: int = 0


class PortfolioRecombineRequest(BaseModel):
    portfolio_id: str
    items: list[PortfolioItem]
    init_cash: float | None = None
    max_total_exposure_pct: float | None = None
    sizing_mode: str | None = None  # falls back to the stored meta


class PortfolioSaveRequest(BaseModel):
    portfolio_id: str
    result: dict  # the combined result to persist
    label: str | None = None


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
def _normalize_pct(pct: float) -> float:
    """Accept either a fraction (0.05) or a percent (5) → fraction."""
    if pct is None:
        return 0.0
    if pct > 1.0:
        return pct / 100.0
    return float(pct)


def _weight_fraction(item: PortfolioItem, init_cash: float) -> float:
    """Item weight → fraction of the sizing base, per its ``weight_unit``.

    'usd' turns the input into a fixed dollar allocation for the strategy:
    fraction = amount / init_cash, so each trade's notional is that many
    dollars ('un número de dinero por estrategia y punto', 2026-08-14).
    """
    unit = (item.weight_unit or "pct").lower()
    v = float(item.pct_equity or 0.0)
    if unit == "usd":
        if init_cash and init_cash > 0:
            return v / init_cash
        return 0.0
    if unit == "fraction":
        return v
    return _normalize_pct(v)


def _req_costs(req: PortfolioRunRequest) -> dict:
    """Build the portfolio-level costs dict (R3 T4) for the cache key + run."""
    return {
        "fees": req.fees,
        "fee_type": req.fee_type,
        "slippage": req.slippage,
        "locates_cost": req.locates_cost,
        "locate_type": req.locate_type,
        "max_locates": req.max_locates,
    }


def _resolve_strategy(item: PortfolioItem, index: int = 0) -> dict:
    """Load the strategy (by id or inline definition) → {id, name, definition}.

    ``index`` disambiguates inline (draft) definitions so two drafts don't
    collide on id="draft" — which would collapse them into a single strategy
    and yield a 1×1 correlation matrix instead of n×n.
    """
    from app.services.data_service import get_strategy

    if item.strategy_id:
        strategy = get_strategy(item.strategy_id)
        if strategy is None:
            if item.strategy_definition:
                return {
                    "id": item.strategy_id,
                    "name": item.strategy_definition.get("name") or "Draft",
                    "definition": item.strategy_definition,
                }
            raise HTTPException(
                status_code=404,
                detail=f"Strategy not found: {item.strategy_id}",
            )
        return strategy
    if item.strategy_definition:
        return {
            "id": f"draft_{index}",
            "name": item.strategy_definition.get("name") or f"Draft {index + 1}",
            "definition": item.strategy_definition,
        }
    raise HTTPException(
        status_code=400,
        detail="Each item needs strategy_id or strategy_definition",
    )


def _strategy_label(strategy: dict) -> str:
    return strategy.get("name") or strategy.get("id") or "Draft"


def _build_result_envelope(
    req: PortfolioRunRequest,
    combined: dict,
    strategies: list[dict],
    portfolio_id: str,
    cache_keys: dict[str, str],
) -> dict:
    """Attach metadata the frontend needs (portfolio_id, labels, params)."""
    strategy_order = combined.get("strategy_order", [])
    name_by_id = {
        (s.get("id") or "draft"): _strategy_label(s) for s in strategies
    }
    combined.update(
        {
            "portfolio_id": portfolio_id,
            "dataset_id": req.dataset_id,
            "date_from": req.date_from,
            "date_to": req.date_to,
            "strategy_names": {
                sid: name_by_id.get(sid, sid) for sid in strategy_order
            },
            "search_mode": "portfolio",
            "label": (
                f"[portfolio] {' + '.join(name_by_id.get(sid, sid) for sid in strategy_order)} "
                f"· {req.date_from or '?'} → {req.date_to or '?'} "
                f"· {datetime.now():%Y-%m-%d %H:%M}"
            ),
        }
    )
    return combined


# ──────────────────────────────────────────────────────────────────────────
# POST /api/portfolio/run
# ──────────────────────────────────────────────────────────────────────────
@router.post("/run")
def run_portfolio(
    req: PortfolioRunRequest,
    response: Response,
    user_id: Optional[str] = Depends(get_current_user_id),
):
    if len(req.items) < 2:
        raise HTTPException(
            status_code=400,
            detail="A portfolio needs at least 2 strategies.",
        )

    # Resolve all strategies + compute cache keys to decide sync vs async.
    strategies: list[dict] = []
    cache_keys: dict[str, str] = {}
    all_cached = True
    for idx, item in enumerate(req.items):
        strat = _resolve_strategy(item, idx)
        strategies.append(strat)
        sid = strat.get("id") or "draft"
        ckey = portfolio_service._strategy_cache_key(
            req.dataset_id, req.date_from, req.date_to, strat.get("definition"),
            _req_costs(req),
        )
        cache_keys[sid] = ckey
        if portfolio_service._STRATEGY_RUN_CACHE.get(ckey) is None:
            all_cached = False

    portfolio_id = f"pf_{uuid.uuid4().hex[:12]}"

    # ── SAVED source (default): sum the curves of the saved runs — instant,
    #    synchronous, nothing is re-run. ──
    if (req.source or "saved").lower() == "saved":
        return _build_from_saved(req, strategies, portfolio_id, user_id)

    # ── RERUN source (legacy) ──
    # SYNC path: everything cached → combine now ──
    if all_cached:
        return _build_and_combine_sync(
            req, strategies, cache_keys, portfolio_id
        )

    # ASYNC path: some strategies need running → background thread ──
    backtest_jobs.cleanup_old_results()
    job_id = backtest_jobs.new_job_id()
    backtest_jobs.set_job_state(
        job_id, req.dataset_id, "running",
        percent=0.0, current=0, total=len(req.items),
    )
    thread = threading.Thread(
        target=_run_portfolio_in_background,
        args=(req, job_id, portfolio_id, strategies, cache_keys, user_id),
        daemon=True,
    )
    thread.start()
    logger.info(f"[PORTFOLIO JOB] {job_id} launched (portfolio={portfolio_id})")

    response.status_code = status.HTTP_202_ACCEPTED
    return {
        "job_id": job_id,
        "portfolio_id": portfolio_id,
        "dataset_id": req.dataset_id,
        "status": "running",
    }


def _build_from_saved(
    req: PortfolioRunRequest,
    strategies: list[dict],
    portfolio_id: str,
    user_id: Optional[str],
) -> dict:
    """Sum-of-curves from the SAVED runs (Baúl) — synchronous and instant.

    For every strategy: fetch its latest saved backtest row, tag its trades,
    stash them in the strategy-run cache (so /recombine works unchanged),
    then combine. Nothing is re-run: each strategy contributes the exact
    curve it was validated with (its own dataset, period and costs are
    already embedded in the saved trades).
    """
    import time as _time

    per_strategy_trades: dict[str, list[dict]] = {}
    weights_pct: dict[str, float] = {}
    cache_keys: dict[str, str] = {}
    saved_runs: dict[str, dict] = {}

    for strat, item in zip(strategies, req.items):
        sid = strat.get("id") or "draft"
        trades, meta = portfolio_service.get_saved_strategy_trades(sid, user_id)
        for t in trades:
            t["strategy_id"] = sid
        per_strategy_trades[sid] = trades
        weights_pct[sid] = _weight_fraction(item, req.init_cash)

        ckey = f"saved_{meta['backtest_id']}"
        cached_trades = [{**t} for t in trades]
        for t in cached_trades:
            t.pop("strategy_id", None)
        portfolio_service._STRATEGY_RUN_CACHE[ckey] = {
            "trades": cached_trades, "ts": _time.time()
        }
        portfolio_service._evict(
            portfolio_service._STRATEGY_RUN_CACHE,
            portfolio_service._STRATEGY_RUN_CACHE_MAX,
        )
        cache_keys[sid] = ckey
        saved_runs[sid] = meta

    combined = portfolio_service.combine_portfolio(
        per_strategy_trades,
        weights_pct,
        req.init_cash,
        req.max_total_exposure_pct,
        req.sizing_mode,
    )
    portfolio_service.register_portfolio(
        portfolio_id,
        strategy_cache_keys=cache_keys,
        strategy_order=combined.get("strategy_order", list(per_strategy_trades.keys())),
        dataset_id=req.dataset_id,
        date_from=req.date_from,
        date_to=req.date_to,
        init_cash=req.init_cash,
        max_total_exposure_pct=req.max_total_exposure_pct,
        sizing_mode=req.sizing_mode,
    )

    # Envelope dates = the span actually covered by the saved runs.
    dfs = [m["date_from"] for m in saved_runs.values() if m.get("date_from")]
    dts = [m["date_to"] for m in saved_runs.values() if m.get("date_to")]
    req.date_from = min(dfs) if dfs else req.date_from
    req.date_to = max(dts) if dts else req.date_to

    envelope = _build_result_envelope(req, combined, strategies, portfolio_id, cache_keys)
    envelope["source"] = "saved"
    envelope["saved_runs"] = saved_runs
    return envelope


def _build_and_combine_sync(
    req: PortfolioRunRequest,
    strategies: list[dict],
    cache_keys: dict[str, str],
    portfolio_id: str,
) -> dict:
    """Fetch cached trades for every strategy + combine + register for recombine."""
    per_strategy_trades: dict[str, list[dict]] = {}
    weights_pct: dict[str, float] = {}
    for strat, item in zip(strategies, req.items):
        sid = strat.get("id") or "draft"
        ckey = cache_keys[sid]
        cached = portfolio_service._STRATEGY_RUN_CACHE.get(ckey)
        if cached is None:
            # Should not happen on the sync path, but guard anyway.
            raise HTTPException(
                status_code=409,
                detail=f"Cache miss for {sid} on sync path — retry.",
            )
        trades = [{**t} for t in cached["trades"]]
        for t in trades:
            t["strategy_id"] = sid
        per_strategy_trades[sid] = trades
        weights_pct[sid] = _weight_fraction(item, req.init_cash)

    combined = portfolio_service.combine_portfolio(
        per_strategy_trades,
        weights_pct,
        req.init_cash,
        req.max_total_exposure_pct,
        req.sizing_mode,
    )
    portfolio_service.register_portfolio(
        portfolio_id,
        strategy_cache_keys=cache_keys,
        strategy_order=combined.get("strategy_order", list(per_strategy_trades.keys())),
        dataset_id=req.dataset_id,
        date_from=req.date_from,
        date_to=req.date_to,
        init_cash=req.init_cash,
        max_total_exposure_pct=req.max_total_exposure_pct,
        sizing_mode=req.sizing_mode,
    )
    return _build_result_envelope(req, combined, strategies, portfolio_id, cache_keys)


def _run_portfolio_in_background(
    req: PortfolioRunRequest,
    job_id: str,
    portfolio_id: str,
    strategies: list[dict],
    cache_keys: dict[str, str],
    user_id: Optional[str],
):
    """Run missing strategies (cached automatically), then combine + save."""
    try:
        per_strategy_trades: dict[str, list[dict]] = {}
        weights_pct: dict[str, float] = {}
        done = 0
        for strat, item in zip(strategies, req.items):
            sid = strat.get("id") or "draft"
            trades, ckey, was_cached = portfolio_service.run_strategy_trades(
                req.dataset_id,
                req.date_from,
                req.date_to,
                strategy_id=strat.get("id"),
                strategy_definition=strat.get("definition"),
                init_cash=req.init_cash,
                fees=req.fees,
                fee_type=req.fee_type,
                slippage=req.slippage,
                locates_cost=req.locates_cost,
                locate_type=req.locate_type,
                max_locates=req.max_locates,
            )
            cache_keys[sid] = ckey  # ensure exact key stored
            per_strategy_trades[sid] = trades
            weights_pct[sid] = _weight_fraction(item, req.init_cash)
            done += 1
            backtest_jobs.set_job_state(
                job_id, req.dataset_id, "running",
                percent=round(done / len(strategies) * 90.0, 1),
                current=done, total=len(strategies),
            )

        combined = portfolio_service.combine_portfolio(
            per_strategy_trades,
            weights_pct,
            req.init_cash,
            req.max_total_exposure_pct,
            req.sizing_mode,
        )
        portfolio_service.register_portfolio(
            portfolio_id,
            strategy_cache_keys=cache_keys,
            strategy_order=combined.get("strategy_order", list(per_strategy_trades.keys())),
            dataset_id=req.dataset_id,
            date_from=req.date_from,
            date_to=req.date_to,
            init_cash=req.init_cash,
            max_total_exposure_pct=req.max_total_exposure_pct,
            sizing_mode=req.sizing_mode,
        )
        envelope = _build_result_envelope(req, combined, strategies, portfolio_id, cache_keys)
        backtest_jobs.save_job_result(job_id, envelope)
        backtest_jobs.set_job_state(
            job_id, req.dataset_id, "succeeded",
            percent=100.0, current=len(strategies), total=len(strategies),
        )
        logger.info(f"[PORTFOLIO JOB] {job_id} succeeded (portfolio={portfolio_id})")
    except HTTPException as he:
        backtest_jobs.set_job_state(
            job_id, req.dataset_id, "failed",
            error=str(he.detail),
        )
        logger.error(f"[PORTFOLIO JOB] {job_id} failed: {he.detail}")
    except Exception as e:
        backtest_jobs.set_job_state(
            job_id, req.dataset_id, "failed", error=str(e)
        )
        logger.error(f"[PORTFOLIO JOB] {job_id} crashed: {e}", exc_info=True)


# ──────────────────────────────────────────────────────────────────────────
# POST /api/portfolio/recombine (sliders — instant, no re-run)
# ──────────────────────────────────────────────────────────────────────────
@router.post("/recombine")
def recombine_portfolio(req: PortfolioRecombineRequest):
    per_strategy_trades = portfolio_service.get_portfolio_cached_trades(req.portfolio_id)
    if per_strategy_trades is None:
        raise HTTPException(
            status_code=404,
            detail="Portfolio cache not found or expired. Re-run /portfolio/run.",
        )
    meta = portfolio_service.get_portfolio_meta(req.portfolio_id) or {}
    init_cash = req.init_cash if req.init_cash is not None else meta.get("init_cash", 10000.0)
    max_exp = (
        req.max_total_exposure_pct
        if req.max_total_exposure_pct is not None
        else meta.get("max_total_exposure_pct", 100.0)
    )
    sizing_mode = (
        req.sizing_mode if req.sizing_mode is not None else meta.get("sizing_mode", "fixed")
    )

    weights_pct: dict[str, float] = {}
    for item in req.items:
        sid = item.strategy_id
        if sid is None:
            continue
        weights_pct[sid] = _weight_fraction(item, init_cash)

    combined = portfolio_service.combine_portfolio(
        per_strategy_trades, weights_pct, init_cash, max_exp, sizing_mode
    )
    combined["portfolio_id"] = req.portfolio_id
    combined["recombined"] = True
    return combined


# ──────────────────────────────────────────────────────────────────────────
# Async polling (reuse backtest_jobs)
# ──────────────────────────────────────────────────────────────────────────
@router.get("/{job_id}")
def get_portfolio_job(job_id: str):
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


@router.get("/{job_id}/result")
def get_portfolio_job_result(job_id: str):
    state = backtest_jobs.get_job_state(job_id)
    if state is not None and state.get("status") in ("running", None):
        return {"status": "running", "percent": state.get("percent", 0.0)}
    if state is not None and state.get("status") == "failed":
        raise HTTPException(status_code=500, detail=state.get("error") or "Portfolio failed")
    result = backtest_jobs.load_job_result_light(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found or expired")
    return result


# ──────────────────────────────────────────────────────────────────────────
# POST /api/portfolio/save (persist → Baúl)
# ──────────────────────────────────────────────────────────────────────────
@router.post("/save")
def save_portfolio(
    req: PortfolioSaveRequest,
    user_id: Optional[str] = Depends(get_current_user_id),
):
    """Persist a portfolio result into backtest_results (search_mode='portfolio').

    Reuses persist_backtest_row so it shows up in the Baúl like any backtest.
    All persistence is wrapped so a DB hiccup never breaks the caller.
    """
    try:
        from app.database import get_user_db_connection, get_user_db_lock
        from app.routers.strategy_search import persist_backtest_row

        result = req.result or {}
        agg = result.get("aggregate_metrics") or {}
        strategy_order = result.get("strategy_order") or []
        strategy_ids = strategy_order

        # results_json = the combined payload + weights + per_strategy + correlation
        results_json = {
            **result,
            "search_mode": "portfolio",
            "label": req.label or result.get("label"),
            "saved_at": datetime.now().isoformat(),
        }

        lock = get_user_db_lock()
        with lock:
            con = get_user_db_connection()
            try:
                persist_backtest_row(
                    con,
                    id=req.portfolio_id,
                    strategy_ids=strategy_ids,
                    results_json=results_json,
                    search_mode="portfolio",
                    search_space="portfolio_run",
                    user_id=user_id,
                )
            finally:
                con.close()
        return {"status": "ok", "id": req.portfolio_id}
    except Exception as e:
        logger.error(f"[PORTFOLIO SAVE] failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not save portfolio: {e}")
