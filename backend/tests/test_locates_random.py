# -*- coding: utf-8 -*-
"""El sorteo de locates aleatorios: determinista, con la forma del mercado
(precio^0,6 y mucha dispersion) y el rango del usuario como banda p10-p90.

18-sep: hasta hoy el rango era un suelo y un techo duros con el centro lineal en
log-precio entre 0,10 y 30 $ y ruido sigma 0,35. Medido contra 99 locates reales
del socio de Jaume (un mes): cobertura del 21 %, el doble de caro para las
acciones baratas y tres veces menos disperso que la realidad. Estos tests fijan
la forma nueva y los numeros medidos.
"""
import math
import random

import pytest

from app.services.locates_random import (
    COLA_MAXIMA,
    EXPONENTE_PRECIO,
    PRECIO_MEDIANO,
    SUELO_PAQUETE,
    centro_por_precio,
    parametros_banda,
    precio_locate,
    resumen,
)


def test_determinista_y_sin_depender_del_orden():
    a = precio_locate(2.5, 0.3, 15, 7, "ABCD", "2026-03-04")
    b = precio_locate(2.5, 0.3, 15, 7, "ABCD", "2026-03-04")
    assert a == b
    # Otra semilla u otro ticker-dia: otro precio (mismo centro).
    c = precio_locate(2.5, 0.3, 15, 8, "ABCD", "2026-03-04")
    d = precio_locate(2.5, 0.3, 15, 7, "ABCD", "2026-03-05")
    assert c["centro"] == a["centro"] == d["centro"]
    assert len({a["precio"], c["precio"], d["precio"]}) == 3


def test_el_nivel_es_la_media_geometrica_del_rango_en_la_accion_de_2_dolares():
    nivel, ruido, techo = parametros_banda(0.3, 15)
    assert nivel == pytest.approx(math.sqrt(0.3 * 15))
    assert centro_por_precio(PRECIO_MEDIANO, 0.3, 15) == pytest.approx(nivel)
    assert techo == pytest.approx(COLA_MAXIMA * 15)
    # Banda mas ancha en proporcion -> mas ruido; 1-20 sale con sigma ~1,0 (la
    # medida real, sin el suelo del broker, es 1,15).
    assert 0.9 < parametros_banda(1, 20)[1] < 1.1
    assert parametros_banda(0.3, 15)[1] > parametros_banda(1, 20)[1] > parametros_banda(1, 10)[1]


def test_el_locate_crece_con_el_precio_como_potencia_0_6():
    # Medido: 1,49 x precio^0,62 sobre los locates reales. Una de 20 $ paga 4
    # veces lo que una de 2 $, no 10; el fade (L / precio) BAJA con el precio.
    assert centro_por_precio(20, 0.3, 15) / centro_por_precio(2, 0.3, 15) == pytest.approx(10 ** EXPONENTE_PRECIO)
    fades = [centro_por_precio(p, 0.3, 15) / p for p in (0.3, 0.5, 1, 2, 3, 5, 10, 20)]
    assert fades == sorted(fades, reverse=True)
    centros = [centro_por_precio(p, 0.3, 15) for p in (0.1, 0.3, 0.5, 1, 2, 3, 5, 10, 20, 50)]
    assert centros == sorted(centros)
    # Los numeros del tooltip del panel (banda 0,3-15).
    assert centro_por_precio(0.5, 0.3, 15) == pytest.approx(0.92, abs=0.02)
    assert centro_por_precio(1.0, 0.3, 15) == pytest.approx(1.40, abs=0.02)
    assert centro_por_precio(3.0, 0.3, 15) == pytest.approx(2.71, abs=0.02)
    assert centro_por_precio(10.0, 0.3, 15) == pytest.approx(5.57, abs=0.02)


def test_la_banda_es_lo_normal_9_de_cada_10_dentro():
    # Precios de referencia como los medidos (lognormal: mediana 2 $, sigma 1).
    rng = random.Random(42)
    refs = [math.exp(rng.gauss(math.log(2.0), 1.0)) for _ in range(6000)]
    for lo, hi in ((0.3, 15), (1, 20), (1, 10)):
        xs = [precio_locate(r, lo, hi, 9, f"T{i}", "2026-01-02")["precio"] for i, r in enumerate(refs)]
        res = resumen(xs)
        dentro = sum(1 for x in xs if lo <= x <= hi) / len(xs)
        assert 0.76 <= dentro <= 0.84, (lo, hi, dentro)
        assert res["p10"] == pytest.approx(lo, rel=0.12)
        assert res["p90"] == pytest.approx(hi, rel=0.12)
        assert res["p50"] == pytest.approx(math.sqrt(lo * hi), rel=0.12)
        # La cola cara existe pero esta acotada; por abajo, el suelo del broker.
        assert res["max"] <= COLA_MAXIMA * hi + 1e-9
        assert res["min"] >= SUELO_PAQUETE


def test_reproduce_los_locates_reales_del_socio():
    # Un mes de locates reales (DAS, 99 cotizaciones con precio del dia): $/paq
    # p10 0,06 (suelo del broker), p50 1,96, p90 12,1; precios p10 0,45, p50
    # 2,1, p90 6. Con la banda 0,3-15 el modelo, sobre esos mismos precios, da
    # una poblacion parecida (medido: p10 0,23, p50 1,8, p90 11,6).
    rng = random.Random(7)
    precios = [math.exp(rng.gauss(math.log(2.1), 1.0)) for _ in range(4000)]
    xs = [precio_locate(p, 0.3, 15, 3, f"S{i}", "2026-09-01")["precio"] for i, p in enumerate(precios)]
    res = resumen(xs)
    assert 1.4 <= res["p50"] <= 2.6
    assert 8.0 <= res["p90"] <= 16.0
    assert res["p10"] <= 0.5


def test_rango_desde_cero_y_rango_invertido():
    # Sin minimo no hay media geometrica: se toma maximo/100 como minimo efectivo.
    nivel, ruido, _ = parametros_banda(0, 10)
    assert nivel == pytest.approx(1.0) and ruido > 1.0
    assert precio_locate(3.0, 0, 10, 1, "TK", "2026-01-02")["precio"] >= SUELO_PAQUETE
    # min > max se ordena; min == max devuelve un sorteo con el ruido minimo.
    assert precio_locate(3.0, 15, 0.3, 1, "TK", "2026-01-02") == precio_locate(3.0, 0.3, 15, 1, "TK", "2026-01-02")
    assert parametros_banda(5, 5)[0] == 5.0
    assert precio_locate(0.0, 0.3, 15, 1, "TK", "2026-01-02")["precio"] > 0
