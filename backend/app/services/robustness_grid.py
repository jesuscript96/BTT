"""Motores de robustez que SI re-ejecutan backtests.

Los otros modulos (basico, Monte Carlo) trabajan sobre los trades ya guardados y
son instantaneos. Estos dos no pueden: la matriz locates x slippage y el
walk-forward completo necesitan volver a simular.

LA IDEA QUE LOS HACE VIABLES
----------------------------
Un backtest se compone de dos cosas muy desiguales:

  1. Cargar las velas de minuto y traducir la estrategia a señales de
     entrada/salida. Es LO CARO.
  2. Simular la ejecucion sobre esas señales. Es lo barato.

`locates_cost` y `slippage` NO intervienen en el paso 1: no cambian la
definicion de la estrategia ni cuando entra o sale, solo cuanto cuesta cada
operacion. Asi que las velas se cargan UNA vez, las señales se cachean por
(ticker, dia) y cada punto de la rejilla es solo el paso 2. Es la misma
maquinaria que usa la superficie de optimizacion, con otros ejes.

En esta maquina solo existe el metodo de arranque `spawn` (Windows), asi que el
optimizador ya cae a su via secuencial con cache compartida; aqui se hace lo
mismo de forma explicita, que ademas es lo que mas rendimiento saca de la cache.

Para el walk-forward la cache de señales se invalida en cuanto se toca un
parametro de indicador, pero NO si solo se mueven parametros de
`risk_management` — igual que en el optimizador.

⚠️ UNIDAD DEL SLIPPAGE
----------------------
El simulador que se usa de verdad (`portfolio_sim_jit._core_simulate_jit`)
aplica `slip = precio * slippage`, SIN dividir entre cien: para el, `slippage`
es una FRACCION. Pero el campo de la pagina de Backtester se titula
"Slippage (%)", asi que un 0,001 escrito ahi acaba siendo un 0,1% real, cien
veces mas de lo que parece. (El motor viejo `app/backtester/engine.py` SI
dividia entre cien — las dos vias no usaban la misma unidad. Ese fichero se
borro el 2026-08-31 por codigo muerto; lo que describe el resto de esta nota,
que es la unidad de ESTA via, sigue igual.)

Aqui se trabaja SIEMPRE en porcentaje de verdad y se convierte al entrar al
motor con `_slip(pct)`. Asi "0,5" significa medio por ciento, que es lo que
espera cualquiera que lo lea. Medido sobre la estrategia de prueba: el punto de
equilibrio esta en torno al 1,2% de slippage real.
"""
from __future__ import annotations

import copy
import logging
import time
from itertools import product

import numpy as np
import pandas as pd

from app.db.gcs_cache import (
    INTRADAY_BATCH_SIZE,
    _fetch_and_cache_month,
    _select_intraday_glob_for_month,
    get_connection,
)
from app.services.backtest_service import run_backtest
from app.services.data_service import fetch_qualifying_data
from app.services.optimization_service import (
    _set_nested_value,
    is_optimization_cancelled,
    set_progress,
)

logger = logging.getLogger(__name__)


class Cancelled(RuntimeError):
    """El usuario paro la ejecucion desde la interfaz."""


def _check_cancel(task_id: str | None) -> None:
    if task_id and is_optimization_cancelled(task_id):
        raise Cancelled("ROBUSTNESS_CANCELLED")


