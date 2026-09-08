"""Metricas por segmento IS / OOS, calculadas en el servidor y PERSISTIDAS.

PRD de Alvaro (2026-09-08), P1. Hasta ahora el backend corria todo el rango y
el recorte IS lo hacia el navegador al pintar: la corrida guardada no sabia
que parte era IS y que parte OOS, asi que en el buscador una corrida «IS 90 %»
y una «IS 100 %» ensenaban las mismas cifras totales.

Correr todo el rango sigue siendo lo correcto (decision de Jaume: quiere poder
ver el 10 % con las mismas condiciones). Lo unico que cambia es que ademas se
guardan los dos bloques. Y se calculan EXACTAMENTE como los calcula hoy el
navegador (`page.tsx`, memo `isFilteredResult`) para que la pestana IS y lo
persistido den el mismo numero:

  - corte por INDICE de la curva de equity: `floor(len(eq) * is / 100)`;
  - trades del IS = los que ENTRARON hasta el instante de ese punto;
  - dias del IS = `day_results` cuya fecha (medianoche UTC) <= ese instante;
  - el PnL en $ va neto de locates (que viajan por dia, no por trade).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone


def _epoch_fecha(fecha: str) -> float:
    """Medianoche UTC de 'YYYY-MM-DD', como hace `new Date(d.date)` en el navegador."""
    try:
        return datetime.strptime(str(fecha)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def _max_dd_pct(valores: list[float], arranque: float) -> float:
    techo, peor = (valores[0] if valores else arranque) or arranque, 0.0
    for v in valores:
        if v > techo:
            techo = v
        if techo > 0:
            dd = (v - techo) / techo * 100.0
            if dd < peor:
                peor = dd
    return peor


def _bloque(trades: list[dict], dias: list[dict], equity: list[dict], init_cash: float) -> dict:
    pnls = [float(t.get("pnl", 0.0)) for t in trades]
    gan = [p for p in pnls if p > 0]
    per = [p for p in pnls if p < 0]
    locates = float(sum(float(d.get("locates_fee", 0.0) or 0.0) for d in dias))
    pnl = float(sum(pnls)) - locates
    bruto_gan = float(sum(gan))
    bruto_per = abs(float(sum(per)))
    r_total = float(sum(float(t.get("r_multiple") or 0.0) for t in trades))
    fechas = sorted({str(t.get("date", ""))[:10] for t in trades if t.get("date")})
    return {
        "total_trades": len(trades),
        "total_days": len({str(t.get("date", ""))[:10] for t in trades}),
        "win_rate_pct": round(len(gan) / len(trades) * 100.0, 4) if trades else 0.0,
        "avg_profit_factor": round(bruto_gan / bruto_per, 4) if bruto_per > 0 else (math.inf if bruto_gan > 0 else 0.0),
        "total_pnl": round(pnl, 2),
        "total_return_pct": round(pnl / init_cash * 100.0, 4) if init_cash > 0 else 0.0,
        "total_return_r": round(r_total, 4),
        "max_drawdown_pct": round(_max_dd_pct([float(p.get("value", 0.0)) for p in equity], init_cash), 4),
        "locates_fee": round(locates, 2),
        "first_date": fechas[0] if fechas else None,
        "last_date": fechas[-1] if fechas else None,
    }


def segmentos_is_oos(results: dict, is_percent: float, init_cash: float) -> dict:
    """Claves a fundir en `aggregate_metrics`. Con IS = 100 no cambia nada."""
    try:
        pct = float(is_percent)
    except (TypeError, ValueError):
        pct = 100.0
    if pct >= 100.0 or pct <= 0.0:
        return {"is_percent": 100.0, "is_metrics": None, "oos_metrics": None}

    eq = results.get("global_equity") or []
    if len(eq) < 2:
        return {"is_percent": pct, "is_metrics": None, "oos_metrics": None}

    corte_idx = max(1, int(math.floor(len(eq) * pct / 100.0)))
    corte_t = float(eq[corte_idx - 1].get("time", 0) or 0)

    trades = results.get("trades") or []
    dias = results.get("day_results") or []
    t_is = [t for t in trades if float(t.get("entry_time_epoch", 0) or 0) <= corte_t]
    t_oos = [t for t in trades if float(t.get("entry_time_epoch", 0) or 0) > corte_t]
    d_is = [d for d in dias if _epoch_fecha(d.get("date", "")) <= corte_t]
    d_oos = [d for d in dias if _epoch_fecha(d.get("date", "")) > corte_t]

    # El OOS arranca donde acaba el IS: su drawdown se mide dentro de su tramo,
    # con el ultimo valor del IS como primer techo (no desde el capital inicial).
    eq_is = eq[:corte_idx]
    eq_oos = eq[corte_idx - 1:]

    return {
        "is_percent": pct,
        "is_cutoff_time": corte_t,
        "is_metrics": _bloque(t_is, d_is, eq_is, init_cash),
        "oos_metrics": _bloque(t_oos, d_oos, eq_oos, init_cash),
    }
