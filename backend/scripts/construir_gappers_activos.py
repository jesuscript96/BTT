# -*- coding: utf-8 -*-
"""Construye la tabla de «Gappers activos (+X %)» desde el lago 1m.

QUÉ ESCRIBE. Un parquet con (fecha DATE, nivel INT, t INT), una fila por
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

⚠️ REGENERAR tras cada actualización del lago (mismo ciclo que el parquet
bygap). Un lago nuevo sin regenerar deja fechas nuevas fuera de la tabla (el
indicador da NaN ruidoso en ellas, nunca 0 silencioso).
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
    pob["fecha_prev"] = (pd.to_datetime(pob["fecha"]) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
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
        # las AH de la víspera calendario (mismo criterio que el estudio),
        # mapeadas al día siguiente (su día de gap). El dict es 1:1 porque
        # fecha = fecha_prev + 1 día calendario SIEMPRE.
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
        velas["t"] = np.where(m_ah.reindex(velas.index, fill_value=False),
                              velas["minuto"] - 960,
                              velas["minuto"] + (720 - 240))
        velas = velas.sort_values(["ticker", "fecha_gap", "t"])
        velas["ratio"] = velas["high"] / velas["prev_close"]
        velas["cummax"] = velas.groupby(["ticker", "fecha_gap"])["ratio"].cummax()
        for nivel in GAPPERS_ACTIVE_LEVELS:
            d = velas[velas["cummax"] >= 1 + nivel / 100.0]
            c = d.groupby(["fecha_gap", "ticker"])["t"].min().reset_index()
            if len(c):
                cruces.append(pd.DataFrame({
                    "fecha": c["fecha_gap"], "nivel": nivel, "t": c["t"]}))
        print(f"      {ym}: {len(velas):,} velas", flush=True)

    print("[3/3] escribiendo tabla...", flush=True)
    if not cruces:
        print("SIN CRUCES — no se escribe nada raro; revisa el lago.")
        return 1
    out = pd.concat(cruces, ignore_index=True).drop_duplicates(["fecha", "nivel", "t"])
    out = out.sort_values(["fecha", "nivel", "t"])
    tmp = out_ruta + ".tmp"
    out.to_parquet(tmp, index=False)
    os.replace(tmp, out_ruta)
    print(f"-> {out_ruta}: {len(out):,} cruces · {out['fecha'].nunique()} fechas · "
          f"{out['nivel'].nunique()} niveles · {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
