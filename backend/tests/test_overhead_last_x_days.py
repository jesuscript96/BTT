# -*- coding: utf-8 -*-
"""Tests de «Overhead last X days».

No necesitan la tabla real: se inyecta un ticker sintetico en la cache del
indicador (`_overhead_cache`), que es exactamente lo que deja ahi el prefetch.
Asi corren en cualquier maquina y siguen probando lo que importa — el ajuste por
splits y la semantica de la regla de volumen.

El ticker esta calcado de GCTK (reverse 20:1 el 2025-02-04), que es el caso que
motivo el ajuste: sin el, el nivel sale 20 veces por debajo del precio y la
condicion "cruza por encima" se cumple en la primera vela del dia, siempre.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import indicators as I
from app.services.indicators import compute_indicator

TICKER = "TEST_OVH"
HOY = "2025-02-06"        # dos dias despues del split
DIA_SPLIT = "2025-02-04"  # mirando desde aqui, la ventana es toda pre-split

# fecha         o       h       l       c        v          cum_split
FILAS = [
    ("2025-01-29", 0.0950, 0.1115, 0.0909, 0.0925, 49_227_308.0,   5.0),
    ("2025-01-30", 0.0700, 0.0717, 0.0611, 0.0707, 37_378_888.0,   5.0),
    ("2025-01-31", 0.0705, 0.0710, 0.0640, 0.0640, 10_481_072.0,   5.0),
    ("2025-02-03", 0.0630, 0.0640, 0.0512, 0.0568, 15_501_878.0,   5.0),
    (DIA_SPLIT,    1.5100, 2.1300, 0.7400, 0.7854, 44_782_088.0, 100.0),  # 20:1
    ("2025-02-05", 0.8000, 0.8300, 0.4850, 0.6982,  5_302_053.0, 100.0),
    (HOY,          0.6600, 0.6999, 0.6300, 0.6702,  1_060_634.0, 100.0),
]


@pytest.fixture(autouse=True)
def cache_sintetica():
    """Mete el ticker en la cache y la deja como estaba al terminar."""
    previo = dict(I._overhead_cache)
    entrada = {"fechas": pd.Index([f[0] for f in FILAS])}
    for i, col in enumerate(("o", "h", "l", "c", "v", "cum_split"), start=1):
        entrada[col] = np.array([f[i] for f in FILAS], dtype=np.float64)
    I._overhead_cache[TICKER] = entrada
    yield
    I._overhead_cache.clear()
    I._overhead_cache.update(previo)


def _velas(n=6, volumen=200_000.0):
    idx = pd.date_range("2025-02-06 09:30", periods=n, freq="1min")
    return pd.DataFrame({
        "open": [0.66] * n, "high": [0.70] * n, "low": [0.63] * n,
        "close": [0.67] * n, "volume": [volumen] * n, "timestamp": idx,
    })


def _ov(volumen=200_000.0, fecha=HOY, **kw):
    return compute_indicator("Overhead last X days", _velas(volumen=volumen),
                             daily_stats={"ticker": TICKER, "date": fecha}, **kw)


class TestAjustePorSplits:
    def test_el_nivel_viene_en_la_escala_de_hoy(self):
        """Desde el 06-feb, el maximo de la ventana es el 2,13 del 04-feb."""
        assert _ov(days_lookback=5).iloc[0] == pytest.approx(2.13, rel=1e-6)

    def test_una_ventana_entera_pre_split_se_reescala(self):
        """Mirando DESDE el dia del split, la ventana es toda anterior a el: el
        maximo crudo es 0,1115 y en escala del dia son 2,23.

        SIN ajustar saldria 0,1115 — un nivel un 92% por debajo del precio de
        ese dia (1,51 de apertura), que dispararia "cruza por encima" en la
        primera vela y en todas las demas. Ese es el bug que el ajuste evita, y
        cae en el 4,3% de los dias de gap con 30 dias de ventana."""
        assert _ov(fecha=DIA_SPLIT, days_lookback=4).iloc[0] == pytest.approx(2.23, rel=1e-6)

    def test_el_volumen_tambien_se_ajusta(self):
        """Tras un 20:1 hay 20 veces menos acciones: los 49,2 M del 29-ene son
        2,46 M en escala del dia del split. Sin ajustarlo, la regla de volumen
        compararia escalas distintas justo en los dias que mas interesan.

        Con 500 k por vela, hoy pasa de 2,46 M en la 5a vela."""
        s = _ov(volumen=500_000.0, fecha=DIA_SPLIT, days_lookback=4,
                overhead_vol_rule="gt")
        assert list(s.notna()) == [True, True, True, True, False, False]


class TestQueDiaYQuePrecio:
    @pytest.mark.parametrize("ref,esperado", [
        ("high", 2.1300), ("low", 0.7400), ("open", 1.5100), ("close", 0.7854),
    ])
    def test_ref_elige_el_precio_de_ESE_dia(self, ref, esperado):
        """Los cuatro salen del MISMO dia (el del maximo), no de cuatro dias."""
        assert _ov(days_lookback=5, overhead_ref=ref).iloc[0] == pytest.approx(esperado, rel=1e-6)

    def test_extreme_min_busca_el_dia_del_minimo(self):
        """El minimo mas bajo de la ventana, ya ajustado, es el 0,485 del 05-feb."""
        s = _ov(days_lookback=5, overhead_extreme="min", overhead_ref="low")
        assert s.iloc[0] == pytest.approx(0.485, rel=1e-6)

    def test_hoy_nunca_entra_en_la_ventana(self):
        """El maximo de hoy (0,6999) no puede ser su propio nivel."""
        assert _ov(days_lookback=5).iloc[0] != pytest.approx(0.6999, rel=1e-6)

    def test_la_ventana_se_acorta_de_verdad(self):
        """Con 2 dias solo entran 04-feb y 05-feb; con 5, tambien los previos."""
        assert _ov(fecha=DIA_SPLIT, days_lookback=1).iloc[0] == pytest.approx(0.0640 * 20, rel=1e-6)
        assert _ov(fecha=DIA_SPLIT, days_lookback=4).iloc[0] == pytest.approx(2.23, rel=1e-6)

    def test_los_nombres_viejos_conservan_sus_defectos(self):
        df, ds = _velas(), {"ticker": TICKER, "date": HOY}
        alto = compute_indicator("High of last X days", df, daily_stats=ds, days_lookback=5)
        bajo = compute_indicator("Low of last X days", df, daily_stats=ds, days_lookback=5)
        assert alto.iloc[0] == pytest.approx(2.13, rel=1e-6)
        assert bajo.iloc[0] == pytest.approx(0.485, rel=1e-6)


class TestReglaDeVolumen:
    """El dia del nivel (04-feb) movio 44,78 M, con factor 1: no se reescala."""

    def test_sin_regla_el_nivel_es_constante(self):
        s = _ov(days_lookback=5, overhead_vol_rule="none")
        assert s.notna().all() and s.nunique() == 1

    def test_gt_se_apaga_cuando_hoy_supera_aquel_dia(self):
        # 10 M por vela: al cierre de la 5a vela hoy lleva 50 M > 44,78 M.
        s = _ov(volumen=10_000_000.0, days_lookback=5, overhead_vol_rule="gt")
        assert list(s.notna()) == [True, True, True, True, False, False]

    def test_lt_es_el_complementario(self):
        s = _ov(volumen=10_000_000.0, days_lookback=5, overhead_vol_rule="lt")
        assert list(s.notna()) == [False, False, False, False, True, True]

    def test_la_regla_mira_el_dia_DEL_MAXIMO_no_el_de_mas_volumen(self):
        """Semantica de Jaume: primero el maximo, DESPUES su volumen. Si el dia
        del maximo no cumple, la senal se descarta — no se baja al siguiente
        techo. En la ventana pre-split el maximo es el 29-ene (2,46 M ajustados);
        el 30-ene movio mas (7,48 M) pero es un techo mas bajo, y da igual: con
        3 M acumulados ya en la primera vela, no hay nivel en todo el dia."""
        s = _ov(volumen=3_000_000.0, fecha=DIA_SPLIT, days_lookback=4,
                overhead_vol_rule="gt")
        assert s.isna().all()


class TestBordes:
    def test_ticker_desconocido_da_NaN_sin_reventar(self):
        s = compute_indicator("Overhead last X days", _velas(),
                              daily_stats={"ticker": "NO_EXISTE", "date": HOY},
                              days_lookback=5)
        assert len(s) == 6 and s.isna().all()

    def test_sin_daily_stats_da_NaN(self):
        s = compute_indicator("Overhead last X days", _velas(), days_lookback=5)
        assert s.isna().all()

    def test_fecha_fuera_de_la_tabla_da_NaN(self):
        """Sin ancla no hay escala de splits fiable: no se inventa un nivel."""
        s = _ov(fecha="1999-01-04", days_lookback=5)
        assert s.isna().all()

    def test_el_primer_dia_de_la_tabla_no_tiene_pasado(self):
        assert _ov(fecha="2025-01-29", days_lookback=5).isna().all()

    def test_ventana_mas_larga_que_la_historia_no_revienta(self):
        assert _ov(days_lookback=9999).iloc[0] == pytest.approx(2.23, rel=1e-6)

    def test_la_cache_distingue_configuraciones(self):
        """Si los parametros no entraran en la clave, dos configuraciones
        distintas compartirian resultado."""
        cache = {}
        df, ds = _velas(), {"ticker": TICKER, "date": HOY}
        a = compute_indicator("Overhead last X days", df, daily_stats=ds,
                              days_lookback=5, overhead_ref="high", cache=cache)
        b = compute_indicator("Overhead last X days", df, daily_stats=ds,
                              days_lookback=5, overhead_ref="close", cache=cache)
        assert a.iloc[0] != b.iloc[0]


def test_el_motor_reconoce_el_nombre():
    """Lo que comprueba `test_genetico_catalogo` para los demas niveles: un
    nombre desconocido devuelve todo NaN, asi que si esto pasa, el nombre esta
    dado de alta en `_compute_raw`."""
    assert _ov(days_lookback=5).notna().any()