# ──────────────────────────────────────────────────────────────────────
# Carga (se paga UNA vez por ejecucion)
# ──────────────────────────────────────────────────────────────────────
def load_grid_context(
    dataset_id: str,
    strategy_def: dict,
    start_date: str | None,
    end_date: str | None,
    task_id: str | None = None,
) -> dict:
    """Candidatos + velas de minuto, ya agrupadas por (dia, ticker).

    Replica la carga de `run_optimization_surface` en vez de llamarla: aquella
    esta soldada a su barrido de parametros y extraerla obligaria a refactorizar
    codigo compartido con produccion. Los helpers que usa (el cache por mes en
    disco, sobre todo) SI se reutilizan, asi que los meses que el precache ya
    escribio son aciertos de cache tambien aqui.
    """
    t0 = time.time()
    apply_day = strategy_def.get("apply_day", "gap_day")
    preconditions = strategy_def.get("postgap_preconditions") or []

    qualifying_df = fetch_qualifying_data(
        dataset_id,
        req_start_date=start_date,
        req_end_date=end_date,
        preconditions=preconditions,
        apply_day=apply_day,
    )
    if qualifying_df is None or qualifying_df.empty:
        raise ValueError("No hay candidatos para ese periodo")

    if start_date:
        qualifying_df = qualifying_df[qualifying_df["date"].astype(str) >= str(start_date)]
    if end_date:
        qualifying_df = qualifying_df[qualifying_df["date"].astype(str) <= str(end_date)]
    if qualifying_df.empty:
        raise ValueError("No hay candidatos para ese periodo")

    _check_cancel(task_id)
    if task_id:
        set_progress(task_id, 2.0)

    dates = pd.to_datetime(qualifying_df["date"])
    ym_pairs = sorted(set(zip(dates.dt.year, dates.dt.month)))

    chunks = []
    for i, (year, month) in enumerate(ym_pairs):
        _check_cancel(task_id)
        mask = (dates.dt.year == year) & (dates.dt.month == month)
        pairs = qualifying_df.loc[mask, ["ticker", "date"]].drop_duplicates().copy()
        if pairs.empty:
            continue
        pairs["date"] = pd.to_datetime(pairs["date"]).dt.strftime("%Y-%m-%d")
        conn = get_connection()
        path = _select_intraday_glob_for_month(conn, year, month)
        if path is None:
            logger.warning(f"[ROB] {year}-{month:02d}: sin parquet de intradia, saltado")
            continue
        chunk = _fetch_and_cache_month(
            year, month, path, pairs,
            batch_size=max(1, int(INTRADAY_BATCH_SIZE)),
            mi=i + 1, n_months=len(ym_pairs),
        )
        if chunk is not None and not chunk.empty:
            chunks.append(chunk)
        if task_id:
            set_progress(task_id, round(2.0 + ((i + 1) / len(ym_pairs)) * 8.0, 2))

    if not chunks:
        raise ValueError("No hay velas de minuto para ese periodo")

    intraday_df = pd.concat(chunks, ignore_index=True)
    valid = qualifying_df[["ticker", "date"]].drop_duplicates().copy()
    valid["date"] = valid["date"].astype(str)
    intraday_df["date"] = intraday_df["date"].astype(str)
    intraday_df = intraday_df.merge(valid, on=["ticker", "date"], how="inner")
    if intraday_df.empty:
        raise ValueError("No hay velas de minuto para ese periodo")

    groups = list(intraday_df.groupby(["date", "ticker"]))
    logger.info(f"[ROB] Contexto cargado: {len(groups)} grupos dia/ticker en {time.time() - t0:.1f}s")

    if task_id:
        set_progress(task_id, 10.0)

    return {
        "qualifying_df": qualifying_df,
        "groups": groups,
        "n_groups": len(groups),
        "load_seconds": round(time.time() - t0, 2),
    }


def _net_return_pct(agg: dict, init_cash: float) -> float | None:
    """Retorno descontando los gastos fijos mensuales.

    `total_return_pct` del motor es PnL de trades / capital inicial, sin
    gastos. `total_pnl_net` si los resta, asi que el retorno neto se
    reconstruye desde ahi.
    """
    net = agg.get("total_pnl_net")
    if net is None or not init_cash:
        return agg.get("total_return_pct")
    return round(float(net) / float(init_cash) * 100.0, 4)


def _slip(pct: float) -> float:
    """% real -> unidades del motor (que espera una fraccion). Ver la nota de arriba."""
    return float(pct) / 100.0


def _bt_kwargs(backtest_params: dict) -> dict:
    """Parametros de ejecucion comunes a todos los puntos de la rejilla."""
    return {
        "init_cash": backtest_params.get("init_cash", 10000.0),
        "risk_r": backtest_params.get("risk_r", 100.0),
        "risk_type": backtest_params.get("risk_type", "FIXED"),
        "fixed_ratio_delta": backtest_params.get("fixed_ratio_delta", 500.0),
        "size_by_sl": backtest_params.get("size_by_sl", False),
        "fees": backtest_params.get("fees", 0.0),
        "fee_type": backtest_params.get("fee_type", "PERCENT"),
        "market_sessions": backtest_params.get("market_sessions"),
        "custom_start_time": backtest_params.get("custom_start_time"),
        "custom_end_time": backtest_params.get("custom_end_time"),
        "locate_type": backtest_params.get("locate_type", "FLAT"),
        # Tope de locates: el barrido mueve el COSTE del locate, no el cupo de
        # acciones, asi que el tope se mantiene fijo en todos los puntos de la
        # rejilla (y del WFO, que reusa esta funcion).
        "max_locates": backtest_params.get("max_locates", 0),
        "look_ahead_prevention": backtest_params.get("look_ahead_prevention", True),
    }


