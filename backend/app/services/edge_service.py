"""Recorrido minuto a minuto de las operaciones, para la pestana Edge.

Responde a «si mi salida fuera a las HH:MM en vez de a la de ahora, cuanto
ganaria de media». Eso no se puede sacar de la lista de trades: hace falta el
precio DESPUES de la salida real, asi que hay que releer las velas.

DECISIONES QUE GOBIERNAN ESTE FICHERO
-------------------------------------

1. **No se toca el motor.** Anadir el minuto del MFE dentro de `portfolio_sim.py`
   parecian dos lineas, pero ese fichero lo comparte el bot de senales en vivo y
   ademas habria que replicarlo en los tres caminos de `run_backtest`. Aqui se
   reconstruye desde fuera, leyendo la misma cache de velas que ya usa la app.

2. **Solo se extiende lo que cerro por tiempo.** Si la operacion salio por SL, TP
   o senal, mover la hora de salida no la habria cambiado: su recorrido acaba
   donde acabo. Solo `EOD` y `Time Limit` se prolongan, porque son las que la
   hora de salida gobierna de verdad.

3. **Al prolongar, el stop SIGUE puesto.** Aguantar mas rato no es aguantar sin
   riesgo: si el precio toca el stop original despues de la salida real, la
   operacion contrafactual muere ahi, a -1R. Sin esto el grafico premiaria
   aguantar siempre, que es justo la conclusion equivocada.

4. **Una vez cerrada, el valor se ARRASTRA.** La curva contesta «cuanto habria
   ganado de media si mi regla de salida fuera el minuto m», no «cuanto llevan
   las que siguen abiertas». Por eso una operacion ya cerrada sigue contando con
   su resultado final: si no, la curva mediria una muestra distinta en cada
   minuto y no se podria comparar consigo misma.
"""
from __future__ import annotations

import logging
import math
import os
from collections import defaultdict
from typing import Any, Iterable

import pandas as pd

logger = logging.getLogger("btt.edge")

# Motivos de salida que la hora de salida gobierna. El resto no se prolonga.
MOTIVOS_POR_TIEMPO = {"EOD", "Time Limit"}

HORIZONTE_POR_DEFECTO = 240   # minutos despues de la entrada
MAX_TRADES = 40_000


def _minuto(ts: pd.Timestamp) -> int:
    return int(ts.hour) * 60 + int(ts.minute)


def _velas_por_dia(dataset_id: str, pares: Iterable[tuple[str, str]]) -> dict[tuple[str, str], pd.DataFrame]:
    """Velas de cada (ticker, fecha), leyendo cada parquet mensual UNA vez.

    `fetch_day_candles` relee el mes entero en cada llamada; con miles de
    operaciones del mismo ticker eso es el cuello de botella. Aqui se agrupa por
    (ticker, ano, mes) y se corta por fecha en memoria.
    """
    from app.db.gcs_cache import CACHE_DIR

    por_mes: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    for ticker, fecha in pares:
        try:
            por_mes[(ticker, int(fecha[:4]), int(fecha[5:7]))].add(fecha)
        except (ValueError, IndexError):
            continue

    out: dict[tuple[str, str], pd.DataFrame] = {}
    faltan: list[tuple[str, str]] = []

    for (ticker, anio, mes), fechas in por_mes.items():
        df = None
        for kind in ("opt", "raw"):
            fp = os.path.join(CACHE_DIR, kind, str(anio), f"{mes:02d}", f"{ticker}.parquet")
            if not os.path.exists(fp):
                continue
            try:
                df = pd.read_parquet(fp, columns=["timestamp", "date", "high", "low", "close"])
                break
            except Exception as e:                       # parquet a medias, permisos…
                logger.warning("[edge] no se pudo leer %s: %s", fp, e)
        if df is None or df.empty:
            faltan.extend((ticker, f) for f in fechas)
            continue
        df["date"] = df["date"].astype(str)
        for fecha in fechas:
            dia = df[df["date"] == fecha]
            if dia.empty:
                faltan.append((ticker, fecha))
                continue
            dia = dia.sort_values("timestamp")
            out[(ticker, fecha)] = pd.DataFrame({
                "ts": pd.to_datetime(dia["timestamp"].values),
                "high": dia["high"].values.astype(float),
                "low": dia["low"].values.astype(float),
                "close": dia["close"].values.astype(float),
            })

    # Los que no estaban en la cache local, por el camino normal (puede ir a GCS).
    if faltan:
        from app.services.data_service import fetch_day_candles
        for ticker, fecha in faltan:
            try:
                velas = fetch_day_candles(dataset_id, ticker, fecha)
            except Exception as e:
                logger.warning("[edge] sin velas para %s %s: %s", ticker, fecha, e)
                continue
            if not velas:
                continue
            out[(ticker, fecha)] = pd.DataFrame({
                "ts": pd.to_datetime([v["time"] for v in velas], unit="s"),
                "high": [float(v["high"]) for v in velas],
                "low": [float(v["low"]) for v in velas],
                "close": [float(v["close"]) for v in velas],
            })
    return out


