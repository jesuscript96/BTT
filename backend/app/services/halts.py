"""
Coste de Halts (12-sep-2026, a peticion de Jaume).

DE DONDE SALEN LOS HALTS. Massive no los da (ni en las velas ni en los codigos
de los ticks, medido). La fuente es el `status` de Nasdaq via Databento, que
la fase 8 del lago deja en un parquet por dia:

    <HALTS_DIR>/AAAA-MM-DD.parquet   (defecto D:/lago_backtester/parquet/halts/dias)

con un halt por fila: symbol, date, halt_ts, resume_ts (NaT si no reabrio ese
dia), reason, motivo, minutos. Las horas van en hora de NUEVA YORK sin zona,
igual que las velas del lago, asi que se comparan directamente.

QUE SIMULA. Dos modos, elegidos por Jaume:
  - «primero»: al PRIMER halt que pille la posicion abierta, se sale en la
    reapertura: al precio de apertura de la primera vela tras la reanudacion,
    penalizado con `slippage_pct` (peor para la posicion).
  - «n»: igual, pero solo cuando el halt es el N-esimo DEL DIA para ese ticker
    (contando desde la apertura, no desde la entrada): si entras despues del
    3.o y N=3, el siguiente que te pille dispara.
En los dos casos, tras salir por halt NO se vuelve a operar ese ticker-dia.
Si el halt que dispara no reabre ese dia (T12, suspension), se cierra al
ultimo precio antes del halt con el mismo slippage y el trade queda marcado
como «atrapado» (decision de Jaume: contarlo, y verlo en la tabla).

Todos los tipos de halt cuentan (LULD, noticia, regulatorios).

DONDE VIVE CADA COSA. Aqui: la configuracion, la carga de la tabla y la
traduccion de cada halt a indices de vela del ticker-dia. La ejecucion del
cierre va en `portfolio_sim.simulate(halts=...)`, detras de un `if` que con
None no ejecuta nada.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

HALTS_DIR_DEFECTO = "D:/lago_backtester/parquet/halts/dias"


def halts_dir() -> str:
    return os.getenv("HALTS_DIR", "").strip() or HALTS_DIR_DEFECTO


@dataclass(frozen=True)
class ConfigHalts:
    """Configuracion del coste de halts. Inmutable."""
    modo: str = "primero"          # "primero" | "n"
    n_halts: int = 1               # modo "n": el halt del dia que dispara (>= 1)
    slippage_pct: float = 5.0      # % peor que el precio de reapertura

    def __post_init__(self):
        if self.modo not in ("primero", "n"):
            raise ValueError(f"modo de halts desconocido: {self.modo!r}")
        if self.modo == "n" and int(self.n_halts) < 1:
            raise ValueError("el numero de halts debe ser >= 1")
        if float(self.slippage_pct) < 0.0:
            raise ValueError("el slippage de halts no puede ser negativo")

    @property
    def umbral(self) -> int:
        """Orden del halt del dia a partir del cual se sale."""
        return 1 if self.modo == "primero" else int(self.n_halts)

    def resumen(self) -> dict:
        return {"modo": self.modo, "n_halts": int(self.umbral),
                "slippage_pct": float(self.slippage_pct)}


@dataclass
class TablaHalts:
    """Halts de la corrida, indexados por (symbol, date) y ordenados por hora."""
    por_dia: dict = field(default_factory=dict)
    n_dias_fichero: int = 0
    n_halts: int = 0

    def de(self, symbol: str, date: str) -> list:
        return self.por_dia.get((symbol, date), [])


def cargar_halts(desde: str | None, hasta: str | None, directorio: str | None = None) -> TablaHalts:
    """Lee los parquets diarios del rango y monta la tabla. Sin ficheros
    devuelve una tabla vacia (el coste no cerrara nada) y el orquestador avisa.
    """
    d = directorio or halts_dir()
    tabla = TablaHalts()
    ficheros = sorted(glob.glob(os.path.join(d, "*.parquet")))
    if desde:
        ficheros = [f for f in ficheros if os.path.basename(f)[:10] >= str(desde)[:10]]
    if hasta:
        ficheros = [f for f in ficheros if os.path.basename(f)[:10] <= str(hasta)[:10]]
    if not ficheros:
        return tabla
    df = pd.concat((pd.read_parquet(f) for f in ficheros), ignore_index=True)
    tabla.n_dias_fichero = len(ficheros)
    if df.empty:
        return tabla
    df = df[df["symbol"].notna()].copy()
    df["date"] = df["date"].astype(str).str[:10]
    df["halt_ts"] = pd.to_datetime(df["halt_ts"])
    df["resume_ts"] = pd.to_datetime(df["resume_ts"])
    df = df.sort_values(["symbol", "date", "halt_ts"])
    for (sym, fecha), g in df.groupby(["symbol", "date"], sort=False):
        tabla.por_dia[(str(sym), str(fecha))] = [
            {
                "halt_ns": int(r.halt_ts.value),
                "resume_ns": (int(r.resume_ts.value) if pd.notna(r.resume_ts) else None),
                "reason": int(r.reason) if pd.notna(r.reason) else 0,
                "motivo": str(r.motivo) if "motivo" in df.columns and pd.notna(r.motivo) else "",
                "minutos": (float(r.minutos) if "minutos" in df.columns and pd.notna(r.minutos) else None),
                "orden": k + 1,
            }
            for k, r in enumerate(g.itertuples(index=False))
        ]
        tabla.n_halts += len(g)
    return tabla


# ── Lectura por DIA, para los indicadores «Halt Down» / «Halt Up» ────────────
# La capa de indicadores no conoce el rango de la corrida: recibe un ticker-dia
# suelto. Se lee el parquet de ESE dia (unos KB) y se cachea agrupado por
# simbolo. Mismo fichero y misma semantica que `cargar_halts`.
_cache_dias: dict = {}


def halts_del_dia(ticker: str, date: str) -> list:
    """Halts del ticker ese dia (ordenados por hora, con `orden`), o []."""
    fecha = str(date)[:10]
    if fecha not in _cache_dias:
        ruta = os.path.join(halts_dir(), f"{fecha}.parquet")
        por_simbolo: dict = {}
        if os.path.exists(ruta):
            try:
                df = pd.read_parquet(ruta)
                df = df[df["symbol"].notna()].copy()
                df["halt_ts"] = pd.to_datetime(df["halt_ts"])
                df["resume_ts"] = pd.to_datetime(df["resume_ts"])
                df = df.sort_values(["symbol", "halt_ts"])
                for sym, g in df.groupby("symbol", sort=False):
                    por_simbolo[str(sym)] = [
                        {
                            "halt_ns": int(r.halt_ts.value),
                            "resume_ns": (int(r.resume_ts.value) if pd.notna(r.resume_ts) else None),
                            "reason": int(r.reason) if pd.notna(r.reason) else 0,
                            "motivo": str(r.motivo) if "motivo" in df.columns and pd.notna(r.motivo) else "",
                            "minutos": (float(r.minutos) if "minutos" in df.columns and pd.notna(r.minutos) else None),
                            "orden": k + 1,
                        }
                        for k, r in enumerate(g.itertuples(index=False))
                    ]
            except Exception:  # noqa: BLE001 — un dia ilegible cuenta como sin halts
                por_simbolo = {}
        _cache_dias[fecha] = por_simbolo
    return _cache_dias[fecha].get(str(ticker), [])


def serie_halts_direccion(open_, close, timestamps, ticker: str, date: str,
                          direccion: str) -> pd.Series:
    """Indicadores «Halt Down» / «Halt Up» (Jaume, 12-sep-2026).

    Cuenta, vela a vela, cuantos halts ha habido HOY en este ticker cuya vela
    de entrada al halt (la ultima con ts <= hora del halt) fue bajista
    (`direccion="down"`: close < open) o alcista (`"up"`: close > open). Un
    doji no cuenta en ninguno. Es un contador que se queda: «Halt Down >= 1»
    se hace verdad en la vela del primer halt bajista y sigue verdad el resto
    del dia; como el motor dispara las entradas en el FLANCO de la condicion,
    eso equivale a «entrar en el momento del primer halt bajista» y la orden se
    llena en la vela siguiente, que es la de reapertura.
    """
    idx = close.index if isinstance(close, pd.Series) else None
    n = len(close)
    vacio = pd.Series(np.zeros(n), index=idx)
    if n == 0 or not ticker or not date:
        return vacio
    lista = halts_del_dia(ticker, date)
    if not lista:
        return vacio
    try:
        ts = (pd.to_datetime(timestamps).values.astype("datetime64[ns]").astype(np.int64))
    except Exception:  # noqa: BLE001
        return vacio
    o = np.asarray(open_, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    marcas = np.zeros(n)
    for h in halts_a_indices(lista, ts):
        i = int(h["halt_idx"])
        if i < 0 or i >= n:
            continue
        if direccion == "down" and c[i] < o[i]:
            marcas[i] += 1.0
        elif direccion == "up" and c[i] > o[i]:
            marcas[i] += 1.0
    return pd.Series(np.cumsum(marcas), index=idx)


def halts_a_indices(halts: list, timestamps: np.ndarray) -> list:
    """Traduce los halts de un ticker-dia a indices de vela del frame que
    simula el dia. `timestamps` en ns (misma base horaria que los halts).

      halt_idx   = ultima vela con ts <= halt_ts (la vela en la que paro)
      resume_idx = primera vela con ts >= resume_ts, o None si no reabrio ese
                   dia o no quedan velas despues

    Halts FUERA del frame se descartan por los dos lados: si el frame esta
    recortado a la sesion, un halt de premercado (antes de la primera vela) o
    de la tarde (despues del ultimo minuto) no puede pillar dentro, pero SI
    cuenta para el orden del dia (el orden viene de la tabla).

    El corte por arriba es `ts[-1] + 1 min`, no `ts[-1]`: un halt dentro del
    ultimo minuto si es de ese minuto. Sin este corte, TODOS los halts de la
    sesion regular de una estrategia de premercado (04:00-08:45) caian en la
    ultima vela del frame como «atrapados»: 451 de 453 en la primera corrida
    real (12-sep-2026).
    """
    out = []
    if halts is None or len(halts) == 0 or timestamps is None or len(timestamps) == 0:
        return out
    ts = np.asarray(timestamps, dtype=np.int64)
    n = len(ts)
    fin = int(ts[-1]) + 60_000_000_000
    for h in halts:
        hn = h["halt_ns"]
        if hn < ts[0] or hn >= fin:
            continue
        hi = int(np.searchsorted(ts, hn, side="right") - 1)
        if hi < 0 or hi >= n:
            continue
        ri = None
        if h["resume_ns"] is not None:
            r = int(np.searchsorted(ts, h["resume_ns"], side="left"))
            if r < n:
                ri = r
        out.append({**h, "halt_idx": hi, "resume_idx": ri})
    return out
