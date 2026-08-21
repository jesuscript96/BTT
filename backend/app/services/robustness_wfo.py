"""Walk-forward: optimizar en el pasado, validar en el futuro que no se ha visto.

DOS MODOS, PORQUE RESPONDEN A COSAS DISTINTAS
---------------------------------------------
RAPIDO (`run_wfo_fast`) — no re-ejecuta nada. Parte los trades YA guardados en
ventanas y compara el rendimiento de la primera mitad de cada ventana (IS) con
el de la segunda (OOS). Es instantaneo y sirve para ver **degradacion**: si la
estrategia rinde mucho peor en la segunda mitad de cada tramo, algo se esta
apagando. Lo que NO es: un walk-forward de verdad, porque no se re-optimiza
nada — no hay parametros ajustados en IS que validar en OOS. Su "eficiencia" es
orientativa.

COMPLETO (`run_wfo_full`) — el de verdad. En cada ventana:
   1. barre una rejilla de parametros sobre el tramo IS
   2. se queda con la combinacion que maximiza la metrica elegida
   3. la aplica, tal cual, al tramo OOS que NO ha visto
La WFO Efficiency es `resultado OOS / resultado IS`. Por debajo de ~0,5 la
estrategia esta sobreajustada: el parametro que ganaba en el pasado no aguanta
fuera de muestra.

Cuesta `ventanas x combinaciones` backtests. Se abarata igual que la matriz de
locates: las velas se cargan una vez para todo el rango, y si solo se optimizan
parametros de `risk_management` las señales tambien se cachean (los indicadores
no cambian, solo el stop o el objetivo).
"""
from __future__ import annotations

import copy
import logging
import time
from itertools import product

import numpy as np
import pandas as pd

from app.services.backtest_service import run_backtest
from app.services.optimization_service import _set_nested_value
from app.services.robustness_grid import (
    Cancelled,
    _bt_kwargs,
    _check_cancel,
    load_grid_context,
)
from app.services.optimization_service import set_progress

logger = logging.getLogger(__name__)

# Nombre en aggregate_metrics de cada metrica que se puede optimizar.
METRIC_KEYS = {
    "sharpe": "avg_sharpe",
    "total_return": "total_return_pct",
    "profit_factor": "avg_profit_factor",
    "expectancy": "expectancy",
    "win_rate": "win_rate_pct",
}


# ──────────────────────────────────────────────────────────────────────
# Ventanas
# ──────────────────────────────────────────────────────────────────────
def build_windows(dates: list[str], n_windows: int, oos_pct: float, anchored: bool) -> list[dict]:
    """Trocea el histórico en ventanas IS/OOS consecutivas.

    - rolling  : cada ventana empieza donde acabo la anterior (tramo movil)
    - anchored : el IS arranca SIEMPRE en el primer dia y se va alargando
    """
    n = len(dates)
    if n < n_windows * 4:
        raise ValueError(
            f"Muy pocos dias ({n}) para {n_windows} ventanas. Reduce las ventanas o amplia el rango."
        )

    seg = n // n_windows
    oos_len = max(1, int(seg * oos_pct / 100.0))
    is_len = seg - oos_len
    if is_len < 2:
        raise ValueError("El tramo de optimizacion queda demasiado corto; baja el % de OOS.")

    out: list[dict] = []
    for w in range(n_windows):
        seg_start = w * seg
        oos_start = seg_start + is_len
        oos_end = min(seg_start + seg, n) - 1
        if oos_start > oos_end:
            continue
        is_start = 0 if anchored else seg_start
        out.append({
            "index": w + 1,
            "is_from": dates[is_start],
            "is_to": dates[oos_start - 1],
            "oos_from": dates[oos_start],
            "oos_to": dates[oos_end],
            "is_days": oos_start - is_start,
            "oos_days": oos_end - oos_start + 1,
        })
    return out


def _slice_groups(groups, d0: str, d1: str):
    """Grupos (dia, ticker) cuyo dia cae en [d0, d1]."""
    out = []
    for key, df in groups:
        day = str(key[0])[:10]
        if d0 <= day <= d1:
            out.append((key, df))
    return out


def _slice_qualifying(qdf: pd.DataFrame, d0: str, d1: str) -> pd.DataFrame:
    s = qdf["date"].astype(str)
    return qdf[(s >= d0) & (s <= d1)]


