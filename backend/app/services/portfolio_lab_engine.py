"""Motor lineal del Portfolio (F1): combinar N estrategias normalizadas.

Recibe corridas ya normalizadas (cada trade con `r_norm` y `risk_usd_orig`,
ver portfolio_lab_service.load_normalized_run) y reconstruye que habria pasado
operandolas TODAS con la misma configuracion de ejecucion: mismo capital,
mismo riesgo por trade, mismas comisiones, slippage y locates.

Principios heredados del motor real (y de las trampas de MEMORIA §4):
  - Se compone POR DIA, no por trade: el riesgo en $ de un dia sale del
    balance de apertura de ese dia, y todos los trades del dia usan el mismo.
  - Un dia sin operar es un dia plano: la estrategia ni gana ni pierde y su
    peso NO se redistribuye a las demas.
  - Costes con las formulas literales de portfolio_sim.py:
      comision FLAT   = fees * 2 por trade (entrada + salida)
      comision PERCENT= fees * |pnl bruto|
      slippage        = fraccion * precio en cada lado -> frac*(entry+exit)*size
      locates         = ceil(max_short_size_del_dia / 100) * coste, una vez por
                        ticker-dia y POR ESTRATEGIA (cada estrategia paga los
                        suyos, como si fueran cuentas separadas)
  - Los gastos fijos mensuales SE RESTAN del retorno (el motor real no lo hace
    en total_return_pct; aqui si, leccion de MEMORIA §4.7).

Todo es reconstruccion sobre trades guardados: nada de aqui toca el lago ni
re-ejecuta backtests. Coste tipico: milisegundos.
"""
from __future__ import annotations

import math
from datetime import date as _date

import numpy as np


def _parse_day(s: str) -> _date:
    y, m, d = str(s)[:10].split("-")
    return _date(int(y), int(m), int(d))


