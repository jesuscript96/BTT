"""Modelos de escalado y ponderacion del Portfolio (F2).

Generaliza la imagen general (portfolio_lab_engine.combine) en dos ejes que se
recalculan en cada REBALANCEO (diario / semanal / mensual):

  ESCALADO GLOBAL — cuanto se arriesga por trade segun el estado de la cuenta:
    fixed        X = base_risk $ constantes (la base lineal de F1)
    percent      X = pct% del capital vivo
    fixed_ratio  Ryan Jones: sube un escalon de base_risk cada vez que el
                 beneficio acumulado cubre delta * N(N-1)/2
    kelly        f* = media/varianza de la R DIARIA del portfolio ponderado en
                 la ventana, multiplicada por kelly_mult (1 = "optima"; 0.5 y
                 0.25 fraccional). X = f * capital. Si el f* estimado sale <= 0
                 (sin edge en la ventana), Kelly manda NO apostar: X = 0.
    combinatoria fixed_ratio mientras capital < threshold_equity; kelly despues

  PONDERACION — como se reparte ese riesgo entre las estrategias vivas:
    equal     iguales
    hrp       Hierarchical Risk Parity (Lopez de Prado): clustering jerarquico
              sobre la correlacion de R diaria y biseccion recursiva con
              varianza inversa
    momentum  proporcional a la R acumulada de la ventana (negativos a suelo)
    ev        proporcional a la expectancy por trade de la ventana
    dd        multiplicador 1 - DD_actual/DD_max_historico, con suelo: una
              estrategia hundida pesa menos, una en maximos pesa entero

Semantica heredada de F1: riesgo de la estrategia i = X * n_vivas * w_i, de
modo que con pesos iguales cada estrategia arriesga X y el resultado coincide
con la imagen general. Los topes (cap_global sobre X, cap_strat sobre cada
estrategia) RECORTAN sin redistribuir: el exceso se queda sin desplegar, que
es exactamente lo que pide el usuario ("Kelly dice 20%, yo quiero 5%").

Los pesos se estiman SIEMPRE con datos estrictamente anteriores a la fecha del
rebalanceo (ventana lookback_days): cero mirada al futuro. Y sobre la R
normalizada SIN costes — la señal pura —, mientras que la simulacion del
capital si aplica todos los costes con las formulas del motor real.
"""
from __future__ import annotations

import math
from datetime import timedelta

import numpy as np

from app.services.portfolio_lab_engine import (
    _parse_day,
    _r6,
    compute_stats,
    correlation_stats,
    var_stats,
)

MIN_OBS = 20  # sesiones minimas de historial para estimar algo
KELLY_CEILING = 0.25  # techo duro de la kelly: % del capital por unidad de R


# ── Ponderaciones ───────────────────────────────────────────────────────

def _hrp_weights(rets: np.ndarray) -> np.ndarray | None:
    """HRP de Lopez de Prado sobre una matriz (dias x estrategias)."""
    try:
        from scipy.cluster.hierarchy import leaves_list, linkage
        from scipy.spatial.distance import squareform
    except Exception:  # noqa: BLE001 - sin scipy se cae a varianza inversa
        return None
    n = rets.shape[1]
    if n < 2 or rets.shape[0] < MIN_OBS:
        return None
    std = rets.std(axis=0, ddof=1)
    if np.any(std <= 0):
        return None
    corr = np.corrcoef(rets, rowvar=False)
    cov = np.cov(rets, rowvar=False)
    dist = np.sqrt(np.clip(0.5 * (1.0 - np.clip(corr, -1.0, 1.0)), 0.0, None))
    np.fill_diagonal(dist, 0.0)
    link = linkage(squareform(dist, checks=False), method="single")
    order = [int(i) for i in leaves_list(link)]

    def cluster_var(idx: list[int]) -> float:
        sub = cov[np.ix_(idx, idx)]
        ivp = 1.0 / np.clip(np.diag(sub), 1e-12, None)
        ivp /= ivp.sum()
        return float(ivp @ sub @ ivp)

    w = np.ones(n)
    stack = [order]
    while stack:
        cl = stack.pop()
        if len(cl) <= 1:
            continue
        half = len(cl) // 2
        left, right = cl[:half], cl[half:]
        vl, vr = cluster_var(left), cluster_var(right)
        alpha = 1.0 - vl / (vl + vr) if (vl + vr) > 0 else 0.5
        for i in left:
            w[i] *= alpha
        for i in right:
            w[i] *= 1.0 - alpha
        stack += [left, right]
    return w / w.sum()


