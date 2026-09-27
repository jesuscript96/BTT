"""tokens.py: composición, propiedad por día (R-A-05, R-C-07) y el generador que continúa desde el diario (H-2)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.bot_das import tokens
from app.bot_das.tipos import Origen
from app.bot_das.tokens import (
    DIA_MAX, MAX_SEQ, MAX_TOKEN, GeneradorTokens, TokensAgotados, componer, descomponer, es_nuestro,
)

HOY = date(2026, 9, 25)
DIA_HOY = HOY.timetuple().tm_yday   # 268


# ── componer / descomponer ─────────────────────────────────────────────
@pytest.mark.parametrize("origen", list(Origen), ids=[o.name for o in Origen])
@pytest.mark.parametrize("dia", [1, DIA_HOY, 366], ids=["dia-1", "dia-hoy", "dia-366"])
@pytest.mark.parametrize("seq", [1, 12_345, MAX_SEQ], ids=["seq-1", "seq-12345", "seq-max"])
def test_roundtrip(origen, dia, seq):
    token = componer(origen, dia, seq)
    assert descomponer(token) == (origen, dia, seq)
    assert token == int(origen) * 10**8 + dia * 10**5 + seq
    assert 0 < token <= MAX_TOKEN


def test_maximo_cabe_en_int32():
    """Corrección 9 del juez: 3·10^8 + 366·10^5 + 99 999 = 336 699 999 < 2^31 − 1."""
    assert componer(Origen.EJECUTOR_LOCATE, DIA_MAX, MAX_SEQ) == 336_699_999
    assert 336_699_999 < MAX_TOKEN == 2**31 - 1
    assert MAX_SEQ == 99_999 and DIA_MAX == 366


def test_sin_colision_entre_origenes_ni_dias():
    vistos = set()
    for origen in Origen:
        for dia in (1, 2, DIA_HOY, 365, 366):
            for seq in (1, 2, 500, MAX_SEQ):
                vistos.add(componer(origen, dia, seq))
    assert len(vistos) == len(Origen) * 5 * 4
    assert descomponer(componer(Origen.VIGILANTE, DIA_HOY, 7))[0] is Origen.VIGILANTE   # R-C-07: quién la puso


@pytest.mark.parametrize("origen,dia,seq", [
    pytest.param(Origen.EJECUTOR, DIA_HOY, 0, id="seq-0"),
    pytest.param(Origen.EJECUTOR, DIA_HOY, MAX_SEQ + 1, id="seq-100000"),
    pytest.param(Origen.EJECUTOR, DIA_HOY, -1, id="seq-negativo"),
    pytest.param(Origen.EJECUTOR, 0, 1, id="dia-0"),
    pytest.param(Origen.EJECUTOR, 367, 1, id="dia-367"),
    pytest.param(1, DIA_HOY, 1, id="origen-int-en-vez-de-Origen"),
    pytest.param(4, DIA_HOY, 1, id="origen-4"),
    pytest.param(Origen.EJECUTOR, DIA_HOY, 5.0, id="seq-float"),
    pytest.param(Origen.EJECUTOR, DIA_HOY, True, id="seq-bool"),
    pytest.param(Origen.EJECUTOR, 12.0, 1, id="dia-float"),
])
def test_componer_rechaza_fuera_de_rango(origen, dia, seq):
    with pytest.raises(ValueError):
        componer(origen, dia, seq)


@pytest.mark.parametrize("token", [
    pytest.param(0, id="cero"),
    pytest.param(-100_268_001, id="negativo"),
    pytest.param(400_000_000, id="origen-4"),
    pytest.param(100_000_001, id="dia-0"),
    pytest.param(136_700_001, id="dia-367"),
    pytest.param(126_800_000, id="seq-0"),
    pytest.param(100_268_000, id="parece-de-hoy-pero-es-dia-2-seq-68000-y-se-descompone-asi"),
    pytest.param(42, id="numero-suelto-riesgo-2"),
    pytest.param(2024, id="anyo-al-final-de-notes"),
    pytest.param(2**31 - 1, id="MAX_INT"),
    pytest.param(2**31, id="fuera-de-int32"),
    pytest.param(True, id="bool"),
    pytest.param(100_268_001.0, id="float"),
    pytest.param("100268001", id="texto"),
])
def test_descomponer_devuelve_none_fuera_del_esquema(token):
    if token == 100_268_000:
        assert descomponer(token) == (Origen.EJECUTOR, 2, 68_000)   # el día va en la posición 10^5, no 10^3
        return
    assert descomponer(token) is None


# ── es_nuestro (R-A-05, R-K-02, 2f.5) ──────────────────────────────────
def test_es_nuestro_hoy_si_ayer_y_manana_no():
    hoy = componer(Origen.EJECUTOR, DIA_HOY, 1)
    ayer = componer(Origen.EJECUTOR, DIA_HOY - 1, 1)
    manana = componer(Origen.EJECUTOR, DIA_HOY + 1, 1)
    assert es_nuestro(hoy, HOY) is True
    assert es_nuestro(ayer, HOY) is False          # a propósito: DAY+ caduca a las 20:00 (2f.5), es AJENA para hoy
    assert es_nuestro(manana, HOY) is False
    assert es_nuestro(ayer, HOY - timedelta(days=1)) is True


@pytest.mark.parametrize("token", [None, 42, 2024, 0, 400_000_000, 126_800_000, "100268001", True],
                         ids=["None", "42", "2024", "0", "origen-4", "seq-0", "texto", "bool"])
def test_es_nuestro_rechaza_otro_esquema(token):
    assert es_nuestro(token, HOY) is False


def test_es_nuestro_con_todos_los_origenes():
    for origen in Origen:
        assert es_nuestro(componer(origen, DIA_HOY, 99), HOY) is True


def test_dia_366_en_bisiesto():
    ultimo = date(2028, 12, 31)
    assert ultimo.timetuple().tm_yday == 366
    g = GeneradorTokens(Origen.EJECUTOR, ultimo)
    token = g.siguiente()
    assert descomponer(token) == (Origen.EJECUTOR, 366, 1) and es_nuestro(token, ultimo)


# ── GeneradorTokens ────────────────────────────────────────────────────
def test_generador_empieza_en_1_y_es_nuestro(tokens, reloj):
    primero = tokens.siguiente()
    assert descomponer(primero) == (Origen.EJECUTOR, DIA_HOY, 1)
    assert es_nuestro(primero, reloj.hoy())
    assert tokens.ultimo_seq == 1 and tokens.origen is Origen.EJECUTOR and tokens.hoy == reloj.hoy()
    assert tokens.siguiente() == primero + 1


def test_generador_continua_desde_ultimo_seq_del_diario():
    g = GeneradorTokens(Origen.VIGILANTE, HOY, ultimo_seq=184)
    assert descomponer(g.siguiente()) == (Origen.VIGILANTE, DIA_HOY, 185)   # H-2: nunca repite tras un reinicio


def test_generador_tokens_agotados():
    g = GeneradorTokens(Origen.EJECUTOR, HOY, ultimo_seq=MAX_SEQ - 1)
    assert descomponer(g.siguiente()) == (Origen.EJECUTOR, DIA_HOY, MAX_SEQ)
    with pytest.raises(TokensAgotados):
        g.siguiente()
    with pytest.raises(TokensAgotados):
        g.siguiente()                       # sigue agotado: no se opera más ese día
    assert g.ultimo_seq == MAX_SEQ


@pytest.mark.parametrize("ultimo_seq", [-1, MAX_SEQ + 1, 5.0, True, "5"], ids=["negativo", "pasado", "float", "bool", "texto"])
def test_generador_rechaza_ultimo_seq_invalido(ultimo_seq):
    with pytest.raises(ValueError):
        GeneradorTokens(Origen.EJECUTOR, HOY, ultimo_seq=ultimo_seq)


def test_generador_rechaza_origen_que_no_es_origen():
    with pytest.raises(ValueError):
        GeneradorTokens(1, HOY)   # type: ignore[arg-type]


def test_cambiar_dia_reinicia_la_secuencia_y_mismo_dia_no():
    g = GeneradorTokens(Origen.EJECUTOR, HOY, ultimo_seq=10)
    g.cambiar_dia(HOY)
    assert g.ultimo_seq == 10
    manana = HOY + timedelta(days=1)
    g.cambiar_dia(manana)
    assert g.ultimo_seq == 0 and g.hoy == manana
    token = g.siguiente()
    assert descomponer(token) == (Origen.EJECUTOR, DIA_HOY + 1, 1)
    assert es_nuestro(token, manana) and not es_nuestro(token, HOY)


def test_generadores_de_procesos_distintos_no_chocan():
    ejecutor = GeneradorTokens(Origen.EJECUTOR, HOY)
    vigilante = GeneradorTokens(Origen.VIGILANTE, HOY)
    locate = GeneradorTokens(Origen.EJECUTOR_LOCATE, HOY)
    emitidos = [g.siguiente() for g in (ejecutor, vigilante, locate) for _ in range(3)]
    assert len(set(emitidos)) == 9
    assert {descomponer(t)[0] for t in emitidos} == set(Origen)


def test_modulo_no_ejecuta_nada_al_importar():
    assert tokens.MAX_TOKEN == 2**31 - 1 and callable(tokens.componer)
