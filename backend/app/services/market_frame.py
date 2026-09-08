"""
Construccion del frame de mercado que consume el motor de estrategias.

Este bloque calcula los niveles de estructura (HOD/LOD, maximos y minimos de
premercado acumulados, Previous Max/Min) y los adjunta al OHLCV del dia. Es el
frame que reciben `translate_strategy` y `simulate`.

POR QUE VIVE AQUI. Estaba escrito dentro de `backtest_service.run_backtest` y
COPIADO tal cual en el bot de senales, fuera del repo. Dos copias que deben dar
lo mismo bit a bit y que nadie compara: tocar una y olvidar la otra no da error,
solo senales distintas semanas despues. Se extrae sin cambiar una linea de la
logica para que ambos llamen al mismo sitio.

OJO — `backtest_signals._compute_signals_for_pair` mantiene su PROPIA version en
numpy puro (camino nativo/paralelo). NO se unifica con esta a proposito: son
implementaciones distintas de la misma formula, y su paridad ya esta verificada
aparte. Fundirlas es un cambio de comportamiento, no una limpieza.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_market_frame(
    day_df: pd.DataFrame,
    ticker: str,
    daily_stats: dict | None = None,
) -> pd.DataFrame:
    """OHLCV del dia + niveles de estructura, listo para el motor.

    `day_df` debe venir ordenado por timestamp y con las columnas
    open/high/low/close/volume/timestamp. `daily_stats` aporta `prev_close` y
    `yesterday_open`; si faltan se cae a la primera barra del dia, igual que
    hacia el backtest.
    """
    return pd.DataFrame(build_market_arrays(day_df, ticker, daily_stats))


def build_market_arrays(
    day_df: pd.DataFrame,
    ticker: str,
    daily_stats: dict | None = None,
) -> dict:
    """Igual que `build_market_frame` pero devuelve el dict de arrays crudo.

    Se expone aparte porque el backtest construia el dict y el DataFrame en dos
    pasos, y libera `day_df` entre medias para no duplicar el dia en memoria.
    """
    daily_stats = daily_stats or {}

    # Compute market structure levels on the full day_df
    high_series = day_df["high"]
    low_series = day_df["low"]
    hod_vals = high_series.cummax().values.astype(np.float64)
    lod_vals = low_series.cummin().values.astype(np.float64)

    # Premarket High/Low
    ts_series = pd.to_datetime(day_df["timestamp"])
    pm_mask = (ts_series.dt.hour * 60 + ts_series.dt.minute >= 4 * 60) & (ts_series.dt.hour * 60 + ts_series.dt.minute < 9 * 60 + 30)
    # PM High/Low ACUMULADOS hasta cada barra (causal). El valor final del día
    # broadcast a todas las barras introducía lookahead en entradas premarket
    # (condiciones PMH/PML y stops de estructura anclados a un máximo futuro).
    # NaN antes de la primera barra PM; tras las 09:30 vale el PM completo.
    # MISMA fórmula numpy que en backtest_signals._compute_signals_for_pair
    # (paridad bit a bit secuencial↔paralelo).
    pm_mask_np = pm_mask.values if hasattr(pm_mask, "values") else np.asarray(pm_mask)
    _h64 = day_df["high"].values.astype(np.float64)
    _l64 = day_df["low"].values.astype(np.float64)
    if pm_mask_np.any():
        pm_highs_vals = np.fmax.accumulate(np.where(pm_mask_np, _h64, np.nan))
        pm_lows_vals = np.fmin.accumulate(np.where(pm_mask_np, _l64, np.nan))
    else:
        pm_highs_vals = np.full(len(day_df), np.nan, dtype=np.float64)
        pm_lows_vals = np.full(len(day_df), np.nan, dtype=np.float64)

    # Previous Max / Previous Min (running high/low shifted by 1 bar)
    prev_highs_vals = pd.Series(hod_vals).shift(1).fillna(high_series.iloc[0] if len(high_series) > 0 else 0.0).values.astype(np.float64)
    prev_lows_vals = pd.Series(lod_vals).shift(1).fillna(low_series.iloc[0] if len(low_series) > 0 else 0.0).values.astype(np.float64)

    # Yesterday's Close from daily_stats (from qualifying_df)
    prev_close_val = daily_stats.get("prev_close")
    if prev_close_val is None or pd.isna(prev_close_val):
        prev_close_val = day_df["close"].iloc[0] if len(day_df) > 0 else np.nan
    prev_closes_vals = np.full(len(day_df), prev_close_val, dtype=np.float64)

    # Yesterday's Open from daily_stats (from qualifying_df)
    yest_open_val = daily_stats.get("yesterday_open", daily_stats.get("lag_rth_open_1"))
    if yest_open_val is None or pd.isna(yest_open_val):
        yest_open_val = day_df["open"].iloc[0] if len(day_df) > 0 else np.nan
    yest_opens_vals = np.full(len(day_df), yest_open_val, dtype=np.float64)

    return {
        "ticker": np.full(len(day_df), ticker, dtype=object),
        "open": day_df["open"].values.astype(np.float64),
        "high": day_df["high"].values.astype(np.float64),
        "low": day_df["low"].values.astype(np.float64),
        "close": day_df["close"].values.astype(np.float64),
        "volume": day_df["volume"].values,
        "timestamp": day_df["timestamp"].values,
        "hod": hod_vals,
        "lod": lod_vals,
        "pm_high": pm_highs_vals,
        "pm_low": pm_lows_vals,
        "prev_high": prev_highs_vals,
        "prev_low": prev_lows_vals,
        "prev_close": prev_closes_vals,
        "yesterday_open": yest_opens_vals,
    }