def _weights_at(
    model: str,
    alive_idx: list[int],
    win_daily: np.ndarray,          # (dias_ventana x n) R diaria normalizada
    win_trade_r: list[list[float]],  # por estrategia, R de cada trade en ventana
    dd_ratio: list[float],           # DD_actual / DD_max_hist por estrategia (0..1)
    floor: float,
) -> tuple[np.ndarray, bool]:
    """Pesos (indexados como alive_idx, suman 1) y si hubo fallback a equal."""
    k = len(alive_idx)
    equal = np.full(k, 1.0 / k)
    if k == 1:
        return equal, False

    fallback = False
    if model == "equal":
        w = equal
    elif model == "hrp":
        sub = win_daily[:, alive_idx] if win_daily.size else np.empty((0, k))
        hw = _hrp_weights(sub)
        if hw is None:
            w, fallback = equal, True
        else:
            w = hw
    elif model == "momentum":
        if win_daily.shape[0] < MIN_OBS:
            w, fallback = equal, True
        else:
            score = np.array([max(0.0, float(win_daily[:, i].sum())) for i in alive_idx])
            w = score / score.sum() if score.sum() > 0 else equal
            fallback = score.sum() <= 0
    elif model == "ev":
        score = np.array([
            max(0.0, float(np.mean(win_trade_r[i]))) if len(win_trade_r[i]) >= 5 else -1.0
            for i in alive_idx
        ])
        if np.all(score < 0):
            w, fallback = equal, True
        else:
            score = np.clip(score, 0.0, None)
            w = score / score.sum() if score.sum() > 0 else equal
            fallback = score.sum() <= 0
    elif model == "dd":
        mult = np.array([max(floor, 1.0 - dd_ratio[i]) for i in alive_idx])
        w = mult / mult.sum()
    else:
        raise ValueError(f"Modelo de ponderacion desconocido: {model}")

    # Suelo relativo: ninguna estrategia viva baja del floor * peso-igual.
    # (En 'dd' el floor ya actua como suelo del multiplicador.)
    if model in ("hrp", "momentum", "ev") and floor > 0:
        w = np.maximum(w, floor / k)
        w = w / w.sum()
    return w, fallback


# ── Escalados ───────────────────────────────────────────────────────────

def _fixed_ratio_x(equity: float, init_cash: float, base_risk: float, delta: float) -> float:
    """Escalon de Ryan Jones: nivel N cuando el beneficio cubre delta*N(N-1)/2."""
    profit = max(0.0, equity - init_cash)
    if delta <= 0:
        return base_risk
    level = int((1.0 + math.sqrt(1.0 + 8.0 * profit / delta)) / 2.0)
    return max(1, level) * base_risk


def _kelly_fraction(portfolio_daily_r: np.ndarray) -> float | None:
    """f* = media/varianza de la R diaria. None si no hay muestra suficiente."""
    if len(portfolio_daily_r) < MIN_OBS:
        return None
    var = float(portfolio_daily_r.var(ddof=1))
    if var <= 0:
        return None
    return float(portfolio_daily_r.mean()) / var


