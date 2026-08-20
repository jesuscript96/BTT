"""Test de estres sobre el histórico de trades, en el dominio correcto.

POR QUE NO SE USA `what_if_service.run_what_if`
------------------------------------------------
Ese servicio suma PnL en DOLARES. Con `risk_type=PERCENT` —lo que usa esta
estrategia: 3% del capital vivo por trade— los dolares de cada trade dependen
del balance que hubiera en ese momento, asi que quitar trades y re-sumar el
resto rompe el vinculo con el capital y produce cifras imposibles.

Medido sobre la corrida real (3.544 trades, +581%):

    quitar el mejor 10% de trades  (354 operaciones)
      suma del top 10%          :  152.578 $   <- mas que TODO el beneficio
      PnL restante, aditivo     :  -94.411 $
      equity final, aditivo     :  -84.411 $   <- dinero negativo, imposible
      equity final, compuesto   :    2.617 $   -> -73,8%

El -73,8% es la respuesta util: sin sus mejores operaciones la estrategia pasa
de +579% a perder tres cuartas partes del capital. El -944% no significa nada.

`what_if_service` no se toca: lo usa la pagina de Backtester y es codigo
compartido con produccion.

COMO SE CASTIGA EN DOMINIO COMPUESTO
------------------------------------
Todo se traduce a R-multiplos y se recompone `equity *= (1 + R * riesgo%)`:

  - slippage extra: un x% de deslizamiento sobre el precio de entrada mueve el
    retorno x puntos. En R eso son `x / stop_pct` unidades, donde `stop_pct` es
    la distancia al stop de ESE trade (se conoce: los trades guardan
    `stop_loss` y `entry_price`). No es una constante para todos.
  - black swan: se fuerza el trade a un retorno de -N%, o sea `-N / stop_pct` R.
  - gastos fijos: se restan del capital al cerrar cada mes.
"""
from __future__ import annotations

import random
from datetime import datetime
from typing import Any

import numpy as np

# Si no se puede deducir la distancia al stop de un trade se usa esta, para no
# descartarlo del analisis. Es el orden de magnitud de un stop tipico aqui.
_FALLBACK_STOP_PCT = 45.0
_MONTHS_ES = {
    "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
    "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12,
}


def _stop_pct(t: dict) -> float:
    """Distancia al stop, en % sobre el precio de entrada."""
    entry = t.get("entry_price") or 0.0
    stop = t.get("stop_loss")
    if entry and stop:
        v = abs(stop - entry) / entry * 100.0
        if v > 0.01:
            return v
    # Deducirla del propio trade: R = retorno / stop_pct.
    r = t.get("r_multiple")
    ret = t.get("return_pct")
    if r and ret and abs(r) > 1e-6:
        v = abs(ret / r)
        if v > 0.01:
            return v
    return _FALLBACK_STOP_PCT


