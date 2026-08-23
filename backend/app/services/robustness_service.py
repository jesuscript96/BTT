"""Motores de la pagina de Robustez (solo entorno local).

Trabaja SOBRE LOS TRADES YA GUARDADOS de una estrategia: cada corrida de
backtest que se guarda en el Baul lleva su `results_json` con `trades`,
`aggregate_metrics`, `global_equity` y `backtest_params`. Eso permite que los
modulos analiticos (basico, Monte Carlo, walk-forward rapido) sean
instantaneos: no se vuelve a tocar el lago ni a leer una vela.

Los dos modulos que SI re-ejecutan backtests (walk-forward completo y la matriz
locates x slippage) viven en `robustness_grid.py` y reutilizan la maquinaria
del optimizador: las velas se cargan una sola vez y cada punto de la rejilla es
solo simulacion.

Gated por ROBUSTNESS_ENABLED — ver routers/robustness.py.
"""
from __future__ import annotations

import json
from typing import Any, Optional

# Campos de trade que necesitan los motores de robustez. Se recortan a
# proposito: el resto (entry_idx, exit_idx, entry_time_epoch...) solo sirve para
# pintar velas y engorda el payload sin aportar nada aqui.
TRADE_FIELDS = (
    "ticker", "date", "entry_time", "exit_time",
    "entry_price", "exit_price", "pnl", "fees", "return_pct",
    "direction", "size", "exit_reason", "mae", "mfe",
    "r_multiple", "entry_hour", "entry_weekday", "gap_pct", "stop_loss",
    # Cost-inclusive pnl (locates), used only by attach_precise_r below to
    # reconstruct the equity curve for Monte Carlo / WFO / stress. Falls back
    # to `pnl` when absent (runs saved before this field existed).
    "pnl_with_locates",
)


