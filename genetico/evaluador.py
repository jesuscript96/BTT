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

from genetico import cromosoma, especie  # noqa: E402

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


def parametros_backtest(config: dict, definicion: dict | None = None) -> dict:
    """Los argumentos de `run_backtest` que NO viajan en la definicion.

    OJO CON LA SESION Y EL MODO DE TAMANO. `run_backtest` los recibe por
    ARGUMENTO y el argumento gana sobre lo que diga la definicion. En modo
    EXPLORAR da igual, porque `cromosoma.a_definicion` los copia del mismo
    config. En modo MEJORAR no: la sesion es de la estrategia (y puede ser un
    gen), asi que pasarle la del panel del explorador la pisaria — la corrida
    entera evaluaria un horario que el usuario no ha pedido, sin ningun error.
    Por eso, con definicion, mandan la definicion y sus genes.
    """
    r = config.get("riesgo", {})
    if definicion:
        rm = definicion.get("risk_management") or {}
        return dict(
            init_cash=float(r.get("init_cash", 50000)),
            risk_r=float(r.get("risk_r", 100)),
            risk_type=str(r.get("risk_type", "FIXED")),
            size_by_sl=bool(rm.get("size_by_sl", False)) or bool(rm.get("hybrid_stop", False)),
            hybrid_stop=bool(rm.get("hybrid_stop", False)),
            hybrid_black_swan_pct=rm.get("hybrid_black_swan_pct"),
            hybrid_max_loss_pct=rm.get("hybrid_max_loss_pct"),
            fees=float(r.get("fees", 0)),
            fee_type=str(r.get("fee_type", "PERCENT")),
            slippage=float(r.get("slippage", 0)),
            market_sessions=list(definicion.get("market_sessions") or ["rth"]),
            custom_start_time=definicion.get("custom_start_time"),
            custom_end_time=definicion.get("custom_end_time"),
            locates_cost=float(r.get("locates_cost", 0)),
            max_locates=int(r.get("max_locates", 0)),
            look_ahead_prevention=True,
        )
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
    definicion = especie.modulo(config).a_definicion(individuo, config)
    t0 = time.time()
    res = run_backtest(
        qualifying_df=qualifying_df,
        strategy_def=definicion,
        day_group_iter=iter(grupos),
        n_groups_hint=len(grupos),
        _signal_cache=None,
        **parametros_backtest(config, definicion if especie.es_mejorar(config) else None),
    )
    agg = res.get("aggregate_metrics", {}) or {}
    m = {k: agg.get(v) for k, v in METRICAS.items()}
    m["avg_r"] = _r_media(m.get("expectancy"), config.get("riesgo", {}))
    m["segundos"] = round(time.time() - t0, 1)
    # `fitness_base` es la nota SIN agregacion de robustez; `fitness` es la que
    # ordena. Con agregacion «valor» son la misma. Se guardan las dos para poder
    # leer en la tabla cuanto ha costado la robustez.
    m["fitness_base"] = fitness(m, config)
    m["fitness"] = agregar(m, res, config)
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


# ── Robustez: agregar la nota por TROZOS del periodo ────────────────────────
#
# Anadido el 2026-09-06 para el modo «mejorar». NO se aplica al explorador:
# `agregacion` no viene en su config y el defecto es «valor», que es
# exactamente lo de siempre.
#
# LA IDEA. Una combinacion que solo funciona en un trimestre concreto tiene una
# nota estupenda y no vale nada. Trocear el periodo y puntuar con el PEOR trozo
# (o con media − sigma) la penaliza sola.
#
# NO CUESTA NI UN BACKTEST MAS: una sola corrida ya devuelve los trades y el
# dia a dia; los trozos salen de ahi.
#
# BASE DE CALCULO: se usa `t["pnl"]`, el MISMO que usa `expectancy` del motor —
# o sea BRUTO de locates. Es deliberado, para que la nota sea comparable con la
# del explorador. Si algun dia se pasa todo a neto, hay que cambiarlo aqui Y en
# el motor a la vez, no solo aqui.

TROZOS_DEFECTO = 4


