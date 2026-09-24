"""Prealertas POR ESTRATEGIA, y las cuentas de una estrategia en UN mensaje.

24-sep-2026, Jaume: «tienen que haber prealertas, alertas y demas por cada
estrategia (que no por cada cuenta: hay estrategias con mas de una cuenta, y
esas van asociadas a una sola estrategia, por tanto solo una prealerta)».

Lo que fallaba, medido ese dia: 10 prealertas, las 10 de UNA estrategia, aunque
las alertas de cierre salieron para las dos. Dos causas: la matricula de la
prealerta no llevaba la estrategia (la segunda se tiraba como repetida), y el
primer aviso cerraba el minuto (la que se cumplia despues ni se miraba).
"""
import pandas as pd

from app.services.bot_alerts_engine import Evento
from app.services.bot_alerts_prealerta_proceso import clave_prealerta, filtrar_nuevas
from app.services.bot_alerts_telegram import agrupar

MINUTO = pd.Timestamp("2026-09-24 04:02:00")


def _ev(estrategia="A", cuenta=None, tipo="entrada", ticker="WETO", acciones=100):
    return Evento(tipo=tipo, ticker=ticker, strategy_id=f"id-{estrategia}",
                  estrategia=f"Estrategia {estrategia}", momento=MINUTO,
                  precio=2.31, direccion="Short", estado="prealerta",
                  acciones=acciones, cuenta=cuenta)


def test_dos_estrategias_en_el_mismo_ticker_dan_dos_prealertas():
    """EL FALLO DEL 24-sep: la segunda estrategia se tiraba como repetida."""
    vivas = set()
    nuevas = filtrar_nuevas([_ev("A"), _ev("B")], vivas)
    assert [e.strategy_id for e in nuevas] == ["id-A", "id-B"]


def test_la_segunda_estrategia_que_llega_mas_tarde_tambien_sale():
    """La otra mitad del fallo: el primer aviso cerraba el minuto y la
    estrategia que se cumplia unos segundos despues ya no se miraba."""
    vivas = set()
    assert len(filtrar_nuevas([_ev("A")], vivas)) == 1          # segundo 45
    assert filtrar_nuevas([_ev("A")], vivas) == []               # segundo 46: A ya dada
    tarde = filtrar_nuevas([_ev("A"), _ev("B")], vivas)          # segundo 50: B se cumple
    assert [e.strategy_id for e in tarde] == ["id-B"]


def test_la_misma_prealerta_no_se_repite_cada_segundo():
    """Lo que protegia cerrar el minuto: sin filtro, una senyal cumplida en el
    52 saldria en el 53, 54... hasta el 59 — ocho mensajes iguales."""
    vivas = set()
    salidas = [filtrar_nuevas([_ev("A")], vivas) for _ in range(8)]
    assert sum(len(s) for s in salidas) == 1


def test_el_minuto_siguiente_vuelve_a_avisar():
    """La matricula lleva el minuto: una oportunidad nueva no es un repetido."""
    vivas = set()
    filtrar_nuevas([_ev("A")], vivas)
    siguiente = _ev("A")
    siguiente.momento = MINUTO + pd.Timedelta(minutes=1)
    assert len(filtrar_nuevas([siguiente], vivas)) == 1


def test_varias_cuentas_de_una_estrategia_salen_en_un_solo_mensaje():
    """Jaume: las cuentas van asociadas a UNA estrategia → una sola prealerta.
    El motor emite un evento por cuenta (otras acciones); pasan los dos el
    filtro y Telegram los junta en UN mensaje."""
    vivas = set()
    evs = [_ev("A", cuenta=None, acciones=455), _ev("A", cuenta="Cuenta 2", acciones=76)]
    nuevas = filtrar_nuevas(evs, vivas)
    assert len(nuevas) == 2, "cada cuenta lleva sus acciones: los dos eventos viajan"
    grupos = agrupar(nuevas)
    assert len(grupos) == 1, f"deberia ser UN mensaje, salen {len(grupos)}"
    assert len(grupos[0]) == 2


def test_dos_estrategias_con_cuentas_dan_un_mensaje_por_estrategia():
    evs = [_ev("A"), _ev("A", cuenta="Cuenta 2"), _ev("B"), _ev("B", cuenta="Cuenta 2")]
    grupos = agrupar(filtrar_nuevas(evs, set()))
    assert len(grupos) == 2
    assert {g[0].strategy_id for g in grupos} == {"id-A", "id-B"}


def test_la_matricula_distingue_estrategia_tipo_minuto_y_cuenta():
    base = clave_prealerta(_ev("A"))
    assert clave_prealerta(_ev("B")) != base
    assert clave_prealerta(_ev("A", tipo="piramide")) != base
    assert clave_prealerta(_ev("A", cuenta="Cuenta 2")) != base
    assert clave_prealerta(_ev("A")) == base