def _x_at(
    scaling: dict,
    equity: float,
    init_cash: float,
    weighted_win: np.ndarray | None,
) -> tuple[float, dict]:
    """Riesgo X en $ por unidad de trade, ANTES del tope global del usuario.

    Devuelve (X, info): info lleva `reason` ('no_sample' | 'no_edge' |
    'ceiling' | None) y `raw_pct` (lo que pedia kelly en crudo, si aplico el
    techo). La nota final para el usuario se compone en run_scaling, donde ya
    se sabe cuanto recorto tambien SU tope — la nota debe hablar siempre del
    porcentaje realmente aplicado, no de un limite interno.
    """
    model = str(scaling.get("model") or "fixed")
    base_risk = float(scaling.get("base_risk") or 100.0)
    pct = float(scaling.get("pct") or 1.0)
    delta = float(scaling.get("delta") or 500.0)
    kelly_mult = float(scaling.get("kelly_mult") or 0.5)
    threshold = float(scaling.get("threshold_equity") or 0.0)

    def kelly_x() -> tuple[float, dict]:
        f = _kelly_fraction(weighted_win) if weighted_win is not None else None
        if f is None:
            return pct / 100.0 * equity, {"reason": "no_sample"}
        if f <= 0:
            return 0.0, {"reason": "no_edge"}
        raw = kelly_mult * f
        # Techo de cordura: la Kelly estimada sobre una ventana de backtest
        # sobreapuesta de forma sistematica (el f* asume que la muestra ES la
        # distribucion completa; un solo dia de -3R fuera de muestra a >30%
        # del capital funde la cuenta). Nunca mas del 25% por unidad de R —
        # el tope del usuario (cap_global) puede recortar aun mas, no menos.
        if raw > KELLY_CEILING:
            return KELLY_CEILING * equity, {"reason": "ceiling", "raw_pct": raw * 100.0}
        return raw * equity, {}

    if model == "fixed":
        return base_risk, {}
    if model == "percent":
        return pct / 100.0 * equity, {}
    if model == "fixed_ratio":
        return _fixed_ratio_x(equity, init_cash, base_risk, delta), {}
    if model == "kelly":
        return kelly_x()
    if model == "combinatoria":
        if threshold > 0 and equity < threshold:
            return _fixed_ratio_x(equity, init_cash, base_risk, delta), {}
        return kelly_x()
    raise ValueError(f"Modelo de escalado desconocido: {model}")


# ── Simulador ───────────────────────────────────────────────────────────

def _period_key(d: str, freq: str) -> str:
    if freq == "D":
        return d
    if freq == "W":
        dt = _parse_day(d)
        y, w, _ = dt.isocalendar()
        return f"{y}-W{w:02d}"
    return d[:7]  # M


