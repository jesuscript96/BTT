"""Evaluar un individuo = correr `run_backtest` con su estrategia traducida.

Misma llamada que `_run_grid_point` en optimization_service.py: datos ya
agrupados por (fecha, ticker), sin cache de senales. Lo que sale es lo que
saldria en el panel con la misma configuracion.
"""
from __future__ import annotations

import math
import time

from genetico import entorno

entorno.preparar()

from genetico import cromosoma  # noqa: E402

# Metricas del motor que se guardan por individuo (claves de aggregate_metrics).
# OJO: `avg_r_ui` NO es la R media, es retorno anualizado / indice Ulcer.
# La R por operacion sale de `expectancy` (PnL medio en $) / riesgo fijo.
METRICAS = {
    "trades": "total_trades",
    "expectancy": "expectancy",
    "pf": "avg_profit_factor",
    "wr": "win_rate_pct",
    "max_dd": "max_drawdown_pct",
    "retorno": "total_return_pct",
    "dd_return": "dd_return_ratio",
    "sharpe": "avg_sharpe",
    "ret_ulcer": "avg_r_ui",
}


def parametros_backtest(config: dict) -> dict:
    r = config.get("riesgo", {})
    return dict(
        init_cash=float(r.get("init_cash", 50000)),
        risk_r=float(r.get("risk_r", 100)),
        risk_type=str(r.get("risk_type", "FIXED")),
        size_by_sl=bool(r.get("size_by_sl", False)),
        fees=float(r.get("fees", 0)),
        fee_type=str(r.get("fee_type", "PERCENT")),
        slippage=float(r.get("slippage", 0)),
        market_sessions=list(config.get("sesiones", ["rth"])),
        custom_start_time=config.get("hora_ini"),
        custom_end_time=config.get("hora_fin"),
        locates_cost=float(r.get("locates_cost", 0)),
        max_locates=int(r.get("max_locates", 0)),
        look_ahead_prevention=True,
    )


def evaluar(individuo: dict, config: dict, qualifying_df, grupos) -> dict:
    from app.services.backtest_service import run_backtest
    definicion = cromosoma.a_definicion(individuo, config)
    t0 = time.time()
    res = run_backtest(
        qualifying_df=qualifying_df,
        strategy_def=definicion,
        day_group_iter=iter(grupos),
        n_groups_hint=len(grupos),
        _signal_cache=None,
        **parametros_backtest(config),
    )
    agg = res.get("aggregate_metrics", {}) or {}
    m = {k: agg.get(v) for k, v in METRICAS.items()}
    m["avg_r"] = _r_media(m.get("expectancy"), config.get("riesgo", {}))
    m["segundos"] = round(time.time() - t0, 1)
    m["fitness"] = fitness(m, config)
    return m


# ── Fitness ─────────────────────────────────────────────────────────────────

def _f(x, defecto=0.0) -> float:
    try:
        v = float(x)
        return defecto if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return defecto


def _r_media(expectancy, riesgo: dict):
    """R media por operacion = PnL medio en $ / lo que se arriesga en una R.

    CON RIESGO FIJO la R son dolares y la division es exacta.

    CON RIESGO PORCENTUAL la R en dolares cambia cada dia con la cuenta, asi que
    aqui se usa la R del PRIMER dia (porcentaje x capital inicial). No es la R
    real de cada operacion — pero es una CONSTANTE, y el fitness solo necesita
    ORDENAR individuos: dividir a toda la poblacion por el mismo numero no
    cambia el orden. Para leer la R de verdad esta `r_precise` del servicio de
    robustez, que si la recalcula dia a dia.

    ANTES DEVOLVIA None en el caso porcentual, y eso era una trampa de las que
    no dan error: `_f(None)` es 0.0, asi que `avg_r` y `expR_sqrtN` habrian dado
    CERO a la poblacion entera — sin excepcion, sin log y sin nada raro en la
    pantalla, igual que un `min_trades` demasiado alto. Hoy la UI del genetico
    fija riesgo FIJO, o sea que la trampa estaba armada pero sin disparar.
    """
    tipo = str(riesgo.get("risk_type", "FIXED"))
    r_cfg = _f(riesgo.get("risk_r"), 0)
    if r_cfg <= 0:
        return None
    if tipo == "PERCENT":
        base = r_cfg / 100.0 * _f(riesgo.get("init_cash"), 0)
        return round(_f(expectancy) / base, 4) if base > 0 else None
    return round(_f(expectancy) / r_cfg, 4)


def fitness(m: dict, config: dict) -> float:
    """La nota. Por debajo del suelo de operaciones, 0: sin eso el genetico
    encuentra las seis operaciones perfectas de la historia.

    EV y R MEDIA SON LA MISMA CURVA a escala distinta: la R es el EV dividido
    por el riesgo, que es constante dentro de una corrida. Ordenan igual. Estan
    las dos porque la R se compara entre corridas con riesgos distintos y el EV
    se lee en dolares, que es como Jaume mira las cuentas.

    LAS VERSIONES `xN` MULTIPLICAN POR LA RAIZ DEL NUMERO DE OPERACIONES. Sin
    eso, una estrategia con 12 operaciones perfectas gana a una con 1.500
    buenas; con la raiz, operar mas cuenta, pero 4.000 operaciones no valen 40
    veces mas que 100. Es la diferencia entre premiar el edge y premiar el edge
    que ademas ocurre a menudo.
    """
    n = int(_f(m.get("trades")))
    if n < int(config.get("min_trades", 100)):
        return 0.0
    modo = config.get("fitness", "expR_sqrtN")
    if modo == "expR_sqrtN":
        return _f(m.get("avg_r")) * math.sqrt(n)
    if modo == "avg_r":
        return _f(m.get("avg_r"))
    if modo == "ev_sqrtN":
        return _f(m.get("expectancy")) * math.sqrt(n)
    if modo == "ev":
        return _f(m.get("expectancy"))
    if modo == "pf":
        return _f(m.get("pf"))
    if modo == "dd_return":
        return _f(m.get("dd_return"))
    if modo == "sharpe":
        return _f(m.get("sharpe"))
    raise ValueError(f"fitness desconocido: {modo}")