def _run_point(
    ctx: dict,
    strategy_def: dict,
    backtest_params: dict,
    *,
    locates_cost: float,
    slippage: float,
    monthly_expenses: float = 0.0,
    signal_cache: dict | None = None,
    groups=None,
) -> dict:
    """Un backtest completo con un coste de locates y un slippage dados."""
    g = ctx["groups"] if groups is None else groups
    res = run_backtest(
        qualifying_df=ctx["qualifying_df"],
        strategy_def=strategy_def,
        slippage=_slip(slippage),
        locates_cost=locates_cost,
        monthly_expenses=monthly_expenses,
        day_group_iter=iter(g),
        n_groups_hint=len(g),
        _signal_cache=signal_cache,
        **_bt_kwargs(backtest_params),
    )
    return res.get("aggregate_metrics", {}) or {}


# ──────────────────────────────────────────────────────────────────────
# Modulo: modelizacion de locates (1D) y matriz locates x slippage (2D)
# ──────────────────────────────────────────────────────────────────────
def _linspace(lo: float, hi: float, steps: int) -> list[float]:
    steps = max(1, int(steps))
    if steps == 1 or abs(hi - lo) < 1e-12:
        return [round(float(lo), 6)]
    return [round(float(v), 6) for v in np.linspace(lo, hi, steps)]


def run_locates_curves(
    *,
    strategy_def: dict,
    dataset_id: str,
    backtest_params: dict,
    locates_values: list[float],
    slippage: float,
    monthly_expenses: float,
    start_date: str | None,
    end_date: str | None,
    task_id: str | None = None,
    ctx: dict | None = None,
) -> dict:
    """Una curva de equity por cada coste de locates. Eje X = tiempo o trades."""
    ctx = ctx or load_grid_context(dataset_id, strategy_def, start_date, end_date, task_id)
    # Las señales no dependen de locates ni de slippage: se calculan en el
    # primer punto y los demas las reutilizan.
    cache: dict = {}
    out = []
    t0 = time.time()
    init_cash = backtest_params.get("init_cash", 10000.0)

    for i, lc in enumerate(locates_values):
        _check_cancel(task_id)
        t1 = time.time()
        res = run_backtest(
            qualifying_df=ctx["qualifying_df"],
            strategy_def=strategy_def,
            slippage=_slip(slippage),
            locates_cost=lc,
            monthly_expenses=monthly_expenses,
            day_group_iter=iter(ctx["groups"]),
            n_groups_hint=ctx["n_groups"],
            _signal_cache=cache,
            **_bt_kwargs(backtest_params),
        )
        agg = res.get("aggregate_metrics", {}) or {}
        # Con gastos fijos hay que pintar la curva que los descuenta; la otra
        # es "solo trades" y no reflejaria lo que se ha pedido simular.
        eq = (
            (res.get("global_equity_expenses") or res.get("global_equity") or [])
            if monthly_expenses
            else (res.get("global_equity") or [])
        )
        trades = res.get("trades", []) or []

        # Curva por trade: PnL acumulado en el orden en que se cerraron.
        # pnl_with_locates (no pnl): esta curva se reconstruye trade a trade, no
        # sale de global_equity, asi que necesita el coste de locates incluido
        # o la reja locates x slippage saldria plana para el eje de locates.
        by_trade = [round(init_cash, 2)]
        acc = init_cash
        for t in sorted(trades, key=lambda x: x.get("exit_time") or ""):
            acc += float(t.get("pnl_with_locates", t.get("pnl")) or 0.0)
            by_trade.append(round(acc, 2))

        out.append({
            "locates_cost": lc,
            "seconds": round(time.time() - t1, 2),
            "metrics": {
                "total_return_pct": agg.get("total_return_pct"),
                # El motor calcula total_return_pct como PnL/capital SIN restar
                # los gastos fijos: solo aparecen en total_pnl_net. Si no se
                # recalcula aqui, poner gastos mensuales no movia ni la curva ni
                # el punto de equilibrio, que es justo para lo que se ponen.
                "return_net_pct": _net_return_pct(agg, init_cash),
                "max_drawdown_pct": agg.get("max_drawdown_pct"),
                "sharpe": agg.get("avg_sharpe"),
                "profit_factor": agg.get("avg_profit_factor"),
                "expectancy": agg.get("expectancy"),
                "total_trades": agg.get("total_trades"),
                "total_pnl": agg.get("total_pnl"),
                "total_pnl_net": agg.get("total_pnl_net"),
                "total_expenses": agg.get("total_expenses"),
            },
            "equity_by_time": [{"time": p.get("time"), "value": p.get("value")} for p in eq],
            "equity_by_trade": by_trade,
        })
        if task_id:
            set_progress(task_id, round(10.0 + ((i + 1) / len(locates_values)) * 90.0, 2))

    return {
        "kind": "locates_curves",
        "slippage": slippage,
        "monthly_expenses": monthly_expenses,
        "curves": out,
        "load_seconds": ctx.get("load_seconds"),
        "sweep_seconds": round(time.time() - t0, 2),
        "n_groups": ctx["n_groups"],
        "break_even": _break_even(
            [c["locates_cost"] for c in out],
            [c["metrics"]["return_net_pct"] for c in out],
        ),
    }


