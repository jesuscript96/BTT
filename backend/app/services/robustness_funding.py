"""Probabilidad de superar una prueba de fondeo, sobre el bootstrap de la estrategia.

La pregunta que responde no es "cuanto gana esta estrategia" sino "que fraccion
de historias alternativas habria SUPERADO el challenge sin saltarse ninguna
regla". Son cosas distintas: una estrategia rentable a un año puede suspender la
mayoria de los challenges si por el camino tiene un dia malo que rompe el limite
diario.

Por que no vale mirar el drawdown maximo y el retorno final por separado
------------------------------------------------------------------------
Porque el orden importa. Si en la sesion 8 revientas el limite de perdida
diaria, la prueba termina ahi: da igual que esa misma simulacion acabase el año
un 40% arriba. Hay que recorrer cada camino en orden y parar en el primer
evento. Eso es lo que hace `_evaluar`.

Reglas implementadas (las eligio el usuario el 2026-08-24)
----------------------------------------------------------
* **Perdida diaria**: se mide contra el balance de APERTURA de cada sesion. El
  limite es una cantidad fija derivada de la cuenta base, no del balance vivo.
* **Drawdown**: TRAILING desde el maximo de equity alcanzado. El suelo sube
  contigo.
* **Objetivo**: alcanzar un % de beneficio sobre la cuenta base, y ademas haber
  cumplido los minimos de sesiones y de operaciones.
* **Plazo**: opcional. Sin plazo se simulan tantas sesiones como tenia el
  histórico; con plazo se simulan exactamente las sesiones del plazo (el
  bootstrap con reemplazo permite extraer mas pasos de los que hubo).

Dos lecturas del mismo challenge
--------------------------------
* **CIERRE**: solo mira el PnL con el que cierra cada sesion. Es la lectura
  limpia y la que los datos soportan exactamente.
* **MAE**: tiene en cuenta ademas lo que la sesion llego a perder EN VIVO en su
  peor momento (Maximum Adverse Excursion). Es una COTA PESIMISTA —supone que
  todas las operaciones del dia tocaron su peor punto a la vez— y sirve para ver
  cuantos challenges se habrian caido por un susto intradia que luego se
  recupero antes del cierre. No es una medida exacta y asi hay que presentarla.

Empates: si el mismo dia rompe una regla y alcanza el objetivo, gana la rotura.
En vivo el limite salta en el momento, no al cierre.
"""
from __future__ import annotations

import numpy as np

_CHUNK_MAX_CELLS = 8_000_000


def _first_true(mask: np.ndarray) -> np.ndarray:
    """Indice del primer True de cada fila; el ancho de la fila si no hay ninguno."""
    n = mask.shape[1]
    hit = mask.any(axis=1)
    return np.where(hit, mask.argmax(axis=1), n)


def _pct(count: int, total: int) -> float:
    return round(float(count) / total * 100.0, 2) if total else 0.0


def _quantiles(x: np.ndarray) -> dict:
    if x.size == 0:
        return {"n": 0}
    return {
        "n": int(x.size),
        "p25": int(np.percentile(x, 25)),
        "p50": int(np.percentile(x, 50)),
        "p75": int(np.percentile(x, 75)),
        "min": int(x.min()),
        "max": int(x.max()),
    }


def _evaluar(
    curves: np.ndarray,
    cum_trades: np.ndarray,
    mae_frac: np.ndarray | None,
    *,
    limit_usd: float,
    dd_value: float,
    dd_basis: str,
    target_usd: float,
    min_trading_days: int,
    min_trades: int,
) -> dict:
    """Recorre cada camino y devuelve el indice del primer evento de cada tipo.

    Trabaja en "espacio de pasos": el paso j va del cierre j al cierre j+1, o
    sea `curves[:, j]` -> `curves[:, j+1]`.
    """
    opens = curves[:, :-1]
    closes = curves[:, 1:]
    steps = closes - opens

    # ── Perdida diaria, contra la apertura del dia ────────────────────────
    perdida_cierre = -steps                      # positiva cuando el dia pierde
    if mae_frac is None:
        perdida_dia = perdida_cierre
        lows = closes
    else:
        # Peor punto intradia: la apertura menos la excursion adversa. La
        # perdida que cuenta es la mayor de las dos (cierre o intradia).
        excursion = opens * mae_frac
        perdida_dia = np.maximum(perdida_cierre, excursion)
        lows = np.minimum(closes, opens - excursion)

    i_daily = _first_true(perdida_dia >= limit_usd)

    # ── Drawdown trailing desde el maximo ─────────────────────────────────
    # El maximo se toma sobre los CIERRES (incluida la apertura de la cuenta):
    # un pico intradia que no se consolida no sube el suelo en ninguna firma.
    run_max = np.maximum.accumulate(curves, axis=1)[:, 1:]
    if dd_basis == "fixed":
        floor = run_max - dd_value
    else:
        floor = run_max * (1.0 - dd_value / 100.0)
    i_dd = _first_true(lows < floor)

    # ── Objetivo alcanzado, con los minimos cumplidos ─────────────────────
    n = closes.shape[1]
    sesiones = np.arange(1, n + 1)[None, :]
    ok = (closes >= target_usd) & (sesiones >= min_trading_days) & (cum_trades >= min_trades)
    i_target = _first_true(ok)

    return {"daily": i_daily, "dd": i_dd, "target": i_target, "n": n}


