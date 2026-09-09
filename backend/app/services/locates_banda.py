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