# ──────────────────────────────────────────────────────────────────────
# Modo rapido: sobre los trades ya guardados
# ──────────────────────────────────────────────────────────────────────
def _window_metrics(trades: list[dict], risk_frac: float, init_cash: float) -> dict:
    """Metricas de un tramo, recomponiendo el capital dia a dia desde 100."""
    if not trades:
        return {"trades": 0, "return_pct": 0.0, "max_drawdown_pct": 0.0, "win_rate_pct": 0.0,
                "profit_factor": 0.0, "sharpe": 0.0, "total_r": 0.0}

    by_day: dict[str, float] = {}
    for t in trades:
        by_day[str(t.get("date"))] = by_day.get(str(t.get("date")), 0.0) + float(
            t.get("r_precise", t.get("r_multiple")) or 0.0
        )

    eq = 100.0
    vals = [eq]
    for d in sorted(by_day):
        eq *= max(1.0 + by_day[d] * risk_frac, 1e-6)
        vals.append(eq)
    arr = np.array(vals)
    run_max = np.maximum.accumulate(arr)
    dd = ((arr - run_max) / np.where(run_max > 0, run_max, 1.0) * 100.0).min()

    rets = np.diff(arr) / np.where(arr[:-1] != 0, arr[:-1], 1.0)
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.size > 1 and rets.std() > 0 else 0.0

    pnls = [float(t.get("pnl") or 0.0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gl = abs(sum(losses))

    return {
        "trades": len(trades),
        "return_pct": round((arr[-1] / 100.0 - 1) * 100, 2),
        "max_drawdown_pct": round(float(dd), 2),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2),
        "profit_factor": round(sum(wins) / gl, 3) if gl > 0 else 0.0,
        "sharpe": round(sharpe, 3),
        "total_r": round(sum(by_day.values()), 3),
    }


def run_wfo_fast(
    trades: list[dict],
    *,
    n_windows: int = 6,
    oos_pct: float = 30.0,
    anchored: bool = False,
    risk_pct: float = 3.0,
    init_cash: float = 10000.0,
    metric: str = "sharpe",
) -> dict:
    """Reparte los trades guardados en ventanas y compara IS contra OOS."""
    if not trades:
        raise ValueError("La estrategia no tiene trades")

    dates = sorted({str(t.get("date")) for t in trades if t.get("date")})
    windows = build_windows(dates, n_windows, oos_pct, anchored)
    risk_frac = risk_pct / 100.0

    by_date: dict[str, list[dict]] = {}
    for t in trades:
        by_date.setdefault(str(t.get("date")), []).append(t)

    def collect(d0: str, d1: str) -> list[dict]:
        out: list[dict] = []
        for d in dates:
            if d0 <= d <= d1:
                out.extend(by_date.get(d, []))
        return out

    rows = []
    for w in windows:
        is_m = _window_metrics(collect(w["is_from"], w["is_to"]), risk_frac, init_cash)
        oos_m = _window_metrics(collect(w["oos_from"], w["oos_to"]), risk_frac, init_cash)
        rows.append({**w, "is": is_m, "oos": oos_m, "efficiency": _efficiency(is_m, oos_m, metric)})

    return {
        "kind": "wfo_fast",
        "mode": "anchored" if anchored else "rolling",
        "metric": metric,
        "windows": rows,
        **_summary(rows),
    }


def _efficiency(is_m: dict, oos_m: dict, metric: str) -> float | None:
    """OOS / IS de la metrica elegida. None si el IS no es positivo."""
    key = {"sharpe": "sharpe", "total_return": "return_pct", "profit_factor": "profit_factor",
           "expectancy": "return_pct", "win_rate": "win_rate_pct"}.get(metric, "sharpe")
    a, b = is_m.get(key), oos_m.get(key)
    if a is None or b is None or a <= 0:
        return None
    return round(float(b) / float(a), 3)


def _summary(rows: list[dict]) -> dict:
    effs = [r["efficiency"] for r in rows if r["efficiency"] is not None]
    oos_pos = sum(1 for r in rows if (r["oos"].get("return_pct") or 0) > 0)
    return {
        "wfo_efficiency": round(float(np.median(effs)), 3) if effs else None,
        "wfo_efficiency_mean": round(float(np.mean(effs)), 3) if effs else None,
        "windows_oos_positive": oos_pos,
        "windows_total": len(rows),
        "consistency_pct": round(oos_pos / len(rows) * 100, 1) if rows else 0.0,
    }


# ──────────────────────────────────────────────────────────────────────
# Modo completo: re-optimiza en IS y valida en OOS
# ──────────────────────────────────────────────────────────────────────
def run_wfo_full(
    *,
    strategy_def: dict,
    dataset_id: str,
    backtest_params: dict,
    param_configs: list[dict],
    n_windows: int = 5,
    oos_pct: float = 30.0,
    anchored: bool = False,
    metric: str = "sharpe",
    start_date: str | None = None,
    end_date: str | None = None,
    task_id: str | None = None,
) -> dict:
    """Walk-forward real. Cuesta `ventanas x combinaciones` backtests."""
    if not param_configs:
        raise ValueError("Elige al menos un parametro que optimizar")

    ctx = load_grid_context(dataset_id, strategy_def, start_date, end_date, task_id)
    qdf, groups = ctx["qualifying_df"], ctx["groups"]

    dates = sorted({str(d)[:10] for d in qdf["date"].astype(str)})
    windows = build_windows(dates, n_windows, oos_pct, anchored)

    axes = [pc.get("values") or _axis(pc) for pc in param_configs]
    combos = list(product(*axes))
    metric_key = METRIC_KEYS.get(metric, "avg_sharpe")

    # Las señales solo sobreviven si NINGUN parametro toca los indicadores.
    risk_only = all(str(pc.get("path", "")).startswith("risk_management.") for pc in param_configs)
    logger.info(
        f"[WFO] {len(windows)} ventanas x {len(combos)} combinaciones = "
        f"{len(windows) * len(combos)} backtests · cache de señales "
        f"{'ACTIVA' if risk_only else 'desactivada (hay parametros de indicador)'}"
    )

    total = len(windows) * (len(combos) + 1)
    done = 0
    rows = []
    t0 = time.time()

    for w in windows:
        _check_cancel(task_id)
        is_groups = _slice_groups(groups, w["is_from"], w["is_to"])
        is_qdf = _slice_qualifying(qdf, w["is_from"], w["is_to"])
        # Una cache por ventana: los grupos cambian de una a otra, pero dentro
        # de la ventana las 25 combinaciones comparten las mismas señales.
        cache: dict | None = {} if risk_only else None

        best = None
        trials = []
        for combo in combos:
            _check_cancel(task_id)
            cand = copy.deepcopy(strategy_def)
            for dim, val in enumerate(combo):
                _set_nested_value(cand, param_configs[dim]["path"], val)
            agg = _safe_backtest(is_qdf, cand, backtest_params, is_groups, cache)
            score = agg.get(metric_key)
            score = float(score) if score is not None and np.isfinite(score) else float("-inf")
            trials.append({
                "params": [float(v) for v in combo],
                "score": None if score == float("-inf") else round(score, 4),
                "return_pct": agg.get("total_return_pct"),
                "trades": agg.get("total_trades"),
            })
            if best is None or score > best["score"]:
                best = {"score": score, "combo": combo, "agg": agg}
            done += 1
            if task_id:
                set_progress(task_id, round(10.0 + (done / total) * 90.0, 2))

        # El ganador del IS, aplicado al OOS que no ha visto.
        _check_cancel(task_id)
        cand = copy.deepcopy(strategy_def)
        for dim, val in enumerate(best["combo"]):
            _set_nested_value(cand, param_configs[dim]["path"], val)
        oos_groups = _slice_groups(groups, w["oos_from"], w["oos_to"])
        oos_qdf = _slice_qualifying(qdf, w["oos_from"], w["oos_to"])
        oos_agg = _safe_backtest(oos_qdf, cand, backtest_params, oos_groups, None)
        done += 1
        if task_id:
            set_progress(task_id, round(10.0 + (done / total) * 90.0, 2))

        is_m = _agg_to_metrics(best["agg"])
        oos_m = _agg_to_metrics(oos_agg)
        rows.append({
            **w,
            "best_params": [float(v) for v in best["combo"]],
            "param_labels": [pc.get("label") or pc.get("path") for pc in param_configs],
            "is": is_m,
            "oos": oos_m,
            "efficiency": _efficiency(is_m, oos_m, metric),
            "trials": trials,
        })

    return {
        "kind": "wfo_full",
        "mode": "anchored" if anchored else "rolling",
        "metric": metric,
        "param_analysis": _param_analysis(rows, axes[0], param_configs[0]) if len(param_configs) == 1 else None,
        "param_configs": [
            {"path": pc["path"], "label": pc.get("label") or pc["path"], "values": ax}
            for pc, ax in zip(param_configs, axes)
        ],
        "windows": rows,
        "n_backtests": total,
        "signal_cache_used": risk_only,
        "load_seconds": ctx.get("load_seconds"),
        "sweep_seconds": round(time.time() - t0, 2),
        **_summary(rows),
    }


def _axis(pc: dict) -> list[float]:
    lo = float(pc.get("min", 1))
    hi = float(pc.get("max", 10))
    steps = max(1, int(pc.get("steps", 5)))
    if steps == 1 or abs(hi - lo) < 1e-12:
        return [round(lo, 6)]
    return [round(float(v), 6) for v in np.linspace(lo, hi, steps)]


def _safe_backtest(qdf, strategy_def, backtest_params, groups, cache) -> dict:
    """Un backtest de un tramo. Un tramo sin operaciones no es un error."""
    if qdf is None or qdf.empty or not groups:
        return {}
    try:
        res = run_backtest(
            qualifying_df=qdf,
            strategy_def=strategy_def,
            slippage=backtest_params.get("slippage", 0.0),
            locates_cost=backtest_params.get("locates_cost", 0.0),
            monthly_expenses=backtest_params.get("monthly_expenses", 0.0),
            day_group_iter=iter(groups),
            n_groups_hint=len(groups),
            _signal_cache=cache,
            **_bt_kwargs(backtest_params),
        )
        return res.get("aggregate_metrics", {}) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[WFO] tramo fallido: {e}")
        return {}


def _agg_to_metrics(agg: dict) -> dict:
    return {
        "trades": agg.get("total_trades", 0) or 0,
        "return_pct": agg.get("total_return_pct", 0.0) or 0.0,
        "max_drawdown_pct": agg.get("max_drawdown_pct", 0.0) or 0.0,
        "win_rate_pct": agg.get("win_rate_pct", 0.0) or 0.0,
        "profit_factor": agg.get("avg_profit_factor", 0.0) or 0.0,
        "sharpe": agg.get("avg_sharpe", 0.0) or 0.0,
        "expectancy": agg.get("expectancy", 0.0) or 0.0,
    }


def _param_analysis(rows: list[dict], values: list[float], cfg: dict) -> dict:
    """Que valor del parametro conviene usar de verdad.

    El ganador de una ventana suelta no sirve: es el que mejor se ajusto a ESE
    tramo, que es justo lo que el walk-forward existe para desconfiar. Lo que
    importa es si hay una MESETA — una zona de valores que van bien en todas las
    ventanas — o si el optimo salta de un extremo a otro.

    Se calcula, por cada valor:
      - `mean` / `std`: puntuacion media y su dispersion entre ventanas
      - `wins`: en cuantas ventanas fue el mejor
      - `plateau`: media del valor y sus dos vecinos. Un pico aislado rodeado de
        malos resultados baja aqui; una meseta ancha aguanta. Es la cifra por la
        que se recomienda, no por la media a secas.
    """
    n_win = len(rows)
    per_value: list[dict] = []

    for i, v in enumerate(values):
        scores = []
        for r in rows:
            for t in r.get("trials", []):
                p = (t.get("params") or [None])[0]
                if p is not None and abs(p - v) < 1e-6 and t.get("score") is not None:
                    scores.append(float(t["score"]))
        wins = sum(1 for r in rows if r.get("best_params") and abs(r["best_params"][0] - v) < 1e-6)
        per_value.append({
            "value": v,
            "mean": round(float(np.mean(scores)), 4) if scores else None,
            "std": round(float(np.std(scores)), 4) if len(scores) > 1 else None,
            "min": round(float(np.min(scores)), 4) if scores else None,
            "wins": wins,
            "windows_scored": len(scores),
        })

    # Meseta: media movil de 3 sobre las medias. Los extremos usan los vecinos
    # que tienen, para no penalizarlos por estar en el borde de la rejilla.
    means = [pv["mean"] for pv in per_value]
    for i, pv in enumerate(per_value):
        window = [means[j] for j in (i - 1, i, i + 1) if 0 <= j < len(means) and means[j] is not None]
        pv["plateau"] = round(float(np.mean(window)), 4) if window else None

    scored = [pv for pv in per_value if pv["plateau"] is not None]
    best = max(scored, key=lambda pv: pv["plateau"]) if scored else None

    # Estabilidad del optimo: si el ganador salta mucho de ventana a ventana, la
    # rejilla esta midiendo ruido. Se normaliza por el ancho del barrido para
    # que la cifra sea comparable entre parametros de escalas distintas.
    winners = [r["best_params"][0] for r in rows if r.get("best_params")]
    span = (max(values) - min(values)) or 1.0
    dispersion = float(np.std(winners)) / span if len(winners) > 1 else 0.0

    # Un recomendado en el BORDE del barrido casi siempre significa que el
    # optimo esta fuera del rango y la rejilla se quedo corta. Merece aviso: sin
    # el, se toma como conclusion un valor que solo gano por no haber mirado mas
    # alla.
    at_edge = bool(best) and best["value"] in (values[0], values[-1]) and len(values) > 1

    return {
        "label": cfg.get("label") or cfg.get("path"),
        "per_value": per_value,
        "at_edge": at_edge,
        "range": [values[0], values[-1]],
        "recommended": best["value"] if best else None,
        "recommended_plateau": best["plateau"] if best else None,
        "winner_dispersion": round(dispersion, 4),
        "winner_values": winners,
        "n_windows": n_win,
        # Un optimo que se mueve menos del 15% del rango entre ventanas se
        # considera estable; por encima del 30%, ruido.
        "stability": "estable" if dispersion < 0.15 else ("dudosa" if dispersion < 0.30 else "ruido"),
    }
