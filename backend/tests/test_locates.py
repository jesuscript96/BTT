"""Tests de la calculadora de locates de Edgie (paquetes de 100, ceil)."""

from app.services.locates import calc_locates


def test_paquetes_ceil_100():
    # 350 shares -> 4 paquetes (nunca 3).
    r = calc_locates(precio_entrada=2.0, precio_stop=2.2, coste_paquete=1.0, shares=350)
    assert r["paquetes_locates"] == 4
    assert r["coste_total_locates"] == 4.0  # 4 paquetes * $1


def test_opcion_riesgo_calcula_shares():
    # riesgo $100, riesgo/share = 0.20 -> 500 shares -> 5 paquetes.
    r = calc_locates(precio_entrada=2.0, precio_stop=2.2, coste_paquete=2.0, riesgo_dolares=100)
    assert r["shares"] == 500
    assert r["paquetes_locates"] == 5


def test_fade_break_even_total():
    r = calc_locates(precio_entrada=10.0, precio_stop=10.5, coste_paquete=5.0, shares=100)
    # riesgo/share=0.5; coste_total=5 (1 paquete); coste/share=0.05
    # fade_total = (0.5+0.05)/10*100 = 5.5%
    assert r["fade_break_even_total_pct"] == 5.5


def test_stop_debe_estar_encima():
    r = calc_locates(precio_entrada=3.0, precio_stop=2.5, coste_paquete=1.0, shares=100)
    assert "error" in r


def test_faltan_datos():
    assert "error" in calc_locates(precio_entrada=2.0, precio_stop=2.2, coste_paquete=1.0)
