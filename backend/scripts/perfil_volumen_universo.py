# -*- coding: utf-8 -*-
"""PERFIL DE VOLUMEN DEL UNIVERSO (22-sep-2026): que fraccion del volumen del
dia hace un gapper tipico en cada minuto del reloj.

PARA QUE. El volumen intradia tiene forma de U muy estable (Admati &
Pfleiderer 1988; Wood, McInish & Ord 1985): el mismo volumen a las 09:35 es
normal y a las 11:20 es un acontecimiento. Un umbral fijo («volumen >
500.000») mide la HORA tanto como la noticia. Con este perfil, el indicador
«RVOL universo» compara el volumen de ahora con el que tocaria a esta hora en
un dia de gap, y sale un numero comparable entre tickers y entre horas.

POR QUE NO ES EL RVOL DE SIEMPRE. El RVOL clasico compara la accion con SUS
dias anteriores. En este universo eso no vale: un gapper del +50 % no tiene
«dias normales» — ayer negociaba cien veces menos. La referencia buena es lo
que hacen LOS DEMAS GAPPERS a esa hora.

FUERA DE MUESTRA A PROPOSITO. El perfil se calcula con dias ANTERIORES a 2024
(por defecto) y Jaume backtestea 2024 en adelante: asi el perfil no ha visto
los dias sobre los que se mide. Si algun dia se recalcula con todo, hay que
decirlo — seria mirar (un poquito) al futuro.

QUE ESCRIBE. Un parquet minusculo (960 filas) en
    {CACHE_DIR}/perfil_volumen/perfil_universo.parquet
    minuto_del_dia  (minutos desde las 00:00 NY; 240 = 04:00, 570 = 09:30)
    fraccion        media de (volumen del minuto / volumen del dia)
    p25, p75        dispersion, para saber si la hora es estable
    n_dias          cuantos ticker-dias entraron en ese minuto
    acumulada       suma de `fraccion` hasta ese minuto (F(m)), normalizada a 1
Y un `perfil_meta.json` con el rango de fechas y cuantos ticker-dias se usaron:
la descripcion del indicador lo ensena, para que nadie use el perfil sin saber
con que se hizo.

NO TOCA NADA VIVO: lee los parquet de la cache del lago y escribe su propio
fichero. Ni DuckDB ni el backend ni la API de Massive.

USO:
    python perfil_volumen_universo.py                     # <2024, todos los qualifying
    python perfil_volumen_universo.py --hasta 2023-12-31 --minimo-dias 200
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

import numpy as np
import pandas as pd

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_DATOS_GENETICO = r"D:\tmp\btt_genetico\datos"
# Minutos del reloj NY que se perfilan: 04:00 (240) a 20:00 (1200).
MIN_INI, MIN_FIN = 4 * 60, 20 * 60


def dir_perfil() -> str:
    base = os.getenv("CACHE_DIR", r"D:\tmp\btt_intraday_cache")
    d = os.path.join(base, "perfil_volumen")
    os.makedirs(d, exist_ok=True)
    return d


def dir_velas() -> str:
    base = os.getenv("CACHE_DIR", r"D:\tmp\btt_intraday_cache")
    return os.path.join(base, "raw")


def ticker_dias(hasta: str) -> pd.DataFrame:
    """Todos los ticker-dia de los qualifying guardados, hasta `hasta`.

    Se mezclan los datasets a proposito: cada uno tiene sus filtros (gap,
    precio, volumen) y lo que se busca aqui NO es un edge, es la FORMA del
    dia de un gapper. Cuantos mas dias, mas estable la mediana.
    """
    filas = []
    for q in glob.glob(os.path.join(DIR_DATOS_GENETICO, "*", "qualifying.feather")):
        try:
            d = pd.read_feather(q)
        except Exception:                                        # noqa: BLE001
            continue
        col = "date" if "date" in d.columns else "timestamp"
        d = d[["ticker", col]].rename(columns={col: "date"})
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        filas.append(d)
    if not filas:
        sys.exit("no encontre ningun qualifying.feather")
    todo = pd.concat(filas, ignore_index=True).drop_duplicates()
    todo["ticker"] = todo["ticker"].astype(str).str.upper()
    return todo[todo["date"] <= hasta].sort_values(["date", "ticker"]).reset_index(drop=True)


def acumular(pares: pd.DataFrame, log=print) -> pd.DataFrame:
    """Recorre las velas y acumula, por minuto del reloj, las fracciones del dia.

    Se agrupa por fichero (ticker-mes) para abrir cada parquet UNA vez: con
    20.000 ticker-dias, abrirlo por dia serian 20.000 lecturas de un disco
    mecanico. Ver [[btt-maquina-de-jaume]].
    """
    pares = pares.copy()
    pares["anyo"] = pares["date"].str[:4]
    pares["mes"] = pares["date"].str[5:7]
    por_fichero: dict[tuple[str, str, str], set] = {}
    for t, d, a, m in zip(pares["ticker"], pares["date"], pares["anyo"], pares["mes"]):
        por_fichero.setdefault((a, m, t), set()).add(d)

    # Una lista de fracciones por minuto: la mediana se calcula al final.
    cubos: dict[int, list] = {m: [] for m in range(MIN_INI, MIN_FIN)}
    n_dias = 0
    t0 = time.time()
    for k, ((a, m, tk), dias) in enumerate(sorted(por_fichero.items()), 1):
        ruta = os.path.join(dir_velas(), a, m, f"{tk}.parquet")
        if not os.path.exists(ruta):
            continue
        try:
            df = pd.read_parquet(ruta, columns=["date", "timestamp", "volume"])
        except Exception as e:                                   # noqa: BLE001
            log(f"  aviso: {ruta}: {e}")
            continue
        df["_d"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df[df["_d"].isin(dias)]
        if df.empty:
            continue
        ts = pd.to_datetime(df["timestamp"])
        df["_min"] = ts.dt.hour * 60 + ts.dt.minute
        df = df[(df["_min"] >= MIN_INI) & (df["_min"] < MIN_FIN)]
        for _, dia in df.groupby("_d", observed=True):
            total = float(dia["volume"].sum())
            if total <= 0:
                continue
            n_dias += 1
            frac = dia.groupby("_min")["volume"].sum() / total
            for minuto, f in frac.items():
                cubos[int(minuto)].append(float(f))
        if k % 500 == 0:
            log(f"  {k}/{len(por_fichero)} ficheros · {n_dias} ticker-dias · {(time.time()-t0)/60:.1f} min")

    filas = []
    for minuto in range(MIN_INI, MIN_FIN):
        v = cubos[minuto]
        # Los minutos SIN vela cuentan como 0: un gapper que no cotiza a las
        # 19:00 tiene volumen cero a esa hora, no «dato ausente». Si no, el
        # perfil de las horas muertas saldria inflado (solo promediaria los
        # dias en que SI hubo negocio).
        faltan = n_dias - len(v)
        arr = np.array(v + [0.0] * max(0, faltan), dtype=np.float64)
        filas.append({
            "minuto_del_dia": minuto,
            # MEDIA, no mediana. Las velas son DISPERSAS (solo hay vela si
            # hubo operacion) y en un minuto cualquiera mas de la mitad de los
            # ticker-dias no tienen ninguna: la mediana con los ceros dentro
            # sale 0 en TODO el dia (medido: el perfil entero a cero). La
            # media es ademas lo que se quiere aqui — «de cada 100 $ del dia,
            # cuantos se mueven a esta hora» — y es lo que usa la literatura
            # del perfil intradia.
            "fraccion": float(arr.mean()) if len(arr) else 0.0,
            "mediana_con_vela": float(np.median(v)) if v else 0.0,
            "p25": float(np.percentile(arr, 25)) if len(arr) else 0.0,
            "p75": float(np.percentile(arr, 75)) if len(arr) else 0.0,
            "n_dias": int(len(v)),
        })
    out = pd.DataFrame(filas)
    # Normalizada para que `acumulada` sea una fraccion del dia de verdad.
    suma = out["fraccion"].sum()
    if suma > 0:
        out["fraccion"] = out["fraccion"] / suma
    out["acumulada"] = out["fraccion"].cumsum()
    out.attrs["n_dias"] = n_dias
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hasta", default="2023-12-31",
                    help="ultimo dia que entra en el perfil (por defecto <2024: fuera de muestra)")
    ap.add_argument("--minimo-dias", type=int, default=200,
                    help="si salen menos ticker-dias, no se escribe nada")
    args = ap.parse_args()

    pares = ticker_dias(args.hasta)
    print(f"ticker-dias candidatos (<= {args.hasta}): {len(pares)}")
    perfil = acumular(pares)
    n = perfil.attrs.get("n_dias", 0)
    if n < args.minimo_dias:
        sys.exit(f"solo {n} ticker-dias con velas: muy pocos para un perfil fiable")

    d = dir_perfil()
    ruta = os.path.join(d, "perfil_universo.parquet")
    tmp = ruta + ".tmp"
    perfil.to_parquet(tmp, index=False)
    os.replace(tmp, ruta)
    meta = {
        "generado": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hasta": args.hasta,
        "desde": str(pares["date"].min()),
        "ticker_dias": n,
        "minutos": [MIN_INI, MIN_FIN],
        "nota": ("Media por minuto del reloj NY de (volumen del minuto / volumen del dia) "
                 "en ticker-dias de gap. Fuera de muestra para backtests posteriores a `hasta`."),
    }
    json.dump(meta, open(os.path.join(d, "perfil_meta.json"), "w", encoding="utf-8"), indent=1)
    print(f"escrito {ruta} · {n} ticker-dias")
    for h in ("04:00", "07:00", "09:30", "09:35", "10:00", "12:00", "15:55", "19:00"):
        m = int(h[:2]) * 60 + int(h[3:])
        f = perfil.loc[perfil["minuto_del_dia"] == m]
        if len(f):
            r = f.iloc[0]
            print(f"  {h}  fraccion {r.fraccion*100:6.3f} %  acumulada {r.acumulada*100:6.2f} %  n {int(r.n_dias)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
