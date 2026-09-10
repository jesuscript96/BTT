# -*- coding: utf-8 -*-
"""Perfil de volumen intradía: el volumen del día repartido por franjas de precio.

Seis indicadores del mismo cálculo: el percentil de la franja donde está el
precio (una medida) y cinco NIVELES de precio.

Los niveles son de DOS clases, y confundirlas es la duda que salió al usarlo:

  · RELATIVOS AL PRECIO — «Nodo de arriba» y «Nodo de abajo» son la primera zona
    que hay por encima y por debajo de donde está el precio AHORA, así que
    saltan cada vez que el precio cruza una franja y parece que le persiguen.
  · DEL DÍA — «Punto de control», «Zona alta» y «Zona baja» no miran dónde está
    el precio. Son el marco estable de la sesión.
"""
import numpy as np
import pandas as pd
import pytest

from app.services.indicators import compute_indicator

BIN = 1.0          # franjas del 1 % del primer precio del día


def _df(precios, volumenes=None, dia="2026-09-08", altos=None, bajos=None):
    n = len(precios)
    c = np.asarray(precios, dtype=float)
    ts = [pd.Timestamp(f"{dia} 09:30") + pd.Timedelta(minutes=i) for i in range(n)]
    return pd.DataFrame({
        "timestamp": ts, "open": c,
        "high": c if altos is None else np.asarray(altos, dtype=float),
        "low": c if bajos is None else np.asarray(bajos, dtype=float),
        "close": c,
        "volume": np.full(n, 1000.0) if volumenes is None else np.asarray(volumenes, dtype=float),
    })


def _v(nombre, df, **kw):
    return compute_indicator(nombre, df, bin_pct=BIN, **kw)


def test_el_punto_de_control_cae_donde_se_cruzo_el_volumen():
    """No donde el precio hizo el máximo: donde se negoció más."""
    # Sube a 110 con volumen ridículo y pasa el resto del día en 100 con mucho.
    precios = [100.0] * 3 + [110.0] + [100.0] * 16
    vols = [50_000.0] * 3 + [10.0] + [50_000.0] * 16
    poc = _v("Punto de control", _df(precios, vols))
    # Franjas del 1 % de 100 = 1 $. El POC tiene que estar en la franja de 100,
    # no en la de 110, aunque 110 sea el máximo del día.
    assert 100.0 <= float(poc.iloc[-1]) < 101.0


def test_el_percentil_es_el_mas_alto_en_la_franja_mas_cargada():
    """OJO A LA ESCALA. El percentil mide qué FRACCIÓN de las franjas con volumen
    tiene MENOS que la del precio, así que estar en la más cargada de N franjas
    da (N-1)/N × 100, no 100 clavado: con 2 franjas son 50 y con 20 son 95.
    Sobre datos reales (OLB del 9-sep, ~20 franjas) el POC daba 95."""
    precios = [100.0, 101.0, 102.0, 103.0, 104.0] + [100.0] * 15
    vols = [1_000.0] * 5 + [50_000.0] * 15
    df = _df(precios, vols)
    pct = _v("Vol. de la franja", df)
    poc = _v("Punto de control", df)
    assert 100.0 <= float(poc.iloc[-1]) < 101.0        # acaba en la franja del POC
    assert float(pct.iloc[-1]) == pytest.approx(float(pct.max()))
    assert float(pct.iloc[-1]) > 60.0


def test_los_nodos_son_la_resistencia_y_el_soporte()  :
    """Dos zonas cargadas y el precio en medio: un nodo a cada lado."""
    # Mucho volumen en 90 y en 110, poco en el medio, y acaba en 100.
    precios = [90.0] * 10 + [110.0] * 10 + [100.0]
    vols = [50_000.0] * 10 + [50_000.0] * 10 + [10.0]
    df = _df(precios, vols)
    arriba = _v("Nodo de arriba", df, liston_pct=60)
    abajo = _v("Nodo de abajo", df, liston_pct=60)
    assert float(arriba.iloc[-1]) > 100.0     # la zona de 110
    assert float(abajo.iloc[-1]) < 100.0      # la zona de 90


def test_el_liston_manda_cuantas_zonas_cuentan():
    """Con el listón alto solo pasan las zonas grandes, así que el nodo queda
    más lejos o desaparece. Es el mando del número de crestas."""
    # La zona intermedia se deja al ~42 % del POC, para que pase el listón de 20
    # y no el de 90. Con el 7 % de la primera versión no pasaba ninguno de los
    # dos, los dos nodos salían iguales y el test no comprobaba nada.
    precios = [90.0] * 10 + [95.0] * 3 + [110.0] * 10 + [100.0]
    vols = [50_000.0] * 10 + [70_000.0] * 3 + [50_000.0] * 10 + [10.0]
    df = _df(precios, vols)
    flojo = _v("Nodo de abajo", df, liston_pct=20).iloc[-1]
    duro = _v("Nodo de abajo", df, liston_pct=90).iloc[-1]
    # Con listón flojo pasa la zona intermedia de 95, que está más cerca.
    assert float(flojo) > float(duro)


