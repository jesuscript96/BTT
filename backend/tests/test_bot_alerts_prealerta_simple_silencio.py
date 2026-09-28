# -*- coding: utf-8 -*-
"""Silencio de la prealerta SIMPLE (28-sep-2026, Jaume): tras N prealertas seguidas del mismo ticker y estrategia
con la MISMA condición pendiente y sin entrar, se calla hasta que cambie la condición que falta."""
from app.services.bot_alerts_prealerta_simple import PrealertaSimple


def test_se_calla_tras_n_seguidas_con_la_misma_condicion():
    p = PrealertaSimple(cada_min=10, max_seguidas=3)
    clave = ("AAA", "s1")
    assert [p._silenciada(clave, "Close < Prev. Low Bar") for _ in range(3)] == [False, False, False]
    assert p._silenciada(clave, "Close < Prev. Low Bar") is True          # la 4.ª ya no sale
    assert p._silenciada(clave, "Close < Prev. Low Bar") is True


def test_cambiar_la_condicion_que_falta_reabre_la_boca():
    p = PrealertaSimple(cada_min=10, max_seguidas=3)
    clave = ("AAA", "s1")
    for _ in range(3):
        p._silenciada(clave, "Close < Prev. Low Bar")
    assert p._silenciada(clave, "Close < Prev. Low Bar") is True
    assert p._silenciada(clave, "Volume > 100000") is False                # otra condición: racha nueva
    assert p._silenciada(clave, "Volume > 100000") is False


def test_cada_ticker_y_estrategia_lleva_su_racha_y_soltar_la_borra():
    p = PrealertaSimple(cada_min=10, max_seguidas=2)
    for _ in range(2):
        p._silenciada(("AAA", "s1"), "c")
    assert p._silenciada(("AAA", "s1"), "c") is True
    assert p._silenciada(("AAA", "s2"), "c") is False                       # otra estrategia
    assert p._silenciada(("BBB", "s1"), "c") is False                       # otro ticker
    p.soltar("AAA")
    assert p._silenciada(("AAA", "s1"), "c") is False                       # el ticker salió del radar: de cero
    p.reiniciar()
    assert p._racha == {}


def test_cero_desactiva_el_silencio():
    p = PrealertaSimple(cada_min=10, max_seguidas=0)
    assert all(p._silenciada(("AAA", "s1"), "c") is False for _ in range(10))
