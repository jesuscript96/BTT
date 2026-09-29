# -*- coding: utf-8 -*-
"""Construye la tabla de «Gappers activos (+X %)» desde el lago 1m.

QUÉ ESCRIBE. (1) Un parquet con (fecha DATE, nivel INT, t INT), una fila por
CRUCE: para cada ticker-día con potencial de gap (ver población), y para cada
nivel de GAPPERS_ACTIVE_LEVELS, el minuto t de la PRIMERA vez que el máximo
corrido de la línea continua AH-víspera + PM-de-hoy cruza +nivel % sobre la
`prev_close` PERSISTIDA (mismo ETL que los gaps del motor). El indicador
cuenta filas con t <= minuto de la vela → causal, sin datos del día completo
y sin filtros de dataset (contador idéntico al estudio del Bloque 7).

POBLACIÓN: ticker-días con `pmh_gap_pct >= 20` (el mínimo nivel) del lago
daily_metrics. Cualquier acción que haya cruzado un nivel ≥ 20 en el PM está;
las que solo cruzaron en el AH de la víspera y cuyo PM no llegó a +20 % no
(están declaradas en el docstring del indicador — caso raro: el gap ES la
noche). Los cruces AH sí cuentan para los ticker-días de la población: es la
línea continua del 5.2-bis.

LÍNEA CONTINUA t: AH 16:00→0 … 19:59→239 · PM 04:00→720 … 09:29→1049.

USO:
    backend/.venv/Scripts/python.exe backend/scripts/construir_gappers_activos.py
Env:
    LOCAL_LAKE_DIR  lago (igual que init_db)
    GAPPERS_ACTIVE_TABLE  ruta de salida (default: {CACHE_DIR}/gappers_activos/gappers_activos.parquet)

(2) Además un PIVOTE gap_start.parquet (ticker, fecha, gap_start_min_<nivel>),
para el filtro de dataset «Hora de inicio del gap» (5.2-bis): el t del primer
cruce de +nivel % en esa línea continua. NULL si el nivel no se cruzó.

⚠️ REGENERAR tras cada actualización del lago (mismo ciclo que el parquet
bygap). Un lago nuevo sin regenerar deja fechas nuevas fuera de la tabla (el
indicador da NaN ruidoso en ellas, nunca 0 silencioso) y el filtro de hora de
inicio no vería los días nuevos (quedan NULL = «sin dato»).
"""
from __future__ import annotations

import os
import sys
import time

import duckdb
import numpy as np
import pandas as pd

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.services.gappers_active import GAPPERS_ACTIVE_LEVELS  # noqa: E402

MIN_POB = 20  # población = pmh_gap_pct >= mínimo nivel


def _env(ruta: str) -> str:
    return ruta.replace("\\", "/")