def _as_dict(raw: Any) -> dict:
    """results_json llega como dict (DuckDB JSON) o como str segun el driver."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    return {}


def _as_list(raw: Any) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else []
        except (TypeError, ValueError):
            return []
    return []


def slim_trade(t: dict) -> dict:
    """Deja un trade con solo los campos que usan los motores."""
    return {k: t.get(k) for k in TRADE_FIELDS if k in t}


def list_runs_for_strategies(con, strategy_ids_wanted: set[str]) -> dict[str, dict]:
    """Devuelve, por strategy_id, la corrida MAS RECIENTE guardada en el Baul.

    Lee solo las columnas tipadas (nunca `results_json`): la lista de
    estrategias tiene que ser ligera. El endpoint del Baul existente devuelve
    48 MB porque arrastra los trades de todas las filas; aqui eso no puede
    pasar.
    """
    rows = con.execute(
        """
        SELECT id, strategy_ids, executed_at, total_trades, win_rate,
               profit_factor, total_return_pct, max_drawdown_pct, sharpe_ratio
        FROM backtest_results
        ORDER BY executed_at DESC
        """
    ).fetchall()

    best: dict[str, dict] = {}
    for r in rows:
        for sid in _as_list(r[1]):
            if sid not in strategy_ids_wanted or sid in best:
                continue  # ORDER BY DESC => la primera que aparece es la mas reciente
            best[sid] = {
                "run_id": r[0],
                "executed_at": str(r[2]) if r[2] else None,
                "total_trades": r[3],
                "win_rate": r[4],
                "profit_factor": r[5],
                "total_return_pct": r[6],
                "max_drawdown_pct": r[7],
                "sharpe_ratio": r[8],
                "backtest_params": {},
            }

    _attach_params(con, best)
    return best


def _attach_params(con, best: dict[str, dict]) -> None:
    """Rellena `backtest_params` de cada corrida sin traerse los trades.

    Se extrae por ruta JSON en la propia base (`json_extract`) en vez de leer
    `results_json` entero y quedarse una clave: ese blob son varios MB por
    corrida, y el listado tiene que seguir siendo ligero — es exactamente el
    problema que hace impracticable el endpoint del Baul.

    Best-effort: si la extraccion falla, se devuelve el dict vacio y la interfaz
    simplemente no enseña esa fila.
    """
    ids = [m["run_id"] for m in best.values()]
    if not ids:
        return
    placeholders = ", ".join("?" for _ in ids)
    try:
        rows = con.execute(
            f"SELECT id, json_extract(results_json, '$.backtest_params') "
            f"FROM backtest_results WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] backtest_params no extraidos: {e}")
        return

    by_id = {r[0]: _as_dict(r[1]) for r in rows}
    for meta in best.values():
        meta["backtest_params"] = by_id.get(meta["run_id"]) or {}


def _epoch_to_day(ts) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def attach_precise_r(
    trades: list[dict],
    global_equity: list[dict],
    init_cash: float,
    risk_pct: float,
) -> bool:
    """Añade `r_precise` a cada trade, in place. Devuelve si pudo ser exacta.

    El `r_multiple` que guarda el motor viene redondeado a DOS decimales. Sobre
    3.544 trades ese redondeo se acumula: recomponer la curva con el se desvia
    un +0,44% del balance final real.

    La R exacta se puede recuperar, porque se sabe como dimensiona el motor:
    arriesga `risk_pct` del balance de APERTURA del dia, asi que

        R = pnl_con_locates / (risk_pct * equity_al_empezar_el_dia)

    y ese balance es el punto anterior de la curva diaria, que viene en el
    payload. Verificado contra la corrida real: reconstruir la curva con esta R
    da 68.167,2441 $ frente a los 68.167,25 $ reales — 0,000009% de desvio,
    frente al 0,44% de la R redondeada.

    Usa `pnl_with_locates` (no `pnl`) porque Monte Carlo/WFO recomponen la
    curva desde estos R-multiplos — no leen `global_equity` salvo para el
    capital inicial — asi que si el R no lleva el coste de locates, cada curva
    simulada sale optimista en el total de locates pagado (`pnl` esta limpio a
    proposito para que no distorsione el win rate en la tabla de trades, ver
    portfolio_sim.py). Corridas guardadas antes de que existiera ese campo caen
    a `pnl` via el .get() de abajo, que es lo que habia siempre.

    Si no hay curva o el riesgo no es porcentual se cae a `r_multiple`.
    """
    if not global_equity or risk_pct <= 0:
        for t in trades:
            t["r_precise"] = float(t.get("r_multiple") or 0.0)
        return False

    start_of_day: dict[str, float] = {}
    prev = init_cash
    for p in global_equity:
        ts = p.get("time")
        if ts is None:
            continue
        start_of_day[_epoch_to_day(ts)] = prev
        prev = float(p.get("value") or prev)

    risk_frac = risk_pct / 100.0
    exact = True
    for t in trades:
        e0 = start_of_day.get(str(t.get("date") or ""))
        if e0 and e0 > 0:
            t["r_precise"] = float(t.get("pnl_with_locates", t.get("pnl")) or 0.0) / (risk_frac * e0)
        else:
            t["r_precise"] = float(t.get("r_multiple") or 0.0)
            exact = False
    return exact


def load_run_payload(con, run_id: str) -> Optional[dict]:
    """Carga UNA corrida y devuelve solo lo que consumen los motores.

    Se descartan `day_results` y `global_equity_expenses`: el primero pesa como
    los trades y no aporta nada que no este ya en ellos; el segundo se
    recalcula cuando se piden gastos fijos.
    """
    row = con.execute(
        "SELECT results_json, executed_at FROM backtest_results WHERE id = ?",
        [run_id],
    ).fetchone()
    if not row:
        return None

    rj = _as_dict(row[0])
    trades = [slim_trade(t) for t in (rj.get("trades") or []) if isinstance(t, dict)]
    params = rj.get("backtest_params") or {}
    equity = rj.get("global_equity") or []

    init_cash = float(params.get("init_cash") or 10000.0)
    # El riesgo solo es un % del capital cuando risk_type es PERCENT; con
    # FIXED se arriesga una cantidad en dolares y no hay composicion que
    # reconstruir.
    is_pct = str(params.get("risk_type") or "").upper() == "PERCENT"
    risk_pct = float(params.get("risk_r") or 0.0) if is_pct else 0.0
    exact = attach_precise_r(trades, equity, init_cash, risk_pct)

    return {
        "run_id": run_id,
        "executed_at": str(row[1]) if row[1] else None,
        "aggregate_metrics": rj.get("aggregate_metrics") or {},
        "backtest_params": params,
        "global_equity": equity,
        "global_drawdown": rj.get("global_drawdown") or [],
        "trades": trades,
        # La interfaz lo usa para elegir modelo por defecto y para avisar.
        "compounding": {
            "is_percent_risk": is_pct,
            "risk_pct": risk_pct,
            "init_cash": init_cash,
            "r_precise_exact": exact,
        },
    }
