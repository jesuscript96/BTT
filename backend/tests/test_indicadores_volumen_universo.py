# -*- coding: utf-8 -*-
"""Los tres indicadores de volumen contra el universo (22-sep-2026).

«RVOL universo» compara el volumen de los últimos N minutos con el que
tocaría a esa hora en un día de gap, usando el perfil que construye
`scripts/perfil_volumen_universo.py`. «Minutos desde el pico de volumen» es
el reloj desde la vela más gorda del día. «Pendiente del volumen» es si el
volumen acelera o se apaga.

Los tres son CAUSALES (solo velas cerradas) y resuelven la ventana por RELOJ,
no por número de velas: en estos tickers las velas son dispersas y «10 velas
atrás» pueden ser 40 minutos.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import indicators as ind
from app.services.indicators import compute_indicator


def _df(volumenes, inicio="2026-09-22 09:00", minutos=None):
    """Un día con un volumen por vela. `minutos` permite velas DISPERSAS."""
    n = len(volumenes)
    if minutos is None:
        ts = pd.date_range(inicio, periods=n, freq="1min")
    else:
        base = pd.Timestamp(inicio)
        ts = pd.DatetimeIndex([base + pd.Timedelta(minutes=int(m)) for m in minutos])
    px = np.full(n, 10.0)
    return pd.DataFrame({"timestamp": ts, "open": px, "high": px * 1.01,
                         "low": px * 0.99, "close": px,
                         "volume": np.asarray(volumenes, dtype=np.float64)})


@pytest.fixture
def perfil_plano(monkeypatch):
    """Perfil de juguete: el volumen del día repartido POR IGUAL entre las
    960 velas de 04:00 a 20:00. Así lo esperado es fácil de calcular a mano y
    el test mide la fórmula, no el perfil real."""
    F = np.zeros(1441)
    ini, fin = 4 * 60, 20 * 60
    for m in range(1441):
        if m < ini:
            F[m] = 0.0
        elif m >= fin:
            F[m] = 1.0
        else:
            F[m] = (m - ini + 1) / (fin - ini)
    monkeypatch.setattr(ind, "_PERFIL_VOL", {"F": F, "meta": {"ticker_dias": 1}})
    return F


# ══ RVOL universo ══════════════════════════════════════════════════════════

def test_volumen_constante_da_uno(perfil_plano):
    """Con el perfil plano y el volumen constante, el RVOL es 1 en todas las
    velas donde se puede calcular: el día va exactamente al ritmo esperado."""
    d = _df([1000.0] * 300, inicio="2026-09-22 04:00")
    r = compute_indicator("RVOL universo", d, range_minutes=10).values
    calculables = r[np.isfinite(r)]
    assert len(calculables) > 200
    assert np.allclose(calculables, 1.0, rtol=1e-9)


def test_el_triple_de_volumen_da_tres(perfil_plano):
    """Diez minutos a triple volumen: el RVOL de esa ventana es 3."""
    v = [1000.0] * 200
    for i in range(150, 160):
        v[i] = 3000.0
    d = _df(v, inicio="2026-09-22 04:00")
    r = compute_indicator("RVOL universo", d, range_minutes=10).values
    assert r[159] == pytest.approx(3.0, rel=1e-6)      # la ventana entera al triple
    assert r[120] == pytest.approx(1.0, rel=1e-6)      # antes, normal


def test_el_secado_baja_de_uno(perfil_plano):
    v = [1000.0] * 200
    for i in range(150, 160):
        v[i] = 200.0
    d = _df(v, inicio="2026-09-22 04:00")
    r = compute_indicator("RVOL universo", d, range_minutes=10).values
    assert r[159] == pytest.approx(0.2, rel=1e-6)


def test_al_principio_del_dia_es_nan(perfil_plano):
    """Con menos del 0,5 % del día acumulado, dividir por casi nada da
    cualquier cosa: NaN a propósito, no un número enorme."""
    d = _df([1000.0] * 300, inicio="2026-09-22 04:00")
    r = compute_indicator("RVOL universo", d, range_minutes=10).values
    assert np.isnan(r[0]) and np.isnan(r[3])
    assert np.isfinite(r[100])


def test_no_depende_del_tamano_del_ticker(perfil_plano):
    """El mismo día multiplicado por mil da el MISMO RVOL: normaliza por el
    tamaño del día, que es lo que lo hace comparable entre tickers."""
    v = [1000.0] * 200
    v[150:160] = [3000.0] * 10
    a = compute_indicator("RVOL universo", _df(v, inicio="2026-09-22 04:00"), range_minutes=10).values
    b = compute_indicator("RVOL universo", _df([x * 1000 for x in v], inicio="2026-09-22 04:00"), range_minutes=10).values
    ok = np.isfinite(a) & np.isfinite(b)
    assert ok.sum() > 100 and np.allclose(a[ok], b[ok], rtol=1e-9)


def test_la_ventana_es_de_reloj_no_de_velas(perfil_plano):
    """Velas dispersas, una cada 5 minutos, con un pico hace media hora.

    Con ventana de 10 MINUTOS ese pico ya no cuenta (quedó fuera). Si la
    ventana fuera de 10 VELAS serían 50 minutos y el pico seguiría dentro,
    inflando el RVOL — el fallo que describe [[btt-velas-dispersas-ventana-reloj]].
    """
    minutos = list(range(0, 600, 5))
    v = [1000.0] * len(minutos)
    pico = 40                                   # vela en el minuto 200
    v[pico] = 50_000.0
    d = _df(v, inicio="2026-09-22 04:00", minutos=minutos)
    r = compute_indicator("RVOL universo", d, range_minutes=10).values
    assert r[pico] > 20, "en la vela del pico el RVOL tiene que dispararse"
    # 30 minutos después (6 velas) el pico ya no está en la ventana
    assert r[pico + 6] < 1.5, r[pico + 6]
    # y con ventana de 60 minutos sí sigue dentro
    r60 = compute_indicator("RVOL universo", d, range_minutes=60).values
    assert r60[pico + 6] > 3, r60[pico + 6]


def test_sin_perfil_es_nan_y_no_revienta(monkeypatch):
    monkeypatch.setattr(ind, "_PERFIL_VOL", {})
    d = _df([1000.0] * 100, inicio="2026-09-22 04:00")
    r = compute_indicator("RVOL universo", d, range_minutes=10).values
    assert np.isnan(r).all()


# ══ Minutos desde el pico de volumen ═══════════════════════════════════════

def test_minutos_desde_el_pico():
    v = [100.0] * 60
    v[20] = 5000.0                      # el pico, en el minuto 20
    d = _df(v, inicio="2026-09-22 09:00")
    r = compute_indicator("Minutos desde el pico de volumen", d).values
    assert r[20] == 0.0                 # en el pico, cero
    assert r[30] == 10.0
    assert r[59] == 39.0
    # ANTES del pico el reloj cuenta desde el máximo de ESE momento (causal).
    # Con todas las velas iguales manda la PRIMERA que alcanzó ese nivel (se
    # compara con `>`, no con `>=`): en la vela 10 han pasado 10 minutos desde
    # la vela 0. Devolver 0 en un empate diría «el clímax es ahora», que es
    # justo lo contrario de lo que pasa cuando el volumen es plano.
    assert r[10] == 10.0


def test_el_pico_se_actualiza_si_llega_otro_mayor():
    v = [100.0] * 60
    v[10] = 3000.0
    v[40] = 9000.0
    d = _df(v, inicio="2026-09-22 09:00")
    r = compute_indicator("Minutos desde el pico de volumen", d).values
    assert r[30] == 20.0                # aún manda el de la vela 10
    assert r[40] == 0.0                 # llega uno mayor
    assert r[50] == 10.0


def test_el_pico_no_mira_al_futuro():
    """En la vela 30 el indicador no puede saber que en la 40 hay un pico
    mayor: sigue contando desde el de la 10."""
    v = [100.0] * 60
    v[10] = 3000.0
    v[40] = 9000.0
    d = _df(v, inicio="2026-09-22 09:00")
    r = compute_indicator("Minutos desde el pico de volumen", d).values
    corto = compute_indicator("Minutos desde el pico de volumen", d.iloc[:31].copy()).values
    assert r[30] == corto[30]


# ══ Pendiente del volumen ══════════════════════════════════════════════════

def test_pendiente_acelera_y_se_apaga():
    v = [1000.0] * 60
    v[40:50] = [3000.0] * 10            # los últimos 10 min, al triple
    d = _df(v, inicio="2026-09-22 09:00")
    r = compute_indicator("Pendiente del volumen", d, range_minutes=10).values
    assert r[49] == pytest.approx(3.0, rel=1e-6)
    v2 = [1000.0] * 60
    v2[40:50] = [250.0] * 10
    r2 = compute_indicator("Pendiente del volumen", _df(v2, inicio="2026-09-22 09:00"),
                           range_minutes=10).values
    assert r2[49] == pytest.approx(0.25, rel=1e-6)


def test_pendiente_sin_ventana_previa_es_nan():
    d = _df([1000.0] * 60, inicio="2026-09-22 09:00")
    r = compute_indicator("Pendiente del volumen", d, range_minutes=10).values
    assert np.isnan(r[5])               # no hay 20 minutos por detrás
    assert np.isfinite(r[40])


def test_los_tres_no_miran_al_futuro(perfil_plano):
    """Recortar el día por la vela k no cambia el valor en k. Es la prueba de
    causalidad que ya se le hizo al resto de indicadores nuevos."""
    rng = np.random.default_rng(7)
    v = rng.integers(100, 50000, 300).astype(float)
    d = _df(v, inicio="2026-09-22 04:00")
    for nombre, kw in (("RVOL universo", {"range_minutes": 10}),
                       ("Minutos desde el pico de volumen", {}),
                       ("Pendiente del volumen", {"range_minutes": 10})):
        entero = compute_indicator(nombre, d, **kw).values
        for k in (120, 200, 260):
            corto = compute_indicator(nombre, d.iloc[:k + 1].copy(), **kw).values
            a, b = entero[k], corto[k]
            assert (np.isnan(a) and np.isnan(b)) or a == pytest.approx(b, rel=1e-9), (nombre, k)