def _break_even(xs: list[float], ys: list) -> float | None:
    """Interpola el x donde y cruza cero por primera vez (de + a -)."""
    for i in range(1, len(xs)):
        a, b = ys[i - 1], ys[i]
        if a is None or b is None:
            continue
        if a > 0 >= b:
            span = a - b
            return round(xs[i - 1] + (xs[i] - xs[i - 1]) * (a / span if span else 0), 4)
    return None


def run_locates_slippage_matrix(
    *,
    strategy_def: dict,
    dataset_id: str,
    backtest_params: dict,
    locates_values: list[float],
    slippage_values: list[float],
    monthly_expenses: float,
    start_date: str | None,
    end_date: str | None,
    task_id: str | None = None,
    ctx: dict | None = None,
) -> dict:
    """Rejilla completa: un backtest por celda (locates, slippage)."""
    ctx = ctx or load_grid_context(dataset_id, strategy_def, start_date, end_date, task_id)
    cache: dict = {}
    n_points = len(locates_values) * len(slippage_values)
    t0 = time.time()

    keys = ("total_return_pct", "return_net_pct", "sharpe", "expectancy",
            "max_drawdown_pct", "profit_factor", "total_trades")
    init_cash = backtest_params.get("init_cash", 10000.0)
    grids = {k: [[None] * len(locates_values) for _ in slippage_values] for k in keys}

    done = 0
    per_point: list[float] = []
    for (si, slip), (li, lc) in product(enumerate(slippage_values), enumerate(locates_values)):
        _check_cancel(task_id)
        t1 = time.time()
        agg = _run_point(
            ctx, strategy_def, backtest_params,
            locates_cost=lc, slippage=slip,
            monthly_expenses=monthly_expenses, signal_cache=cache,
        )
        grids["total_return_pct"][si][li] = agg.get("total_return_pct")
        grids["return_net_pct"][si][li] = _net_return_pct(agg, init_cash)
        grids["sharpe"][si][li] = agg.get("avg_sharpe")
        grids["expectancy"][si][li] = agg.get("expectancy")
        grids["max_drawdown_pct"][si][li] = agg.get("max_drawdown_pct")
        grids["profit_factor"][si][li] = agg.get("avg_profit_factor")
        grids["total_trades"][si][li] = agg.get("total_trades")

        per_point.append(time.time() - t1)
        done += 1
        if task_id:
            set_progress(task_id, round(10.0 + (done / n_points) * 90.0, 2))
        if done % 10 == 0:
            logger.info(f"[ROB] matriz {done}/{n_points} ({time.time() - t0:.0f}s)")

    # Frontera de rentabilidad: para cada slippage, el coste de locates al que
    # el retorno cruza cero. Es la lectura util de la matriz.
    frontier = []
    for si, slip in enumerate(slippage_values):
        frontier.append({
            "slippage": slip,
            "break_even_locates": _break_even(locates_values, grids["return_net_pct"][si]),
        })

    return {
        "kind": "locates_slippage_matrix",
        "locates_values": locates_values,
        "slippage_values": slippage_values,
        "monthly_expenses": monthly_expenses,
        "grids": grids,
        "frontier": frontier,
        "n_points": n_points,
        "n_groups": ctx["n_groups"],
        "load_seconds": ctx.get("load_seconds"),
        "sweep_seconds": round(time.time() - t0, 2),
        "seconds_per_point": round(float(np.mean(per_point)), 3) if per_point else None,
        "first_point_seconds": round(per_point[0], 2) if per_point else None,
    }
