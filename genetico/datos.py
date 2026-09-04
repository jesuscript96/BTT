"""Datos del dataset para el genetico, SIN abrir el lago.

`local_data.duckdb` esta cerrado con llave por el backend (comprobado en la
fase 0: un proceso externo no lo abre ni en solo lectura). Aqui se evita:

  * qualifying  -> `daily_metrics_bygap/*.parquet` (el MISMO fichero que lee
                   el backend via QUALIFYING_WINDOWED_PARQUET) JOIN los pares
                   del dataset. DuckDB en memoria, sin fichero, sin lock.
  * velas       -> la MISMA receta que el optimizador: `_fetch_and_cache_month`
                   sobre la cache de parquet en disco (D:/tmp/btt_intraday_cache).
  * pares       -> `pairs.parquet` en el directorio de la corrida. Si no esta,
                   se lee `users.duckdb` en solo lectura y se cierra al instante
                   (provisional: en la pagina los escribira el backend, que es
                   quien tiene la base abierta).

El resultado se deja en feather en el directorio de la corrida y cada worker
lo recarga en segundos.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from genetico import entorno

entorno.preparar()

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402

BYGAP = os.getenv(
    "QUALIFYING_WINDOWED_PARQUET",
    "D:/lago_backtester/parquet/edgecute/cold_storage/daily_metrics_bygap/*.parquet",
)
COLS_VELAS = ["ticker", "date", "timestamp", "open", "high", "low", "close", "volume"]


def _pares(dataset_id: str, dir_corrida: str, fecha_ini: str | None, fecha_fin: str | None) -> pd.DataFrame:
    ruta = os.path.join(dir_corrida, "pairs.parquet")
    if os.path.exists(ruta):
        pares = pd.read_parquet(ruta)
    else:
        con = duckdb.connect(os.path.join(entorno.BACKEND, "users.duckdb"), read_only=True)
        try:
            pares = con.execute(
                "SELECT ticker, CAST(date AS VARCHAR) AS date FROM dataset_pairs "
                "WHERE dataset_id = ? ORDER BY date, ticker", [dataset_id],
            ).fetchdf()
        finally:
            con.close()
        pares.to_parquet(ruta, index=False)
    if fecha_ini:
        pares = pares[pares["date"] >= fecha_ini]
    if fecha_fin:
        pares = pares[pares["date"] <= fecha_fin]
    return pares.reset_index(drop=True)


def _qualifying(pares: pd.DataFrame, log) -> pd.DataFrame:
    t = time.time()
    con = duckdb.connect()
    try:
        con.register("pares", pares)
        q = con.execute(
            f'SELECT d.*, CAST(d."timestamp" AS DATE) AS date '
            f"FROM read_parquet('{BYGAP}') d "
            f'JOIN pares p ON p.ticker = d.ticker AND CAST(p.date AS DATE) = CAST(d."timestamp" AS DATE)'
        ).fetchdf()
    finally:
        con.close()
    q["date"] = pd.to_datetime(q["date"]).dt.strftime("%Y-%m-%d")
    q = q.sort_values(["date", "ticker"]).reset_index(drop=True)
    log(f"qualifying: {len(q)} filas de {len(pares)} pares en {time.time()-t:.0f}s")
    return q


def _velas(q: pd.DataFrame, log) -> pd.DataFrame:
    from app.db.gcs_cache import (
        INTRADAY_BATCH_SIZE, _fetch_and_cache_month, _select_intraday_glob_for_month, get_connection,
    )
    t = time.time()
    fechas = pd.to_datetime(q["date"])
    meses = sorted(set(zip(fechas.dt.year, fechas.dt.month)))
    conn = get_connection()
    trozos = []
    for i, (y, m) in enumerate(meses):
        mascara = (fechas.dt.year == y) & (fechas.dt.month == m)
        vpm = q.loc[mascara, ["ticker", "date"]].drop_duplicates().copy()
        if vpm.empty:
            continue
        ruta = _select_intraday_glob_for_month(conn, y, m)
        if ruta is None:
            log(f"  {y}-{m:02d}: sin parquet en el lago, saltado")
            continue
        ch = _fetch_and_cache_month(y, m, ruta, vpm, batch_size=max(1, int(INTRADAY_BATCH_SIZE)),
                                    mi=i + 1, n_months=len(meses))
        if ch is not None and not ch.empty:
            trozos.append(ch[COLS_VELAS])
        if (i + 1) % 12 == 0:
            log(f"  velas: mes {i+1}/{len(meses)} ({time.time()-t:.0f}s)")
    if not trozos:
        raise ValueError("No hay velas para ningun mes del periodo")
    velas = pd.concat(trozos, ignore_index=True)
    vp = q[["ticker", "date"]].drop_duplicates().copy()
    velas["date"] = velas["date"].astype(str)
    velas = velas.merge(vp, on=["ticker", "date"], how="inner")
    velas = velas.sort_values(["date", "ticker", "timestamp"]).reset_index(drop=True)
    log(f"velas: {len(velas)} en {velas.groupby(['date','ticker']).ngroups} pares, {time.time()-t:.0f}s")
    return velas


def preparar(dataset_id: str, dir_corrida: str, fecha_ini: str | None = None,
             fecha_fin: str | None = None, log=print) -> dict:
    """Deja qualifying.feather + velas.feather + datos.json en dir_corrida."""
    os.makedirs(dir_corrida, exist_ok=True)
    rq, rv = os.path.join(dir_corrida, "qualifying.feather"), os.path.join(dir_corrida, "velas.feather")
    rmeta = os.path.join(dir_corrida, "datos.json")
    # El qualifying bueno lo escribe el BACKEND (misma funcion que el panel).
    # Solo si no esta (uso desde la consola, sin backend) se construye aqui con
    # dataset_pairs, que NO es exactamente lo del panel (ver router genetico).
    if os.path.exists(rq):
        q = pd.read_feather(rq)
        origen = "backend (fetch_qualifying_data)"
    else:
        pares = _pares(dataset_id, dir_corrida, fecha_ini, fecha_fin)
        if pares.empty:
            raise ValueError("El dataset no tiene pares en ese periodo")
        q = _qualifying(pares, log)
        q.to_feather(rq)
        origen = "dataset_pairs (sin backend: puede no cuadrar con el panel)"
    firma = hashlib.md5("|".join(sorted(f"{t}:{d}" for t, d in zip(q["ticker"], q["date"]))).encode()).hexdigest()
    if os.path.exists(rv) and os.path.exists(rmeta):
        meta = json.load(open(rmeta, encoding="utf-8"))
        if meta.get("firma") == firma:
            log(f"datos ya preparados ({meta.get('pares')} pares), se reutilizan")
            return meta
        log("el qualifying ha cambiado: se rehacen las velas")
    velas = _velas(q, log)
    velas.to_feather(rv)
    meta = {"dataset_id": dataset_id, "fecha_ini": fecha_ini, "fecha_fin": fecha_fin,
            "pares": int(velas.groupby(["date", "ticker"]).ngroups), "velas": int(len(velas)),
            "primer_dia": str(q["date"].min()), "ultimo_dia": str(q["date"].max()),
            "origen_qualifying": origen, "firma": firma}
    json.dump(meta, open(os.path.join(dir_corrida, "datos.json"), "w", encoding="utf-8"), indent=1)
    return meta


def cargar(dir_corrida: str):
    """(qualifying_df, grupos) listos para run_backtest. Adelgazado: ticker y
    date como categoria (no cadenas sueltas) y sin conservar el frame entero."""
    q = pd.read_feather(os.path.join(dir_corrida, "qualifying.feather"))
    v = pd.read_feather(os.path.join(dir_corrida, "velas.feather"), columns=COLS_VELAS)
    v["ticker"] = v["ticker"].astype("category")
    v["date"] = v["date"].astype("category")
    # observed=True: con categorias, sin esto pandas genera el producto
    # cartesiano de todas las fechas x todos los tickers.
    grupos = list(v.groupby(["date", "ticker"], observed=True, sort=True))
    del v
    return q, grupos