def _r6(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return round(v, 6)


def compute_stats(
    calendar: list[str],
    equity_curve: list[float],
    daily_ret: list[float],
    trade_rows: list[tuple],
    init_cash: float,
) -> dict:
    """Metricas de una curva diaria + sus trades re-escalados.

    Compartida entre la imagen general (combine) y los modelos de escalado
    (portfolio_lab_scaling): misma vara de medir para todos los modulos.
    `trade_rows` son tuplas (date, entry_time, i, r_net, pnl_net).
    """
    eq = np.asarray(equity_curve, dtype=float)
    ret = np.asarray(daily_ret, dtype=float)
    peak = np.maximum.accumulate(np.maximum(eq, 1e-9))
    dd_pct = (eq / peak - 1.0) * 100.0
    max_dd = float(dd_pct.min()) if len(dd_pct) else 0.0

    # Episodios de drawdown: el mas largo en dias CIVILES y el tiempo total
    # bajo maximos (en dias de calendario de trading del portfolio).
    days = [_parse_day(d) for d in calendar]
    longest_ep = 0
    ep_start: _date | None = None
    in_dd_count = 0
    for i in range(len(eq)):
        if dd_pct[i] < -1e-9:
            in_dd_count += 1
            if ep_start is None:
                ep_start = days[i - 1] if i > 0 else days[i]
            longest_ep = max(longest_ep, (days[i] - ep_start).days)
        else:
            ep_start = None
    span_days = max(1, (days[-1] - days[0]).days)
    time_in_dd_pct = 100.0 * in_dd_count / len(eq) if len(eq) else 0.0

    # Anualizacion con la frecuencia EFECTIVA de la serie, no con 252 fijo.
    # El calendario solo contiene dias con operaciones: un portfolio que opera
    # 60 sesiones al año no tiene 252 observaciones, y anualizar como si las
    # tuviera inflaba el Sharpe ~1/sqrt(fraccion activa). Con periodos = obs
    # por año reales, el resultado coincide con rellenar los dias planos.
    obs_per_year = min(252.0, max(1.0, len(ret) * 365.25 / span_days))
    ann = math.sqrt(obs_per_year)

    std = float(ret.std(ddof=1)) if len(ret) > 1 else 0.0
    sharpe = float(ret.mean() / std * ann) if std > 0 else 0.0
    # Downside deviation canonica: RMS de min(ret, 0) sobre TODAS las
    # observaciones. La version anterior (std de solo los dias perdedores
    # alrededor de su propia media) ignoraba la frecuencia de perdida y daba
    # 0 — es decir, "sin medir" — a las curvas con perdidas muy uniformes.
    neg = np.minimum(ret, 0.0)
    dstd = float(np.sqrt(np.mean(neg ** 2))) if len(ret) else 0.0
    sortino = float(ret.mean() / dstd * ann) if dstd > 0 else 0.0
    ulcer = float(np.sqrt(np.mean(dd_pct ** 2))) if len(dd_pct) else 0.0

    final_eq = float(eq[-1])
    total_return_pct = (final_eq / init_cash - 1.0) * 100.0
    cagr = ((max(final_eq, 1e-9) / init_cash) ** (365.0 / span_days) - 1.0) * 100.0
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0

    # Estadisticas por trade (sobre el PnL neto re-escalado).
    nets = np.asarray([r[4] for r in trade_rows], dtype=float)
    wins = nets[nets > 0]
    losses = nets[nets < 0]
    n_trades = int(len(nets))
    win_rate = 100.0 * len(wins) / n_trades if n_trades else 0.0
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else 0.0
    r_nets = np.asarray([r[3] for r in trade_rows], dtype=float)
    expectancy_r = float(r_nets.mean()) if n_trades else 0.0
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    payoff = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

    return {
        "final_equity": _r6(final_eq),
        "total_return_pct": _r6(total_return_pct),
        "cagr_pct": _r6(cagr),
        "max_drawdown_pct": _r6(max_dd),
        "longest_dd_days": longest_ep,
        "longest_dd_pct_of_span": _r6(100.0 * longest_ep / span_days),
        "time_in_dd_pct": _r6(time_in_dd_pct),
        "span_days": span_days,
        "sharpe": _r6(sharpe),
        "sortino": _r6(sortino),
        "calmar": _r6(calmar),
        "ulcer_index": _r6(ulcer),
        "n_trades": n_trades,
        "win_rate": _r6(win_rate),
        "profit_factor": _r6(pf),
        "expectancy_r": _r6(expectancy_r),
        "avg_win": _r6(avg_win),
        "avg_loss": _r6(avg_loss),
        "payoff": _r6(payoff),
    }


def correlation_stats(
    run_ids: list,
    calendar: list[str],
    r_cols: list,
    spans: list[tuple[str, str]],
) -> dict | None:
    """Correlacion entre estrategias sobre su R diaria normalizada (sin costes).

    Por pares y SOLO sobre el tramo en que ambas existen: un dia anterior al
    inicio del backtest de una estrategia no es un 0 real y contarlo
    fabricaria descorrelacion. Dentro del tramo comun, un dia sin trades SI
    es un 0 real (estar plano es una decision de la estrategia).
    Compartida entre la imagen general y los modelos de escalado.
    """
    n = len(run_ids)
    if n < 2:
        return None
    mat = [[None] * n for _ in range(n)]
    overlap = [[0] * n for _ in range(n)]
    pairs: list[tuple[float, int, int]] = []
    alive = []
    for i in range(n):
        s0, s1 = spans[i]
        alive.append(np.asarray([(s0 <= d <= s1) if s0 and s1 else False for d in calendar]))
    for i in range(n):
        mat[i][i] = 1.0
        overlap[i][i] = int(alive[i].sum())
        for j in range(i + 1, n):
            both = alive[i] & alive[j]
            overlap[i][j] = overlap[j][i] = int(both.sum())
            if both.sum() >= 20:
                a, b = r_cols[i][both], r_cols[j][both]
                if a.std() > 0 and b.std() > 0:
                    c = float(np.corrcoef(a, b)[0, 1])
                    mat[i][j] = mat[j][i] = _r6(c)
                    pairs.append((c, i, j))
    avg = _r6(np.mean([p[0] for p in pairs])) if pairs else None
    top = max(pairs, key=lambda p: abs(p[0])) if pairs else None
    return {
        "ids": run_ids,
        "matrix": mat,
        "overlap_days": overlap,
        "avg_pairwise": avg,
        "max_pair": {"i": top[1], "j": top[2], "corr": _r6(top[0])} if top else None,
        "min_overlap_warning": any(
            0 < overlap[i][j] < 60 for i in range(n) for j in range(i + 1, n)
        ),
    }


def var_stats(daily_ret: list[float]) -> dict | None:
    """VaR / CVaR del retorno diario (%). None con menos de 20 sesiones."""
    ret_pct = np.asarray(daily_ret, dtype=float) * 100.0
    if len(ret_pct) < 20:
        return None
    v95 = float(np.percentile(ret_pct, 5))
    v99 = float(np.percentile(ret_pct, 1))
    tail95 = ret_pct[ret_pct <= v95]
    tail99 = ret_pct[ret_pct <= v99]
    bins = min(40, max(10, len(ret_pct) // 10))
    counts, edges = np.histogram(ret_pct, bins=bins)
    return {
        "var95": _r6(v95),
        "cvar95": _r6(tail95.mean() if len(tail95) else v95),
        "var99": _r6(v99),
        "cvar99": _r6(tail99.mean() if len(tail99) else v99),
        "hist_counts": [int(c) for c in counts],
        "hist_edges": [_r6(e) for e in edges],
    }


def combine(runs: list[dict], cfg: dict) -> dict:
    """Simula el portfolio lineal. `runs` sale de load_normalized_run.

    cfg: init_cash, risk_type (FIXED|PERCENT), risk_r, fees, fee_type
    (FLAT|PERCENT, fraccion si PERCENT), slippage (FRACCION real), locates_cost,
    monthly_expenses, start_date?, end_date?.
    """
    init_cash = float(cfg.get("init_cash") or 10000.0)
    is_pct = str(cfg.get("risk_type") or "FIXED").upper() == "PERCENT"
    risk_r = float(cfg.get("risk_r") or 0.0)
    fees = float(cfg.get("fees") or 0.0)
    fee_flat = str(cfg.get("fee_type") or "FLAT").upper() == "FLAT"
    slip_frac = float(cfg.get("slippage") or 0.0)
    locates_cost = float(cfg.get("locates_cost") or 0.0)
    monthly_expenses = float(cfg.get("monthly_expenses") or 0.0)
    d_from = str(cfg.get("start_date") or "") or None
    d_to = str(cfg.get("end_date") or "") or None

    if risk_r <= 0:
        raise ValueError("El riesgo por trade tiene que ser mayor que cero")

    # Trades por (estrategia, dia), ya filtrados al rango pedido.
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

    n = len(runs)
    risk_frac = risk_r / 100.0

    equity = init_cash
    months_seen: set[str] = set()
    ruined = False

    equity_curve: list[float] = []
    daily_pnl: list[float] = []
    daily_ret: list[float] = []      # fraccion sobre el balance de apertura
    daily_r_net: list[float] = []    # PnL del dia / riesgo en $ del dia (para MC)
    per_pnl: list[list[float]] = [[] for _ in range(n)]
    per_r: list[list[float]] = [[] for _ in range(n)]

    tot_fees = tot_slip = tot_loc = tot_exp = 0.0
    strat_tot = [
        {"pnl_net": 0.0, "cum_r": 0.0, "n_trades": 0, "wins": 0,
         "fees": 0.0, "slippage": 0.0, "locates": 0.0}
        for _ in range(n)
    ]
    trade_rows: list[tuple[str, str, int, float, float]] = []  # (date, entry_time, i, r_net, pnl_net)

    for d in calendar:
        month = d[:7]
        expense = 0.0
        if monthly_expenses > 0 and month not in months_seen:
            months_seen.add(month)
            expense = monthly_expenses

        equity_open = equity
        if equity_open <= 0:
            ruined = True
        # Cuenta quebrada: no se abre nada mas y tampoco se siguen cobrando
        # gastos fijos — una cuenta muerta no acumula deuda, se queda en cero.
        if ruined:
            expense = 0.0
        risk_usd = 0.0 if ruined else (equity_open * risk_frac if is_pct else risk_r)

        day_total = 0.0
        for i in range(n):
            trades_d = by_day[i].get(d)
            if ruined or not trades_d:
                per_pnl[i].append(0.0)
                per_r[i].append(0.0)
                continue
            pnl_i = 0.0
            r_i = 0.0
            shorts_max: dict[str, float] = {}
            for t in trades_d:
                rn = float(t.get("r_norm") or 0.0)
                orig = float(t.get("risk_usd_orig") or 0.0)
                size = float(t.get("size") or 0.0)
                entry = float(t.get("entry_price") or 0.0)
                exitp = float(t.get("exit_price") or 0.0)

                scale = (risk_usd / orig) if orig > 0 else (0.0 if risk_usd == 0 else 1.0)
                new_size = size * scale
                gross = rn * risk_usd
                # Comision PERCENT sobre el NOCIONAL de cada lado, igual que el
                # motor real tras el fix de 2026-08-21 (antes iba sobre |PnL|).
                fee = (fees * 2 if fee_flat else fees * (entry + exitp) * new_size) if risk_usd > 0 else 0.0
                slip = slip_frac * (entry + exitp) * new_size
                net = gross - fee - slip

                if locates_cost > 0 and str(t.get("direction") or "") == "Short":
                    tk = str(t.get("ticker") or "")
                    if new_size > shorts_max.get(tk, 0.0):
                        shorts_max[tk] = new_size

                pnl_i += net
                r_i += rn
                tot_fees += fee
                tot_slip += slip
                st = strat_tot[i]
                st["n_trades"] += 1
                st["fees"] += fee
                st["slippage"] += slip
                if net > 0:
                    st["wins"] += 1
                trade_rows.append((d, str(t.get("entry_time") or ""), i,
                                   (net / risk_usd) if risk_usd > 0 else 0.0, net))

            loc_i = sum(math.ceil(sz / 100.0) * locates_cost for sz in shorts_max.values())
            pnl_i -= loc_i
            tot_loc += loc_i
            strat_tot[i]["locates"] += loc_i
            strat_tot[i]["pnl_net"] += pnl_i
            strat_tot[i]["cum_r"] += r_i
            per_pnl[i].append(pnl_i)
            per_r[i].append(r_i)
            day_total += pnl_i

        day_total -= expense
        tot_exp += expense
        equity += day_total
        # El dia que el capital cruza cero, la cuenta muere AHI: se liquida en
        # cero, no en un numero negativo arbitrario del overshoot de ese dia.
        if equity < 0:
            day_total -= equity  # lo que de verdad se pierde es hasta cero
            equity = 0.0

        equity_curve.append(equity)
        daily_pnl.append(day_total)
        daily_ret.append(day_total / equity_open if equity_open > 0 else 0.0)
        daily_r_net.append(day_total / risk_usd if risk_usd > 0 else 0.0)

    # ── Metricas y VaR (funciones compartidas con los modelos de escalado) ─
    metrics = compute_stats(calendar, equity_curve, daily_ret, trade_rows, init_cash)
    var_out = var_stats(daily_ret)

    # ── Correlacion entre estrategias (funcion compartida, ver abajo) ──
    correlation = correlation_stats(
        [r.get("run_id") for r in runs],
        calendar,
        [np.asarray(x, dtype=float) for x in per_r],
        spans,
    )

    # ── Secuencia por trade (para el eje X "por trades") ────────────────
    trade_rows.sort(key=lambda r: (r[0], r[1]))
    trades_seq = {
        "dates": [r[0] for r in trade_rows],
        "strategy_idx": [r[2] for r in trade_rows],
        "r_net": [_r6(r[3]) for r in trade_rows],
        "pnl_net": [_r6(r[4]) for r in trade_rows],
    }

    per_strategy = []
    for i, run in enumerate(runs):
        st = strat_tot[i]
        per_strategy.append({
            "run_id": run.get("run_id"),
            "name": run.get("name"),
            "alive_from": spans[i][0] or None,
            "alive_to": spans[i][1] or None,
            "pnl_daily": [_r6(x) for x in per_pnl[i]],
            "r_daily": [_r6(x) for x in per_r[i]],
            "totals": {
                "pnl_net": _r6(st["pnl_net"]),
                "cum_r": _r6(st["cum_r"]),
                "n_trades": st["n_trades"],
                "win_rate": _r6(100.0 * st["wins"] / st["n_trades"]) if st["n_trades"] else 0.0,
                "fees": _r6(st["fees"]),
                "slippage": _r6(st["slippage"]),
                "locates": _r6(st["locates"]),
            },
        })

    return {
        "config": {
            "init_cash": init_cash, "risk_type": "PERCENT" if is_pct else "FIXED",
            "risk_r": risk_r, "fees": fees, "fee_type": "FLAT" if fee_flat else "PERCENT",
            "slippage": slip_frac, "locates_cost": locates_cost,
            "monthly_expenses": monthly_expenses,
            "start_date": d_from, "end_date": d_to,
        },
        "calendar": calendar,
        "equity": [_r6(x) for x in equity_curve],
        "daily_pnl": [_r6(x) for x in daily_pnl],
        "daily_r_net": [_r6(x) for x in daily_r_net],
        "ruined": ruined,
        "metrics": metrics,
        "costs": {
            "fees": _r6(tot_fees),
            "slippage": _r6(tot_slip),
            "locates": _r6(tot_loc),
            "expenses": _r6(tot_exp),
        },
        "var": var_out,
        "correlation": correlation,
        "per_strategy": per_strategy,
        "trades_seq": trades_seq,
    }