def _resumen(ev: dict, finals: np.ndarray, account: float, sims: int) -> dict:
    d, dd, t, n = ev["daily"], ev["dd"], ev["target"], ev["n"]

    # Empates a favor de la rotura: en vivo el limite salta antes del cierre.
    primera_rotura = np.minimum(d, dd)
    aprueba = t < primera_rotura
    rompe_daily = ~aprueba & (d < n) & (d <= dd)
    rompe_dd = ~aprueba & (dd < n) & (dd < d)
    sin_resolver = ~aprueba & ~rompe_daily & ~rompe_dd

    dias_hasta_pasar = (t[aprueba] + 1).astype(np.int64)
    dia_de_rotura = (primera_rotura[rompe_daily | rompe_dd] + 1).astype(np.int64)

    return {
        "pass_pct": _pct(int(aprueba.sum()), sims),
        "fail_daily_pct": _pct(int(rompe_daily.sum()), sims),
        "fail_dd_pct": _pct(int(rompe_dd.sum()), sims),
        "unresolved_pct": _pct(int(sin_resolver.sum()), sims),
        "sessions_to_pass": _quantiles(dias_hasta_pasar),
        "session_of_breach": _quantiles(dia_de_rotura),
        "final_return_pct": {
            "p5": round(float(np.percentile(finals, 5) / account - 1) * 100, 2),
            "p50": round(float(np.percentile(finals, 50) / account - 1) * 100, 2),
            "p95": round(float(np.percentile(finals, 95) / account - 1) * 100, 2),
        },
    }


