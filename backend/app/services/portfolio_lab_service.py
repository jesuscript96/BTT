"""Pagina de Portfolio (laboratorio local): union y estudio de estrategias.

Modulo LOCAL, gated por PORTFOLIO_LAB_ENABLED (ver routers/portfolio_lab.py).
El prefijo /api/portfolio pertenece al modulo de produccion del equipo
(PRD_portfolio_ANTIGRAVITY); este vive aparte en /api/portfolio-lab y no toca
nada de aquel.

Mismo principio que Robustez: se trabaja SOBRE LAS CORRIDAS YA GUARDADAS.
Cada estrategia se lleva a un dominio comun — R normalizada por trade, sin
costes — y desde ahi la combinacion, la correlacion y la re-aplicacion de
costes son reconstruccion pura: no se re-ejecuta ningun backtest.

La normalizacion deshace tres cosas de la corrida guardada:
  1. el compound (riesgo PERCENT): igual que attach_precise_r, usando la curva
     diaria guardada para saber el riesgo en $ de cada dia;
  2. las comisiones: `pnl` viene neto de `fees`, se suman de vuelta;
  3. el slippage: el motor lo mete en los precios de fill (precio * fraccion en
     cada lado), se estima y se devuelve. Es la unica pata aproximada — por eso
     una corrida guardada CON slippage recibe distintivo ambar, no verde.
Los locates no necesitan deshacerse: `pnl` ya esta limpio de ellos (fix de la
sesion 5, ver MEMORIA §5).
"""
from __future__ import annotations

import threading
from typing import Any, Optional

from app.services import robustness_service as rs

BUCKETS = ("portfolio", "incubadora")


# ── Asignaciones baul/portfolio/incubadora ──────────────────────────────
# Tablas propias, creadas de forma perezosa SOLO cuando el modulo esta activo.
# No se toca init_db.py ni el esquema compartido: en produccion estas tablas
# simplemente no existen.
#
# El DDL se ejecuta UNA SOLA VEZ por proceso y bajo su propio cerrojo: DuckDB
# lanza "Catalog write-write conflict" si dos hilos entran a la vez al mismo
# CREATE TABLE, pese al IF NOT EXISTS. Y como los GET de la pagina se disparan
# en paralelo al abrirla (monitor + monitor/real), la carrera era real.

_DDL_LOCK = threading.Lock()
_DDL_DONE: set[str] = set()


def _ensure_once(con, key: str, statements: tuple[str, ...]) -> None:
    """Ejecuta el DDL de `key` una vez por proceso, serializado."""
    if key in _DDL_DONE:
        return
    with _DDL_LOCK:
        if key in _DDL_DONE:
            return
        for sql in statements:
            con.execute(sql)
        _DDL_DONE.add(key)


def ensure_assignments_table(con) -> None:
    _ensure_once(
        con,
        "assignments",
        (
            """
            CREATE TABLE IF NOT EXISTS portfolio_lab_assignments (
                strategy_id VARCHAR NOT NULL,
                bucket VARCHAR NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (strategy_id, bucket)
            )
            """,
        ),
    )


def ensure_monitor_tables(con) -> None:
    """Tablas de la Monitorizacion (F3), tambien perezosas y solo-local."""
    _ensure_once(
        con,
        "monitor",
        (
            """
            CREATE TABLE IF NOT EXISTS portfolio_lab_monitor (
                strategy_id VARCHAR PRIMARY KEY,
                refreshed_at TIMESTAMP,
                payload JSON
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS portfolio_lab_real_pnl (
                fecha DATE PRIMARY KEY,
                pnl DOUBLE
            )
            """,
        ),
    )


def save_monitor_snapshot(con, strategy_id: str, payload: dict) -> None:
    import json as _json
    ensure_monitor_tables(con)
    con.execute(
        "INSERT OR REPLACE INTO portfolio_lab_monitor (strategy_id, refreshed_at, payload) "
        "VALUES (?, CURRENT_TIMESTAMP, ?)",
        [strategy_id, _json.dumps(payload)],
    )


def get_monitor_snapshots(con) -> dict[str, dict]:
    ensure_monitor_tables(con)
    rows = con.execute(
        "SELECT strategy_id, refreshed_at, payload FROM portfolio_lab_monitor"
    ).fetchall()
    out: dict[str, dict] = {}
    for sid, ts, payload in rows:
        p = rs._as_dict(payload)
        p["refreshed_at"] = str(ts) if ts else None
        out[sid] = p
    return out


def monitor_snapshot_from_result(result: dict, start_date: str) -> dict:
    """Reduce el resultado de un backtest a lo que necesita la tarjeta de
    monitorizacion: curva diaria, drawdown actual y metricas basicas."""
    equity = result.get("global_equity") or []
    agg = result.get("aggregate_metrics") or {}
    dd_now = 0.0
    peak = None
    for p in equity:
        v = float(p.get("value") or 0.0)
        if peak is None or v > peak:
            peak = v
        if peak and peak > 0:
            dd_now = (v / peak - 1.0) * 100.0
    return {
        "start_date": start_date,
        "equity": [{"time": p.get("time"), "value": p.get("value")} for p in equity],
        "n_trades": agg.get("total_trades"),
        "return_pct": agg.get("total_return_pct"),
        "max_dd_pct": agg.get("max_drawdown_pct"),
        "win_rate": agg.get("win_rate_pct"),
        "profit_factor": agg.get("avg_profit_factor"),
        "dd_now_pct": round(dd_now, 4),
    }