def run_scaling(runs: list[dict], cfg: dict) -> dict:
    """Simula el portfolio con escalado y ponderacion dinamicos.

    cfg: init_cash, fees, fee_type, slippage (FRACCION), locates_cost,
    monthly_expenses, start_date?, end_date?, rebalance (D|W|M),
    lookback_days, scaling {model,...}, weighting {model, floor,
    cap_strat_pct}, cap_global_pct.
    """
    init_cash = float(cfg.get("init_cash") or 10000.0)
    fees = float(cfg.get("fees") or 0.0)
    fee_flat = str(cfg.get("fee_type") or "FLAT").upper() == "FLAT"
    slip_frac = float(cfg.get("slippage") or 0.0)
    locates_cost = float(cfg.get("locates_cost") or 0.0)
    monthly_expenses = float(cfg.get("monthly_expenses") or 0.0)
    d_from = str(cfg.get("start_date") or "") or None
    d_to = str(cfg.get("end_date") or "") or None
    freq = str(cfg.get("rebalance") or "M").upper()
    lookback = int(cfg.get("lookback_days") or 90)
    scaling = dict(cfg.get("scaling") or {})
    weighting = dict(cfg.get("weighting") or {})
    w_model = str(weighting.get("model") or "equal")
    floor = float(weighting.get("floor") or 0.1)
    cap_strat = float(weighting.get("cap_strat_pct") or 0.0)
    cap_global = float(cfg.get("cap_global_pct") or 0.0)

    # ── Preparacion: trades por dia, series de señal, spans ─────────────
    n = len(runs)
    by_day: list[dict[str, list[dict]]] = []
    spans: list[tuple[str, str]] = []
    for run in runs:
        idx: dict[str, list[dict]] = {}
        dates: list[str] = []
        for t in run.get("trades") or []:
            d = str(t.get("date") or "")
            if not d or (d_from and d < d_from) or (d_to and d > d_to):
                continue
            idx.setdefault(d, []).append(t)
            dates.append(d)
        by_day.append(idx)
        span = run.get("span") or {}
        s0 = str(span.get("start") or (min(dates) if dates else ""))
        s1 = str(span.get("end") or (max(dates) if dates else ""))
        if d_from and s0 and s0 < d_from:
            s0 = d_from
        if d_to and s1 and s1 > d_to:
            s1 = d_to
        spans.append((s0, s1))

    calendar = sorted({d for idx in by_day for d in idx})
    if not calendar:
        raise ValueError("Ninguna estrategia tiene trades en el rango elegido")
    days = [_parse_day(d) for d in calendar]
    day_pos = {d: i for i, d in enumerate(calendar)}

    # Señal pura por dia (R normalizada, sin costes) y R por trade con fecha.
    r_daily = np.zeros((len(calendar), n))
    trade_r_dates: list[list[tuple[str, float]]] = [[] for _ in range(n)]
    for i in range(n):
        for d, trades_d in by_day[i].items():
            p = day_pos[d]
            for t in trades_d:
                rn = float(t.get("r_norm") or 0.0)
                r_daily[p, i] += rn
                trade_r_dates[i].append((d, rn))
        trade_r_dates[i].sort()
    alive_mask = np.zeros((len(calendar), n), dtype=bool)
    for i in range(n):
        s0, s1 = spans[i]
        if s0 and s1:
            alive_mask[:, i] = [(s0 <= d <= s1) for d in calendar]

    # DD en unidades de R de la señal de cada estrategia (para el modelo 'dd').
    cum_r = np.cumsum(r_daily, axis=0)
    peak_r = np.maximum.accumulate(cum_r, axis=0)
    dd_r = cum_r - peak_r                     # <= 0
    ddmax_r = np.minimum.accumulate(dd_r, axis=0)  # el peor visto hasta la fecha

    # ── Bucle diario con rebalanceos ────────────────────────────────────
    equity = init_cash
    months_seen: set[str] = set()
    ruined = False
    cur_w = np.full(n, 1.0 / n)
    cur_risk = np.zeros(n)
    cur_x = 0.0
    last_period: str | None = None

    equity_curve: list[float] = []
    daily_pnl: list[float] = []
    daily_ret: list[float] = []
    daily_r_net: list[float] = []   # PnL del dia en unidades del X vigente (eje R)
    trade_rows: list[tuple[str, str, int, float, float]] = []
    timeline: list[dict] = []
    fallbacks_w = 0
    kelly_notes = 0
    cap_hits = 0  # rebalanceos en los que el tope global del usuario recorto

    tot_fees = tot_slip = tot_loc = tot_exp = 0.0
    strat_tot = [
        {"pnl_net": 0.0, "cum_r": 0.0, "n_trades": 0, "wins": 0}
        for _ in range(n)
    ]

    for p, d in enumerate(calendar):
        month = d[:7]
        expense = 0.0
        if monthly_expenses > 0 and month not in months_seen:
            months_seen.add(month)
            expense = monthly_expenses

        equity_open = equity
        if equity_open <= 0:
            ruined = True
        if ruined:
            expense = 0.0

        # ── Rebalanceo al abrir el primer dia de cada periodo ───────────
        period = _period_key(d, freq)
        if period != last_period and not ruined:
            last_period = period
            alive_idx = [i for i in range(n) if alive_mask[p, i]]
            if not alive_idx:
                alive_idx = list(range(n))
            cut = days[p] - timedelta(days=lookback)
            w0 = next((k for k in range(p) if days[k] >= cut), p)
            win = r_daily[w0:p, :]
            win_trades = [
                [r for (td, r) in trade_r_dates[i] if calendar[w0] <= td < d] if p > w0 else []
                for i in range(n)
            ]
            dd_ratio = [
                float(dd_r[p - 1, i] / ddmax_r[p - 1, i]) if p > 0 and ddmax_r[p - 1, i] < 0 else 0.0
                for i in range(n)
            ]
            w_alive, fb = _weights_at(w_model, alive_idx, win, win_trades, dd_ratio, floor)
            if fb:
                fallbacks_w += 1
            cur_w = np.zeros(n)
            for k, i in enumerate(alive_idx):
                cur_w[i] = w_alive[k]

            # Serie diaria del portfolio PONDERADO en la ventana, para Kelly.
            n_alive = len(alive_idx)
            weighted_win = None
            if p > w0:
                weighted_win = (win[:, alive_idx] * (w_alive * n_alive)).sum(axis=1)
            x, info = _x_at(scaling, equity_open, init_cash, weighted_win)
            pre_cap = x
            if cap_global > 0:
                x = min(x, cap_global / 100.0 * equity_open)

            # La nota habla SIEMPRE del % realmente aplicado y de quien
            # recorto: el techo interno de kelly, el tope del usuario, o ambos.
            note = None
            reason = info.get("reason")
            final_pct = 100.0 * x / equity_open if equity_open > 0 else 0.0
            if reason == "no_sample":
                note = "sin muestra suficiente para kelly: usado el % base"
                kelly_notes += 1
            elif reason == "no_edge":
                note = "kelly <= 0: sin edge en la ventana, no se apuesta"
                kelly_notes += 1
            else:
                limits = []
                if reason == "ceiling":
                    limits.append(f"techo interno de kelly ({KELLY_CEILING * 100:.0f}%)")
                    kelly_notes += 1
                if x < pre_cap - 1e-9:
                    limits.append(f"tu tope global ({cap_global:g}%)")
                    cap_hits += 1
                if limits:
                    asked = info.get("raw_pct") or (100.0 * pre_cap / equity_open if equity_open > 0 else 0.0)
                    note = (
                        f"el modelo pedía {asked:.1f}% del capital por trade; "
                        f"aplicado {final_pct:.2f}% — recorta {' y '.join(limits)}"
                    )

            cur_x = x
            cur_risk = cur_x * n_alive * cur_w
            if cap_strat > 0:
                cur_risk = np.minimum(cur_risk, cap_strat / 100.0 * equity_open)

            timeline.append({
                "date": d,
                "equity": _r6(equity_open),
                "x": _r6(cur_x),
                "x_pct": _r6(100.0 * cur_x / equity_open) if equity_open > 0 else 0.0,
                "weights": [_r6(v) for v in cur_w],
                "risks": [_r6(v) for v in cur_risk],
                "note": note or None,
                # El modelo de pesos cayo a IGUALES por falta de muestra en la
                # ventana — la interfaz debe decirlo, o un 50/50 parece un bug.
                "w_fallback": bool(fb),
            })

        # ── Trading del dia con los riesgos vigentes ────────────────────
        day_total = 0.0
        for i in range(n):
            trades_d = by_day[i].get(d)
            if ruined or not trades_d:
                continue
            risk_usd = float(cur_risk[i])
            # Riesgo 0 = el modelo mando NO apostar (kelly sin edge). Esos
            # trades NO se ejecutan: contarlos como operaciones de resultado 0
            # diluia el win rate y la expectancy, y sumaba R de señal que
            # nunca se desplego. Se saltan igual que los dias de cuenta rota.
            if risk_usd <= 0:
                continue
            pnl_i = 0.0
            shorts_max: dict[str, float] = {}
            for t in trades_d:
                rn = float(t.get("r_norm") or 0.0)
                orig = float(t.get("risk_usd_orig") or 0.0)
                size = float(t.get("size") or 0.0)
                entry = float(t.get("entry_price") or 0.0)
                exitp = float(t.get("exit_price") or 0.0)

                scale = (risk_usd / orig) if orig > 0 else 0.0
                new_size = size * scale
                gross = rn * risk_usd
                # Comision PERCENT sobre el NOCIONAL de cada lado, igual que el
                # motor real tras el fix de 2026-08-21 (antes iba sobre |PnL|).
                # FLAT = $ POR ACCION en los dos lados (fix de 2026-08-22).
                fee = (fees * new_size * 2 if fee_flat else fees * (entry + exitp) * new_size) if risk_usd > 0 else 0.0
                slip = slip_frac * (entry + exitp) * new_size
                net = gross - fee - slip

                if locates_cost > 0 and str(t.get("direction") or "") == "Short":
                    tk = str(t.get("ticker") or "")
                    if new_size > shorts_max.get(tk, 0.0):
                        shorts_max[tk] = new_size

                pnl_i += net
                tot_fees += fee
                tot_slip += slip
                st = strat_tot[i]
                st["n_trades"] += 1
                st["cum_r"] += rn
                if net > 0:
                    st["wins"] += 1
                trade_rows.append((d, str(t.get("entry_time") or ""), i,
                                   (net / risk_usd) if risk_usd > 0 else 0.0, net))

            loc_i = sum(math.ceil(sz / 100.0) * locates_cost for sz in shorts_max.values())
            pnl_i -= loc_i
            tot_loc += loc_i
            strat_tot[i]["pnl_net"] += pnl_i
            day_total += pnl_i

        day_total -= expense
        tot_exp += expense
        equity += day_total
        if equity < 0:
            day_total -= equity
            equity = 0.0

        equity_curve.append(equity)
        daily_pnl.append(day_total)
        daily_ret.append(day_total / equity_open if equity_open > 0 else 0.0)
        daily_r_net.append(day_total / cur_x if cur_x > 0 else 0.0)

    metrics = compute_stats(calendar, equity_curve, daily_ret, trade_rows, init_cash)
    correlation = correlation_stats(
        [r.get("run_id") for r in runs],
        calendar,
        [r_daily[:, i] for i in range(n)],
        spans,
    )

    now = timeline[-1] if timeline else None
    per_strategy = []
    for i, run in enumerate(runs):
        st = strat_tot[i]
        per_strategy.append({
            "run_id": run.get("run_id"),
            "name": run.get("name"),
            "pnl_net": _r6(st["pnl_net"]),
            "cum_r": _r6(st["cum_r"]),
            "n_trades": st["n_trades"],
            "win_rate": _r6(100.0 * st["wins"] / st["n_trades"]) if st["n_trades"] else 0.0,
            "weight_now": now["weights"][i] if now else None,
            "risk_now": now["risks"][i] if now else None,
        })

    return {
        "config": {
            "init_cash": init_cash, "fees": fees,
            "fee_type": "FLAT" if fee_flat else "PERCENT", "slippage": slip_frac,
            "locates_cost": locates_cost, "monthly_expenses": monthly_expenses,
            "rebalance": freq, "lookback_days": lookback,
            "scaling": scaling, "weighting": weighting,
            "cap_global_pct": cap_global,
            "start_date": d_from, "end_date": d_to,
        },
        "calendar": calendar,
        "equity": [_r6(x) for x in equity_curve],
        "daily_pnl": [_r6(x) for x in daily_pnl],
        "daily_r_net": [_r6(x) for x in daily_r_net],
        "ruined": ruined,
        "metrics": metrics,
        "var": var_stats(daily_ret),
        "correlation": correlation,
        "costs": {
            "fees": _r6(tot_fees), "slippage": _r6(tot_slip),
            "locates": _r6(tot_loc), "expenses": _r6(tot_exp),
        },
        "timeline": timeline,
        "now": now,
        "per_strategy": per_strategy,
        "n_rebalances": len(timeline),
        "weight_fallbacks": fallbacks_w,
        "kelly_notes": kelly_notes,
        # Diagnostico del tope: si recorta en la mayoria de rebalanceos, el
        # modelo vive por encima de la tolerancia del usuario — la palanca
        # correcta es bajar la fraccion (templar el modelo), no quitar el tope.
        "cap_hits": cap_hits,
    }


