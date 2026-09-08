"""RSI y las tres lineas del MACD, expuestos en las condiciones (2026-08-31).

El calculo ya existia en el backend desde siempre y hasta iba por la via
rapida; lo que faltaba era poder ELEGIRLOS en una condicion. Y dos de los
nombres ("MACD Signal" y "MACD Histogram") ni siquiera estaban en el enum, asi
que guardar una estrategia con ellos habria devuelto 422 en silencio — el mismo
fallo que tuvo Darvas Box.

Lo que se cubre:
  1. Que los cuatro nombres estan en el enum y pasan por pydantic (el 422).
  2. Que la via viva los calcula y devuelve numeros, no NaN.
  3. Las relaciones que los hacen utiles: histograma = linea - señal, y el RSI
     acotado en 0-100. Sin esto, un cruce "MACD cruza su Señal" podria estar
     comparando dos series que no son lo que dicen ser.
  4. Que respetan los periodos que se les pasan (12/26/9 no esta cableado).
"""
import numpy as np
import pandas as pd

from app.schemas.strategy import IndicatorConfig, IndicatorType
from app.services.indicators import compute_indicator


def _dia(n: int = 300, semilla: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    close = 20.0 + np.cumsum(rng.normal(0, 0.15, n))
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-11-12 08:00", periods=n, freq="1min"),
        "ticker": "TEST",
        "open": close, "high": close + 0.1, "low": close - 0.1,
        "close": close, "volume": rng.uniform(500, 5000, n),
    })


def test_los_cuatro_nombres_estan_en_el_enum():
    """Si falta uno, guardar la estrategia devuelve 422 sin explicar por que."""
    assert IndicatorType.RSI.value == "RSI"
    assert IndicatorType.MACD.value == "MACD"
    assert IndicatorType.MACD_SIGNAL.value == "MACD Signal"
    assert IndicatorType.MACD_HISTOGRAM.value == "MACD Histogram"


def test_pydantic_acepta_las_cuatro_configuraciones():
    """La capa que devuelve el 422 es esta, no el motor."""
    for nombre in ("RSI", "MACD", "MACD Signal", "MACD Histogram"):
        cfg = IndicatorConfig(name=nombre, period=12, period2=26, period3=9)
        assert cfg.name.value == nombre


def test_rsi_calcula_y_esta_acotado():
    df = _dia()
    rsi = np.asarray(compute_indicator("RSI", df, period=14), dtype=np.float64)
    validos = rsi[~np.isnan(rsi)]
    assert len(validos) > 200, "el RSI casi no devuelve valores"
    assert validos.min() >= 0.0 and validos.max() <= 100.0, "el RSI se sale de 0-100"


def test_histograma_es_linea_menos_señal():
    """La relacion que hace util al MACD: el histograma cruzando cero ES el
    cruce de la linea con su señal. Si no se cumple, las tres series no son
    las que dicen ser y un cruce no significaria nada."""
    df = _dia()
    kw = dict(period=12, period2=26, period3=9)
    linea = np.asarray(compute_indicator("MACD", df, **kw), dtype=np.float64)
    senal = np.asarray(compute_indicator("MACD Signal", df, **kw), dtype=np.float64)
    hist = np.asarray(compute_indicator("MACD Histogram", df, **kw), dtype=np.float64)

    assert np.allclose(hist, linea - senal, equal_nan=True), \
        "histograma != linea - señal: los cruces del MACD no serian de fiar"
    assert not np.allclose(linea, senal), "la linea y su señal no pueden ser iguales"


def test_los_periodos_del_macd_se_respetan():
    """12/26/9 son el DEFECTO, no algo cableado: cambiarlos tiene que cambiar
    el resultado. (El motor legacy si los tiene cableados, pero es codigo
    muerto y no se usa.)"""
    df = _dia()
    clasico = np.asarray(compute_indicator("MACD", df, period=12, period2=26, period3=9), dtype=np.float64)
    rapido = np.asarray(compute_indicator("MACD", df, period=5, period2=13, period3=4), dtype=np.float64)
    assert not np.allclose(clasico, rapido, equal_nan=True), \
        "cambiar los periodos no cambia nada: estarian cableados"


def test_el_rsi_respeta_su_periodo():
    df = _dia()
    corto = np.asarray(compute_indicator("RSI", df, period=5), dtype=np.float64)
    largo = np.asarray(compute_indicator("RSI", df, period=50), dtype=np.float64)
    assert not np.allclose(corto, largo, equal_nan=True)
    # Un RSI corto oscila mas que uno largo: es la comprobacion de cordura.
    assert np.nanstd(corto) > np.nanstd(largo)