def get_assignments(con) -> dict[str, list[str]]:
    ensure_assignments_table(con)
    rows = con.execute(
        "SELECT strategy_id, bucket FROM portfolio_lab_assignments"
    ).fetchall()
    out: dict[str, list[str]] = {}
    for sid, bucket in rows:
        out.setdefault(sid, []).append(bucket)
    return out


def set_assignment(con, strategy_id: str, bucket: str, present: bool) -> list[str]:
    """Añade o quita una estrategia de un cuadro. Devuelve sus cuadros actuales."""
    ensure_assignments_table(con)
    if present:
        con.execute(
            "INSERT OR REPLACE INTO portfolio_lab_assignments (strategy_id, bucket) VALUES (?, ?)",
            [strategy_id, bucket],
        )
    else:
        con.execute(
            "DELETE FROM portfolio_lab_assignments WHERE strategy_id = ? AND bucket = ?",
            [strategy_id, bucket],
        )
    rows = con.execute(
        "SELECT bucket FROM portfolio_lab_assignments WHERE strategy_id = ?",
        [strategy_id],
    ).fetchall()
    return [r[0] for r in rows]


# ── Normalizacion ───────────────────────────────────────────────────────

def normalization_report(params: dict) -> dict:
    """Con que se corrio la corrida guardada y que habra que deshacer.

    `normalized=True` significa que la corrida ya esta en el dominio comun
    (costes a cero) y la R normalizada es EXACTA. Cada issue es una pata que
    la tuberia tiene que reconstruir; solo el slippage degrada a aproximado.
    """
    p = params or {}
    issues: list[str] = []
    if float(p.get("fees") or 0) > 0:
        issues.append("comisiones")
    if float(p.get("slippage") or 0) > 0:
        issues.append("slippage")
    if float(p.get("locates_cost") or 0) > 0:
        issues.append("locates")
    if float(p.get("monthly_expenses") or 0) > 0:
        issues.append("gastos fijos")
    is_pct = str(p.get("risk_type") or "").upper() == "PERCENT"
    if is_pct:
        issues.append("riesgo compound")
    return {
        "normalized": not issues,
        # Sin slippage la reconstruccion es exacta (fees y compound se
        # deshacen sin perdida); con slippage es aproximada.
        "exact": float(p.get("slippage") or 0) == 0,
        "issues": issues,
    }


def _start_of_day_equity(global_equity: list[dict], init_cash: float) -> dict[str, float]:
    """Balance de APERTURA de cada dia, desde la curva diaria guardada.

    Misma mecanica que attach_precise_r: el punto i de `global_equity` es el
    cierre del dia i, asi que la apertura del dia i es el punto anterior.
    """
    out: dict[str, float] = {}
    prev = init_cash
    for p in global_equity or []:
        ts = p.get("time")
        if ts is None:
            continue
        out[rs._epoch_to_day(ts)] = prev
        prev = float(p.get("value") or prev)
    return out


def load_normalized_run(con, run_id: str, name: str = "") -> Optional[dict]:
    """Carga una corrida y añade a cada trade su R normalizada sin costes.

    A cada trade se le anota:
      - `r_norm`: R del trade con el PnL BRUTO (sin comisiones, sin slippage,
        sin locates) dividido por el riesgo en $ que uso el motor ese dia.
      - `risk_usd_orig`: ese riesgo en $, necesario despues para re-escalar
        tamanos (new_size = size * risk_nuevo / risk_orig).
    """
    payload = rs.load_run_payload(con, run_id)
    if not payload:
        return None

    params = payload.get("backtest_params") or {}
    trades = payload.get("trades") or []
    comp = payload.get("compounding") or {}
    init_cash = float(comp.get("init_cash") or 10000.0)
    is_pct = bool(comp.get("is_percent_risk"))
    risk_pct = float(comp.get("risk_pct") or 0.0)
    fixed_risk = float(params.get("risk_r") or 0.0)
    slip_frac = float(params.get("slippage") or 0.0)

    sod = _start_of_day_equity(payload.get("global_equity") or [], init_cash) if is_pct else {}
    risk_frac = risk_pct / 100.0

    exact = True
    for t in trades:
        pnl = float(t.get("pnl") or 0.0)
        fees = float(t.get("fees") or 0.0)
        size = float(t.get("size") or 0.0)
        entry = float(t.get("entry_price") or 0.0)
        exitp = float(t.get("exit_price") or 0.0)
        # Bruto = neto + comisiones + slippage estimado (fraccion * precio en
        # cada lado, la formula literal de portfolio_sim.py). `pnl` ya viene
        # limpio de locates.
        gross = pnl + fees + slip_frac * (entry + exitp) * size

        if is_pct:
            e0 = sod.get(str(t.get("date") or ""))
            if e0 and e0 > 0:
                risk_usd = risk_frac * e0
            else:
                risk_usd = risk_frac * init_cash
                exact = False
        else:
            risk_usd = fixed_risk

        if risk_usd > 0:
            t["r_norm"] = gross / risk_usd
        else:
            t["r_norm"] = float(t.get("r_multiple") or 0.0)
            exact = False
        t["risk_usd_orig"] = risk_usd

    dates = sorted(str(t.get("date")) for t in trades if t.get("date"))
    report = normalization_report(params)
    report["exact"] = report["exact"] and exact

    return {
        "run_id": run_id,
        "name": name,
        "trades": trades,
        "backtest_params": params,
        "normalization": report,
        "span": {
            "start": params.get("start_date") or (dates[0] if dates else None),
            "end": params.get("end_date") or (dates[-1] if dates else None),
        },
    }
