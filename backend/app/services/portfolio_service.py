"""
Portfolio de estrategias — fusión ponderada por % de equity.

PRD: PRD_portfolio_ANTIGRAVITY.md (§3 = corazón de la combinación).

Capa NUEVA encima del simulador single-strategy vivo (sim_dispatch /
portfolio_sim_jit). NO toca ni revive BacktestEngine (muerto).

Modelo de sizing (fase 1): % de equity como TAMAÑO de posición. Cada trade
abre notional = p_k · base_equity. El PnL$ se calcula como
``notional · (return_pct / 100)`` donde ``return_pct`` es el ratio
size-independiente que emite el sim (verificado en portfolio_sim_jit:556-557:
``ret_pct = pnl / (entry_price * size) * 100``).

Modelo de combinación (cambio 2026-08-14, decisión de Álvaro): NO hay
backtest conjunto. Sumar las curvas de PnL diarias de cada estrategia
validada da el mismo resultado que testearlas juntas, así que el portfolio
ES esa suma: cada estrategia se simula de forma independiente con su peso
``p_k`` y el PnL diario total es la suma de los PnLs diarios de todas. El
drawdown se calcula SOBRE la curva total sumada (curva densa diaria). El
tope de exposición (``max_total_exposure_pct``) se aplica DENTRO de cada
estrategia (nunca entre estrategias): ninguna puede ser desplazada por la
actividad de otra.

Dos funciones públicas:
  - ``run_strategy_trades``  → corre (o usa cache) UNA estrategia y devuelve
    su lista de trades. Cachea por hash(dataset_id, date_from, date_to,
    strategy_definition) para que cambiar pesos solo re-combine.
  - ``combine_portfolio``    → suma de curvas. Devuelve equity total (suma
    diaria), métricas sobre la curva total, per-strategy, correlación y
    standalone.

El "standalone" de cada estrategia ES la curva individual que luego se suma:
combinado vs standalone difieren ÚNICAMENTE en la diversificación (el DD
total se mide sobre la suma, no como suma de DDs).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time

import numpy as np

logger = logging.getLogger("backtester.portfolio")

# Sanity guard thresholds (PRD R3 T5). Tunable; a portfolio exceeding these
# is almost certainly a sizing/compounding artifact, not a real result.
# Exceeded -> logger.warning + entry in the payload's sanity_warnings.
SANITY_MAX_TOTAL_RETURN_PCT = 100_000.0  # >100.000% total return -> warn
SANITY_MAX_NOTIONAL_MULT = 10.0          # a trade notional > 10x init_cash -> warn

# ──────────────────────────────────────────────────────────────────────────
# In-memory cache de corridas por-estrategia
# ──────────────────────────────────────────────────────────────────────────
# Clave: hash(dataset_id, date_from, date_to, strategy_definition).
# Valor: {"trades": [...], "ts": epoch}. Cambiar pesos → solo re-combina.
_STRATEGY_RUN_CACHE: dict[str, dict] = {}
_STRATEGY_RUN_CACHE_MAX = 64

# portfolio_id → metadatos para recombine (trades cacheados por strategy).
_PORTFOLIO_STORE: dict[str, dict] = {}
_PORTFOLIO_STORE_MAX = 32


# ──────────────────────────────────────────────────────────────────────────
# Saved-results source: the portfolio sums ALREADY-VALIDATED runs (Baúl)
# ──────────────────────────────────────────────────────────────────────────
def get_saved_strategy_trades(
    strategy_id: str, user_id: str | None = None
) -> tuple[list[dict], dict]:
    """Latest SAVED backtest run for a strategy → ``(trades, meta)``.

    2026-08-14: the portfolio does NOT re-run strategies. Each validated
    strategy already has its trades stored in ``backtest_results`` (the
    Baúl) — with ``return_pct`` (size-independent ratio), dates and epochs.
    Fetch the newest row linked to the strategy (user-scoped, legacy NULL
    rows visible to everyone) and return exactly what
    ``combine_portfolio`` consumes, plus display metadata.
    """
    import json as _json

    from app.database import get_user_db_connection, get_user_db_lock

    lock = get_user_db_lock()
    with lock:
        con = get_user_db_connection()
        try:
            scope = ""
            params: list = [f'%"{strategy_id}"%']
            if user_id:
                scope = " AND (user_id IS NULL OR user_id = ?)"
                params.append(user_id)
            row = con.execute(
                "SELECT id, results_json, executed_at FROM backtest_results "
                f"WHERE strategy_ids LIKE ?{scope} "
                "ORDER BY executed_at DESC LIMIT 1",
                params,
            ).fetchone()
        finally:
            con.close()

    if row is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=404,
            detail=(
                f"La estrategia '{strategy_id}' no tiene ningún backtest guardado "
                "en el Baúl. Corre y guarda un backtest de esa estrategia primero."
            ),
        )

    backtest_id, rj, executed_at = row
    data = _json.loads(rj)
    trades = data.get("trades") or []
    bp = data.get("backtest_params") or {}
    meta = {
        "backtest_id": backtest_id,
        "executed_at": str(executed_at),
        "date_from": bp.get("start_date"),
        "date_to": bp.get("end_date"),
        "n_trades": len(trades),
        "label": data.get("label"),
    }
    return trades, meta


def _evict(cache: dict, max_size: int):
    """LRU-ish eviction: drop oldest entries by insertion order when over cap."""
    while len(cache) > max_size:
        try:
            oldest = next(iter(cache))
            cache.pop(oldest, None)
        except StopIteration:
            break


def _strategy_cache_key(
    dataset_id: str | None,
    date_from: str | None,
    date_to: str | None,
    strategy_definition: dict | None,
    costs: dict | None = None,
) -> str:
    # Each strategy carries its own universe/dataset in its definition; use it
    # so the key reflects the ACTUAL dataset the strategy runs over (falls back
    # to the passed dataset_id for inline drafts without one).
    # PRD §2 corrección 2026-08-11.
    # R3 T4: costs (fees/slippage/locates) are included because they change the
    # emitted return_pct (portfolio_sim_jit.py:556) → a cost change must re-run.
    effective = (strategy_definition or {}).get("dataset_id") or dataset_id
    blob = json.dumps(
        {
            "dataset_id": effective,
            "date_from": date_from,
            "date_to": date_to,
            "strategy_definition": strategy_definition,
            "costs": costs or {},
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ──────────────────────────────────────────────────────────────────────────
# B1 — run_strategy_trades: corre una estrategia (o usa cache) → trades[]
# ──────────────────────────────────────────────────────────────────────────
def run_strategy_trades(
    dataset_id: str,
    date_from: str | None,
    date_to: str | None,
    *,
    strategy_id: str | None = None,
    strategy_definition: dict | None = None,
    init_cash: float = 10000.0,
    look_ahead_prevention: bool = True,
    fees: float = 0.0,
    fee_type: str = "PERCENT",
    slippage: float = 0.0,
    locates_cost: float = 0.0,
    locate_type: str = "FLAT",
    # Tope de locates: maximo de paquetes de 100 acciones en corto por
    # ticker-dia. 0 = sin tope. Va en la clave de cache porque CAMBIA el tamano
    # de las posiciones (y con el, el return_pct de cada trade).
    max_locates: int = 0,
) -> tuple[list[dict], str, bool]:
    """Run ONE strategy through the live orchestrator and return its trades.

    Returns ``(trades, cache_key, was_cached)``. ``trades`` are the enriched
    trade dicts (entry_time_epoch, exit_time_epoch, ticker, return_pct, pnl…)
    tagged with ``strategy_id``. Cached in-memory so changing weights only
    re-combines (instant).

    R3 T4: costs (fees/slippage/locates) ARE passed to the orchestrator because
    they change the emitted ``return_pct`` (portfolio_sim_jit.py:556:
    ``ret_pct = pnl/(entry_price*size)*100`` with ``pnl = gross - fees`` and
    slip-adjusted prices). They are portfolio-level (broker costs, not strategy
    params) and included in the cache key so a cost change re-runs.
    ``look_ahead_prevention`` is forced True per AGENTS.md (no es un default
    neutro).
    """
    # Resolve the strategy definition (for cache key + orchestrator fallback).
    from app.services.data_service import get_strategy

    strategy = None
    if strategy_id:
        strategy = get_strategy(strategy_id)
    if strategy is None and strategy_definition:
        strategy = {
            "id": strategy_id or "draft",
            "name": strategy_definition.get("name") or "Draft",
            "definition": strategy_definition,
        }
    if strategy is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=404,
            detail=f"Strategy not found: {strategy_id}",
        )

    sdef = strategy.get("definition") or {}
    # Each strategy runs over ITS OWN universe (sdef["dataset_id"]); fall back
    # to the request dataset_id only for inline drafts without one.
    # PRD §2 corrección 2026-08-11.
    effective_dataset_id = sdef.get("dataset_id") or dataset_id
    # R3 T4: costs are part of the cache key (they change return_pct).
    costs = {
        "fees": fees,
        "fee_type": fee_type,
        "slippage": slippage,
        "locates_cost": locates_cost,
        "locate_type": locate_type,
        "max_locates": max_locates,
    }
    cache_key = _strategy_cache_key(
        effective_dataset_id, date_from, date_to, sdef, costs
    )

    cached = _STRATEGY_RUN_CACHE.get(cache_key)
    if cached is not None:
        trades = cached["trades"]
        # tag strategy_id (cache stores generic trades)
        sid = strategy.get("id") or strategy_id or cache_key
        for t in trades:
            t["strategy_id"] = sid
        return trades, cache_key, True

    # ── Run the live single-strategy orchestrator ──
    from app.services.backtest_orchestrator import (
        BacktestRequest,
        run_backtest_orchestrator,
    )

    req = BacktestRequest(
        dataset_id=effective_dataset_id,
        strategy_id=strategy.get("id"),
        strategy_definition=sdef,
        init_cash=init_cash,
        start_date=date_from,
        end_date=date_to,
        look_ahead_prevention=look_ahead_prevention,
        fees=fees,
        fee_type=fee_type,
        slippage=slippage,
        locates_cost=locates_cost,
        locate_type=locate_type,
        max_locates=max_locates,
    )
    result = run_backtest_orchestrator(req)
    trades = result.get("trades", []) or []

    sid = strategy.get("id") or strategy_id or cache_key
    for t in trades:
        t["strategy_id"] = sid

    # Cache a strategy_id-stripped copy so the same entry can serve different
    # portfolio contexts (the id is re-tagged on read above).
    cached_trades = [{**t} for t in trades]
    for t in cached_trades:
        t.pop("strategy_id", None)
    _STRATEGY_RUN_CACHE[cache_key] = {"trades": cached_trades, "ts": time.time()}
    _evict(_STRATEGY_RUN_CACHE, _STRATEGY_RUN_CACHE_MAX)

    return trades, cache_key, False


# ──────────────────────────────────────────────────────────────────────────
# Partial-TP aggregation — one ENTRADA = one position (PRD R4)
# ──────────────────────────────────────────────────────────────────────────
def _aggregate_partials(trades: list[dict]) -> tuple[list[dict], int]:
    """Group a strategy's raw trade rows by ENTRY into ONE logical position.

    A strategy with partial take-profits emits ONE row per partial exit, all
    sharing the same ``entry_time_epoch``/``entry_price``/``size`` and a
    distinct ``exit_time_epoch``/``exit_reason``. Their ``return_pct`` are
    ADDITIVE contributions to the position (verified 2026-08-12 on Sailor RTH 1:
    856/856 multi-partial groups satisfy ``sum(pnl) == size*entry*sum(ret%)/100``
    and every group's partials share entry_price & size).

    Without this aggregation the portfolio sized EACH partial at full
    ``pct_equity`` (PRD R4 §1: 3131 entries -> 6051 positions; one entry alone
    held 20 fake positions = 100% of equity). Grouping here means the portfolio
    sizes each ENTRY once.

    Group key = ``(ticker, entry_time_epoch)`` (PRD R4 T1). Per group:
      * ``entry_time_epoch`` = the common entry;
      * ``exit_time_epoch``  = ``max`` of the partial exits — the position is
        considered closed when the LAST tramo exits. PRD R4 T4 holding note:
        the position occupies ``pct_equity`` from entry until that last exit;
        v1 holds the FULL pct the whole time (a partial TP reduces the real
        size progressively, but modelling that progressive release is deferred
        to a later round — documented here on purpose);
      * ``return_pct``       = ``sum`` of the partials (additive);
      * audit: ``n_partials``, ``pnl_backtest`` (sum pnl), ``r_multiple`` (sum),
        ``exit_reasons`` (list) — not consumed by the simulator, but cheap and
        useful for diagnostics.

    Rows missing ``entry_time_epoch``/``exit_time_epoch``/``return_pct`` are
    dropped (same filter the old flatten applied). Returns
    ``(aggregated_positions, n_raw_rows)``.
    """
    from collections import OrderedDict

    groups: "OrderedDict[tuple, list[dict]]" = OrderedDict()
    for t in trades:
        entry_t = t.get("entry_time_epoch")
        exit_t = t.get("exit_time_epoch")
        rp = t.get("return_pct")
        if entry_t is None or exit_t is None or rp is None:
            continue
        key = (t.get("ticker"), int(entry_t))
        groups.setdefault(key, []).append(t)

    aggregated: list[dict] = []
    for rows in groups.values():
        first = rows[0]
        exit_t = max(int(r.get("exit_time_epoch") or 0) for r in rows)
        return_pct = sum(float(r.get("return_pct") or 0.0) for r in rows)
        aggregated.append(
            {
                "ticker": first.get("ticker"),
                "date": first.get("date"),
                "entry_time_epoch": int(first["entry_time_epoch"]),
                "exit_time_epoch": exit_t,
                "return_pct": return_pct,
                "n_partials": len(rows),
                "pnl_backtest": sum(float(r.get("pnl") or 0.0) for r in rows),
                "r_multiple": sum(float(r.get("r_multiple") or 0.0) for r in rows),
                "exit_reasons": [r.get("exit_reason") for r in rows],
            }
        )
    return aggregated, len(trades)


# ──────────────────────────────────────────────────────────────────────────
# Core event-driven combination (§3)
# ──────────────────────────────────────────────────────────────────────────
def _simulate_combined(
    all_trades: list[dict],
    weights_pct: dict[str, float],
    init_cash: float,
    max_total_exposure_pct: float,
    sizing_mode: str = "fixed",
) -> dict:
    """Walk every trade's entry/exit as time-ordered events (T1 leak fix).

    Desde 2026-08-14 se llama UNA VEZ POR ESTRATEGIA (nunca en conjunto):
    produce la curva de PnL diaria individual que ``combine_portfolio`` luego
    suma. El tope de exposición se aplica dentro de esa única estrategia.

    Sizing base (PRD R3 T2) — ``notional = p_k · base_equity`` (NOT the
    instantaneous equity ``E``):

      * ``sizing_mode='fixed'`` (default): ``base_equity = init_cash`` always.
        Returns are LINEAR (no compounding) — clean view of the R.
      * ``sizing_mode='daily_compound'``: ``base_equity`` = equity at the START
        of the session day (rolled once when the trade's ``date`` changes).
        Within a session day every trade uses the SAME base; the equity is
        recomputed a single time at the close of each day. Never intraday
        compounding.

    The exposure cap (T3) is measured against the SAME ``base_equity`` (not
    ``E``). At each EXIT the PnL is still realized into the real equity ``E``
    (the curve is real); only the sizing BASE changes with the mode.

    At each ENTRY: enforce the cap, scaling or skipping the trade if it would
    breach. At each EXIT: realize ``pnl$ = notional · return_pct/100``.

    Ordering — per-timestamp 3-phase sweep (PRD FIX_CRITICO T1):
      ① close trades opened at a STRICTLY EARLIER timestamp (frees capital
        first → the original intent, more permissive and realistic);
      ② open new entries at this timestamp (respecting the cap);
      ③ close trades that opened at THIS SAME timestamp (zero-duration trades).

    A trade's EXIT can therefore NEVER precede its own ENTRY — which is what
    caused the permanent exposure leak: a zero-duration trade's exit was
    popped before its entry, so the entry reserved notional that was never
    freed; ~20 such leaks saturated the cap and silently dropped every later
    entry (the combined curve "died" after a few days).

    Anti-silence (T2) + reconciliation (T3) counters are returned so leaks and
    silent cap-skips can never happen invisibly again.
    """
    from collections import defaultdict

    exposure_cap_frac = max(0.0, max_total_exposure_pct) / 100.0

    # ── Build per-timestamp event buckets. Clamp exit so a trade can NEVER
    #    exit before it enters (real data showed exit <= entry for ~23 trades). ──
    entries_by_time: dict[int, list[int]] = defaultdict(list)
    exits_by_time: dict[int, list[int]] = defaultdict(list)
    for i, t in enumerate(all_trades):
        entry_t = int(t["entry_time_epoch"])
        exit_t = int(t["exit_time_epoch"])
        if exit_t < entry_t:
            exit_t = entry_t
        entries_by_time[entry_t].append(i)
        exits_by_time[exit_t].append(i)

    all_times = sorted(set(entries_by_time) | set(exits_by_time))

    E = float(init_cash)
    # R3 T2: sizing base. 'fixed' = init_cash always; 'daily_compound' = equity
    # at the start of the session day, rolled once per new `date` (NY session).
    sizing_mode = (sizing_mode or "fixed").lower()
    if sizing_mode not in ("fixed", "daily_compound"):
        sizing_mode = "fixed"
    base_equity = float(init_cash)
    current_day: str | None = None
    open_by_idx: dict[int, float] = {}  # trade_idx -> notional (set at entry)
    detail_by_idx: dict[int, dict] = {}

    first_t = all_times[0] if all_times else 0
    equity_curve: list[dict] = [{"time": int(first_t), "value": round(E, 4)}]

    # per-strategy daily PnL$ (keyed by date string) for correlation
    daily_pnl: dict[str, dict[str, float]] = {}
    per_strat_pnl_total: dict[str, float] = {}

    # T2/T3 counters.
    skipped_by_cap = 0
    scaled_by_cap = 0
    skipped_zero_weight = 0
    registered = 0
    skipped_busted = 0  # entries skipped because the account hit ≤ 0 equity

    def _open(idx: int) -> None:
        nonlocal skipped_by_cap, scaled_by_cap, skipped_zero_weight, registered
        nonlocal skipped_busted, base_equity, current_day
        trade = all_trades[idx]
        sid = trade["strategy_id"]
        p_k = float(weights_pct.get(sid, 0.0))
        if p_k <= 0:
            skipped_zero_weight += 1
            return
        # Account-bust guard: once equity hits ≤ 0 the strategy is done —
        # no more entries, no negative sizing bases. Without this a position
        # returning worse than -100% flips E negative and the compounding
        # explodes to absurd values (2026-08-14, USD weights + daily_compound).
        if E <= 0 or base_equity <= 0:
            skipped_busted += 1
            return
        # R3 T2: roll the sizing base when the NY session day changes. Session
        # day comes from the trade's `date` field (NEVER derived from a UTC
        # epoch). base_equity = E at the start of the new day.
        if sizing_mode == "daily_compound":
            t_day = trade.get("date") or ""
            if t_day and t_day != current_day:
                current_day = t_day
                base_equity = E
        notional = p_k * base_equity
        current_exposure = sum(open_by_idx.values())
        cap = exposure_cap_frac * base_equity
        scaled = False
        if cap >= 0 and current_exposure + notional > cap + 1e-9:
            remaining = cap - current_exposure
            if remaining <= 1e-9:
                notional = 0.0
                scaled = True
                skipped_by_cap += 1
            else:
                notional = remaining
                scaled = True
                scaled_by_cap += 1
        if notional > 0:
            open_by_idx[idx] = notional
            registered += 1
            detail_by_idx[idx] = {
                "strategy_id": sid,
                "ticker": trade.get("ticker"),
                "date": trade.get("date"),
                "entry_time_epoch": trade["entry_time_epoch"],
                "exit_time_epoch": trade["exit_time_epoch"],
                "return_pct": trade["return_pct"],
                "notional": round(notional, 4),
                "scaled": scaled,
                "pnl_dollars": None,
            }

    def _close(idx: int, ev_time: int) -> None:
        nonlocal E
        notional = open_by_idx.pop(idx, None)
        if notional is None:
            return
        trade = all_trades[idx]
        pnl_dollars = notional * (trade["return_pct"] / 100.0)
        E += pnl_dollars
        equity_curve.append({"time": int(ev_time), "value": round(E, 4)})

        d = detail_by_idx.get(idx)
        if d is not None:
            d["pnl_dollars"] = round(pnl_dollars, 4)

        # accumulate per-strategy daily PnL$ + totals
        sid = trade["strategy_id"]
        day = trade.get("date") or ""
        daily_pnl.setdefault(sid, {})
        daily_pnl[sid][day] = daily_pnl[sid].get(day, 0.0) + pnl_dollars
        per_strat_pnl_total[sid] = per_strat_pnl_total.get(sid, 0.0) + pnl_dollars

    for t in all_times:
        # ① Close trades already open from EARLIER timestamps (free capital).
        #    Zero-duration trades opening at `t` are not open yet → deferred.
        deferred: list[int] = []
        for idx in exits_by_time.get(t, []):
            if idx in open_by_idx:
                _close(idx, t)
            else:
                deferred.append(idx)
        # ② Open new entries at `t` (cap enforced with the capital just freed).
        for idx in entries_by_time.get(t, []):
            _open(idx)
        # ③ Close trades that opened at `t` (zero-duration). Now they're open.
        for idx in deferred:
            _close(idx, t)

    # ── T2: anti-silence guard — any position still open is a leak. ──
    open_positions_leaked = len(open_by_idx)
    if open_positions_leaked:
        logger.error(
            "[portfolio] LEAK DETECTED: %d position(s) still open after the "
            "simulation (notional reserved but never freed → PnL never realized). "
            "This is a bug; open_positions_leaked must be 0.",
            open_positions_leaked,
        )

    # ── T3: reconciliation — every attempted entry is either registered or
    #    skipped by the cap. A mismatch is a bug. ──
    trades_entrada_totales = len(all_trades) - skipped_zero_weight
    trades_registrados = registered
    if trades_entrada_totales != trades_registrados + skipped_by_cap:
        logger.error(
            "[portfolio] RECONCILIATION FAILED: entrada=%d != registrados=%d + "
            "skipped_by_cap=%d (delta=%d)",
            trades_entrada_totales,
            trades_registrados,
            skipped_by_cap,
            trades_entrada_totales - trades_registrados - skipped_by_cap,
        )

    combined_trades = [detail_by_idx[i] for i in sorted(detail_by_idx.keys())]
    return {
        "equity_curve": equity_curve,
        "combined_trades": combined_trades,
        "final_equity": E,
        "daily_pnl": daily_pnl,
        "per_strat_pnl_total": per_strat_pnl_total,
        "open_positions_leaked": open_positions_leaked,
        "skipped_by_cap": skipped_by_cap,
        "scaled_by_cap": scaled_by_cap,
        "skipped_zero_weight": skipped_zero_weight,
        "skipped_busted": skipped_busted,
        "trades_entrada_totales": trades_entrada_totales,
        "trades_registrados": registered,
        "sizing_mode": sizing_mode,
    }


# ──────────────────────────────────────────────────────────────────────────
# Metrics from a combined/standalone equity curve + trades
# ──────────────────────────────────────────────────────────────────────────
def _safe_round(v, n=4):
    try:
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return 0.0
        return round(float(v), n)
    except Exception:
        return 0.0


def _compute_metrics(
    equity_curve: list[dict],
    combined_trades: list[dict],
    init_cash: float,
) -> dict:
    """Metrics for a combined/standalone portfolio curve + trades.

    Delegates to the SAME function the normal backtester uses
    (``backtest_service._aggregate_metrics``) over a dense daily equity/drawdown
    built by ``_compute_global_equity_and_drawdown``. This keeps the portfolio
    numbers consistent with running each strategy separately and fixes the
    Calmar (near-zero drawdown from the sparse event curve → exploding CAGR) and
    Sharpe (bespoke divergent copy) bugs at the source. PRD §PART1 M1-M3.
    """
    from app.services.backtest_service import (
        _aggregate_metrics,
        _compute_global_equity_and_drawdown,
    )

    empty = {
        "total_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "sharpe": 0.0,
        "calmar": 0.0,
        "profit_factor": 0.0,
        "win_rate": 0.0,
        "total_trades": 0,
        "final_equity": init_cash,
        "init_cash": init_cash,
        "sortino": 0.0,
        "sharpe_note": None,
    }

    # Trades with realized pnl$ → the {pnl, date} shape the shared helpers expect.
    bt_trades = [
        {"date": t.get("date") or "", "pnl": float(t["pnl_dollars"])}
        for t in combined_trades
        if t.get("pnl_dollars") is not None
    ]

    if not bt_trades or not equity_curve or len(equity_curve) < 2:
        return {
            **empty,
            "final_equity": equity_curve[-1]["value"] if equity_curve else init_cash,
        }

    final_equity = float(equity_curve[-1]["value"])

    # Dense daily equity + drawdown (same construction as the normal backtest) so
    # the max drawdown is measured on a real calendar curve, not the sparse
    # event-driven one (which produced the ~0 DD that exploded Calmar).
    global_eq, global_dd, _ = _compute_global_equity_and_drawdown(bt_trades, init_cash)
    agg = _aggregate_metrics([], bt_trades, global_eq, global_dd, init_cash)

    sharpe = _safe_round(agg.get("avg_sharpe", 0.0))
    max_dd = _safe_round(agg.get("max_drawdown_pct", 0.0))
    total_return = _safe_round(agg.get("total_return_pct", 0.0))

    # ── Calmar sanity clamp (PRD M2): total_return/abs(maxDD) on a real drawdown.
    #    A value > ~1000 still signals a degenerate (near-flat) drawdown → N/A. ──
    calmar = _safe_round(agg.get("calmar_ratio", 0.0))
    if abs(calmar) > 1000.0:
        logger.warning(
            "[portfolio] Calmar %.2f out of sane range (maxDD=%.4f%%, ret=%.4f%%); "
            "returning N/A",
            calmar,
            max_dd,
            total_return,
        )
        calmar = None

    # ── Sharpe reliability note (PRD M3): sparse trades inflate the ratio. ──
    sharpe_note = "few trades" if len(bt_trades) < 30 else None

    return {
        "total_return_pct": total_return,
        "max_drawdown_pct": max_dd,
        "sharpe": sharpe,
        "calmar": _safe_round(calmar) if calmar is not None else None,
        "profit_factor": _safe_round(agg.get("avg_profit_factor", 0.0), 2),
        "win_rate": _safe_round(agg.get("win_rate_pct", 0.0), 2),
        "total_trades": int(agg.get("total_trades", len(bt_trades))),
        "final_equity": _safe_round(final_equity, 2),
        "init_cash": _safe_round(init_cash, 2),
        "sortino": _safe_round(agg.get("sortino_ratio", 0.0)),
        "sharpe_note": sharpe_note,
        # ── Aliases so the Baúl's _map_aggregate_metrics (strategy_search.py)
        # populates the typed columns when a portfolio is saved. ──
        "win_rate_pct": _safe_round(agg.get("win_rate_pct", 0.0), 2),
        "sharpe_ratio": sharpe,
        "avg_sharpe": sharpe,
        "avg_profit_factor": _safe_round(agg.get("avg_profit_factor", 0.0), 2),
        "calmar_ratio": _safe_round(calmar) if calmar is not None else None,
        "sortino_ratio": _safe_round(agg.get("sortino_ratio", 0.0)),
    }


def _compute_correlation(
    daily_pnl: dict[str, dict[str, float]],
    strategy_order: list[str],
) -> list[list[float]]:
    """Pearson correlation matrix of per-strategy daily PnL$ series.

    Aligned on the union of trading days; missing days = 0 (no PnL that day).
    Returns an n×n matrix in ``strategy_order``. Diagonal = 1.0; a strategy
    with zero variance (constant or empty) yields 0.0 off-diagonal.
    """
    n = len(strategy_order)
    if n < 2:
        return [[1.0]] if n == 1 else []

    # union of all days
    all_days: set[str] = set()
    for sid in strategy_order:
        all_days.update(daily_pnl.get(sid, {}).keys())
    days = sorted(all_days)
    if not days:
        return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]

    series = np.zeros((n, len(days)), dtype=np.float64)
    for i, sid in enumerate(strategy_order):
        dp = daily_pnl.get(sid, {})
        for j, d in enumerate(days):
            series[i, j] = dp.get(d, 0.0)

    corr = []
    for i in range(n):
        row = []
        for j in range(n):
            si = series[i]
            sj = series[j]
            vi = float(np.std(si))
            vj = float(np.std(sj))
            if vi < 1e-12 or vj < 1e-12:
                row.append(1.0 if i == j else 0.0)
                continue
            c = float(np.corrcoef(si, sj)[0, 1])
            if math.isnan(c):
                row.append(1.0 if i == j else 0.0)
            else:
                row.append(round(c, 4))
        corr.append(row)
    return corr


# ──────────────────────────────────────────────────────────────────────────
# Public: combine_portfolio — SUMA DE CURVAS DE PnL DIARIAS (sin backtest conjunto)
# ──────────────────────────────────────────────────────────────────────────
def _date_to_epoch(day: str) -> int:
    """'YYYY-MM-DD' → epoch UTC medianoche (eje X de la curva total diaria)."""
    from datetime import datetime, timezone

    try:
        return int(
            datetime.strptime(str(day)[:10], "%Y-%m-%d")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except (ValueError, TypeError):
        return 0


def combine_portfolio(
    per_strategy_trades: dict[str, list[dict]],
    weights_pct: dict[str, float],
    init_cash: float,
    max_total_exposure_pct: float = 100.0,
    sizing_mode: str = "fixed",
) -> dict:
    """Suma de curvas de PnL diarias — NO hay simulación conjunta (2026-08-14).

    Cada estrategia se simula de forma INDEPENDIENTE con su peso ``p_k``
    (``_simulate_combined`` con una sola estrategia: el tope de exposición se
    aplica dentro de esa estrategia, nunca entre estrategias). El portfolio
    es la SUMA: el PnL diario total = Σ_k PnL_diario_k(d), y la curva de
    equity total es ``init_cash + PnL acumulado`` sobre la unión de días
    (curva densa diaria). Todas las métricas agregadas — incluido el max
    drawdown — se calculan SOBRE esa curva total sumada.

    ``per_strategy_trades``: {strategy_id: [trade, ...]} donde cada trade tiene
    entry_time_epoch, exit_time_epoch, ticker, return_pct, date.
    ``weights_pct``: {strategy_id: fraction of equity, e.g. 0.05}.

    Devuelve:
      - equity_curve (densa, diaria, suma), aggregate_metrics sobre la curva total
      - per_strategy: {sid: {pct_equity, trades, return_contribution_pct,
        return_contribution_dollars, max_drawdown_pct, win_rate}}
      - correlation (matrix), strategy_order
      - standalone: {sid: {equity_curve, aggregate_metrics}} — exactamente las
        curvas individuales que se suman
      - combined_trades (detalle con notional, pnl$, scaled)
      - combination_mode: "sum_of_daily_pnl_curves"
    """
    strategy_order = sorted(per_strategy_trades.keys())

    # ── R4 T1/T2: aggregate partials per strategy into ONE position per ENTRY,
    #    THEN flatten. Each entry is sized once by the simulator (not each
    #    partial at full pct_equity). T3: standalone reuses this same aggregated
    #    `all_trades`, so combined-vs-standalone compares positions with
    #    positions. Counts feed the reconciliation banner (PRD R4 T5):
    #    input_rows_per_strategy (raw rows) vs positions_per_strategy
    #    (aggregated) vs positions_registradas/skipped_by_cap. ──
    all_trades: list[dict] = []
    input_rows_per_strategy: dict[str, int] = {}
    positions_per_strategy: dict[str, int] = {}
    trades_by_sid: dict[str, list[dict]] = {}
    for sid in strategy_order:
        raw = per_strategy_trades.get(sid, [])
        positions, n_raw = _aggregate_partials(raw)
        input_rows_per_strategy[sid] = n_raw
        positions_per_strategy[sid] = len(positions)
        strat_positions = [
            {
                "strategy_id": sid,
                "ticker": pos["ticker"],
                "date": pos["date"],
                "entry_time_epoch": pos["entry_time_epoch"],
                "exit_time_epoch": pos["exit_time_epoch"],
                "return_pct": pos["return_pct"],
                "n_partials": pos.get("n_partials", 1),
            }
            for pos in positions
        ]
        trades_by_sid[sid] = strat_positions
        all_trades.extend(strat_positions)
    # Backward-compatible alias (raw rows) for older UI/code paths.
    input_trades_per_strategy = input_rows_per_strategy

    # ── Simulación INDEPENDIENTE por estrategia → curva de PnL diaria propia.
    #    No existe simulación conjunta: sumar estas curvas equivale a testear
    #    las estrategias juntas (sizing lineal). El tope de exposición se
    #    aplica dentro de cada estrategia, nunca entre estrategias. ──
    solo_sims: dict[str, dict] = {}
    for sid in strategy_order:
        p_k = float(weights_pct.get(sid, 0.0))
        solo_sims[sid] = _simulate_combined(
            trades_by_sid[sid],
            {sid: p_k},
            init_cash,
            max_total_exposure_pct,
            sizing_mode,
        )

    # ── El portfolio ES la suma: PnL diario total = Σ_k PnL_diario_k(d). ──
    total_daily_pnl: dict[str, float] = {}
    for sid in strategy_order:
        for day, pnl in solo_sims[sid]["daily_pnl"].get(sid, {}).items():
            total_daily_pnl[day] = total_daily_pnl.get(day, 0.0) + pnl

    days = sorted(total_daily_pnl)
    E = float(init_cash)
    equity_curve: list[dict] = []
    if days:
        equity_curve.append({"time": _date_to_epoch(days[0]), "value": round(E, 4)})
        for day in days:
            E += total_daily_pnl[day]
            equity_curve.append(
                {"time": _date_to_epoch(day), "value": round(E, 4)}
            )
    else:
        equity_curve.append({"time": 0, "value": round(E, 4)})

    # Union of per-strategy trade details (already carry pnl_dollars), in time order.
    combined_trades: list[dict] = []
    for sid in strategy_order:
        combined_trades.extend(solo_sims[sid]["combined_trades"])
    combined_trades.sort(key=lambda t: (t.get("entry_time_epoch") or 0,))

    combined_metrics = _compute_metrics(equity_curve, combined_trades, init_cash)

    # ── Per-strategy contribution (from its own independent curve) ──
    per_strategy: dict[str, dict] = {}
    for sid in strategy_order:
        p_k = float(weights_pct.get(sid, 0.0))
        strat_trades = solo_sims[sid]["combined_trades"]
        pnl_total = solo_sims[sid]["per_strat_pnl_total"].get(sid, 0.0)
        # standalone DD proxy from this strategy's own pnl stream
        strat_pnls = [
            t["pnl_dollars"] for t in strat_trades if t.get("pnl_dollars") is not None
        ]
        max_dd = _max_dd_from_pnls(strat_pnls, init_cash)
        wins = sum(1 for p in strat_pnls if p > 0)
        per_strategy[sid] = {
            "pct_equity": _safe_round(p_k, 4),
            "trades": len(strat_trades),
            "return_contribution_pct": _safe_round(
                (pnl_total / init_cash) * 100.0 if init_cash > 0 else 0.0
            ),
            "return_contribution_dollars": _safe_round(pnl_total, 2),
            "max_drawdown_pct": _safe_round(max_dd),
            "win_rate": _safe_round(
                (wins / len(strat_pnls) * 100.0) if strat_pnls else 0.0, 2
            ),
        }

    # ── Correlation (per-strategy daily PnL$ — unchanged by the sum model) ──
    merged_daily_pnl: dict[str, dict[str, float]] = {
        sid: solo_sims[sid]["daily_pnl"].get(sid, {}) for sid in strategy_order
    }
    correlation = _compute_correlation(merged_daily_pnl, strategy_order)

    # ── Standalone = exactly the individual curves that were summed ──
    standalone: dict[str, dict] = {}
    for sid in strategy_order:
        solo = solo_sims[sid]
        standalone[sid] = {
            "equity_curve": solo["equity_curve"],
            "aggregate_metrics": _compute_metrics(
                solo["equity_curve"], solo["combined_trades"], init_cash
            ),
        }

    # Keep per-strategy maxDD consistent with the standalone dense-curve metric
    # (PRD §PART1 M4) so the contribution table matches the standalone column.
    for sid in strategy_order:
        sa = standalone.get(sid, {}).get("aggregate_metrics", {})
        if "max_drawdown_pct" in sa:
            per_strategy[sid]["max_drawdown_pct"] = sa["max_drawdown_pct"]

    # ── Counters: sums of the per-strategy sims (cap is per-strategy now). ──
    skipped_by_cap = sum(s["skipped_by_cap"] for s in solo_sims.values())
    scaled_by_cap = sum(s["scaled_by_cap"] for s in solo_sims.values())
    skipped_zero_weight = sum(s["skipped_zero_weight"] for s in solo_sims.values())
    skipped_busted = sum(s.get("skipped_busted", 0) for s in solo_sims.values())
    trades_registrados = sum(s["trades_registrados"] for s in solo_sims.values())
    open_positions_leaked = sum(
        s["open_positions_leaked"] for s in solo_sims.values()
    )
    trades_entrada_totales = len(all_trades) - skipped_zero_weight

    # ── R3 T5: sanity guard — flag absurd results (compounding/cost artifacts)
    #    so the UI can warn instead of showing 211M% as if it were normal. ──
    sanity_warnings: list[str] = []
    total_ret = combined_metrics.get("total_return_pct", 0.0) or 0.0
    if abs(total_ret) > SANITY_MAX_TOTAL_RETURN_PCT:
        msg = (
            f"total_return_pct={total_ret:.2f}% exceeds sanity threshold "
            f"({SANITY_MAX_TOTAL_RETURN_PCT}%)"
        )
        logger.warning("[portfolio] %s", msg)
        sanity_warnings.append(msg)
    max_notional = max(
        (t.get("notional", 0.0) for t in combined_trades),
        default=0.0,
    )
    if init_cash > 0 and max_notional > SANITY_MAX_NOTIONAL_MULT * init_cash:
        msg = (
            f"max trade notional={max_notional:.2f} exceeds "
            f"{SANITY_MAX_NOTIONAL_MULT}x init_cash ({init_cash})"
        )
        logger.warning("[portfolio] %s", msg)
        sanity_warnings.append(msg)

    return {
        "equity_curve": equity_curve,
        "aggregate_metrics": combined_metrics,
        "per_strategy": per_strategy,
        "correlation": correlation,
        "strategy_order": strategy_order,
        "standalone": standalone,
        "combined_trades": combined_trades,
        "weights": {sid: _safe_round(weights_pct.get(sid, 0.0), 4) for sid in strategy_order},
        "init_cash": _safe_round(init_cash, 2),
        "max_total_exposure_pct": _safe_round(max_total_exposure_pct, 2),
        "sizing_mode": sizing_mode,
        "sanity_warnings": sanity_warnings,
        # ── Sum-of-curves model markers. ──
        "combination_mode": "sum_of_daily_pnl_curves",
        "daily_pnl_total": {d: _safe_round(v, 4) for d, v in sorted(total_daily_pnl.items())},
        # ── T2/T3 — anti-silence + reconciliation (per-strategy, summed). ──
        "open_positions_leaked": open_positions_leaked,
        "skipped_by_cap": skipped_by_cap,
        "scaled_by_cap": scaled_by_cap,
        "skipped_zero_weight": skipped_zero_weight,
        "skipped_busted": skipped_busted,
        "trades_entrada_totales": trades_entrada_totales,
        "trades_registrados": trades_registrados,
        "input_trades_per_strategy": input_trades_per_strategy,
        # ── R4 T5: rows-vs-positions reconciliation. positions_registradas is
        #    an alias of trades_registrados. ──
        "input_rows_per_strategy": input_rows_per_strategy,
        "positions_per_strategy": positions_per_strategy,
        "positions_registradas": trades_registrados,
    }


def _max_dd_from_pnls(pnls: list[float], init_cash: float) -> float:
    """Max drawdown (%) from an ordered PnL$ stream, cumulative equity."""
    if not pnls:
        return 0.0
    eq = init_cash
    peak = init_cash
    max_dd = 0.0
    for p in pnls:
        eq += p
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (eq - peak) / peak * 100.0
            if dd < max_dd:
                max_dd = dd
    return max_dd


# ──────────────────────────────────────────────────────────────────────────
# Portfolio store (for recombine)
# ──────────────────────────────────────────────────────────────────────────
def register_portfolio(
    portfolio_id: str,
    *,
    strategy_cache_keys: dict[str, str],  # strategy_id -> cache_key
    strategy_order: list[str],
    dataset_id: str,
    date_from: str | None,
    date_to: str | None,
    init_cash: float,
    max_total_exposure_pct: float,
    sizing_mode: str = "fixed",
):
    """Stash the per-strategy cache keys so /recombine can fetch trades fast."""
    _PORTFOLIO_STORE[portfolio_id] = {
        "strategy_cache_keys": strategy_cache_keys,
        "strategy_order": strategy_order,
        "dataset_id": dataset_id,
        "date_from": date_from,
        "date_to": date_to,
        "init_cash": init_cash,
        "max_total_exposure_pct": max_total_exposure_pct,
        "sizing_mode": sizing_mode,
        "ts": time.time(),
    }
    _evict(_PORTFOLIO_STORE, _PORTFOLIO_STORE_MAX)


def get_portfolio_cached_trades(portfolio_id: str) -> dict[str, list[dict]] | None:
    """Return {strategy_id: trades} for a registered portfolio, or None."""
    entry = _PORTFOLIO_STORE.get(portfolio_id)
    if entry is None:
        return None
    out: dict[str, list[dict]] = {}
    for sid, ckey in entry["strategy_cache_keys"].items():
        cached = _STRATEGY_RUN_CACHE.get(ckey)
        if cached is None:
            return None  # cache evicted → caller must re-run
        trades = [{**t} for t in cached["trades"]]
        for t in trades:
            t["strategy_id"] = sid
        out[sid] = trades
    return out


def get_portfolio_meta(portfolio_id: str) -> dict | None:
    return _PORTFOLIO_STORE.get(portfolio_id)
