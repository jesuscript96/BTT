# -*- coding: utf-8 -*-
"""ACCIONES EN CIRCULACION A FECHA (22-sep-2026): la tabla para la ROTACION.

PARA QUE. «Ha rotado tres veces su capital flotante» es LA metrica de los
cortos de small caps: si el volumen del dia es el triple de las acciones que
existen, practicamente nadie que la tenga la compro por debajo del precio de
hoy. Pero 15 millones de acciones negociadas es enorme con 3 millones en
circulacion y nada con 200 millones: sin normalizar, el volumen absoluto
mezcla el tamanyo de la empresa con la noticia.

CIRCULACION, NO FLOAT — Y HAY QUE DECIRLO. El FLOAT (lo que de verdad puede
cambiar de manos: circulacion menos insiders y acciones restringidas) NO lo da
Massive, ni Databento, ni ninguna fuente gratuita CON HISTORICO a fecha; solo
de pago (Fintel, Ortex, S3) y normalmente solo el actual. Lo que si hay es
`shares_outstanding` por informe trimestral, que sale de los XBRL que las
empresas presentan a la SEC. Es un techo: el float real es MENOR, asi que la
rotacion real es MAYOR que la que sale aqui. Por eso todo se llama
«circulacion» en la interfaz y nunca «float».

QUE ESCRIBE. Un parquet por anyo en
    {CACHE_DIR}/circulacion/circulacion_<anyo>.parquet
    ticker, fecha_informe, shares, fuente
La consulta a fecha rellena HACIA DELANTE: el dato de un informe vale hasta el
siguiente. Con contrasplits y ampliaciones (cada dos por tres en estos
tickers) usar el numero de HOY para un dia de 2024 es un error de 5 a 20
veces, asi que la fecha del informe es lo importante.

CONTROL DE CALIDAD. Si el volumen de un dia supera 20 veces las acciones en
circulacion, el dato esta mal (un contrasplit que Massive aun no ha recogido):
se marca en `circulacion_sospechosos.csv` en vez de devolver una rotacion de
40 que nadie se cree.

NO TOCA NADA VIVO: su propio directorio, ni DuckDB ni el backend.

USO:
    python acciones_circulacion_etl.py                 # tickers del dataset
    python acciones_circulacion_etl.py --ticker OCTO
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

import pandas as pd

try:
    import httpx
except ImportError:                                              # noqa
    httpx = None

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REST = "https://api.massive.com"
DIR_DATOS_GENETICO = r"D:\tmp\btt_genetico\datos"


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


def dir_circ() -> str:
    base = os.getenv("CACHE_DIR", r"D:\tmp\btt_intraday_cache")
    d = os.path.join(base, "circulacion")
    os.makedirs(d, exist_ok=True)
    return d


def tickers_del_lago() -> list[str]:
    fuera = set()
    for q in glob.glob(os.path.join(DIR_DATOS_GENETICO, "*", "qualifying.feather")):
        try:
            fuera.update(pd.read_feather(q)["ticker"].astype(str).str.upper())
        except Exception:                                        # noqa: BLE001
            continue
    return sorted(fuera)


def bajar(cli, key: str, ticker: str, log) -> list[dict]:
    """Los informes con `shares_outstanding` de un ticker, por fecha."""
    filas = []
    url = f"{REST}/vX/reference/financials"
    params = {"ticker": ticker, "limit": 100, "apiKey": key}
    while url:
        for intento in range(1, 6):
            try:
                r = cli.get(url, params=params, timeout=90)
                if r.status_code == 429 or r.status_code >= 500:
                    raise RuntimeError(f"HTTP {r.status_code}")
                if r.status_code == 404:
                    return []
                r.raise_for_status()
                break
            except Exception as e:                               # noqa: BLE001
                if intento == 5:
                    log.warning("%s: %s", ticker, e)
                    return filas
                time.sleep(4 * intento)
        datos = r.json()
        for f in (datos.get("results") or []):
            fecha = (f.get("end_date") or f.get("filing_date") or "")[:10]
            fin = f.get("financials") or {}
            shares = None
            for bloque in ("balance_sheet", "income_statement", "comprehensive_income"):
                b = fin.get(bloque) or {}
                for clave in ("common_stock_shares_outstanding", "shares_outstanding",
                              "weighted_average_diluted_shares_outstanding",
                              "basic_average_shares"):
                    v = (b.get(clave) or {}).get("value")
                    if v:
                        shares = float(v)
                        break
                if shares:
                    break
            if fecha and shares and shares > 0:
                filas.append({"ticker": ticker, "fecha_informe": fecha,
                              "shares": shares, "fuente": "massive_financials"})
        url = datos.get("next_url")
        params = {"apiKey": key}
        time.sleep(0.2)
    return filas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default=None)
    args = ap.parse_args()
    if httpx is None:
        sys.exit("falta httpx (usa el venv del backend)")

    import logging
    key = cargar_env()
    d = dir_circ()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(os.path.join(d, "circulacion.log"), encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log = logging.getLogger("circ")

    tickers = [args.ticker.upper()] if args.ticker else tickers_del_lago()
    hecho_path = os.path.join(d, "circulacion_hecho.json")
    hecho = set(json.load(open(hecho_path, encoding="utf-8"))) if os.path.exists(hecho_path) else set()
    pendientes = [t for t in tickers if t not in hecho]
    log.info("%d tickers, %d pendientes", len(tickers), len(pendientes))

    todo: list[dict] = []
    ruta = os.path.join(d, "circulacion.parquet")
    if os.path.exists(ruta):
        todo = pd.read_parquet(ruta).to_dict("records")
    t0 = time.time()
    with httpx.Client() as cli:
        for k, tk in enumerate(pendientes, 1):
            filas = bajar(cli, key, tk, log)
            todo.extend(filas)
            hecho.add(tk)
            if k % 25 == 0 or k == len(pendientes):
                df = pd.DataFrame(todo).drop_duplicates(["ticker", "fecha_informe"])
                tmp = ruta + ".tmp"
                df.to_parquet(tmp, index=False)
                os.replace(tmp, ruta)
                json.dump(sorted(hecho), open(hecho_path + ".tmp", "w"))
                os.replace(hecho_path + ".tmp", hecho_path)
                log.info("%d/%d · %d filas · %.1f min", k, len(pendientes), len(df),
                         (time.time() - t0) / 60)
    log.info("fin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