def _parse_dt(s: Any) -> datetime | None:
    if isinstance(s, datetime):
        return s
    if not isinstance(s, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def _all_days(trades: list[dict]) -> list[str]:
    """Calendario completo de sesiones, en orden."""
    return sorted({str(t.get("date") or "") for t in trades} - {""})


def _equity_curve(
    trades: list[dict],
    init_cash: float,
    compound: bool,
    risk_frac: float,
    monthly_expenses: float,
    calendar: list[str] | None = None,
) -> tuple[list[dict], float]:
    """Curva de equity diaria. Devuelve (puntos, balance final).

    `calendar` fija el eje temporal: la curva tiene un punto por cada dia de esa
    lista, tenga trades o no. Es imprescindible para la curva estresada, porque
    los castigos VACIAN dias enteros (dias perdidos al mes, limite de trades por
    dia, quitar los mejores...). Sin el, esos dias desaparecian de la serie y
    pasaban dos cosas malas:

      - la grafica se acortaba, como si el histórico terminase antes;
      - peor: las dos curvas dejaban de estar alineadas en el tiempo, porque el
        punto i de la estresada ya no era la misma fecha que el punto i de la
        original.

    Un dia sin trades no adelanta ni retrasa el capital: se arrastra el valor
    anterior, que es lo que pasa de verdad cuando no operas.
    """
    by_day: dict[str, list[dict]] = {}
    for t in trades:
        d = str(t.get("date") or "")
        if d:
            by_day.setdefault(d, []).append(t)

    days = calendar if calendar is not None else sorted(by_day)
    if not days:
        return [], init_cash

    eq = init_cash
    pts: list[dict] = []
    prev_month = days[0][:7]
    for d in days:
        # Gastos fijos: se cobran al cambiar de mes, se opere o no.
        if monthly_expenses and d[:7] != prev_month:
            eq -= monthly_expenses
            prev_month = d[:7]
        todays = by_day.get(d)
        if todays:
            if compound:
                # El motor de backtest compone POR DIA, no por trade: dentro de
                # una misma sesion todas las posiciones se dimensionan sobre el
                # balance de apertura y el PnL se acumula al cerrar el dia (ver
                # `compounding_cash` en backtest_signals.simulate_and_accumulate).
                # Componer trade a trade daba un 579,3% frente al 581,7% real;
                # haciendolo por dia la base cuadra con la corrida guardada.
                r_day = sum(float(t.get("_r", 0.0)) for t in todays)
                eq *= max(1.0 + r_day * risk_frac, 1e-6)
            else:
                eq += sum(float(t.get("_pnl", 0.0)) for t in todays)
        pts.append({"date": d, "value": round(eq, 2)})
    return pts, eq


def _metrics(pts: list[dict], init_cash: float, trades: list[dict]) -> dict:
    if not pts:
        return {}
    vals = np.array([init_cash] + [p["value"] for p in pts], dtype=np.float64)
    running_max = np.maximum.accumulate(vals)
    dd = (vals - running_max) / np.where(running_max > 0, running_max, 1.0) * 100.0

    daily_ret = np.diff(vals) / np.where(vals[:-1] != 0, vals[:-1], 1.0)
    sharpe = 0.0
    if daily_ret.size > 1 and daily_ret.std() > 0:
        sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252))

    wins = [t for t in trades if float(t.get("_pnl", 0.0)) > 0]
    losses = [t for t in trades if float(t.get("_pnl", 0.0)) < 0]
    gross_win = sum(float(t["_pnl"]) for t in wins)
    gross_loss = abs(sum(float(t["_pnl"]) for t in losses))

    return {
        "total_trades": len(trades),
        "total_return_pct": round((vals[-1] / init_cash - 1) * 100, 2),
        "final_balance": round(float(vals[-1]), 2),
        "max_drawdown_pct": round(float(dd.min()), 2),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else 0.0,
        "sharpe": round(sharpe, 3),
        # `trading_days` es la longitud del eje (el mismo para las dos curvas).
        # `active_days` es lo informativo cuando un castigo vacia sesiones: los
        # dias en los que de verdad se opero.
        "trading_days": len(pts),
        "active_days": len({str(t.get("date")) for t in trades if t.get("date")}),
    }