def test_reset_diario():
    """Un perfil no se arrastra de una sesión a la siguiente."""
    d1 = _df([100.0] * 10, [50_000.0] * 10, dia="2026-09-08")
    d2 = _df([200.0] * 10, [50_000.0] * 10, dia="2026-09-09")
    df = pd.concat([d1, d2], ignore_index=True)
    poc = _v("Punto de control", df)
    assert 100.0 <= float(poc.iloc[9]) < 101.0     # el día 8
    assert 200.0 <= float(poc.iloc[-1]) < 202.0    # el día 9, sin rastro del 8


def test_es_causal_no_mira_al_futuro():
    """EL TEST QUE DE VERDAD IMPORTA.

    El valor en la barra `i` tiene que salir igual calculado con el día entero
    que calculado con la serie CORTADA en `i`. Si en algún momento el cálculo
    usara velas posteriores —para fijar el rango, los bordes de las franjas o lo
    que sea— los dos números dejarían de coincidir, y el backtest estaría viendo
    un futuro que en vivo no existe.
    """
    rng = np.random.default_rng(11)
    n = 60
    precios = 50 + np.cumsum(rng.normal(0, 0.4, n))
    altos = precios * 1.01
    bajos = precios * 0.99
    vols = rng.integers(1_000, 80_000, n).astype(float)
    completo = _df(precios, vols, altos=altos, bajos=bajos)

    for nombre, kw in (("Vol. de la franja", {}), ("Punto de control", {}),
                       ("Nodo de arriba", {"liston_pct": 60}),
                       ("Nodo de abajo", {"liston_pct": 60})):
        entero = _v(nombre, completo, **kw)
        for i in (20, 35, 50):
            cortado = _v(nombre, completo.iloc[:i + 1].copy(), **kw)
            a, b = entero.iloc[i], cortado.iloc[i]
            if pd.isna(a) and pd.isna(b):
                continue
            assert a == pytest.approx(b), (
                f"{nombre} en la barra {i} cambia si se ve el resto del dia: "
                f"{a} con el dia entero, {b} cortando ahi")


def test_sin_volumen_no_hay_perfil():
    df = _df([100.0] * 10, [0.0] * 10)
    poc = _v("Punto de control", df)
    assert poc.isna().all()


# ══ La zona de valor: las bandas del día ══════════════════════════════════
#
# A diferencia de los nodos, NO mira dónde está el precio: arranca en el punto
# de control y va tragando la franja vecina más gorda hasta juntar el % de
# volumen pedido. Por eso es estable — solo se mueve cuando cambia el reparto
# del volumen, no cada vez que el precio cruza una franja.


def test_la_zona_envuelve_al_punto_de_control():
    precios = [100.0] * 10 + [104.0] * 4 + [96.0] * 4
    df = _df(precios, [50_000.0] * 10 + [20_000.0] * 4 + [20_000.0] * 4)
    alta = _v("Zona alta", df, zona_pct=70)
    baja = _v("Zona baja", df, zona_pct=70)
    poc = _v("Punto de control", df)
    assert float(baja.iloc[-1]) <= float(poc.iloc[-1]) <= float(alta.iloc[-1])


def test_mas_porcentaje_ensancha_la_zona():
    rng = np.random.default_rng(3)
    n = 40
    precios = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = _df(precios, rng.integers(1_000, 60_000, n).astype(float),
             altos=precios * 1.004, bajos=precios * 0.996)
    estrecha = float(_v("Zona alta", df, zona_pct=30).iloc[-1]) - float(_v("Zona baja", df, zona_pct=30).iloc[-1])
    ancha = float(_v("Zona alta", df, zona_pct=95).iloc[-1]) - float(_v("Zona baja", df, zona_pct=95).iloc[-1])
    assert ancha > estrecha


def test_la_zona_es_mas_estable_que_los_nodos():
    """La razón de ser de este indicador: los nodos saltan cada vez que el precio
    cruza una franja porque son relativos a él; la zona no."""
    rng = np.random.default_rng(9)
    n = 120
    precios = 50 + np.cumsum(rng.normal(0, 0.35, n))
    df = _df(precios, rng.integers(1_000, 60_000, n).astype(float),
             altos=precios * 1.006, bajos=precios * 0.994)
    zona = _v("Zona alta", df, zona_pct=70).dropna()
    nodo = _v("Nodo de arriba", df, liston_pct=60).dropna()
    cambios_zona = int((zona.diff().abs() > 1e-9).sum())
    cambios_nodo = int((nodo.diff().abs() > 1e-9).sum())
    assert cambios_zona < cambios_nodo, (
        f"la zona cambia {cambios_zona} veces y el nodo {cambios_nodo}: "
        "la zona deberia ser la estable")


def test_la_zona_tambien_es_causal():
    rng = np.random.default_rng(17)
    n = 50
    precios = 30 + np.cumsum(rng.normal(0, 0.3, n))
    completo = _df(precios, rng.integers(1_000, 50_000, n).astype(float),
                   altos=precios * 1.008, bajos=precios * 0.992)
    for nombre in ("Zona alta", "Zona baja"):
        entero = _v(nombre, completo, zona_pct=70)
        for i in (20, 35, 45):
            cortado = _v(nombre, completo.iloc[:i + 1].copy(), zona_pct=70)
            a, b = entero.iloc[i], cortado.iloc[i]
            if pd.isna(a) and pd.isna(b):
                continue
            assert a == pytest.approx(b), f"{nombre} en la barra {i} mira al futuro"