def run_funding(
    values: list[float],
    *,
    mae_fracs: list[float] | None = None,
    trades_per_day: list[int] | None = None,
    account: float = 25_000.0,
    risk_pct: float = 3.0,
    mode: str = "compound",
    target_pct: float = 8.0,
    daily_loss_pct: float = 2.0,
    max_dd_pct: float = 6.0,
    dd_basis: str = "percent",
    min_trading_days: int = 0,
    min_trades: int = 0,
    horizon_days: int | None = None,
    simulations: int = 5000,
    seed: int | None = None,
    # Capital con el que se corrio el backtest del que salen `values`. Solo se
    # usa en ADITIVO, para reescalar. Ver el bloque de `escala` mas abajo.
    values_base_cash: float | None = None,
) -> dict:
    """Fraccion de historias alternativas que habrian superado el challenge."""
    arr = np.asarray([v for v in values if v is not None], dtype=np.float64)
    n_hist = int(arr.size)
    if n_hist == 0:
        raise ValueError("La estrategia no tiene sesiones utilizables")
    if account <= 0:
        raise ValueError("La cuenta base tiene que ser mayor que cero")

    mae = None
    if mae_fracs is not None and len(mae_fracs) == n_hist:
        # Se sanea: negativo no tiene sentido y >1 vaciaria la cuenta en un dia.
        mae = np.clip(np.asarray(mae_fracs, dtype=np.float64), 0.0, 0.95)

    counts = (
        np.asarray(trades_per_day, dtype=np.int64)
        if trades_per_day is not None and len(trades_per_day) == n_hist
        else np.ones(n_hist, dtype=np.int64)
    )

    sims = max(10, min(int(simulations), 50_000))
    # Sin plazo se simula la longitud del histórico. Con plazo, exactamente el
    # plazo: el bootstrap con reemplazo puede extraer mas pasos de los que hubo.
    n_steps = int(horizon_days) if horizon_days and horizon_days > 0 else n_hist
    n_steps = max(1, min(n_steps, 5_000))

    rng = np.random.default_rng(seed)
    compound = mode == "compound"
    risk_frac = risk_pct / 100.0

    # ── Reescalado de la serie en ADITIVO ─────────────────────────────────
    # En aditivo `values` son PnL en DOLARES, y esos dolares salen del capital
    # con el que se corrio el backtest. Cambiar `account` sin tocarlos simulaba
    # una cuenta de X moviendose como si operase Y: las reglas (que son % de la
    # cuenta) se encogian pero el tamaño de las apuestas no, asi que el numero
    # de la casilla movia el resultado sin significar nada (0,7% con 25.000 y
    # 24,1% con 100.000 sobre la MISMA serie).
    #
    # En compuesto no hace falta: los R-multiplos son proporciones y escalan
    # solos. `mae_fracs` tampoco se toca — son fracciones de la apertura.
    escala = 1.0
    if not compound and values_base_cash and values_base_cash > 0:
        escala = account / float(values_base_cash)
        if escala != 1.0:
            arr = arr * escala

    limit_usd = account * daily_loss_pct / 100.0
    target_usd = account * (1.0 + target_pct / 100.0)
    dd_value = max_dd_pct if dd_basis != "fixed" else account * max_dd_pct / 100.0

    acc: dict[str, list] = {"closed": [], "mae": []}
    finals = np.empty(sims, dtype=np.float64)

    chunk = max(1, min(sims, _CHUNK_MAX_CELLS // max(1, n_steps + 1)))
    done = 0
    while done < sims:
        m = min(chunk, sims - done)
        idx = rng.integers(0, n_hist, size=(m, n_steps))
        draws = arr[idx]

        curves = np.empty((m, n_steps + 1), dtype=np.float64)
        curves[:, 0] = account
        if compound:
            factors = np.clip(1.0 + draws * risk_frac, 1e-6, None)
            curves[:, 1:] = account * np.cumprod(factors, axis=1)
        else:
            curves[:, 1:] = account + np.cumsum(draws, axis=1)

        finals[done:done + m] = curves[:, -1]
        cum_trades = np.cumsum(counts[idx], axis=1)

        comun = dict(
            limit_usd=limit_usd, dd_value=dd_value, dd_basis=dd_basis,
            target_usd=target_usd, min_trading_days=min_trading_days,
            min_trades=min_trades,
        )
        acc["closed"].append(_evaluar(curves, cum_trades, None, **comun))
        if mae is not None:
            acc["mae"].append(_evaluar(curves, cum_trades, mae[idx], **comun))

        del curves, draws, idx, cum_trades
        done += m

    def junta(parts: list[dict]) -> dict | None:
        if not parts:
            return None
        ev = {
            "daily": np.concatenate([p["daily"] for p in parts]),
            "dd": np.concatenate([p["dd"] for p in parts]),
            "target": np.concatenate([p["target"] for p in parts]),
            "n": parts[0]["n"],
        }
        return _resumen(ev, finals, account, sims)

    return {
        "simulations": sims,
        "account": account,
        "n_steps": n_steps,
        "history_days": n_hist,
        "mode": "compound" if compound else "additive",
        "risk_pct": risk_pct,
        # Factor aplicado a la serie en aditivo (1 = sin reescalar). Se expone
        # para que la interfaz pueda decir que los dolares NO son los del
        # backtest, sino los de la cuenta que se esta simulando.
        "scale": round(escala, 6),
        "values_base_cash": round(float(values_base_cash), 2) if values_base_cash else None,
        "rules": {
            "target_pct": target_pct,
            "target_usd": round(target_usd - account, 2),
            "daily_loss_pct": daily_loss_pct,
            "daily_loss_usd": round(limit_usd, 2),
            "max_dd_pct": max_dd_pct,
            "dd_basis": dd_basis,
            "dd_usd_at_start": round(account * max_dd_pct / 100.0, 2),
            "min_trading_days": min_trading_days,
            "min_trades": min_trades,
            "horizon_days": int(horizon_days) if horizon_days and horizon_days > 0 else None,
        },
        "closed": junta(acc["closed"]),
        "mae": junta(acc["mae"]),
    }
