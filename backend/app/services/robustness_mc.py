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
    # Los no finitos se APARTAN antes de mirar nada. Con interes compuesto una
    # trayectoria muy buena puede desbordar la equity a +inf, y el plan B de
    # abajo tambien reventaba porque calculaba `lo - pad` sobre ese inf.
    x = np.asarray(x, dtype=np.float64)
    finitos = x[np.isfinite(x)]
    if finitos.size == 0:
        return {"counts": [0], "edges": [0.0, 1.0]}

    lo, hi = float(finitos.min()), float(finitos.max())
    # El umbral es RELATIVO a la magnitud, no absoluto. numpy no falla porque el
    # rango sea cero, sino cuando el ancho de bin cae por debajo del espaciado
    # del float a esa magnitud: un rango de 1.000 sobre valores de 1e18 pasaba
    # el `hi - lo < 1e-9` de antes y explotaba igual ("Too many bins for data
    # range").
    escala = max(abs(lo), abs(hi), 1.0)
    if hi - lo <= escala * 1e-12:
        pad = escala * 0.01
        counts, edges = np.histogram(finitos, bins=3, range=(lo - pad, hi + pad))
    else:
        try:
            counts, edges = np.histogram(finitos, bins=bins)
        except ValueError:
            # Red de seguridad: donde no caben 40 bins, 3 siempre caben. Mas
            # vale un histograma basto que tumbar el Monte Carlo entero.
            counts, edges = np.histogram(finitos, bins=3)
    return {"counts": counts.tolist(), "edges": np.round(edges, 2).tolist()}


_GRID_Q = 501  # puntos de la rejilla de cuantiles que viaja al navegador


def _grid(x: np.ndarray, decimals: int = 2) -> list[float]:
    """La ECDF comprimida: cuantiles equiespaciados de 0 a 100.

    Con esto el navegador contesta "¿que probabilidad hay de perder X?" por
    interpolacion, sin volver a pedir nada al servidor cada vez que se mueve un
    slider. 501 puntos dan una resolucion de 0,2 puntos porcentuales —de sobra
    para lo que se pregunta aqui— y ocupan 4 KB en vez de los 400 KB que
    costaria mandar 50.000 simulaciones.
    """
    qs = np.linspace(0.0, 100.0, _GRID_Q)
    return np.percentile(x, qs).round(decimals).tolist()


def _max_losing_run(neg: np.ndarray) -> np.ndarray:
    """Racha maxima de pasos negativos consecutivos, por fila.

    El bucle es sobre COLUMNAS (n pasos), no sobre filas: cada iteracion es una
    operacion vectorizada sobre las m simulaciones a la vez. Con n del orden de
    mil y m de unos miles, son mil operaciones numpy, no millones en Python.
    """
    m, n = neg.shape
    acc = np.zeros(m, dtype=np.int32)
    best = np.zeros(m, dtype=np.int32)
    for j in range(n):
        acc = np.where(neg[:, j], acc + 1, 0)
        best = np.maximum(best, acc)
    return best


def _streak_histogram(runs: np.ndarray) -> list[dict]:
    """Cuantas simulaciones tuvieron cada longitud de racha perdedora maxima."""
    if runs.size == 0:
        return []
    top = int(runs.max())
    counts = np.bincount(runs, minlength=top + 1)
    return [{"length": int(i), "count": int(c)} for i, c in enumerate(counts) if c and i > 0]


def _describe(x: np.ndarray) -> dict:
    """Resumen de una muestra: media, mediana y los percentiles utiles."""
    if x.size == 0:
        return {"n": 0, "mean": 0.0, "median": 0.0, "p5": 0.0, "p25": 0.0,
                "p75": 0.0, "p95": 0.0, "worst": 0.0, "best": 0.0}
    return {
        "n": int(x.size),
        "mean": round(float(x.mean()), 2),
        "median": round(float(np.median(x)), 2),
        "p5": round(float(np.percentile(x, 5)), 2),
        "p25": round(float(np.percentile(x, 25)), 2),
        "p75": round(float(np.percentile(x, 75)), 2),
        "p95": round(float(np.percentile(x, 95)), 2),
        "worst": round(float(x.min()), 2),
        "best": round(float(x.max()), 2),
    }


