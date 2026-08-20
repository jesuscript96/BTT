"""Monte Carlo sobre el histórico de trades de una estrategia guardada.

Por que no se reutiliza `montecarlo_service.run_montecarlo`:

  1. Solo hace PERMUTACION (baraja los mismos trades sin reemplazo). Eso mide
     el efecto del ORDEN, pero no el error muestral: todas las simulaciones
     terminan en el mismo balance final, asi que la distribucion de resultados
     finales es un punto y la "probabilidad de acabar perdiendo" sale 0 o 100
     por construccion. El bootstrap (con reemplazo) es el que responde a "y si
     me hubieran tocado OTROS trades de la misma distribucion".
  2. Suma PnL en DOLARES. Eso solo vale si el tamaño de posicion es fijo. Con
     `risk_type=PERCENT` —lo que usa la estrategia de esta casa— cada trade
     arriesga un % del capital VIVO, asi que el PnL en dolares de un trade
     depende del balance que hubiera en ese momento. Barajar dolares rompe ese
     vinculo y produce disparates: en pruebas daba drawdowns de -194%, imposible
     salvo que la equity cruce el cero.
  3. Corre un bucle Python por simulacion. Aqui se vectoriza con numpy.

Modelos disponibles:
  - COMPUESTO (`mode="compound"`): remuestrea R-multiplos y recompone
    `equity *= (1 + R * riesgo%)`. Es lo que hizo el backtest de verdad.
    Verificado contra la corrida real: recomponer los 3.544 R-multiplos
    guardados devuelve 67.926 $ frente a los 68.167 $ reales (0,35% de desvio,
    atribuible al redondeo de r_multiple a dos decimales).
  - ADITIVO (`mode="additive"`): suma PnL en dolares. Correcto solo con tamaño
    de posicion fijo.
"""
from __future__ import annotations

import numpy as np

# Las metricas escalares (balance final, drawdown maximo) se acumulan sobre
# TODAS las simulaciones: son vectores 1D y cuestan nada.
#
# Las bandas por paso, en cambio, necesitan las curvas completas a la vez: una
# matriz densa sims x trades. Con 10.000 x 3.500 serian 280 MB en una maquina de
# 16 GB que ya tiene abierta una base de 62 GB. Asi que las bandas salen de una
# SUBMUESTRA acotada: con 1.500 trayectorias los percentiles ya son lisos y el
# error es despreciable frente al ancho de las propias bandas.
_BANDS_MAX_CURVES = 1500
_CHUNK_MAX_CELLS = 8_000_000


def _max_drawdowns(curves: np.ndarray) -> np.ndarray:
    """Drawdown maximo (%) de cada fila, vectorizado."""
    running_max = np.maximum.accumulate(curves, axis=1)
    safe = np.where(running_max > 0, running_max, 1.0)
    return ((curves - running_max) / safe).min(axis=1) * 100.0


def _draw(rng, arr: np.ndarray, m: int, n: int, bootstrap: bool) -> np.ndarray:
    """m x n muestras: con reemplazo (bootstrap) o barajando (permutacion)."""
    if bootstrap:
        return rng.choice(arr, size=(m, n), replace=True)
    # Permutacion vectorizada: ordenar ruido da una permutacion por fila, y
    # evita el bucle Python que hacia lento al servicio original.
    return arr[np.argsort(rng.random((m, n)), axis=1)]


def _curves_from(draws: np.ndarray, init_cash: float, compound: bool, risk_frac: float) -> np.ndarray:
    """Convierte una matriz de muestras en curvas de equity."""
    m, n = draws.shape
    curves = np.empty((m, n + 1), dtype=np.float64)
    curves[:, 0] = init_cash
    if compound:
        # draws son R-multiplos: cada trade mueve el capital un R * riesgo%.
        # El clip evita que un R absurdo genere un factor negativo (ruina
        # instantanea con equity < 0, que no existe: el broker cierra antes).
        factors = np.clip(1.0 + draws * risk_frac, 1e-6, None)
        curves[:, 1:] = init_cash * np.cumprod(factors, axis=1)
    else:
        curves[:, 1:] = init_cash + np.cumsum(draws, axis=1)
    return curves


