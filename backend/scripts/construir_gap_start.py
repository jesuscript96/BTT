# -*- coding: utf-8 -*-
"""Construye el pivote gap_start.parquet del filtro «Hora de cruce de gap».

QUÉ ESCRIBE. Una fila por (ticker, fecha) con gap_start_min_<nivel> = t del
PRIMER minuto en que el MÁXIMO corrido (high de las velas 1m) cruza +nivel %
sobre la `prev_close` persistida, en la línea continua:

    AH víspera 16:00→t 0 … 19:59→239 · PM 04:00→720 … 09:29→1049
    · RTH 09:30→1050 … 15:59→1439

NULL si ese día no cruzó el nivel. Niveles: GAP_START_LEVELS (20→200 de 5 en 5).
El filtro distingue el tramo por el propio t: PMH = t ≤ 1049, RTH = t ≥ 1050.

POBLACIÓN: ticker-días con máximo del día (PM o RTH) ≥ +20 % sobre prev_close
en daily_metrics. Los que solo cruzaron en el AH de la víspera y luego no
llegaron a +20 % ni en PM ni en RTH quedan fuera (caso raro).

POR QUÉ UN SCRIPT APARTE (2026-10-01): hasta hoy este pivote salía de
construir_gappers_activos.py en la misma pasada que la tabla del indicador
«Gappers activos». Ampliar la ventana a RTH y la población habría cambiado
los valores del indicador; separadas, el indicador queda bit a bit igual.

Compatibilidad: el cummax es causal, así que los t de cruces antes de las
09:30 son los mismos que en el pivote anterior (mismas velas, misma fórmula);
las reglas guardadas con gap_start_min_20/50 siguen dando lo mismo en PM.

USO:
    backend/.venv/Scripts/python.exe backend/scripts/construir_gap_start.py
Env:
    LOCAL_LAKE_DIR   lago (igual que init_db)
    GAP_START_TABLE  ruta de salida (default {CACHE_DIR}/gappers_activos/gap_start.parquet)

⚠️ REGENERAR tras cada actualización del lago (mismo ciclo que el bygap).
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

from app.services.qualifying_windows import GAP_START_LEVELS, gap_start_parquet_path  # noqa: E402

MIN_POB = min(GAP_START_LEVELS)


def _lake() -> str:
    lake = os.getenv("LOCAL_LAKE_DIR", "").strip()
    if not lake:
        for linea in open(os.path.join(BACKEND, ".env"), encoding="utf-8"):
            if linea.startswith("LOCAL_LAKE_DIR="):
                lake = linea.split("=", 1)[1].strip().strip('"').strip("'")
                break
    return lake.replace("\\", "/")


def main() -> int:
    lake = _lake()
    if not lake:
        print("Falta LOCAL_LAKE_DIR (env o backend/.env)")
        return 1
    d_met = f"{lake}/cold_storage/daily_metrics/*/*/*.parquet"
    d_1m = f"{lake}/cold_storage/intraday_1m"
    # CACHE_DIR del .env si no viene por entorno (misma ruta que lee el backend)
    if not os.getenv("CACHE_DIR") and not os.getenv("GAP_START_TABLE"):
        for linea in open(os.path.join(BACKEND, ".env"), encoding="utf-8"):
            if linea.startswith("CACHE_DIR="):
                os.environ["CACHE_DIR"] = linea.split("=", 1)[1].strip().strip('"').strip("'")
                break
    ruta_piv = gap_start_parquet_path()
    if not os.path.isabs(ruta_piv):
        ruta_piv = os.path.join(BACKEND, ruta_piv)
    os.makedirs(os.path.dirname(ruta_piv), exist_ok=True)

    con = duckdb.connect()
    t0 = time.time()
    print(f"[1/3] población (máx. del día >= +{MIN_POB} % sobre prev_close)...", flush=True)
    pob = con.execute(f"""
        SELECT ticker, CAST("timestamp" AS DATE) AS fecha, prev_close
        FROM read_parquet('{d_met}', hive_partitioning=true)
        WHERE prev_close > 0
          AND GREATEST(COALESCE(pm_high, 0), COALESCE(rth_high, 0), COALESCE(high, 0))
              >= prev_close * {1 + MIN_POB / 100.0}
    """).fetchdf()
    pob["fecha"] = pd.to_datetime(pob["fecha"]).dt.strftime("%Y-%m-%d")
    # Víspera = sesión hábil anterior (lunes cuenta desde el AH del viernes).
    fechas_habiles = con.execute(f"""
        SELECT DISTINCT CAST("timestamp" AS DATE) AS f
        FROM read_parquet('{d_met}', hive_partitioning=true) ORDER BY 1
    """).fetchdf()["f"].astype(str).tolist()
    prev_habil = {fechas_habiles[i]: fechas_habiles[i - 1] for i in range(1, len(fechas_habiles))}
    pob["fecha_prev"] = pob["fecha"].map(prev_habil)
    pob = pob.drop_duplicates(["ticker", "fecha"])
    print(f"      {len(pob):,} ticker-días ({pob['ticker'].nunique():,} tickers) "
          f"en {time.time()-t0:.0f}s", flush=True)

    pob["ym_D"] = pob["fecha"].str[:7]
    pob["ym_prev"] = pob["fecha_prev"].str[:7]
    pares_d = pob.groupby("ym_D")
    pares_ah = pob.groupby("ym_prev")
    mapa_prev = dict(zip(pob["fecha_prev"], pob["fecha"]))

    print("[2/3] velas 1m por mes (AH víspera + PM + RTH) y cruces...", flush=True)
    cruces: list[pd.DataFrame] = []
    for ym in sorted(set(pob["ym_D"]) | set(pob["ym_prev"].dropna())):
        anio, mes = ym[:4], ym[5:7].lstrip("0")
        g_d = pares_d.get_group(ym) if ym in pares_d.groups else None
        g_ah = pares_ah.get_group(ym) if ym in pares_ah.groups else None
        tickers = sorted(set(g_d["ticker"] if g_d is not None else [])
                         | set(g_ah["ticker"] if g_ah is not None else []))
        if not tickers:
            continue
        fechas = sorted(set(g_d["fecha"] if g_d is not None else [])
                        | set(g_ah["fecha_prev"] if g_ah is not None else []))
        tk_sql = ", ".join(f"'{t}'" for t in tickers)
        f_sql = ", ".join(f"'{f}'" for f in fechas)
        velas = con.execute(f"""
            SELECT ticker, CAST("timestamp" AS DATE) AS fecha,
                   hour("timestamp")*60+minute("timestamp") AS minuto, high
            FROM read_parquet('{d_1m}/year={anio}/month={mes}/**/*.parquet')
            WHERE ticker IN ({tk_sql})
              AND CAST("timestamp" AS DATE) IN ({f_sql})
              AND ((hour("timestamp")*60+minute("timestamp")) BETWEEN 960 AND 1199
                OR (hour("timestamp")*60+minute("timestamp")) BETWEEN 240 AND 959)
        """).fetchdf()
        if velas.empty:
            print(f"      {ym}: sin velas", flush=True)
            continue
        velas["fecha"] = pd.to_datetime(velas["fecha"]).dt.strftime("%Y-%m-%d")
        # Velas de hoy (04:00-15:59) son de su propio día; las AH (>=16:00) de
        # la víspera hábil, mapeadas al día de gap siguiente.
        velas["fecha_gap"] = velas["fecha"]
        m_ah = velas["minuto"] >= 960
        velas.loc[m_ah, "fecha_gap"] = velas.loc[m_ah, "fecha"].map(mapa_prev)
        velas = velas.dropna(subset=["fecha_gap"])
        velas = velas.merge(
            pob[["ticker", "fecha", "prev_close"]].rename(columns={"fecha": "fecha_gap"}),
            on=["ticker", "fecha_gap"], how="inner")
        velas = velas[velas["prev_close"] > 0]
        # t SIEMPRE después del merge (máscara sobre el índice final).
        es_ah = velas["minuto"] >= 960
        velas["t"] = np.where(es_ah, velas["minuto"] - 960, velas["minuto"] + 480)
        velas = velas.sort_values(["ticker", "fecha_gap", "t"])
        velas["cummax"] = (velas["high"] / velas["prev_close"]).groupby(
            [velas["ticker"], velas["fecha_gap"]]).cummax()
        for nivel in GAP_START_LEVELS:
            d = velas[velas["cummax"] >= 1 + nivel / 100.0]
            c = d.groupby(["fecha_gap", "ticker"], as_index=False)["t"].min()
            if len(c):
                cruces.append(pd.DataFrame({
                    "ticker": c["ticker"], "fecha": c["fecha_gap"],
                    "nivel": nivel, "t": c["t"]}))
        print(f"      {ym}: {len(velas):,} velas", flush=True)

    if not cruces:
        print("SIN CRUCES — no se escribe nada; revisa el lago.")
        return 1
    print("[3/3] pivote...", flush=True)
    out = pd.concat(cruces, ignore_index=True).drop_duplicates(["ticker", "fecha", "nivel"])
    piv = out.pivot_table(index=["ticker", "fecha"], columns="nivel",
                          values="t", aggfunc="first").reset_index()
    piv.columns = [str(c) if c in ("ticker", "fecha") else f"gap_start_min_{c}"
                   for c in piv.columns]
    # Todas las columnas existen aunque un nivel no tenga cruces (error de
    # columna inexistente = nunca; NULL = «sin dato»).
    for n in GAP_START_LEVELS:
        col = f"gap_start_min_{n}"
        if col not in piv.columns:
            piv[col] = np.nan
    piv.to_parquet(ruta_piv + ".tmp", index=False)
    os.replace(ruta_piv + ".tmp", ruta_piv)
    print(f"-> {ruta_piv}: {len(piv):,} ticker-días · {len(GAP_START_LEVELS)} niveles · "
          f"{time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
