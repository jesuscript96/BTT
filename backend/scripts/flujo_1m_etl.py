# -*- coding: utf-8 -*-
"""FLUJO DE ORDENES POR MINUTO (22-sep-2026): la tabla de la que cuelgan
«Presion compradora», «Spread relativo» y «Desequilibrio del libro».

QUE HACE. Para cada ticker-dia de una lista (por defecto, el qualifying del
dataset actual), baja de Massive por REST las OPERACIONES y las COTIZACIONES
del dia (04:00-20:00 NY), clasifica cada operacion como compra o venta
agresiva contra la cotizacion vigente en ese instante (Lee & Ready 1991:
por encima del punto medio = compra con prisa, por debajo = venta con prisa,
en el medio = regla del tick), suma por MINUTO y guarda SOLO el resumen del
minuto. Los ticks se descartan: un dia gordo son millones de filas y el
resumen son 960.

DONDE ESCRIBE. Parquet por ticker y mes, como la cache intradia del lago:
    {CACHE_DIR}/flujo_1m/{anyo}/{mes}/{TICKER}.parquet
NUNCA toca el DuckDB que tiene abierto el backend (escribir ahi desde fuera
con el backend encendido es justo lo que corrompe). Cada fichero se escribe a
un temporal y se renombra: entero o nada. Reanudable: `flujo_hecho.json`
apunta cada ticker-dia terminado.

COLUMNAS POR MINUTO (ts_min = inicio del minuto, epoch segundos):
    vol_compra_usd, vol_venta_usd, vol_neutro_usd   dinero por lado
    n_compra, n_venta, n_neutro                     operaciones por lado
    spread_rel_med   mediana del minuto de (ask-bid)/mid, en %
    bid_size_med, ask_size_med                      medianas del minuto
    n_quotes         cotizaciones validas del minuto
    clasificados_pct % de operaciones clasificadas (compra o venta):
                     la CALIDAD del minuto. Bajo = spread ancho / libro
                     vacio; el indicador vale menos ese dia.

USO (con el venv del backend; lee MASSIVE_API_KEY de backend/.env):
    python flujo_1m_etl.py                      # el dataset actual
    python flujo_1m_etl.py --feather ruta.feather --desde 2024-01-01 --hasta 2025-12-31
    python flujo_1m_etl.py --ticker OCTO --dia 2025-09-08
Va a una peticion por vez con 0,2 s entre paginas: REST compartido, sin prisa.
Log en {CACHE_DIR}/flujo_1m/flujo_etl.log.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REST = "https://api.massive.com"
ET = ZoneInfo("America/New_York")
DESDE, HASTA = (4, 0), (20, 0)
DATASET_FEATHER = r"D:\tmp\btt_genetico\datos\universo_4fff2e7fb8_2024-01-01_2026-01-01\qualifying.feather"


def cargar_env() -> str:
    ruta = os.path.join(BACKEND, ".env")
    if os.path.exists(ruta):
        for linea in open(ruta, encoding="utf-8"):
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    key = os.getenv("MASSIVE_API_KEY", "").strip()
    if not key:
        sys.exit("falta MASSIVE_API_KEY en backend/.env")
    return key


def dir_flujo() -> str:
    base = os.getenv("CACHE_DIR", r"D:\tmp\btt_intraday_cache")
    d = os.path.join(base, "flujo_1m")
    os.makedirs(d, exist_ok=True)
    return d


def ns_et(dia: str, hm: tuple[int, int]) -> int:
    a, m, d = (int(x) for x in dia.split("-"))
    return int(datetime(a, m, d, hm[0], hm[1], tzinfo=ET).timestamp()) * 1_000_000_000


def paginar(cli: httpx.Client, key: str, url: str, params: dict, log) -> list[dict]:
    """Todas las paginas de un endpoint v3 (next_url lleva el cursor)."""
    filas: list[dict] = []
    params = dict(params, apiKey=key)
    while url:
        for intento in range(1, 7):
            try:
                r = cli.get(url, params=params, timeout=120)
                if r.status_code == 429 or r.status_code >= 500:
                    raise RuntimeError(f"HTTP {r.status_code}")
                r.raise_for_status()
                break
            except Exception as e:                                   # noqa: BLE001
                if intento == 6:
                    raise
                log.warning("reintento %d: %s", intento, e)
                time.sleep(5 * intento)
        datos = r.json()
        filas.extend(datos.get("results") or [])
        url = datos.get("next_url")
        params = {"apiKey": key}
        time.sleep(0.2)
    return filas


def clasificar(trades: pd.DataFrame, quotes: pd.DataFrame) -> pd.DataFrame:
    """Lee-Ready vectorizado. Devuelve trades con `lado` (+1 compra, -1 venta, 0 neutro)."""
    t = trades.sort_values("ts").reset_index(drop=True)
    lado = np.zeros(len(t), dtype=np.int8)
    if len(quotes):
        q = quotes.sort_values("ts").reset_index(drop=True)
        idx = np.searchsorted(q["ts"].values, t["ts"].values, side="right") - 1
        tiene = idx >= 0
        mid = np.full(len(t), np.nan)
        mid[tiene] = ((q["bid"].values[idx[tiene]] + q["ask"].values[idx[tiene]]) / 2.0)
        px = t["price"].values
        lado[np.isfinite(mid) & (px > mid)] = 1
        lado[np.isfinite(mid) & (px < mid)] = -1
    # Regla del tick para los que caen en el medio (o sin cotizacion): mayor
    # que el precio anterior distinto = compra; menor = venta; igual = el
    # ultimo lado conocido.
    px = t["price"].values
    prev = np.r_[np.nan, px[:-1]]
    sube = px > prev
    baja = px < prev
    sin = lado == 0
    lado[sin & sube] = 1
    lado[sin & baja] = -1
    # arrastre del ultimo lado conocido para los iguales (en orden)
    ult = 0
    for i in range(len(lado)):
        if lado[i] == 0:
            lado[i] = ult
        else:
            ult = lado[i]
    t["lado"] = lado
    return t


def resumir_minuto(t: pd.DataFrame, q: pd.DataFrame) -> pd.DataFrame:
    """Un minuto por fila: dinero y operaciones por lado + spread/libro."""
    t = t.copy()
    t["usd"] = t["price"] * t["size"]
    t["ts_min"] = (t["ts"] // 60_000_000_000) * 60
    for nombre, val in (("compra", 1), ("venta", -1), ("neutro", 0)):
        es = t["lado"].values == val
        t[f"vol_{nombre}_usd"] = np.where(es, t["usd"].values, 0.0)
        t[f"n_{nombre}"] = es.astype(np.int64)
    out = t.groupby("ts_min")[["vol_compra_usd", "vol_venta_usd", "vol_neutro_usd",
                               "n_compra", "n_venta", "n_neutro"]].sum()
    n = out[["n_compra", "n_venta", "n_neutro"]].sum(axis=1)
    out["clasificados_pct"] = np.where(n > 0, (out["n_compra"] + out["n_venta"]) / n.replace(0, 1) * 100.0, 0.0)
    if len(q):
        q = q.copy()
        q["ts_min"] = (q["ts"] // 60_000_000_000) * 60
        q["spread_rel"] = (q["ask"] - q["bid"]) / ((q["ask"] + q["bid"]) / 2.0) * 100.0
        gq = q.groupby("ts_min")
        qq = pd.DataFrame({
            "spread_rel_med": gq["spread_rel"].median(),
            "bid_size_med": gq["bs"].median(),
            "ask_size_med": gq["as"].median(),
            "n_quotes": gq.size(),
        })
        out = out.join(qq, how="outer")
    else:
        out["spread_rel_med"] = np.nan
        out["bid_size_med"] = np.nan
        out["ask_size_med"] = np.nan
        out["n_quotes"] = 0
    out = out.fillna({"vol_compra_usd": 0.0, "vol_venta_usd": 0.0, "vol_neutro_usd": 0.0,
                      "n_compra": 0, "n_venta": 0, "n_neutro": 0, "clasificados_pct": 0.0,
                      "n_quotes": 0})
    out.index.name = "ts_min"
    return out.reset_index()


def bajar_dia(cli, key, ticker: str, dia: str, log) -> pd.DataFrame | None:
    lo, hi = ns_et(dia, DESDE), ns_et(dia, HASTA)
    params = {"timestamp.gte": lo, "timestamp.lt": hi, "limit": 50000, "order": "asc", "sort": "timestamp"}
    tr = paginar(cli, key, f"{REST}/v3/trades/{ticker}", params, log)
    if not tr:
        return None
    qu = paginar(cli, key, f"{REST}/v3/quotes/{ticker}", params, log)
    t = pd.DataFrame({
        "ts": [int(x.get("sip_timestamp") or x.get("participant_timestamp") or 0) for x in tr],
        "price": [float(x.get("price") or 0) for x in tr],
        "size": [float(x.get("size") or 0) for x in tr],
    })
    t = t[(t["ts"] > 0) & (t["price"] > 0) & (t["size"] > 0)]
    q = pd.DataFrame({
        "ts": [int(x.get("sip_timestamp") or x.get("participant_timestamp") or 0) for x in qu],
        "bid": [float(x.get("bid_price") or 0) for x in qu],
        "ask": [float(x.get("ask_price") or 0) for x in qu],
        "bs": [float(x.get("bid_size") or 0) for x in qu],
        "as": [float(x.get("ask_size") or 0) for x in qu],
    }) if qu else pd.DataFrame(columns=["ts", "bid", "ask", "bs", "as"])
    if len(q):
        # sin mercado (bid o ask a 0, o cruzado): fuera, como en el spread del bot
        q = q[(q["ts"] > 0) & (q["bid"] > 0) & (q["ask"] > 0) & (q["ask"] >= q["bid"])]
    if t.empty:
        return None
    res = resumir_minuto(clasificar(t, q), q)
    res.insert(0, "date", dia)
    res.insert(0, "ticker", ticker)
    res["n_trades_raw"] = len(tr)
    res["n_quotes_raw"] = len(qu)
    return res


def ruta_parquet(ticker: str, dia: str) -> str:
    a, m = dia[:4], dia[5:7]
    d = os.path.join(dir_flujo(), a, m)
    os.makedirs(d, exist_ok=True)
    seguro = "".join(c if c.isalnum() or c in "._-" else "_" for c in ticker)
    return os.path.join(d, f"{seguro}.parquet")


def guardar(res: pd.DataFrame, ticker: str, dia: str) -> None:
    """Fusiona el dia en el fichero del ticker-mes; escritura atomica."""
    ruta = ruta_parquet(ticker, dia)
    if os.path.exists(ruta):
        viejo = pd.read_parquet(ruta)
        viejo = viejo[viejo["date"] != dia]
        res = pd.concat([viejo, res], ignore_index=True)
    res = res.sort_values(["date", "ts_min"]).reset_index(drop=True)
    tmp = ruta + f".tmp{os.getpid()}"
    res.to_parquet(tmp, index=False)
    os.replace(tmp, ruta)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feather", default=DATASET_FEATHER)
    ap.add_argument("--desde", default=None)
    ap.add_argument("--hasta", default=None)
    ap.add_argument("--ticker", default=None)
    ap.add_argument("--dia", default=None)
    args = ap.parse_args()

    key = cargar_env()
    d = dir_flujo()
    log_path = os.path.join(d, "flujo_etl.log")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(log_path, encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    logging.getLogger("httpx").setLevel(logging.WARNING)      # la URL lleva la clave
    log = logging.getLogger("flujo")

    hecho_path = os.path.join(d, "flujo_hecho.json")
    hecho: dict[str, list[str]] = json.load(open(hecho_path, encoding="utf-8")) if os.path.exists(hecho_path) else {}

    if args.ticker and args.dia:
        pares = [(args.ticker.upper(), args.dia)]
    else:
        q = pd.read_feather(args.feather)
        col_fecha = "date" if "date" in q.columns else "timestamp"
        q["_d"] = pd.to_datetime(q[col_fecha]).dt.strftime("%Y-%m-%d")
        if args.desde:
            q = q[q["_d"] >= args.desde]
        if args.hasta:
            q = q[q["_d"] <= args.hasta]
        if args.ticker:
            q = q[q["ticker"].astype(str).str.upper() == args.ticker.upper()]
        pares = sorted({(str(t).upper(), dd) for t, dd in zip(q["ticker"], q["_d"])})

    pendientes = [(t, dd) for t, dd in pares if t not in hecho.get(dd, [])]
    log.info("ticker-dias: %d en la lista, %d pendientes", len(pares), len(pendientes))

    t0 = time.time()
    with httpx.Client() as cli:
        for k, (ticker, dia) in enumerate(pendientes, 1):
            try:
                res = bajar_dia(cli, key, ticker, dia, log)
            except Exception as e:                                   # noqa: BLE001
                log.error("%s %s: FALLO %s", ticker, dia, e)
                continue
            if res is None:
                log.info("%s %s: sin operaciones", ticker, dia)
            else:
                guardar(res, ticker, dia)
                clasif = float(res["clasificados_pct"].mean()) if len(res) else 0.0
                log.info("%s %s: %d min · %d ops · %d cotiz · clasificados %.0f%% · %d/%d · %.1f min",
                         ticker, dia, len(res), int(res["n_trades_raw"].iloc[0]), int(res["n_quotes_raw"].iloc[0]),
                         clasif, k, len(pendientes), (time.time() - t0) / 60)
            hecho.setdefault(dia, []).append(ticker)
            tmp = hecho_path + ".tmp"
            json.dump(hecho, open(tmp, "w", encoding="utf-8"))
            os.replace(tmp, hecho_path)
    log.info("fin: %d ticker-dias en %.1f min", len(pendientes), (time.time() - t0) / 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
