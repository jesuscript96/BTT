"""Reproducir un día real por el motor de alarmas, sin tocar el WebSocket.

Por qué existe: Massive admite UNA conexión concurrente por API key. Si el
backend de QA y el de producción levantan los dos el live screener con la misma
clave, se expulsan en bucle y ninguno de los dos sirve. Eso deja la rama de QA
sin forma de probar las alarmas de verdad.

Esto lo resuelve: se piden las barras de 1 minuto de un día por REST y se meten
por el MISMO camino que usaría el stream (`SessionBars` → `snapshot()` →
`evaluate()`). Lo que se prueba es el motor real, no una maqueta: mismo anclaje a
las 04:00, mismo VWAP acumulado, mismas EMA, mismo enfriamiento.

NO es un backtest y no debe presentarse como tal. No simula ejecuciones, no
aplica slippage ni comisiones y no calcula rendimiento: solo dice «esta alarma
habría avisado a estas horas y a estos precios». Sigue sin importar nada del
backtester.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

from . import fields as F
from .bars import SessionBars, et_minute_of_day
from .engine import _compute_sizing, _format_message, _in_window, _minutes, _f
from .evaluator import evaluate, mode_of, normalize_conditions

logger = logging.getLogger("btt.alarms.replay")

API_KEY = os.getenv("MASSIVE_API_KEY", "")
REST_BASE = os.getenv("MASSIVE_API_BASE_URL", "https://api.massive.com")


class ReplayError(RuntimeError):
    pass


async def _fetch(client: httpx.AsyncClient, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    r = await client.get(url, params={**params, "apiKey": API_KEY})
    if r.status_code >= 400:
        raise ReplayError(f"Massive respondió {r.status_code} en {url.rsplit('/', 3)[-1]}")
    return r.json()


async def _prev_close(client: httpx.AsyncClient, ticker: str, date: str) -> Optional[float]:
    """Cierre de la sesión anterior. Es la base de `pmh_gap_pct`, o sea del filtro
    de universo de la 1B: sin él la reproducción no puede evaluar el universo."""
    d = datetime.strptime(date, "%Y-%m-%d").date()
    start = (d - timedelta(days=12)).isoformat()
    data = await _fetch(client, f"{REST_BASE}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{date}",
                        {"adjusted": "true", "sort": "asc", "limit": 50})
    prev = None
    for row in data.get("results") or []:
        ts = row.get("t")
        if ts is None:
            continue
        row_date = datetime.utcfromtimestamp(ts / 1000.0).strftime("%Y-%m-%d")
        if row_date >= date:
            break
        prev = _f(row.get("c"))
    return prev


def _instant_from_replay(series: SessionBars, bar: Dict[str, float],
                         prev_close: Optional[float], day_high: float,
                         day_low: float, day_volume: float) -> Dict[str, Optional[float]]:
    """Reconstruye los campos INSTANTÁNEOS desde la propia serie reproducida.

    En vivo salen del estado en RAM del screener; aquí se derivan de las barras
    ya vistas. La clave es que sea CAUSAL: `pmh_gap_pct` usa el máximo de
    premarket acumulado hasta este minuto, no el del día entero — si usara el
    final, la reproducción avisaría a las 5:00 de algo que no se sabía hasta las
    8:00 y no se parecería en nada a lo que hace el motor en vivo."""
    close = bar["close"]
    pm_high = series.pm_high
    return {
        "price": close,
        "change_pct": ((close / prev_close - 1.0) * 100.0) if prev_close else None,
        "volume": day_volume,
        "pmh_gap_pct": ((pm_high / prev_close - 1.0) * 100.0) if (pm_high and prev_close) else None,
        "pre_volume": series.cum_vol if bar["minute"] < 570 else None,
        "pre_high": pm_high,
        "gap_pct": None,          # necesita la apertura RTH; se deja explícito en None
        "prev_close": prev_close,
        "day_high": day_high,
        "day_low": day_low,
        "rvol": None,             # necesita la media de 20 sesiones; fuera de alcance
    }


async def replay_alarm(alarm: Dict[str, Any], ticker: str, date: str,
                       max_signals: int = 50) -> Dict[str, Any]:
    """Reproduce `ticker` en `date` contra una alarma. No entrega nada: devuelve
    lo que HABRÍA avisado."""
    if not API_KEY:
        raise ReplayError("Falta MASSIVE_API_KEY en este entorno.")
    ticker = ticker.strip().upper()

    d = alarm.get("definition") or {}
    conditions = normalize_conditions(d.get("conditions"))
    universe = normalize_conditions(d.get("universe"))
    if not conditions:
        raise ReplayError("La alarma no tiene condiciones.")
    window = d.get("window") or {}
    w_from, w_to = _minutes(window.get("from")), _minutes(window.get("to"))
    cooldown = d.get("cooldown") or {}
    max_per_ticker = int(cooldown.get("max_per_ticker_per_day") or 3)
    min_minutes = float(cooldown.get("min_minutes_between") or 5)
    watchlist = {str(t).upper() for t in (d.get("watchlist") or [])}
    if watchlist and ticker not in watchlist:
        raise ReplayError(f"{ticker} no está en la watchlist de esta alarma.")
    sizing_cfg = d.get("sizing") or {}
    side = alarm.get("side", "long")

    async with httpx.AsyncClient(timeout=30.0) as client:
        prev_close = await _prev_close(client, ticker, date)
        data = await _fetch(client, f"{REST_BASE}/v2/aggs/ticker/{ticker}/range/1/minute/{date}/{date}",
                            {"adjusted": "true", "sort": "asc", "limit": 50000})
    results = data.get("results") or []
    if not results:
        raise ReplayError(f"No hay barras de {ticker} para {date} "
                          "(¿día no bursátil, o ticker sin operaciones?).")

    series = SessionBars(ticker, date)
    signals: List[Dict[str, Any]] = []
    in_universe = not universe          # sin filtro de universo, entra desde el principio
    day_high = day_low = None
    day_volume = 0.0
    fired = 0
    last_minute: Optional[int] = None
    evaluated_bars = 0

    for row in results:
        ts = row.get("t")
        if ts is None:
            continue
        bar = series.ingest(int(ts), _f(row.get("o")), _f(row.get("h")),
                            _f(row.get("l")), _f(row.get("c")), _f(row.get("v")))
        if bar is None:
            continue
        day_high = bar["high"] if day_high is None else max(day_high, bar["high"])
        day_low = bar["low"] if day_low is None else min(day_low, bar["low"])
        day_volume += bar["volume"]
        evaluated_bars += 1

        instant = _instant_from_replay(series, bar, prev_close, day_high, day_low, day_volume)
        ctx = {**instant, **series.snapshot()}
        minute = bar["minute"]

        # Universo pegajoso, igual que en vivo: una vez dentro, dentro todo el día.
        if not in_universe and evaluate(universe, ctx)[0]:
            in_universe = True
        if not in_universe or not _in_window(minute, w_from, w_to):
            continue
        if fired >= max_per_ticker or len(signals) >= max_signals:
            continue
        if last_minute is not None and (minute - last_minute) < min_minutes:
            continue

        ok, reasons = evaluate(conditions, ctx, prev_lookup=series.prev_snapshot_value)
        if not ok:
            continue
        fired += 1
        last_minute = minute
        payload = {
            "alarm_name": alarm.get("name", "Alarma"), "ticker": ticker, "side": side,
            "price": ctx.get("close"), "reasons": reasons,
            "sizing": _compute_sizing(sizing_cfg, side, ctx.get("close"), ctx),
            "fired_minute": f"{minute // 60:02d}:{minute % 60:02d}",
        }
        signals.append({**payload, "message": _format_message(payload)})

    return {
        "ticker": ticker, "date": date, "mode": mode_of(conditions),
        "bars": evaluated_bars, "prev_close": prev_close,
        "entered_universe": in_universe, "signals": signals,
        "note": ("Reproducción del motor de alarmas sobre datos históricos. "
                 "No es un backtest: no simula ejecuciones ni calcula rendimiento."),
    }
