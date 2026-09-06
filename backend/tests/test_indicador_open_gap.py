"""«Open Gap (%)»: el gap con el que ABRIÓ el mercado.

Pedido por Jaume el 6-sep-2026 como guarda del genético: «añade también lo de
gap de apertura mínimo, por si no quiero solo ver el de PM».

LO IMPORTANTE ES QUE ES CAUSAL. El dato existe como columna del lago
(`gap_at_open_pct`) y habría sido trivial devolverlo constante todo el día —
pero eso es LOOKAHEAD: una estrategia que entra a las 08:00 estaría usando la
apertura de las 09:30, que todavía no ha ocurrido. Por eso es NaN hasta que el
mercado abre, igual que «% Session Fade». El NaN de la mañana no es un fallo.

Y se comprueba la PARIDAD con el camino nativo N2a: dos implementaciones del
mismo indicador que se separen dan backtests distintos según una variable de
entorno, que es de los errores más difíciles de ver.
"""
import numpy as np
import pandas as pd
import pytest

from app.services.indicators import compute_indicator
from app.services.strategy_engine import _RAW_INDICATOR_DISPATCH


def _dia(inicio="2026-09-04 04:00", n=480, apertura_rth=12.0):
    """04:00 → 11:59. El precio va a 10 en premercado y salta a 12 al abrir."""
    ts = pd.date_range(inicio, periods=n, freq="1min")
    mins = ts.hour * 60 + ts.minute
    close = np.where(mins < 570, 10.0, apertura_rth)
    return pd.DataFrame({
        "timestamp": ts, "open": close, "high": close * 1.001,
        "low": close * 0.999, "close": close, "volume": np.full(n, 100_000.0),
    })


DS = {"prev_close": 10.0, "rth_open": 12.0}


def test_es_NaN_antes_de_que_abra_el_mercado():
    """EL PUNTO. A las 08:00 nadie sabe a cuánto va a abrir el RTH."""
    df = _dia()
    serie = compute_indicator("Open Gap (%)", df, daily_stats=DS)
    mins = pd.to_datetime(df["timestamp"]).dt.hour * 60 + pd.to_datetime(df["timestamp"]).dt.minute
    antes = serie[mins < 570]
    assert antes.isna().all(), "hay valores antes de las 09:30: eso es mirar el futuro"


def test_desde_la_apertura_vale_el_gap_de_apertura():
    df = _dia()
    serie = compute_indicator("Open Gap (%)", df, daily_stats=DS)
    mins = pd.to_datetime(df["timestamp"]).dt.hour * 60 + pd.to_datetime(df["timestamp"]).dt.minute
    despues = serie[mins >= 570]
    # (12 − 10) / 10 × 100 = 20 %
    assert np.allclose(despues.values, 20.0)


def test_no_se_mueve_con_el_precio_como_si_hace_Current_Gap():
    """Es la diferencia entre los dos: el de apertura se congela, el otro no."""
    ts = pd.date_range("2026-09-04 09:30", periods=60, freq="1min")
    close = np.linspace(12.0, 18.0, 60)          # el precio sube tras abrir
    df = pd.DataFrame({"timestamp": ts, "open": close, "high": close,
                       "low": close, "close": close, "volume": np.full(60, 1e5)})
    apertura = compute_indicator("Open Gap (%)", df, daily_stats=DS)
    vivo = compute_indicator("Current Gap (%)", df, daily_stats=DS)
    assert np.allclose(apertura.values, 20.0), "el de apertura no se mueve"
    assert vivo.iloc[-1] > vivo.iloc[0], "el vivo sí sigue al precio"


def test_sin_cierre_de_ayer_no_inventa_un_numero():
    df = _dia()
    serie = compute_indicator("Open Gap (%)", df, daily_stats={"prev_close": 0})
    assert serie.isna().all()


def test_paridad_con_el_camino_nativo():
    """Dos implementaciones que se separen dan resultados distintos según una
    env, y eso no se ve en ningún log."""
    assert "Open Gap (%)" in _RAW_INDICATOR_DISPATCH
    df = _dia()
    legacy = compute_indicator("Open Gap (%)", df, daily_stats=DS).values

    mins = (pd.to_datetime(df["timestamp"]).dt.hour * 60
            + pd.to_datetime(df["timestamp"]).dt.minute).values
    ds_nativo = {**DS, "_mins": mins}
    c = df["close"].values.astype(np.float64)
    o = df["open"].values.astype(np.float64)
    nativo = _RAW_INDICATOR_DISPATCH["Open Gap (%)"](
        c, df["high"].values.astype(np.float64), df["low"].values.astype(np.float64),
        o, df["volume"].values.astype(np.float64),
        None, None, None, None, None, ds_nativo)

    assert np.allclose(legacy, np.asarray(nativo, dtype=np.float64), equal_nan=True)


def test_esta_en_las_guardas_del_genetico():
    """Las guardas se ofrecen en los DOS modos, explorar y mejorar."""
    import sys
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[2]
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from genetico import catalogo as C
    nombres = {g[1] for g in C.GUARDAS}
    assert "Open Gap (%)" in nombres
    assert "PM High Gap (%)" in nombres, "la de premercado sigue estando"


def test_esta_declarado_en_TODAS_las_listas_blancas():
    """El patrón que más muerde en este repo: un indicador que existe en el
    motor pero falta en una lista blanca se cae EN SILENCIO — la condición
    evalúa False, la estrategia no opera y nadie ve un error.

    OJO, una capa que NO se toca a propósito: el bot de avisos en vivo
    (`bot_alerts_universo`) tiene su propio mapa de nombres y es zona cerrada
    (AGENTS.md). Una estrategia con este indicador funciona en el backtest pero
    el bot NO la entiende todavía.
    """
    from app.schemas.strategy import IndicatorType
    from app.api_public.modules.backtest.catalog import _CATEGORY

    assert IndicatorType.OPEN_GAP.value == "Open Gap (%)"
    todos = {n for grupo in _CATEGORY.values() for n in grupo}
    assert "Open Gap (%)" in todos