def run_stress(
    trades: list[dict],
    params: dict,
    *,
    init_cash: float = 10000.0,
    mode: str = "compound",
    risk_pct: float = 3.0,
    seed: int | None = None,
) -> dict:
    """Aplica los castigos y devuelve base vs estresado, con la misma metrica."""
    if not trades:
        raise ValueError("No hay trades que estresar")

    compound = mode == "compound"
    risk_frac = risk_pct / 100.0
    rng = random.Random(seed)

    # Copia de trabajo con los dos campos que mueve el estres.
    work: list[dict] = []
    for t in trades:
        c = dict(t)
        # r_precise viene del cargador (exacta); r_multiple es el respaldo.
        c["_r"] = float(t.get("r_precise", t.get("r_multiple")) or 0.0)
        c["_pnl"] = float(t.get("pnl") or 0.0)
        c["_stop_pct"] = _stop_pct(t)
        c["_dt"] = _parse_dt(t.get("entry_time")) or _parse_dt(t.get("date"))
        work.append(c)
    work.sort(key=lambda x: (x["_dt"] or datetime.min))

    # Eje temporal compartido: el histórico completo, sin castigar. Las dos
    # curvas se dibujan sobre EL MISMO calendario para que se puedan comparar
    # fecha a fecha.
    calendar = _all_days(work)

    base_pts, _ = _equity_curve(work, init_cash, compound, risk_frac, 0.0, calendar)
    base_metrics = _metrics(base_pts, init_cash, work)

    kept = list(work)

    # ── Filtros temporales ──────────────────────────────────────────
    excl_days = set(params.get("exclude_days") or [])
    if excl_days:
        kept = [t for t in kept if not t["_dt"] or t["_dt"].weekday() not in excl_days]

    excl_months: set[int] = set()
    for m in params.get("exclude_months") or []:
        if isinstance(m, int):
            excl_months.add(m + 1)
        elif isinstance(m, str):
            excl_months.add(_MONTHS_ES.get(m, int(m) + 1 if m.isdigit() else 0))
    excl_months.discard(0)
    if excl_months:
        kept = [t for t in kept if not t["_dt"] or t["_dt"].month not in excl_months]

    h0, h1 = params.get("exclude_hour_start"), params.get("exclude_hour_end")
    if h0 is not None and h1 is not None:
        kept = [t for t in kept if not t["_dt"] or not (h0 <= t["_dt"].hour <= h1)]

    # Dias aleatorios perdidos al mes (vacaciones, cortes de luz, despistes).
    rmd = int(params.get("random_monthly_days") or 0)
    if rmd > 0:
        by_month: dict[str, set[str]] = {}
        for t in kept:
            d = str(t.get("date") or "")
            if d:
                by_month.setdefault(d[:7], set()).add(d)
        drop: set[str] = set()
        for _, ds in by_month.items():
            pool = sorted(ds)
            drop.update(rng.sample(pool, min(rmd, len(pool))))
        kept = [t for t in kept if str(t.get("date")) not in drop]

    # ── Limites de actividad ────────────────────────────────────────
    dmt = int(params.get("daily_max_trades") or 0)
    if dmt > 0:
        seen: dict[str, int] = {}
        out = []
        for t in kept:
            d = str(t.get("date") or "")
            if seen.get(d, 0) < dmt:
                seen[d] = seen.get(d, 0) + 1
                out.append(t)
        kept = out

    mct = int(params.get("max_concurrent_trades") or 0)
    if mct > 0:
        active: list[datetime] = []
        out = []
        for t in kept:
            start = t["_dt"]
            end = _parse_dt(t.get("exit_time")) or start
            if start is None:
                out.append(t)
                continue
            active = [e for e in active if e > start]
            if len(active) < mct:
                active.append(end or start)
                out.append(t)
        kept = out

    # ── Castigos ────────────────────────────────────────────────────
    skip_top = float(params.get("skip_top_pct") or 0)
    if skip_top > 0 and kept:
        n_skip = int(len(kept) * skip_top / 100.0)
        if n_skip > 0:
            # Los mejores POR R, que es la unidad en la que se compara de forma
            # justa: el mismo R gana mas dolares cuanto mas tarde ocurre.
            order = sorted(range(len(kept)), key=lambda i: kept[i]["_r"], reverse=True)
            drop_idx = set(order[:n_skip])
            kept = [t for i, t in enumerate(kept) if i not in drop_idx]

    slip = float(params.get("extra_slippage") or 0)
    if slip > 0:
        for t in kept:
            # x puntos de retorno son x/stop_pct unidades de R para ESE trade.
            t["_r"] -= slip / t["_stop_pct"]
            t["_pnl"] -= abs(t.get("size") or 0.0) * (t.get("entry_price") or 0.0) * slip / 100.0

    swans = int(params.get("black_swan_count") or 0)
    swan_pct = abs(float(params.get("black_swan_pct") or 0)) or 500.0
    if swans > 0 and kept:
        for i in rng.sample(range(len(kept)), min(swans, len(kept))):
            t = kept[i]
            t["_r"] = -swan_pct / t["_stop_pct"]
            t["_pnl"] = -abs((t.get("size") or 0.0) * (t.get("entry_price") or 0.0) * swan_pct / 100.0)
            t["exit_reason"] = "BLACK SWAN"

    monthly_expenses = float(params.get("monthly_expenses") or 0)

    stressed_pts, _ = _equity_curve(kept, init_cash, compound, risk_frac, monthly_expenses, calendar)
    stressed_metrics = _metrics(stressed_pts, init_cash, kept)

    return {
        "mode": "compound" if compound else "additive",
        "risk_pct": risk_pct,
        "init_cash": init_cash,
        "base": base_metrics,
        "stressed": stressed_metrics,
        "base_curve": base_pts,
        "stressed_curve": stressed_pts,
        "trades_removed": len(work) - len(kept),
        "trades_kept": len(kept),
    }