def main() -> int:
    lake = os.getenv("LOCAL_LAKE_DIR", "").strip()
    if not lake:
        # mismo .env que el backend (los scripts se lanzan desde backend/)
        for linea in open(os.path.join(BACKEND, ".env"), encoding="utf-8"):
            if linea.startswith("LOCAL_LAKE_DIR="):
                lake = linea.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not lake:
        print("Falta LOCAL_LAKE_DIR (env o backend/.env)")
        return 1
    lake = _env(lake)
    d_met = f"{lake}/cold_storage/daily_metrics/*/*/*.parquet"
    d_1m = f"{lake}/cold_storage/intraday_1m"

    out_ruta = os.getenv("GAPPERS_ACTIVE_TABLE", "").strip() or os.path.join(
        os.getenv("CACHE_DIR", os.path.join(BACKEND, ".cache", "intraday")),
        "gappers_activos", "gappers_activos.parquet")
    os.makedirs(os.path.dirname(out_ruta), exist_ok=True)

    con = duckdb.connect()
    t0 = time.time()
    print("[1/3] población (ticker-días con pmh_gap_pct >= "
          f"{MIN_POB}) desde daily_metrics...", flush=True)
    pob = con.execute(f"""
        SELECT ticker, CAST("timestamp" AS DATE) AS fecha, prev_close
        FROM read_parquet('{d_met}', hive_partitioning=true)
        WHERE pmh_gap_pct >= {MIN_POB} AND prev_close > 0
    """).fetchdf()
    pob["fecha"] = pd.to_datetime(pob["fecha"]).dt.strftime("%Y-%m-%d")
    # VÍSPERA = SESIÓN HÁBIL ANTERIOR (28-sep, pedido de Álvaro): un gap del
    # lunes que empezó el VIERNES por la tarde cuenta desde el viernes. Antes
    # era víspera CALENDAR y los lunes (y post-festivos) perdían el AH del día
    # de bolsa anterior. El calendario hábil sale de las fechas presentes en
    # daily_metrics (cualquier ticker): es la referencia de sesiones del lago.
    fechas_habiles = con.execute(f"""
        SELECT DISTINCT CAST("timestamp" AS DATE) AS f
        FROM read_parquet('{d_met}', hive_partitioning=true)
        ORDER BY 1
    """).fetchdf()["f"].astype(str).tolist()
    prev_habil = {fechas_habiles[i]: fechas_habiles[i - 1] for i in range(1, len(fechas_habiles))}
    pob["fecha_prev"] = pob["fecha"].map(prev_habil)
    pob = pob.drop_duplicates(["ticker", "fecha"])
    print(f"      {len(pob):,} ticker-días ({pob['ticker'].nunique():,} tickers) "
          f"en {time.time()-t0:.0f}s", flush=True)

    # Necesidades de velas por mes: PM del día D (población) + AH de la
    # víspera D-1. Una fecha puede caer en el mes anterior al de su vela.
    pob["ym_D"] = pob["fecha"].str[:7]
    pob["ym_prev"] = pob["fecha_prev"].str[:7]
    pares_pm = pob.groupby("ym_D")  # (ticker, fecha) para PM de D
    pares_ah = pob.groupby("ym_prev")  # (ticker, fecha_prev) para AH de D-1

    print("[2/3] velas 1m por mes (PM del día + AH de la víspera) y cruces...",
          flush=True)
    cruces: list[pd.DataFrame] = []
    for ym in sorted(set(pob["ym_D"]) | set(pob["ym_prev"])):
        anio, mes = ym[:4], ym[5:7].lstrip("0")
        # tickers y fechas a leer de ESTE mes
        g_pm = pares_pm.get_group(ym) if ym in pares_pm.groups else None
        g_ah = pares_ah.get_group(ym) if ym in pares_ah.groups else None
        tickers = sorted(set(g_pm["ticker"]) | set(g_ah["ticker"])) if (g_pm is not None or g_ah is not None) else []
        if not tickers:
            continue
        fechas_pm = sorted(g_pm["fecha"].unique()) if g_pm is not None else []
        fechas_ah = sorted(g_ah["fecha_prev"].unique()) if g_ah is not None else []
        fechas = sorted(set(fechas_pm) | set(fechas_ah))
        tk_sql = ", ".join(f"'{t}'" for t in tickers)
        f_sql = ", ".join(f"'{f}'" for f in fechas)
        velas = con.execute(f"""
            SELECT ticker, CAST("timestamp" AS DATE) AS fecha,
                   hour("timestamp")*60+minute("timestamp") AS minuto, high
            FROM read_parquet('{d_1m}/year={anio}/month={mes}/**/*.parquet')
            WHERE ticker IN ({tk_sql})
              AND CAST("timestamp" AS DATE) IN ({f_sql})
              AND ((hour("timestamp")*60+minute("timestamp")) BETWEEN 960 AND 1199
                OR (hour("timestamp")*60+minute("timestamp")) BETWEEN 240 AND 569)
        """).fetchdf()
        if velas.empty:
            print(f"      {ym}: sin velas", flush=True)
            continue
        velas["fecha"] = pd.to_datetime(velas["fecha"]).dt.strftime("%Y-%m-%d")
        # A qué DÍA DE GAP pertenece cada vela: las PM son de su propio día;
        # las AH de la SESIÓN HÁBIL anterior, mapeadas al día de gap siguiente.
        # El dict sigue siendo 1:1: sesiones hábiles consecutivas distintas
        # tienen vísperas distintas (inyectivo).
        mapa_prev = dict(zip(pob["fecha_prev"], pob["fecha"]))
        m_ah = velas["minuto"] >= 960
        velas["fecha_gap"] = velas["fecha"]
        velas.loc[m_ah, "fecha_gap"] = velas.loc[m_ah, "fecha"].map(mapa_prev)
        velas = velas.dropna(subset=["fecha_gap"])
        # prev_close del DÍA DE GAP (una sola vía: por (ticker, fecha_gap)).
        velas = velas.merge(
            pob[["ticker", "fecha", "prev_close"]].rename(columns={"fecha": "fecha_gap"}),
            on=["ticker", "fecha_gap"], how="left")
        velas = velas[velas["prev_close"] > 0]
        # ⚠️ t SIEMPRE después del merge: la máscara AH/PM se recalcula sobre
        # el índice FINAL. Una máscara pre-merge reindexada por etiquetas tras
        # el merge alineaba booleanos de OTRAS filas y mandaba velas PM a la
        # escala AH (t negativos) — bug de la primera versión, corregido
        # 2026-09-28 tras la reconciliación trade a trade.
        es_ah = velas["minuto"] >= 960
        velas["t"] = np.where(es_ah, velas["minuto"] - 960,
                              velas["minuto"] + (720 - 240))
        velas = velas.sort_values(["ticker", "fecha_gap", "t"])
        velas["ratio"] = velas["high"] / velas["prev_close"]
        velas["cummax"] = velas.groupby(["ticker", "fecha_gap"])["ratio"].cummax()
        for nivel in GAPPERS_ACTIVE_LEVELS:
            d = velas[velas["cummax"] >= 1 + nivel / 100.0]
            c = d.groupby(["fecha_gap", "ticker"], as_index=False)["t"].min()
            if len(c):
                cruces.append(pd.DataFrame({
                    "ticker": c["ticker"], "fecha": c["fecha_gap"],
                    "nivel": nivel, "t": c["t"]}))
        print(f"      {ym}: {len(velas):,} velas", flush=True)

    print("[3/3] escribiendo tabla...", flush=True)
    if not cruces:
        print("SIN CRUCES — no se escribe nada raro; revisa el lago.")
        return 1
    out = pd.concat(cruces, ignore_index=True).drop_duplicates(["ticker", "fecha", "nivel"])
    out = out.sort_values(["fecha", "nivel", "t"])
    tmp = out_ruta + ".tmp"
    out.to_parquet(tmp, index=False)

    # ── PIVOTE «Hora de inicio del gap» (5.2-bis, ORDEN §3 de Álvaro) ──────────
    # Una fila por (ticker, fecha) con gap_start_min_<nivel> = t del PRIMER
    # cruce de +nivel % en la línea continua 16:00 víspera → 09:30 (misma
    # definición que la tabla de arriba; NULL si ese día no cruzó el nivel).
    # Lo consume el FILTRO DE DATASET «Hora de inicio del gap» vía LEFT JOIN
    # en las tres vías del qualifying (ver qualifying_windows.gap_start_*).
    piv = out.pivot_table(index=["ticker", "fecha"], columns="nivel",
                          values="t", aggfunc="first").reset_index()
    piv.columns = [str(c) if c in ("ticker", "fecha") else f"gap_start_min_{c}"
                   for c in piv.columns]
    ruta_piv = os.path.join(os.path.dirname(out_ruta), "gap_start.parquet")
    piv.to_parquet(ruta_piv + ".tmp", index=False)
    os.replace(ruta_piv + ".tmp", ruta_piv)
    print(f"[4/4] pivote gap_start: {len(piv):,} ticker-días -> {ruta_piv}")
    os.replace(tmp, out_ruta)
    print(f"-> {out_ruta}: {len(out):,} cruces · {out['fecha'].nunique()} fechas · "
          f"{out['nivel'].nunique()} niveles · {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