def _trozos_de_fechas(fechas: list[str], n: int) -> list[set]:
    """Parte las fechas en `n` tramos contiguos con el MISMO numero de dias.

    Por dias de mercado y no por trimestre natural: un trimestre flojo en dias
    daria un trozo con cuatro operaciones y una nota de ruido.
    """
    unicas = sorted(set(fechas))
    if not unicas or n <= 1:
        return [set(unicas)] if unicas else []
    tam = max(1, len(unicas) // n)
    out = []
    for i in range(n):
        ini = i * tam
        fin = len(unicas) if i == n - 1 else min(len(unicas), (i + 1) * tam)
        if ini < fin:
            out.append(set(unicas[ini:fin]))
    return out


def _nota_de_trozo(trades: list, dias: list, config: dict, modo: str) -> float:
    """La metrica elegida, calculada SOLO con lo que cae en ese trozo."""
    n = len(trades)
    if n == 0:
        return 0.0
    pnls = [_f(t.get("pnl")) for t in trades]
    ev = sum(pnls) / n
    if modo in ("ev", "ev_sqrtN"):
        return ev * (math.sqrt(n) if modo == "ev_sqrtN" else 1.0)
    if modo in ("avg_r", "expR_sqrtN"):
        r = _r_media(ev, config.get("riesgo", {}))
        if r is None:
            return 0.0
        return r * (math.sqrt(n) if modo == "expR_sqrtN" else 1.0)
    if modo == "pf":
        gan = sum(p for p in pnls if p > 0)
        per = abs(sum(p for p in pnls if p < 0))
        # Sin perdidas el PF es infinito. Se acota para que un trozo de tres
        # operaciones ganadoras no gane a uno de doscientas equilibradas.
        return gan / per if per > 1e-9 else (10.0 if gan > 0 else 0.0)
    if modo == "sharpe":
        rets = [_f(d.get("total_return_pct")) for d in dias]
        if len(rets) < 2:
            return 0.0
        med = sum(rets) / len(rets)
        var = sum((x - med) ** 2 for x in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        return (med / sd * math.sqrt(252)) if sd > 1e-12 else 0.0
    if modo == "dd_return":
        acum, pico, peor = 0.0, 0.0, 0.0
        for p in pnls:
            acum += p
            pico = max(pico, acum)
            peor = min(peor, acum - pico)
        return acum / abs(peor) if peor < -1e-9 else (acum if acum > 0 else 0.0)
    return ev


def agregar(m: dict, res: dict, config: dict) -> float:
    """La nota que ORDENA. Con «valor» es la de siempre, sin tocar nada."""
    modo_ag = str(config.get("agregacion", "valor")).strip().lower()
    base = _f(m.get("fitness_base"))
    if modo_ag in ("", "valor", "none"):
        return base
    # El suelo de operaciones manda por encima de todo: si el individuo no
    # llega, ya vale 0 y no hay nada que agregar.
    if base == 0.0:
        return 0.0
    if modo_ag == "vecindario":
        # Se resuelve en el motor, que es quien tiene la cache de evaluados.
        return base

    trades = res.get("trades") or []
    dias = res.get("day_results") or []
    n_trozos = max(2, int(config.get("trozos", TROZOS_DEFECTO)))
    trozos = _trozos_de_fechas([str(t.get("date")) for t in trades], n_trozos)
    if len(trozos) < 2:
        return base

    modo = str(config.get("fitness", "expR_sqrtN"))
    notas = []
    for fechas in trozos:
        tr = [t for t in trades if str(t.get("date")) in fechas]
        dd = [d for d in dias if str(d.get("date")) in fechas]
        notas.append(_nota_de_trozo(tr, dd, config, modo))

    if modo_ag == "peor_trozo":
        return min(notas)
    if modo_ag == "media_menos_sigma":
        med = sum(notas) / len(notas)
        var = sum((x - med) ** 2 for x in notas) / len(notas)
        lam = float(config.get("lambda_sigma", 1.0))
        return med - lam * math.sqrt(var)
    raise ValueError(f"agregacion desconocida: {modo_ag}")
