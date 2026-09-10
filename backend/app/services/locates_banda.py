"""Banda de locates: Monte Carlo sobre el precio del locate, SIN volver a correr.

Jaume, 8-sep-2026: «entre qué dos curvas de ganancia voy a acabar segun me
toquen los locates». Es un Monte Carlo, pero con un atajo que lo hace barato:
cambiar de semilla NO cambia ni un trade (sin la puerta por EV), solo cambia lo
que cuesta cada ticker-dia. Asi que con la corrida que ya hay se recalcula la
factura para N semillas y salen N curvas de equity en segundos.

Con la puerta por EV activa esto es una APROXIMACION (los trades cambiarian con
cada semilla); la pantalla lo avisa. La version exacta con puerta es una tarea
larga (una pasada por semilla) y queda para despues.

La curva se construye POR FECHA, igual que `_compute_global_equity_and_drawdown`:
PnL de los trades cerrados ese dia menos la factura de locates de ese dia.
Va NETA de locates y BRUTA de gastos fijos (que no dependen de la semilla).
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from app.services.locates_random import precio_locate

MAX_SEMILLAS = 200


def _percentil(xs: np.ndarray, q: float) -> float:
    return float(np.percentile(xs, q)) if xs.size else 0.0


def _max_dd_pct(curva: np.ndarray) -> float:
    techo = np.maximum.accumulate(curva)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(techo > 0, (curva - techo) / techo * 100.0, 0.0)
    return float(dd.min()) if dd.size else 0.0


def banda(
    trades: list[dict],
    init_cash: float,
    minimo: float,
    maximo: float,
    n_semillas: int,
    semilla_base: int = 1,
    semilla_actual: int | None = None,
) -> dict:
    n = max(1, min(int(n_semillas), MAX_SEMILLAS))
    init_cash = float(init_cash)

    # PnL por fecha (todos los trades) y paquetes por ticker-dia (solo cortos,
    # sobre el MAXIMO en corto del dia: es lo que cobra el motor).
    pnl_por_fecha: dict[str, float] = defaultdict(float)
    dias: dict[tuple[str, str], dict] = {}
    for t in trades:
        f = str(t.get("fecha") or "")[:10]
        if not f:
            continue
        pnl_por_fecha[f] += float(t.get("pnl", 0.0) or 0.0)
        if str(t.get("dir", "")).lower().startswith("l"):
            continue
        clave = (str(t.get("ticker", "")), f)
        d = dias.setdefault(clave, {"max_short": 0.0, "ref": float(t.get("precio_ref") or 0.0)})
        d["max_short"] = max(d["max_short"], float(t.get("size", 0.0) or 0.0))
        if not d["ref"]:
            d["ref"] = float(t.get("precio_ref") or 0.0)

    fechas = sorted(pnl_por_fecha)
    if not fechas:
        return {"error": "sin operaciones"}
    idx = {f: i for i, f in enumerate(fechas)}
    pnl = np.array([pnl_por_fecha[f] for f in fechas], dtype=np.float64)
    bruta = init_cash + np.cumsum(pnl)

    paquetes = {k: math.ceil(v["max_short"] / 100.0) for k, v in dias.items() if v["max_short"] > 0}

    def curva_de(semilla: int) -> tuple[np.ndarray, float]:
        fee = np.zeros(len(fechas), dtype=np.float64)
        for (ticker, f), paq in paquetes.items():
            fee[idx[f]] += paq * precio_locate(dias[(ticker, f)]["ref"], minimo, maximo, semilla, ticker, f)["precio"]
        return init_cash + np.cumsum(pnl - fee), float(fee.sum())

    semillas = list(range(int(semilla_base), int(semilla_base) + n))
    curvas = np.empty((n, len(fechas)), dtype=np.float64)
    facturas = np.empty(n, dtype=np.float64)
    for i, s in enumerate(semillas):
        curvas[i], facturas[i] = curva_de(s)

    finales = curvas[:, -1] - init_cash
    dds = np.array([_max_dd_pct(c) for c in curvas])

    actual = None
    if semilla_actual is not None:
        c_act, f_act = curva_de(int(semilla_actual))
        actual = {
            "semilla": int(semilla_actual),
            "curva": [round(float(x), 2) for x in c_act],
            "final": round(float(c_act[-1] - init_cash), 2),
            "max_dd_pct": round(_max_dd_pct(c_act), 4),
            "factura": round(f_act, 2),
            # Donde cae la semilla que le toco entre las N: percentil del final.
            "percentil_final": round(float((finales < (c_act[-1] - init_cash)).mean() * 100.0), 1),
        }

    return {
        "fechas": fechas,
        "n_semillas": n,
        "semilla_base": int(semilla_base),
        "rango": {"min": float(minimo), "max": float(maximo)},
        "ticker_dias_con_locate": len(paquetes),
        "curvas": {
            "p10": [round(float(x), 2) for x in np.percentile(curvas, 10, axis=0)],
            "p50": [round(float(x), 2) for x in np.percentile(curvas, 50, axis=0)],
            "p90": [round(float(x), 2) for x in np.percentile(curvas, 90, axis=0)],
            "min": [round(float(x), 2) for x in curvas.min(axis=0)],
            "max": [round(float(x), 2) for x in curvas.max(axis=0)],
            "bruta": [round(float(x), 2) for x in bruta],
        },
        "finales": [round(float(x), 2) for x in finales],
        "max_dd_pct": [round(float(x), 4) for x in dds],
        "facturas": [round(float(x), 2) for x in facturas],
        "resumen": {
            "final_p10": round(_percentil(finales, 10), 2),
            "final_p50": round(_percentil(finales, 50), 2),
            "final_p90": round(_percentil(finales, 90), 2),
            "final_min": round(float(finales.min()), 2),
            "final_max": round(float(finales.max()), 2),
            "dd_mediana": round(_percentil(dds, 50), 4),
            "dd_peor": round(float(dds.min()), 4),
            "dd_p95": round(_percentil(dds, 5), 4),
            "factura_media": round(float(facturas.mean()), 2),
            "bruta_final": round(float(bruta[-1] - init_cash), 2),
        },
        "actual": actual,
    }


# ---------------------------------------------------------------------------
# Bootstrap: la pregunta de Jaume (10-sep-2026) — «¿gana igual con OTRO
# histórico?». La banda de arriba fija las operaciones y mueve el precio; aquí
# se mueven las dos cosas: cada réplica saca N ticker-días CON REEMPLAZO de la
# bolsa de N y les sortea precio con una de las semillas.
#
# Por qué con reemplazo y no reordenando: una permutación suma los mismos
# números en otro orden, así que el resultado final es idéntico por
# construcción (solo cambia el drawdown; eso ya lo hace la envolvente del Edge).
# Para que el resultado final se mueva hay que sacar una MUESTRA distinta.
#
# La unidad es el ticker-día, no la operación: el locate se alquila por día y
# las reentradas y pirámides comparten paquete. Sorteando operaciones sueltas se
# rompería la aritmética de los paquetes.
#
# OJO con lo que NO contesta: el bootstrap supone que todas las operaciones
# salen de la misma bolsa. Si el edge se ha degradado con los años, mezcla los
# buenos con los malos y da una respuesta optimista.

MAX_REPLICAS = 5000


def _unidades(trades: list[dict]):
    """Agrupa por (ticker, fecha): PnL del día, paquetes y precio de referencia."""
    u: dict[tuple[str, str], dict] = {}
    for t in trades:
        f = str(t.get("fecha") or "")[:10]
        if not f:
            continue
        k = (str(t.get("ticker", "")), f)
        d = u.setdefault(k, {"pnl": 0.0, "max_short": 0.0, "ref": 0.0})
        d["pnl"] += float(t.get("pnl", 0.0) or 0.0)
        if str(t.get("dir", "")).lower().startswith("l"):
            continue
        d["max_short"] = max(d["max_short"], float(t.get("size", 0.0) or 0.0))
        if not d["ref"]:
            d["ref"] = float(t.get("precio_ref") or 0.0)
    claves = sorted(u)
    pnl = np.array([u[k]["pnl"] for k in claves], dtype=np.float64)
    paq = np.array([math.ceil(u[k]["max_short"] / 100.0) for k in claves], dtype=np.float64)
    refs = [u[k]["ref"] for k in claves]
    return claves, pnl, paq, refs


def _dd_filas(curvas: np.ndarray) -> np.ndarray:
    techo = np.maximum.accumulate(curvas, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(techo > 0, (curvas - techo) / techo * 100.0, 0.0)
    return dd.min(axis=1)


def bootstrap(
    trades: list[dict],
    init_cash: float,
    minimo: float,
    maximo: float,
    n_semillas: int,
    semilla_base: int = 1,
    n_replicas: int = 1000,
    semilla_mc: int = 20260910,
) -> dict | None:
    claves, pnl, paq, refs = _unidades(trades)
    U = len(claves)
    if U < 30:
        return None
    init_cash = float(init_cash)
    R = max(1, min(int(n_replicas), MAX_REPLICAS))

    # Matriz de COSTE por (semilla de precio, ticker-día). Se reutilizan las
    # mismas semillas de la banda, recortadas si la corrida es enorme.
    S = max(1, min(int(n_semillas), MAX_SEMILLAS))
    S = max(1, min(S, max(8, 4_000_000 // max(1, U))))
    coste = np.zeros((S, U), dtype=np.float64)
    for s in range(S):
        semilla = int(semilla_base) + s
        for j in range(U):
            if paq[j]:
                coste[s, j] = paq[j] * precio_locate(
                    refs[j], minimo, maximo, semilla, claves[j][0], claves[j][1]
                )["precio"]

    pasos = np.unique(np.linspace(0, U - 1, min(U, 400)).astype(int))
    rng = np.random.default_rng(int(semilla_mc))
    trozo = max(1, min(R, 1_000_000 // max(1, U)))

    tramos, finales, dds, brutos, facturas = [], [], [], [], []
    hecho = 0
    while hecho < R:
        m = min(trozo, R - hecho)
        idx = rng.integers(0, U, size=(m, U))
        fila = rng.integers(0, S, size=m)
        bruto = pnl[idx]
        fee = coste[fila[:, None], idx]
        cur = init_cash + np.cumsum(bruto - fee, axis=1)
        tramos.append(cur[:, pasos])
        finales.append(cur[:, -1] - init_cash)
        dds.append(_dd_filas(cur))
        brutos.append(bruto.sum(axis=1))
        facturas.append(fee.sum(axis=1))
        hecho += m

    curvas = np.concatenate(tramos)
    fin = np.concatenate(finales)
    dd = np.concatenate(dds)
    bru = np.concatenate(brutos)
    fac = np.concatenate(facturas)

    # Histograma del resultado final; el 0 tiene que caer dentro para que se vea
    # cuánta masa queda en rojo.
    lo, hi = float(min(fin.min(), 0.0)), float(max(fin.max(), 0.0))
    nb = 30
    ancho = (hi - lo) / nb or 1.0
    conteo, _ = np.histogram(fin, bins=nb, range=(lo, lo + ancho * nb))
    hist = [{"c": round(lo + ancho * (i + 0.5), 2), "n": int(conteo[i])} for i in range(nb)]

    pc = lambda q: round(float(np.percentile(fin, q)), 2)  # noqa: E731
    return {
        "n_replicas": R,
        "n_unidades": U,
        "n_semillas_precio": S,
        "pasos": [int(x) for x in pasos],
        "curvas": {
            "p5": [round(float(x), 2) for x in np.percentile(curvas, 5, axis=0)],
            "p25": [round(float(x), 2) for x in np.percentile(curvas, 25, axis=0)],
            "p50": [round(float(x), 2) for x in np.percentile(curvas, 50, axis=0)],
            "p75": [round(float(x), 2) for x in np.percentile(curvas, 75, axis=0)],
            "p95": [round(float(x), 2) for x in np.percentile(curvas, 95, axis=0)],
        },
        "hist": hist,
        "positivo_pct": round(float((fin > 0).mean() * 100.0), 1),
        "positivo_bruto_pct": round(float((bru > 0).mean() * 100.0), 1),
        "resumen": {
            "p5": pc(5), "p25": pc(25), "p50": pc(50), "p75": pc(75), "p95": pc(95),
            "media": round(float(fin.mean()), 2),
            "peor": round(float(fin.min()), 2),
            "mejor": round(float(fin.max()), 2),
            "bruto_p50": round(float(np.percentile(bru, 50)), 2),
            "factura_p50": round(float(np.percentile(fac, 50)), 2),
            "dd_p50": round(float(np.percentile(dd, 50)), 4),
            "dd_p95": round(float(np.percentile(dd, 5)), 4),
            "dd_peor": round(float(dd.min()), 4),
        },
    }