def run_bootstrap(
    values: list[float],
    *,
    init_cash: float = 10000.0,
    simulations: int = 2000,
    method: str = "bootstrap",
    mode: str = "compound",
    risk_pct: float = 3.0,
    ruin_pct: float = 50.0,
    unit: str = "day",
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
    # Peor paso de cada simulacion. Un "paso" es la unidad que se remuestrea:
    # una SESION si el frontend manda valores por dia (lo normal), o un trade si
    # manda valores por trade. En $ y en % del capital con el que arranco ese
    # paso — en modo compuesto las dos cosas no son intercambiables, porque el
    # mismo % duele mas dolares cuanto mayor sea la cuenta.
    worst_step = np.empty(sims, dtype=np.float64)
    worst_step_pct = np.empty(sims, dtype=np.float64)
    lose_runs = np.empty(sims, dtype=np.int32)
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

        # PnL de cada paso y su peor caso, sobre TODAS las simulaciones: son
        # vectores 1D y las colas es justo donde esta la informacion util.
        steps = np.diff(curves, axis=1)
        opens = curves[:, :-1]
        worst_step[done:done + m] = steps.min(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            steps_pct = np.where(opens > 0, steps / opens, 0.0) * 100.0
        worst_step_pct[done:done + m] = steps_pct.min(axis=1)
        lose_runs[done:done + m] = _max_losing_run(steps < 0)
        del steps, opens, steps_pct

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
    losses = _loss_block(band_curves, worst_step, worst_step_pct, lose_runs, maxdds, unit)

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
        "losses": losses,
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


def _loss_block(
    band_curves: np.ndarray,
    worst_step: np.ndarray,
    worst_step_pct: np.ndarray,
    lose_runs: np.ndarray,
    maxdds: np.ndarray,
    unit: str,
) -> dict:
    """Perdidas paso a paso y las rejillas para preguntar probabilidades.

    Dos familias de numeros que NO significan lo mismo y que la interfaz debe
    separar sin ambiguedad:

    * `step_*` describe UN paso cualquiera (una sesion, o un trade). Responde a
      "¿que suele pasar en un dia?" y a "¿que probabilidad hay de que UN dia
      cualquiera pierda mas de X?".
    * `worst_*` describe el PEOR paso de cada simulacion completa. Responde a
      "¿que probabilidad hay de que EN ALGUN MOMENTO de la corrida haya un dia
      que pierda mas de X?". Esta segunda cifra siempre es mucho mayor, y es la
      que importa para un limite de perdida diaria: basta con romperlo una vez.

    Los estadisticos agregados de paso salen de la submuestra de curvas que ya
    se guardaba para las bandas (hasta 1.500 trayectorias). Es una muestra
    aleatoria de la misma distribucion y evita tener que retener en memoria
    todas las simulaciones. Los extremos por simulacion, en cambio, se acumulan
    sobre TODAS: las colas son justo lo que se esta midiendo.
    """
    if band_curves.size == 0:
        return {}

    steps = np.diff(band_curves, axis=1)
    opens = band_curves[:, :-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        steps_pct = np.where(opens > 0, steps / opens, 0.0) * 100.0

    flat = steps.ravel()
    flat_pct = steps_pct.ravel()
    wins = flat[flat > 0]
    losses_only = flat[flat < 0]
    wins_pct = flat_pct[flat_pct > 0]
    losses_pct = flat_pct[flat_pct < 0]

    total = int(flat.size)
    return {
        "unit": "trade" if unit == "trade" else "day",
        "sampled_curves": int(band_curves.shape[0]),
        "sampled_steps": total,
        # Un paso cualquiera
        "step_usd": _describe(flat),
        "step_pct": _describe(flat_pct),
        "win_usd": _describe(wins),
        "loss_usd": _describe(losses_only),
        "win_pct": _describe(wins_pct),
        "loss_pct": _describe(losses_pct),
        "win_rate_pct": round(float(wins.size / total * 100.0), 2) if total else 0.0,
        # El peor paso de cada simulacion
        "worst_step_usd": _describe(worst_step),
        "worst_step_pct": _describe(worst_step_pct),
        # Racha de pasos perdedores seguidos
        "streak": {
            "median": int(np.median(lose_runs)),
            "p95": int(np.percentile(lose_runs, 95)),
            "p99": int(np.percentile(lose_runs, 99)),
            "worst": int(lose_runs.max()),
            "mean": round(float(lose_runs.mean()), 2),
            "histogram": _streak_histogram(lose_runs),
        },
        # Rejillas de cuantiles: con estas el navegador resuelve cualquier
        # umbral por interpolacion, sin volver a simular al mover un slider.
        "grids": {
            "step_usd": _grid(flat),
            "step_pct": _grid(flat_pct, 3),
            "worst_step_usd": _grid(worst_step),
            "worst_step_pct": _grid(worst_step_pct, 3),
            "max_dd_pct": _grid(maxdds),
        },
    }


def run_horizon(
    values: list[float],
    *,
    init_cash: float = 10000.0,
    simulations: int = 5000,
    mode: str = "compound",
    risk_pct: float = 3.0,
    ruin_pct: float = 50.0,
    target_pct: float = 8.0,
    max_days: int = 120,
    seed: int | None = None,
) -> dict:
    """Probabilidad ACUMULADA de tocar la ruina o el objetivo dentro de X pasos.

    Contesta lo que `run_bootstrap` no puede: alli el horizonte es fijo (el
    largo del historico) y solo se conoce el desenlace al final del todo, asi
    que su `prob_ruin_pct` es "en algun momento de los ~N dias que duro el
    backtest". Aqui el horizonte es la VARIABLE, y la respuesta es una curva:
    para cada dia 1..D, que porcentaje de trayectorias ya habia tocado el
    nivel.

    Siempre remuestrea CON REEMPLAZO. El estudio mira hacia adelante y el
    horizonte puede superar el historico; una permutacion, que solo reordena lo
    que ya paso, no puede alargarse mas alla de su propio tamaño.
    """
    arr = np.asarray([v for v in values if v is not None], dtype=np.float64)
    n = int(arr.size)
    if n == 0:
        raise ValueError("La estrategia no tiene trades utilizables")

    dias = max(1, min(int(max_days), 2000))
    sims = max(100, min(int(simulations), 50_000))
    rng = np.random.default_rng(seed)
    compound = mode == "compound"
    risk_frac = risk_pct / 100.0

    ruin_level = init_cash * (1.0 - ruin_pct / 100.0)
    target_level = init_cash * (1.0 + target_pct / 100.0)

    # Histograma del PRIMER paso en que se toca cada nivel; acumulandolo sale la
    # curva entera sin tener que guardar una matriz sims x dias completa.
    first_ruin = np.zeros(dias + 2, dtype=np.int64)
    first_target = np.zeros(dias + 2, dtype=np.int64)
    # Objetivo alcanzado ANTES de arruinarse: es el numero que de verdad importa
    # para una prueba de fondeo, porque llegar al objetivo con la cuenta ya
    # reventada no la aprueba.
    first_target_alive = np.zeros(dias + 2, dtype=np.int64)

    chunk = max(1, min(sims, _CHUNK_MAX_CELLS // (dias + 1)))
    done = 0
    while done < sims:
        m = min(chunk, sims - done)
        curves = _curves_from(_draw(rng, arr, m, dias, True), init_cash, compound, risk_frac)
        pasos = curves[:, 1:]          # la columna 0 es el capital inicial

        hit_r = pasos <= ruin_level
        hit_t = pasos >= target_level
        any_r = hit_r.any(axis=1)
        any_t = hit_t.any(axis=1)
        # argmax sobre booleanos da el primer True. El +1 lleva el indice de
        # columna al numero de dia; las que no tocan van a `dias + 1`, fuera de
        # la curva, para que no cuenten en ningun acumulado.
        day_r = np.where(any_r, hit_r.argmax(axis=1) + 1, dias + 1)
        day_t = np.where(any_t, hit_t.argmax(axis=1) + 1, dias + 1)

        first_ruin += np.bincount(day_r[any_r], minlength=dias + 2)[: dias + 2]
        first_target += np.bincount(day_t[any_t], minlength=dias + 2)[: dias + 2]
        vivas = any_t & (day_t < day_r)
        first_target_alive += np.bincount(day_t[vivas], minlength=dias + 2)[: dias + 2]

        done += m

    def acumulada(h: np.ndarray) -> list[float]:
        return (np.cumsum(h[1:dias + 1]) / sims * 100.0).round(2).tolist()

    return {
        "days": list(range(1, dias + 1)),
        "prob_ruin_pct": acumulada(first_ruin),
        "prob_target_pct": acumulada(first_target),
        "prob_target_alive_pct": acumulada(first_target_alive),
        "init_cash": round(init_cash, 2),
        "ruin_pct": ruin_pct,
        "target_pct": target_pct,
        "ruin_level": round(ruin_level, 2),
        "target_level": round(target_level, 2),
        "max_days": dias,
        "simulations": sims,
        "sample_size": n,
    }