def weights_now(runs: list[dict], lookback_days: int, model: str, floor: float) -> dict:
    """Pesos "de AHORA" sobre corridas normalizadas: la misma maquinaria del
    rebalanceo, aplicada UNA vez en la ultima fecha disponible. Para el panel
    de Control en tiempo real (F3): dime que % destinar a cada estrategia hoy.
    """
    n = len(runs)
    by_day: list[dict[str, float]] = []
    trade_r: list[list[tuple[str, float]]] = []
    all_days: set[str] = set()
    for run in runs:
        acc: dict[str, float] = {}
        tr: list[tuple[str, float]] = []
        for t in run.get("trades") or []:
            d = str(t.get("date") or "")
            if not d:
                continue
            rn = float(t.get("r_norm") or 0.0)
            acc[d] = acc.get(d, 0.0) + rn
            tr.append((d, rn))
        tr.sort()
        by_day.append(acc)
        trade_r.append(tr)
        all_days.update(acc.keys())
    calendar = sorted(all_days)
    if len(calendar) < 2:
        raise ValueError("Sin historial suficiente en las estrategias elegidas")

    r_daily = np.zeros((len(calendar), n))
    for i in range(n):
        for p, d in enumerate(calendar):
            r_daily[p, i] = by_day[i].get(d, 0.0)

    end = calendar[-1]
    cut = (_parse_day(end) - timedelta(days=lookback_days)).isoformat()
    w0 = next((k for k, d in enumerate(calendar) if d >= cut), 0)
    win = r_daily[w0:, :]
    win_trades = [[r for (td, r) in trade_r[i] if td >= cut] for i in range(n)]

    cum = np.cumsum(r_daily, axis=0)
    peak = np.maximum.accumulate(cum, axis=0)
    dd = cum - peak
    ddmax = dd.min(axis=0)
    dd_ratio = [float(dd[-1, i] / ddmax[i]) if ddmax[i] < 0 else 0.0 for i in range(n)]

    alive_idx = list(range(n))
    w, fb = _weights_at(model, alive_idx, win, win_trades, dd_ratio, floor)
    return {
        "weights": [_r6(v) for v in w],
        "fallback": bool(fb),
        "window": {"from": calendar[max(w0, 0)], "to": end, "sessions": int(win.shape[0])},
    }


def run_scaling_compare(runs: list[dict], cfg: dict, variants: list[dict]) -> list[dict]:
    """Corre varios modelos sobre los MISMOS datos y devuelve el resumen de
    cada uno (curva completa incluida: ~500 puntos por modelo, asumible)."""
    out = []
    for v in variants:
        c = dict(cfg)
        c["scaling"] = v.get("scaling") or cfg.get("scaling")
        c["weighting"] = v.get("weighting") or cfg.get("weighting")
        try:
            r = run_scaling(runs, c)
            out.append({
                "label": v.get("label") or "?",
                "metrics": r["metrics"],
                "equity": r["equity"],
                "calendar": r["calendar"],
                "daily_r_net": r["daily_r_net"],
                "ruined": r["ruined"],
                "now": r["now"],
                "costs": r["costs"],
            })
        except ValueError as e:
            out.append({"label": v.get("label") or "?", "error": str(e)})
    return out