def _safe_hist(x: np.ndarray, bins: int = 40) -> dict:
    """Histograma que no revienta cuando todos los valores son identicos.

    Pasa en modo permutacion: el balance final es el mismo en todas las
    simulaciones, el rango es cero y np.histogram lanza "Too many bins".
    """
    lo, hi = float(np.min(x)), float(np.max(x))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-9:
        pad = max(abs(lo) * 0.01, 1.0)
        counts, edges = np.histogram(x, bins=3, range=(lo - pad, hi + pad))
    else:
        counts, edges = np.histogram(x, bins=bins)
    return {"counts": counts.tolist(), "edges": np.round(edges, 2).tolist()}


def run_bootstrap(
    values: list[float],
    *,
    init_cash: float = 10000.0,
    simulations: int = 2000,
    method: str = "bootstrap",
    mode: str = "compound",
    risk_pct: float = 3.0,
    ruin_pct: float = 50.0,
    seed: int | None = None,
) -> dict:
    """Remuestrea el histórico y describe el abanico de resultados.

    `values` son R-multiplos si mode="compound", o PnL en dolares si
    mode="additive".
    """
    arr = np.asarray([v for v in values if v is not None], dtype=np.float64)
    n = int(arr.size)
    if n == 0:
        raise ValueError("La estrategia no tiene trades utilizables")

    sims = max(10, min(int(simulations), 50_000))
    rng = np.random.default_rng(seed)
    is_bootstrap = method != "permutacion"
    compound = mode == "compound"
    risk_frac = risk_pct / 100.0

    finals = np.empty(sims, dtype=np.float64)
    maxdds = np.empty(sims, dtype=np.float64)
    ruined = 0
    ruin_level = init_cash * (1.0 - ruin_pct / 100.0)

    n_band = min(sims, _BANDS_MAX_CURVES)
    band_curves = np.empty((n_band, n + 1), dtype=np.float64)
    band_kept = 0

    chunk = max(1, min(sims, _CHUNK_MAX_CELLS // max(1, n + 1)))
    done = 0
    while done < sims:
        m = min(chunk, sims - done)
        curves = _curves_from(_draw(rng, arr, m, n, is_bootstrap), init_cash, compound, risk_frac)

        finals[done:done + m] = curves[:, -1]
        maxdds[done:done + m] = _max_drawdowns(curves)
        ruined += int(np.count_nonzero(curves.min(axis=1) <= ruin_level))

        if band_kept < n_band:
            take = min(n_band - band_kept, m)
            band_curves[band_kept:band_kept + take] = curves[:take]
            band_kept += take

        del curves
        done += m

    band_curves = band_curves[:band_kept]
    # Los drawdowns de la submuestra guardada, en el MISMO orden: band_curves se
    # rellena desde el principio de la iteracion, asi que sus drawdowns son los
    # primeros de `maxdds`.
    band_dds = maxdds[:band_kept]

    bands = {
        f"p{p}": np.percentile(band_curves, p, axis=0).round(2).tolist()
        for p in (5, 25, 50, 75, 95)
    }
    spaghetti = band_curves[: min(120, band_kept)].round(2).tolist()

    base_curve = _curves_from(arr[None, :], init_cash, compound, risk_frac)[0]
    base_final = float(base_curve[-1])

    dd_paths = _representative_dd_paths(band_curves, band_dds, maxdds, base_curve)

    def p(a: np.ndarray, q: float) -> float:
        return round(float(np.percentile(a, q)), 2)

    return {
        "method": "bootstrap" if is_bootstrap else "permutacion",
        "mode": "compound" if compound else "additive",
        "risk_pct": risk_pct,
        "simulations": sims,
        "n_trades": n,
        "init_cash": init_cash,
        "bands_from": band_kept,
        # Curva real reconstruida con el MISMO modelo, para que la comparacion
        # con el abanico sea limpia (si no, se compararian dos cosas distintas).
        "base_curve": base_curve.round(2).tolist(),
        "base_final": round(base_final, 2),
        "base_return_pct": round((base_final / init_cash - 1) * 100, 2),
        "base_max_drawdown": round(float(_max_drawdowns(base_curve[None, :])[0]), 2),
        "spaghetti": spaghetti,
        "bands": bands,
        "final_balance": {
            "p5": p(finals, 5), "p25": p(finals, 25), "p50": p(finals, 50),
            "p75": p(finals, 75), "p95": p(finals, 95),
            "mean": round(float(finals.mean()), 2),
            "min": round(float(finals.min()), 2),
            "max": round(float(finals.max()), 2),
        },
        "return_pct": {
            "p5": round((p(finals, 5) / init_cash - 1) * 100, 2),
            "p50": round((p(finals, 50) / init_cash - 1) * 100, 2),
            "p95": round((p(finals, 95) / init_cash - 1) * 100, 2),
        },
        # Ojo con el sentido: el drawdown es negativo, asi que el percentil 5 es
        # el escenario MALO y el 95 el benigno.
        "drawdown": {
            "p5": p(maxdds, 5), "p25": p(maxdds, 25), "p50": p(maxdds, 50),
            "p75": p(maxdds, 75), "p95": p(maxdds, 95),
            "worst": round(float(maxdds.min()), 2),
            "mean": round(float(maxdds.mean()), 2),
        },
        # La pregunta util: cuanto DD hay que estar dispuesto a tragar para que
        # solo el 5% (o el 1%) de los escenarios lo superen.
        "dd_tolerance": {"p95": p(maxdds, 5), "p99": p(maxdds, 1)},
        "prob_losing_pct": round(float(np.count_nonzero(finals < init_cash) / sims) * 100, 2),
        "prob_ruin_pct": round(float(ruined / sims) * 100, 2),
        "ruin_pct_threshold": ruin_pct,
        "hist_final": _safe_hist(finals),
        "hist_drawdown": _safe_hist(maxdds),
        "dd_paths": dd_paths,
    }


def _underwater(curve: np.ndarray) -> np.ndarray:
    """Serie 'bajo el agua': distancia al maximo previo, en %."""
    run_max = np.maximum.accumulate(curve)
    return (curve - run_max) / np.where(run_max > 0, run_max, 1.0) * 100.0


def _representative_dd_paths(
    band_curves: np.ndarray,
    band_dds: np.ndarray,
    all_dds: np.ndarray,
    base_curve: np.ndarray,
) -> dict:
    """Curvas de drawdown de escenarios representativos, para superponerlas.

    Los percentiles sueltos (-30,1%, -36,1%) dicen CUANTO, pero no COMO: si esa
    caida llega de golpe o se arrastra medio año. Aqui se eligen simulaciones
    concretas cuyo drawdown maximo cae lo mas cerca posible de cada percentil y
    se devuelve su recorrido entero, para poder compararlo con el real.

    Las candidatas salen de la submuestra que ya se guardaba para las bandas
    (hasta 1.500 trayectorias), no de las 5.000+: es una muestra aleatoria de la
    misma distribucion, asi que contiene escenarios cerca de cualquier
    percentil, y evita tener que conservar todas las curvas en memoria.
    """
    if band_curves.size == 0:
        return {}

    def closest(target: float) -> list[float]:
        idx = int(np.argmin(np.abs(band_dds - target)))
        return _underwater(band_curves[idx]).round(3).tolist()

    p50 = float(np.percentile(all_dds, 50))
    p95 = float(np.percentile(all_dds, 5))   # el que solo 1 de cada 20 supera
    p99 = float(np.percentile(all_dds, 1))   # el que solo 1 de cada 100 supera

    return {
        "real": _underwater(base_curve).round(3).tolist(),
        "p50": closest(p50),
        "p95": closest(p95),
        "p99": closest(p99),
        "levels": {
            "real": round(float(_underwater(base_curve).min()), 2),
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
        },
    }
