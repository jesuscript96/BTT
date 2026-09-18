# -*- coding: utf-8 -*-
"""El sorteo de locates aleatorios: determinista, sesgado por precio como una
ley de potencia entre los extremos del rango, y el rango se usa ENTERO.

18-sep: hasta hoy la escala iba de 0,10 a 30 $ (suelo y techo del universo) y
como los gappers que se operan viven entre 0,3 y 25 $, con rango 1-20 el locate
mas barato de una corrida entera era 2,69 y las acciones de menos de 1 $ pagaban
7-9 $ el paquete (10 % de fade): la puerta por EV las tumbaba a todas y parecia
cosa del EV. Estos tests fijan la forma nueva.
"""
import math
import random

import pytest

from app.services.locates_random import (
    PRECIO_BARATA,
    PRECIO_CARA,
    SIGMA,
    centro_por_precio,
    posicion_por_precio,
    precio_locate,
    resumen,
)


def test_determinista_y_sin_depender_del_orden():
    a = precio_locate(2.5, 1, 20, 7, "ABCD", "2026-03-04")
    b = precio_locate(2.5, 1, 20, 7, "ABCD", "2026-03-04")
    assert a == b
    # Otra semilla u otro ticker-dia: otro precio (mismo centro).
    c = precio_locate(2.5, 1, 20, 8, "ABCD", "2026-03-04")
    d = precio_locate(2.5, 1, 20, 7, "ABCD", "2026-03-05")
    assert c["centro"] == a["centro"] == d["centro"]
    assert len({a["precio"], c["precio"], d["precio"]}) == 3


def test_la_barata_paga_el_minimo_y_la_cara_el_maximo():
    # Por debajo de la barata y por encima de la cara el centro se pega al
    # extremo del rango: asi el rango que pide el usuario se usa entero.
    assert posicion_por_precio(PRECIO_BARATA) == 0.0
    assert posicion_por_precio(PRECIO_BARATA / 2) == 0.0
    assert posicion_por_precio(PRECIO_CARA) == pytest.approx(1.0)
    assert posicion_por_precio(PRECIO_CARA * 4) == pytest.approx(1.0)
    assert centro_por_precio(0.20, 1, 20) == pytest.approx(1.0)
    assert centro_por_precio(0.30, 1, 20) == pytest.approx(1.0)
    assert centro_por_precio(25.0, 1, 20) == pytest.approx(20.0)
    assert centro_por_precio(80.0, 1, 20) == pytest.approx(20.0)


def test_ley_de_potencia_entre_los_extremos():
    # log(L) lineal en log(precio): el exponente es log(max/min)/log(cara/barata).
    b = math.log(20 / 1) / math.log(PRECIO_CARA / PRECIO_BARATA)
    assert 0.6 < b < 0.75                      # crece con el precio, MENOS que proporcional
    assert centro_por_precio(10, 1, 20) / centro_por_precio(1, 1, 20) == pytest.approx(10 ** b)
    # Medido el 18-sep y escrito en el modulo y en el tooltip del panel.
    assert centro_por_precio(0.50, 1, 20) == pytest.approx(1.41, abs=0.02)
    assert centro_por_precio(1.00, 1, 20) == pytest.approx(2.26, abs=0.02)
    assert centro_por_precio(3.00, 1, 20) == pytest.approx(4.76, abs=0.02)
    assert centro_por_precio(10.0, 1, 20) == pytest.approx(10.75, abs=0.02)
    # Y el fade al centro (L / precio) BAJA con el precio, como en la realidad.
    fades = [centro_por_precio(p, 1, 20) / p for p in (0.5, 1, 2, 3, 5, 10, 20)]
    assert fades == sorted(fades, reverse=True)


def test_el_centro_es_monotono_en_el_precio():
    precios = [0.1, 0.3, 0.5, 0.75, 1, 1.5, 2, 3, 5, 8, 10, 15, 20, 25, 40, 100]
    centros = [centro_por_precio(p, 1, 20) for p in precios]
    assert centros == sorted(centros)


def test_el_sorteo_no_se_sale_del_rango_y_se_reparte_alrededor_del_centro():
    xs = [precio_locate(3.0, 1, 20, s, "TK", "2026-01-02")["precio"] for s in range(1, 2001)]
    assert min(xs) >= 1.0 and max(xs) <= 20.0
    c = centro_por_precio(3.0, 1, 20)
    # Mediana en el centro (el ruido es lognormal de media 0 en log) y dos de
    # cada tres entre x0,7 y x1,4: sigma 0,35.
    xs.sort()
    assert xs[len(xs) // 2] == pytest.approx(c, rel=0.06)
    dentro = sum(1 for x in xs if c * math.exp(-SIGMA) <= x <= c * math.exp(SIGMA))
    assert 0.62 <= dentro / len(xs) <= 0.74


def test_sobre_un_universo_de_gappers_el_rango_se_usa_entero():
    # Precios de referencia como los medidos el 18-sep (lognormal: mediana 2,5 $,
    # sigma 1 en log). Antes del 18-sep el minimo de una corrida asi era 2,69 y la
    # mediana 11 $; ahora el minimo es el minimo del rango, el maximo el maximo,
    # y la mediana cae cerca de la media geometrica del rango (sqrt(1*20) = 4,5).
    rng = random.Random(42)
    refs = [math.exp(rng.gauss(math.log(2.5), 1.0)) for _ in range(4000)]
    xs = [precio_locate(r, 1, 20, 9, f"T{i}", "2026-01-02")["precio"] for i, r in enumerate(refs)]
    r = resumen(xs)
    assert r["min"] == pytest.approx(1.0, abs=0.01)
    assert r["max"] == pytest.approx(20.0, abs=0.01)
    assert 3.0 <= r["p50"] <= 6.0
    assert r["p10"] < 2.5 and r["p90"] > 9.0


def test_rango_desde_cero_interpola_lineal():
    # Sin minimo no hay potencia posible (0 elevado a nada): lineal en log-precio.
    pos = posicion_por_precio(3.0)
    assert centro_por_precio(3.0, 0, 10) == pytest.approx(10 * pos)
    assert precio_locate(3.0, 0, 10, 1, "TK", "2026-01-02")["precio"] <= 10.0


def test_rango_invertido_o_degenerado():
    # min > max se ordena; min == max devuelve ese precio siempre.
    assert precio_locate(3.0, 20, 1, 1, "TK", "2026-01-02") == precio_locate(3.0, 1, 20, 1, "TK", "2026-01-02")
    assert precio_locate(3.0, 5, 5, 1, "TK", "2026-01-02")["precio"] == 5.0
    assert precio_locate(0.0, 1, 20, 1, "TK", "2026-01-02")["posicion"] == 0.0