def _camino(trade: dict, velas: pd.DataFrame, en_r: bool, horizonte: int):
    """Valor de UNA operacion minuto a minuto. Devuelve (puntos, minuto_mfe).

    `puntos` son pares (minuto del dia, valor). El valor va en R si hay stop, o
    en % de precio si no. El ultimo punto es el de cierre: quien consuma esto
    arrastra ese valor hacia adelante.
    """
    entrada = float(trade["entrada"])
    if entrada <= 0:
        return [], None
    sl_dist = float(trade.get("sl_dist") or 0.0)
    if en_r and sl_dist <= 0:
        return [], None
    largo = str(trade.get("dir", "")).lower().startswith("l")
    sl_px = float(trade.get("sl") or 0.0)

    ts_ent = pd.Timestamp(trade["entrada_ts"])
    ts_sal = pd.Timestamp(trade["salida_ts"])
    prolongable = str(trade.get("motivo", "")) in MOTIVOS_POR_TIEMPO
    # Nunca por debajo de la salida real: el horizonte ALARGA, no recorta. Una
    # entrada a las 04:05 con salida a las 09:00 dura 295 min, mas que el
    # horizonte por defecto, y truncarla se comeria la operacion de verdad.
    tope = max(ts_sal, ts_ent + pd.Timedelta(minutes=horizonte)) if prolongable else ts_sal

    ts = velas["ts"].values
    ini = int(ts.searchsorted(ts_ent.to_datetime64(), side="left"))
    fin = int(ts.searchsorted(tope.to_datetime64(), side="right"))
    if fin <= ini:
        return [], None

    highs = velas["high"].values[ini:fin]
    lows = velas["low"].values[ini:fin]
    closes = velas["close"].values[ini:fin]
    momentos = velas["ts"].iloc[ini:fin]

    puntos: list[tuple[int, float]] = []
    mejor, minuto_mejor = None, None
    seg_sal = ts_sal.to_datetime64()

    for j in range(fin - ini):
        t = momentos.iloc[j]
        # Prolongada y con stop: el stop original sigue vivo.
        if prolongable and sl_px > 0 and t.to_datetime64() > seg_sal:
            tocado = (lows[j] <= sl_px) if largo else (highs[j] >= sl_px)
            if tocado:
                puntos.append((_minuto(t), -1.0 if en_r else -sl_dist))
                break
        favor = ((closes[j] - entrada) if largo else (entrada - closes[j])) / entrada * 100.0
        extremo = ((highs[j] - entrada) if largo else (entrada - lows[j])) / entrada * 100.0
        if mejor is None or extremo > mejor:
            mejor = extremo
            minuto_mejor = int((t - ts_ent).total_seconds() // 60)
        puntos.append((_minuto(t), favor / sl_dist if en_r else favor))

    return puntos, minuto_mejor


def _resumen(vals: list[float]) -> dict[str, float]:
    n = len(vals)
    if not n:
        return {"n": 0, "media": 0.0, "ee": 0.0}
    m = sum(vals) / n
    if n < 2:
        return {"n": n, "media": round(m, 5), "ee": 0.0}
    var = sum((v - m) ** 2 for v in vals) / (n - 1)
    return {"n": n, "media": round(m, 5), "ee": round(math.sqrt(var / n), 5)}


def _percentiles(vals: list[float], ps=(0.25, 0.5, 0.75)) -> list[float]:
    if not vals:
        return [0.0] * len(ps)
    o = sorted(vals)
    out = []
    for p in ps:
        i = (len(o) - 1) * p
        lo, hi = math.floor(i), math.ceil(i)
        out.append(round(o[lo] if lo == hi else o[lo] + (i - lo) * (o[hi] - o[lo]), 2))
    return out


def calcular_recorrido(
    dataset_id: str,
    trades: list[dict],
    unidad: str = "R",
    horizonte: int = HORIZONTE_POR_DEFECTO,
) -> dict[str, Any]:
    """Curva por minuto, deltas pareados entre horas y tiempo hasta el MFE."""
    if not trades:
        return {"error": "sin operaciones"}
    if len(trades) > MAX_TRADES:
        trades = trades[:MAX_TRADES]

    en_r = unidad == "R"
    velas = _velas_por_dia(dataset_id, ((t["ticker"], t["fecha"]) for t in trades))

    # Valor de cada operacion por minuto, ya arrastrado tras el cierre.
    caminos: list[tuple[str, dict[int, float], int, float]] = []   # periodo, valores, minuto entrada, ultimo
    tiempos_mfe: dict[str, list[float]] = defaultdict(list)
    sin_velas = 0

    for t in trades:
        v = velas.get((t["ticker"], t["fecha"]))
        if v is None or v.empty:
            sin_velas += 1
            continue
        puntos, minuto_mfe = _camino(t, v, en_r, horizonte)
        if not puntos:
            sin_velas += 1
            continue
        caminos.append((t.get("periodo", "?"), dict(puntos), puntos[0][0], puntos[-1][1]))
        if minuto_mfe is not None:
            tiempos_mfe[t.get("periodo", "?")].append(float(minuto_mfe))

    if not caminos:
        return {"error": "no se pudo reconstruir ningun recorrido", "sin_velas": sin_velas}

    minutos = sorted({m for _, vals, _, _ in caminos for m in vals})
    if not minutos:
        return {"error": "recorridos vacios", "sin_velas": sin_velas}
    # La rejilla se alinea a multiplos de 5 para que las horas candidatas (cada
    # 15 min) caigan SIEMPRE en un punto de la rejilla.
    m0, m1 = (minutos[0] // 5) * 5, minutos[-1]
    rejilla = list(range(m0, m1 + 1, 5))
    idx = {m: i for i, m in enumerate(rejilla)}

    # Cada operacion se densifica UNA vez sobre la rejilla: antes de entrar es
    # None y despues de cerrar arrastra su resultado final. Buscar el valor con
    # un escaneo por minuto y operacion era O(n^3) y con miles de operaciones
    # tardaba minutos; asi todo lo de abajo es un acceso por indice.
    densos: list[tuple[str, list[float | None]]] = []
    for periodo, vals, entrada_min, _ultimo in caminos:
        pares = sorted(vals.items())
        fila: list[float | None] = [None] * len(rejilla)
        j, actual = 0, None
        for i, m in enumerate(rejilla):
            while j < len(pares) and pares[j][0] <= m:
                actual = pares[j][1]
                j += 1
            if m >= entrada_min and actual is not None:
                fila[i] = actual
        densos.append((periodo, fila))

    periodos = sorted({p for p, _ in densos})
    por_periodo: dict[str, list[list[float | None]]] = defaultdict(list)
    for p, fila in densos:
        por_periodo[p].append(fila)

    # ---- curva por periodo y minuto ----
    curva: dict[str, list[dict]] = {}
    for p in periodos:
        serie = []
        for i, m in enumerate(rejilla):
            vals = [f[i] for f in por_periodo[p] if f[i] is not None]
            if len(vals) < 5:
                continue
            serie.append({"m": m, **_resumen(vals)})
        if serie:
            curva[p] = serie

    # ---- horas candidatas: cada 15 min donde ya hay muestra suficiente ----
    # El umbral es bajo (10 %) a proposito: cortar en el 25 % dejaba fuera las
    # horas tempranas, que son justo las que se quieren comparar cuando el
    # movimiento se adelanta. Cada fila lleva su `n`, asi que una hora con poca
    # muestra se ve en la tabla y no engana a nadie.
    total = len(densos)
    horas = []
    for m in range(((m0 + 14) // 15) * 15, m1 + 1, 15):
        i = idx.get(m)
        if i is None:
            continue
        abiertos = sum(1 for _, f in densos if f[i] is not None)
        if abiertos >= max(15, total * 0.10):
            horas.append(m)
    if len(horas) > 26:
        salto = math.ceil(len(horas) / 26)
        horas = horas[::salto]

    # ---- delta PAREADO entre cada par de horas ----
    # Pareado a proposito: la diferencia de una misma operacion entre A y B tiene
    # mucha menos varianza que sus dos niveles por separado, asi que detecta con
    # mucha menos muestra. Las que aun no habian entrado en A no cuentan.
    delta: dict[str, dict[str, dict[str, dict]]] = {}
    for p in periodos:
        filas = por_periodo[p]
        porA: dict[str, dict[str, dict]] = {}
        for a in horas:
            ia = idx[a]
            porB: dict[str, dict] = {}
            for b in horas:
                if b == a:
                    continue
                ib = idx[b]
                difs = [f[ib] - f[ia] for f in filas
                        if f[ia] is not None and f[ib] is not None]
                if len(difs) >= 5:
                    porB[str(b)] = _resumen(difs)
            if porB:
                porA[str(a)] = porB
        if porA:
            delta[p] = porA

    return {
        "unidad": "R" if en_r else "%",
        "periodos": periodos,
        "horas": horas,
        "curva": curva,
        "delta": delta,
        "tiempo_mfe": {
            p: {"n": len(v), "p": _percentiles(v)}
            for p, v in tiempos_mfe.items() if v
        },
        "trades_usados": len(caminos),
        "sin_velas": sin_velas,
        "horizonte": horizonte,
    }
