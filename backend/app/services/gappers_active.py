# -*- coding: utf-8 -*-
"""«Gappers activos (+X %)» — el 7.2b del Bloque 7 como indicador de vela.

QUÉ ES: en cada minuto del día del gap, cuántas acciones DISTINTAS del
universo ya han cruzado +X % sobre su cierre de ayer en la línea continua
AH-víspera(16:00-19:59) + premarket(04:00-09:29). Cross-sectional: no sale
del frame del ticker, sale de una TABLA PRECOMPUTADA por (fecha, nivel).

CAUSAL por construcción: la tabla guarda, para cada (fecha, nivel), los
MINUTOS DE CRUCE de cada acción; el indicador cuenta solo los cruces con
minuto ≤ la vela actual. Ningún dato del día completo, ningún filtro del
dataset — el MISMO contador del estudio (INFORME_BLOQUE7 §8, pureza (2)).

TABLA (la genera backend/scripts/construir_gappers_activos.py):
    parquet con columnas (fecha DATE, nivel INT, t INT) — una fila por cruce.
    t = minuto en la línea continua: AH 16:00→0 … 19:59→239; PM 04:00→720
    … 09:29→1049. Niveles precomputados: GAPPERS_ACTIVE_LEVELS. La ruta va
    en GAPPERS_ACTIVE_TABLE (default: {CACHE_DIR}/gappers_activos/gappers_activos.parquet).
    ⚠️ Regenerar tras cada actualización del lago (mismo ciclo que bygap).

FLAG: GAPPERS_ACTIVE_ENABLED (apagado por defecto, como ROBUSTNESS_ENABLED).
Sin el flag el indicador NO aparece en la UI (GET /api/gappers-active) y el
motor devuelve NaN + un ERROR único en el log — sin el flag, nada cambia.

NO TOCA market_frame.py ni nada del bot: solo lectura de un parquet propio.
El bot en vivo NO ve este indicador (no tiene la tabla); si Jaume lo quiere
para el bot, la decisión es suya (aviso en MEMORIA_MADRE).
"""
import logging
import os
import threading

import numpy as np
import pandas as pd

logger = logging.getLogger("backtester.gappers")

# Niveles X precomputados en la tabla. El selector de la UI ofrece SOLO
# estos; cualquier otro X revienta con ERROR (nivel no admitido) en vez de
# caer a otro nivel en silencio.
GAPPERS_ACTIVE_LEVELS = (20, 30, 40, 50, 60, 75, 100, 150, 200)

# Línea continua t: AH de la víspera [0, 240), PM de hoy [720, 1050).
_PM_T0 = 720      # t del 04:00
_PM_TFIN = 1050   # t de las 09:30 (fin del premarket)
_POST_FIN = 1049   # a partir de las 09:30 el contador ya es el final

_TABLA: dict | None = None          # fecha -> {nivel: np.array(t) ordenado}
_AVISADO = False
_LOCK = threading.Lock()


def gappers_activos_enabled() -> bool:
    return os.getenv("GAPPERS_ACTIVE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _ruta_tabla() -> str:
    ruta = os.getenv("GAPPERS_ACTIVE_TABLE", "").strip()
    if ruta:
        return ruta
    base = os.getenv("CACHE_DIR", ".cache/intraday")
    return os.path.join(base, "gappers_activos", "gappers_activos.parquet")


def _avisar_una_vez(msg: str) -> None:
    global _AVISADO
    if _AVISADO:
        return
    _AVISADO = True
    logger.error("[GAPPERS] %s — el indicador valdrá NaN y sus condiciones no dispararán.", msg)


def _cargar_tabla() -> dict:
    """Carga el parquet UNA vez por proceso: {fecha: {nivel: array(t) sorted}}."""
    global _TABLA
    with _LOCK:
        if _TABLA is not None:
            return _TABLA
        ruta = _ruta_tabla()
        if not os.path.exists(ruta):
            _avisar_una_vez(
                f"no encuentro la tabla ({ruta}). Genera backend/scripts/"
                f"construir_gappers_activos.py y pon GAPPERS_ACTIVE_TABLE")
            _TABLA = {}
            return _TABLA
        try:
            df = pd.read_parquet(ruta)
            out: dict = {}
            for fecha, g in df.groupby("fecha", sort=False):
                por_nivel = {}
                for nivel, gn in g.groupby("nivel"):
                    por_nivel[int(nivel)] = np.sort(gn["t"].to_numpy(dtype=np.float64))
                out[str(fecha)[:10]] = por_nivel
            _TABLA = out
            logger.info("[GAPPERS] tabla cargada: %d fechas (%s)", len(out), ruta)
        except Exception as e:                                # noqa: BLE001
            _avisar_una_vez(f"falló cargar la tabla ({e})")
            _TABLA = {}
        return _TABLA


def serie_gappers_activos(df, daily_stats, gap_pct) -> pd.Series | None:
    """Serie por vela del nº de gappers ya cruzados a +gap_pct %.

    Devuelve None cuando NO se puede calcular (flag apagado, tabla ausente,
    nivel no admitido, fecha sin datos, frame sin fecha) — el caller devuelve
    NaN y las condiciones evalúan False. Nada se rellena en silencio.
    """
    if not gappers_activos_enabled():
        _avisar_una_vez("GAPPERS_ACTIVE_ENABLED no está puesto")
        return None
    try:
        nivel = int(gap_pct) if gap_pct is not None else 50
    except (TypeError, ValueError):
        _avisar_una_vez(f"nivel no numérico ({gap_pct!r})")
        return None
    if nivel not in GAPPERS_ACTIVE_LEVELS:
        _avisar_una_vez(
            f"nivel +{nivel} % no está en la tabla (admitidos: "
            f"{list(GAPPERS_ACTIVE_LEVELS)}). Regenera el script con ese nivel.")
        return None

    fecha = str((daily_stats or {}).get("date") or "")[:10]
    if not fecha or fecha == "NaT":
        return None
    por_nivel = _cargar_tabla().get(fecha)
    if not por_nivel or nivel not in por_nivel:
        # Fecha fuera de la tabla (lago más viejo que la tabla o viceversa):
        # NaN ruidoso, no 0 — un 0 diría "mañana tranquila" sin haberla medido.
        _avisar_una_vez(f"la fecha {fecha} no está en la tabla para nivel {nivel}")
        return None
    cruces = por_nivel[nivel]

    timestamps = pd.to_datetime(df["timestamp"])
    minutos = timestamps.dt.hour.values * 60 + timestamps.dt.minute.values
    # t de la línea continua por vela: PM de hoy; RTH/after (>=09:30) ven el
    # contador FINAL del premarket; antes de las 04:00 no hay línea.
    t = np.where(minutos >= 570, _POST_FIN,
                 np.where(minutos >= 240, minutos.astype(float) + (_PM_T0 - 240),
                          np.nan))
    ok = np.isfinite(t)
    out = np.full(len(minutos), np.nan)
    if ok.any():
        out[ok] = np.searchsorted(cruces, t[ok], side="right")
    return pd.Series(out, index=df.index)
