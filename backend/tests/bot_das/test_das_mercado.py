"""Tests de `app.bot_das.mercado_das` (§3.12; §10 fila test_das_mercado; riesgos 15 y 17).

Casos obligatorios de §10: `$Quote` parcial no borra bid/ask; `fresca`;
`dollar_volume`; `marcar_halt` cuenta k solo UP en RTH; `suscripciones` con
tope 100 y prioridad; `sin_cotizacion_desde`. Sin red, sin hilos, con el
reloj simulado del conftest.
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest

from app.bot_das.mercado_das import FRESCA_MAX_S, TOLERANCIA_BANDA_PCT, MercadoDAS
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    MAX_LV1,
    MsgBP,
    MsgIssueStatus,
    MsgLDLU,
    MsgQuote,
    MsgShortInfo,
)

AHORA_ET = datetime(2026, 9, 25, 10, 15, tzinfo=ET)


def quote(ticker: str, **campos: str) -> MsgQuote:
    return MsgQuote(cruda="$Quote " + ticker, ticker=ticker, campos=dict(campos))


def estado(ticker: str, ta=None, tat=None, ssr=None) -> MsgIssueStatus:
    return MsgIssueStatus(cruda="$IssueStatus " + ticker, ticker=ticker, ssr=ssr, ta=ta, tat=tat)


def ldlu(ticker: str, down: str, up: str) -> MsgLDLU:
    return MsgLDLU(cruda="$LDLU", ticker=ticker, limit_down=Decimal(down), limit_up=Decimal(up))


@pytest.fixture
def mercado(reloj):
    return MercadoDAS(reloj)


# ── construcción ────────────────────────────────────────────────────────
@pytest.mark.parametrize("valor", [0, -1, True, 1.5], ids=["cero", "negativo", "bool", "no-entero"])
def test_max_lv1_invalido(reloj, valor):
    with pytest.raises(ValueError):
        MercadoDAS(reloj, max_lv1=valor)


def test_tolerancia_negativa(reloj):
    with pytest.raises(ValueError):
        MercadoDAS(reloj, tolerancia_banda_pct=Decimal("-0.1"))


def test_defectos():
    assert MAX_LV1 == 100
    assert TOLERANCIA_BANDA_PCT == Decimal("0.5")
    assert FRESCA_MAX_S == 5.0


# ── $Quote como parche (riesgo 15) ──────────────────────────────────────
def test_quote_completa_convierte_tipos(mercado, reloj):
    t = mercado.aplicar(quote("abc", A="2.51", Asz="300", B="2.50", Bsz="200", V="123456",
                              L="2.505", Hi="3.1", Lo="1.9", VWAP="2.4", T="10:15:01",
                              op="2", ycl="1.8", tcl="1.8", PE="0"))
    assert t == "ABC"
    cot = mercado.cotizacion("ABC")
    assert (cot.ask, cot.bid, cot.last, cot.hi, cot.lo, cot.vwap) == (
        Decimal("2.51"), Decimal("2.50"), Decimal("2.505"), Decimal("3.1"), Decimal("1.9"), Decimal("2.4"))
    assert all(isinstance(x, Decimal) for x in (cot.ask, cot.bid, cot.last, cot.vwap))
    assert (cot.asz, cot.bsz, cot.volumen) == (300, 200, 123456)
    assert all(type(x) is int for x in (cot.asz, cot.bsz, cot.volumen))
    assert cot.hora_servidor == "10:15:01"
    assert cot.actualizada_en == reloj.mono()


@pytest.mark.parametrize("parche", [{"V": "1000"}, {"L": "2.6"}, {"Asz": "100"}, {}],
                         ids=["riesgo15-solo-V", "riesgo15-solo-L", "riesgo15-solo-Asz", "riesgo15-vacio"])
def test_quote_parcial_no_borra_bid_ask(mercado, reloj, parche):
    mercado.aplicar(quote("ABC", A="2.51", B="2.50"))
    reloj.avanzar(3)
    mercado.aplicar(quote("ABC", **parche))
    cot = mercado.cotizacion("ABC")
    assert cot.bid == Decimal("2.50") and cot.ask == Decimal("2.51")
    assert cot.actualizada_en == reloj.mono()


@pytest.mark.parametrize("valor", ["", "abc", "NaN", "Infinity", "-inf", "1,5"],
                         ids=["vacio", "texto", "nan", "inf", "menos-inf", "coma"])
def test_quote_valor_no_numerico_se_ignora(mercado, valor):
    mercado.aplicar(quote("ABC", A="2.51", B="2.50", V="100", L="2.5"))
    mercado.aplicar(quote("ABC", A=valor, V=valor, L=valor))
    cot = mercado.cotizacion("ABC")
    assert cot.ask == Decimal("2.51") and cot.volumen == 100 and cot.last == Decimal("2.5")
    assert mercado.foto()["campos_ignorados"] == 3


@pytest.mark.parametrize("valor", ["-5", "1.5"], ids=["negativo", "fraccion"])
def test_quote_entero_invalido_se_ignora(mercado, valor):
    mercado.aplicar(quote("ABC", Bsz="200"))
    mercado.aplicar(quote("ABC", Bsz=valor))
    assert mercado.cotizacion("ABC").bsz == 200


def test_quote_entero_con_decimales_cero(mercado):
    mercado.aplicar(quote("ABC", V="1500.0"))
    assert mercado.cotizacion("ABC").volumen == 1500


def test_quote_cero_explicito_borra(mercado, reloj):
    """B:0 / A:0 (halt, fuera de horario) no son precios: bid/ask quedan None y ya no es fresca."""
    mercado.aplicar(quote("ABC", A="2.51", B="2.50"))
    assert mercado.fresca("ABC", reloj.mono())
    mercado.aplicar(quote("ABC", B="0"))
    assert mercado.cotizacion("ABC").bid is None
    assert not mercado.fresca("ABC", reloj.mono())


def test_quote_claves_sin_mayusculas_y_desconocidas(mercado):
    mercado.aplicar(quote("ABC", a="1.01", b="1.00", vwap="1.005", RVOL="3", tradesAllDay="9"))
    cot = mercado.cotizacion("ABC")
    assert (cot.ask, cot.bid, cot.vwap) == (Decimal("1.01"), Decimal("1.00"), Decimal("1.005"))
    assert mercado.foto()["campos_ignorados"] == 0


def test_quote_ticker_vacio(mercado):
    assert mercado.aplicar(quote("  ", A="1")) is None
    assert mercado.foto()["cotizaciones"] == 0


def test_mensaje_ajeno_se_ignora(mercado):
    assert mercado.aplicar(MsgBP(cruda="BP 1 1", bp=Decimal("1"), bp_overnight=Decimal("1"))) is None


def test_cotizacion_de_ticker_desconocido(mercado):
    assert mercado.cotizacion("NADA") is None


# ── estado del símbolo ─────────────────────────────────────────────────
def test_issue_status_ssr_y_halt(mercado, reloj):
    assert mercado.aplicar(estado("abc", ta="H", tat="10:00:00", ssr=True)) == "ABC"
    simb = mercado.simbolo("ABC")
    assert (simb.ssr, simb.ta, simb.tat, simb.consultado_en) == (True, "H", "10:00:00", reloj.mono())
    mercado.aplicar(estado("ABC"))   # sin TA = normal; ssr ausente conserva el anterior
    assert simb.ta is None and simb.tat is None and simb.ssr is True
    # `aplicar` no toca la transición de halt ni k
    assert simb.halt_desde is None and simb.k_halts_up == 0


def test_ldlu(mercado):
    assert mercado.aplicar(ldlu("ABC", "1.80", "2.20")) == "ABC"
    simb = mercado.simbolo("ABC")
    assert (simb.limit_down, simb.limit_up) == (Decimal("1.80"), Decimal("2.20"))
    mercado.aplicar(ldlu("ABC", "0", "2.20"))
    assert simb.limit_down is None


def test_shortinfo(mercado):
    msg = MsgShortInfo(cruda="$SHORTINFO", ticker="ABC", shortable=True, short_size=1000, marginable=True,
                       tasa_larga=Decimal("0"), tasa_corta=Decimal("12.5"), prohibido=False, reg_sho=True)
    assert mercado.aplicar(msg) == "ABC"
    simb = mercado.simbolo("ABC")
    assert (simb.shortable, simb.tasa_corta, simb.reg_sho) == (True, Decimal("12.5"), True)


def test_estado_con_ticker_vacio_no_crea_simbolo(mercado):
    assert mercado.aplicar(estado(" ", ta="H")) is None
    assert mercado.aplicar(ldlu("", "1", "2")) is None
    assert mercado.foto()["halts"] == {}


def test_simbolo_se_crea_vacio(mercado):
    simb = mercado.simbolo("xyz")
    assert simb.ticker == "XYZ" and simb.k_halts_up == 0 and simb.halt_desde is None
    assert mercado.simbolo("XYZ") is simb


# ── fresca (riesgo 15, R-B-01 «sin cotización no se entra») ─────────────
def test_fresca_limites(mercado, reloj):
    assert not mercado.fresca("ABC", reloj.mono())
    mercado.aplicar(quote("ABC", A="2.51"))
    assert not mercado.fresca("ABC", reloj.mono())          # falta bid
    mercado.aplicar(quote("ABC", B="2.50"))
    t0 = reloj.mono()
    assert mercado.fresca("ABC", t0)
    assert mercado.fresca("ABC", t0 + 5.0)                   # justo en el límite
    assert not mercado.fresca("ABC", t0 + 5.01)
    assert mercado.fresca("ABC", t0 + 9, max_s=10)


def test_fresca_parche_refresca(mercado, reloj):
    mercado.aplicar(quote("ABC", A="2.51", B="2.50"))
    reloj.avanzar(4)
    mercado.aplicar(quote("ABC", V="10"))                    # riesgo 15: el parche mantiene viva la cotización
    reloj.avanzar(4)
    assert mercado.fresca("ABC", reloj.mono())


def test_fresca_libro_cruzado(mercado, reloj):
    mercado.aplicar(quote("ABC", A="2.49", B="2.50"))
    assert not mercado.fresca("ABC", reloj.mono())


# ── dollar_volume (R-I-04) ──────────────────────────────────────────────
def test_dollar_volume(mercado):
    assert mercado.dollar_volume("ABC") is None
    mercado.aplicar(quote("ABC", V="1000000"))
    assert mercado.dollar_volume("ABC") is None              # falta VWAP
    mercado.aplicar(quote("ABC", VWAP="2.0"))
    dv = mercado.dollar_volume("ABC")
    assert dv == Decimal("2000000") and isinstance(dv, Decimal)
    mercado.aplicar(quote("ABC", V="999999"))
    assert mercado.dollar_volume("ABC") == Decimal("1999998.0")


def test_dollar_volume_sin_volumen(mercado):
    mercado.aplicar(quote("ABC", VWAP="3"))
    assert mercado.dollar_volume("ABC") is None


# ── marcar_halt (R-F-01: k solo UP en RTH) ──────────────────────────────
def _preparar(mercado, last="2.20", up="2.20", down="1.80"):
    mercado.aplicar(ldlu("ABC", down, up))
    mercado.aplicar(quote("ABC", A="2.21", B="2.19", L=last))


@pytest.mark.parametrize("franja, last, k", [
    ("RTH", "2.20", 1),                    # en la banda
    ("RTH", "2.189", 1),                   # a 0,5 % de la banda (tolerancia)
    ("RTH", "2.1889", 0),                  # justo por debajo de la tolerancia
    ("RTH (media sesion)", "2.20", 1),
    ("premercado", "2.20", 0),             # T1/T12: no suma k
    ("postmercado", "2.20", 0),
    ("RTH", "1.80", 0),                    # halt DOWN
], ids=["R-F-01-up-rth", "R-F-01-tolerancia", "R-F-01-bajo-tolerancia", "R-F-01-media-sesion",
        "R-F-01-pm-no-cuenta", "R-F-01-post-no-cuenta", "R-F-01-down-no-cuenta"])
def test_marcar_halt_k(mercado, franja, last, k):
    _preparar(mercado)
    r = mercado.marcar_halt("ABC", estado("ABC", ta="P", tat="10:15:00"), AHORA_ET, Decimal(last), franja)
    simb = mercado.simbolo("ABC")
    assert r == "halt"
    assert simb.k_halts_up == k
    assert simb.precio_parada == Decimal(last)
    assert simb.halt_desde == datetime(2026, 9, 25, 10, 15, tzinfo=ET)
    assert simb.orden_open_enviada is False


def test_marcar_halt_sin_bandas_no_cuenta(mercado):
    r = mercado.marcar_halt("ABC", estado("ABC", ta="H"), AHORA_ET, Decimal("5"), "RTH")
    assert r == "halt" and mercado.simbolo("ABC").k_halts_up == 0


def test_marcar_halt_ciclo_completo_y_repetido(mercado):
    """R-F-01 + injerto §8.23 (riesgo 27): $IssueStatus repetido no es otro halt ni resetea la guardia."""
    _preparar(mercado)
    simb = mercado.simbolo("ABC")
    assert mercado.marcar_halt("ABC", estado("ABC", ta="P", tat="10:15:00"), AHORA_ET, Decimal("2.2"), "RTH") == "halt"
    simb.orden_open_enviada = True                           # el decisor ya mandó la OPEN
    assert mercado.marcar_halt("ABC", estado("ABC", ta="P", tat="10:15:00"), AHORA_ET, Decimal("2.2"), "RTH") is None
    assert mercado.marcar_halt("ABC", estado("ABC", ta="H", tat="10:16:00"), AHORA_ET, Decimal("2.2"), "RTH") is None
    assert simb.k_halts_up == 1 and simb.orden_open_enviada is True
    assert mercado.marcar_halt("ABC", estado("ABC", ta="T", tat="10:20:00"), AHORA_ET, Decimal("2.5"), "RTH") == "reapertura"
    assert simb.halt_desde is None and simb.orden_open_enviada is False
    assert simb.precio_parada == Decimal("2.2")              # se conserva para medir la subida (R-F-05)
    assert mercado.marcar_halt("ABC", estado("ABC"), AHORA_ET, Decimal("2.5"), "RTH") is None
    # segundo halt UP: k = 2
    mercado.aplicar(ldlu("ABC", "2.2", "2.64"))
    assert mercado.marcar_halt("ABC", estado("ABC", ta="P", tat="10:30:00"), AHORA_ET, Decimal("2.64"), "RTH") == "halt"
    assert simb.k_halts_up == 2 and simb.precio_parada == Decimal("2.64")


@pytest.mark.parametrize("ta", ["Q", "T", None], ids=["R-F-01-Q", "R-F-01-T", "R-F-01-sin-TA"])
def test_reapertura_con_cualquier_ta_no_parado(mercado, ta):
    mercado.marcar_halt("ABC", estado("ABC", ta="H"), AHORA_ET, Decimal("2"), "RTH")
    assert mercado.marcar_halt("ABC", estado("ABC", ta=ta), AHORA_ET, None, "RTH") == "reapertura"


def test_marcar_halt_sin_estado_previo_no_es_reapertura(mercado):
    assert mercado.marcar_halt("ABC", estado("ABC", ta="T"), AHORA_ET, None, "RTH") is None


def test_marcar_halt_tras_aplicar_mismo_mensaje(mercado):
    """La transición va por halt_desde, no por el TA anterior: da igual que el decisor llamara antes a aplicar."""
    msg = estado("ABC", ta="H", tat="10:00:00")
    mercado.aplicar(msg)
    assert mercado.marcar_halt("ABC", msg, AHORA_ET, Decimal("2"), "RTH") == "halt"


@pytest.mark.parametrize("tat", [None, "25:00:00", "basura"], ids=["sin-tat", "tat-fuera-rango", "tat-mal"])
def test_halt_desde_sin_tat_valido_usa_ahora(mercado, tat):
    mercado.marcar_halt("ABC", estado("ABC", ta="H", tat=tat), AHORA_ET, Decimal("2"), "RTH")
    assert mercado.simbolo("ABC").halt_desde == AHORA_ET


def test_halt_desde_ahora_naive_es_et(mercado):
    mercado.marcar_halt("ABC", estado("ABC", ta="H"), datetime(2026, 9, 25, 11, 0), Decimal("2"), "RTH")
    assert mercado.simbolo("ABC").halt_desde == datetime(2026, 9, 25, 11, 0, tzinfo=ET)


def test_precio_parada_del_libro_si_no_hay_last(mercado):
    _preparar(mercado, last="2.20")
    mercado.marcar_halt("ABC", estado("ABC", ta="P"), AHORA_ET, None, "RTH")
    simb = mercado.simbolo("ABC")
    assert simb.precio_parada == Decimal("2.20") and simb.k_halts_up == 1


def test_precio_parada_float_se_convierte(mercado):
    mercado.marcar_halt("ABC", estado("ABC", ta="P"), AHORA_ET, 2.2, "RTH")
    assert mercado.simbolo("ABC").precio_parada == Decimal("2.2")


# ── suscripciones (manual L1996, riesgo 17) ─────────────────────────────
def test_suscripciones_altas_bajas_idempotente(mercado):
    altas, bajas = mercado.suscripciones({"aaa", "BBB"}, {"CCC"}, {"DDD"})
    assert altas == ["AAA", "BBB", "CCC", "DDD"] and bajas == []
    assert mercado.suscripciones({"AAA", "BBB"}, {"CCC"}, {"DDD"}) == ([], [])
    altas, bajas = mercado.suscripciones({"AAA"}, set(), {"EEE"})
    assert altas == ["EEE"] and bajas == ["BBB", "CCC", "DDD"]
    assert mercado.suscritos() == ["AAA", "EEE"]


def test_suscripciones_tope_100_y_prioridad(mercado):
    posiciones = {f"P{i:03d}" for i in range(10)}
    intentos = {f"I{i:03d}" for i in range(20)}
    radar = {f"R{i:03d}" for i in range(200)}
    altas, bajas = mercado.suscripciones(posiciones, intentos, radar)
    assert len(altas) == 100 and bajas == []
    assert altas[:10] == sorted(posiciones) and altas[10:30] == sorted(intentos)
    assert altas[30:] == sorted(radar)[:70]
    assert mercado.foto()["descartados_por_tope"] == 130
    # llega una posición nueva: entra y sale el último del radar
    altas, bajas = mercado.suscripciones(posiciones | {"ZNEW"}, intentos, radar)
    assert altas == ["ZNEW"] and bajas == [sorted(radar)[69]]
    assert len(mercado.suscritos()) == 100


def test_suscripciones_duplicado_cuenta_una_vez_con_su_mayor_prioridad(reloj):
    m = MercadoDAS(reloj, max_lv1=2)
    altas, _ = m.suscripciones({"AAA"}, set(), {"AAA", "BBB", "CCC"})
    assert altas == ["AAA", "BBB"]
    assert m.foto()["descartados_por_tope"] == 1


def test_suscripciones_con_dict(mercado):
    altas, bajas = mercado.suscripciones({"posiciones": ["AAA"], "radar": ["ZZZ"], "intentos": ["MMM"]})
    assert altas == ["AAA", "MMM", "ZZZ"] and bajas == []


def test_suscripciones_dict_clave_desconocida_no_toca_estado(mercado):
    mercado.suscripciones({"AAA"})
    with pytest.raises(ValueError):
        mercado.suscripciones({"posiciones": ["BBB"], "otros": ["CCC"]})
    assert mercado.suscritos() == ["AAA"]


def test_suscripciones_texto_suelto_es_error(mercado):
    with pytest.raises(TypeError):
        mercado.suscripciones("AAPL")
    with pytest.raises(TypeError):
        mercado.suscripciones({"posiciones": "AAPL"})
    assert mercado.suscritos() == []


def test_suscripciones_marca_momento_y_reinicio(mercado, reloj):
    mercado.suscripciones({"AAA"})
    t0 = reloj.mono()
    assert mercado.suscrito_en("aaa") == t0
    assert mercado.suscrito_en("BBB") is None
    mercado.reiniciar_suscripciones()
    reloj.avanzar(2)
    altas, bajas = mercado.suscripciones({"AAA"})
    assert altas == ["AAA"] and bajas == []                  # tras reconectar se repite el alta
    assert mercado.suscrito_en("AAA") == t0 + 2


# ── sin_cotizacion_desde (A7) ───────────────────────────────────────────
def test_sin_cotizacion_desde(mercado, reloj):
    mercado.suscripciones({"ABC"})
    t0 = mercado.suscrito_en("ABC")
    assert not mercado.sin_cotizacion_desde("ABC", t0, t0 + 4.9)     # aún en plazo
    assert mercado.sin_cotizacion_desde("ABC", t0, t0 + 5.0)         # A7: no casa
    reloj.avanzar(1)
    mercado.aplicar(quote("ABC", L="2"))
    assert not mercado.sin_cotizacion_desde("ABC", t0, t0 + 10)


def test_sin_cotizacion_desde_quote_anterior_no_cuenta(mercado, reloj):
    mercado.aplicar(quote("ABC", L="2"))
    reloj.avanzar(10)
    t_sus = reloj.mono()
    assert mercado.sin_cotizacion_desde("ABC", t_sus, t_sus + 6)
    assert mercado.sin_cotizacion_desde("ABC", t_sus, t_sus + 3, max_s=2)


# ── foto ────────────────────────────────────────────────────────────────
def test_foto_serializable(mercado):
    mercado.suscripciones({"ABC"})
    mercado.aplicar(quote("ABC", A="2.21", B="2.19", L="2.2", V="10"))
    _preparar(mercado)
    mercado.marcar_halt("ABC", estado("ABC", ta="P", tat="10:15:00"), AHORA_ET, Decimal("2.2"), "RTH")
    foto = mercado.foto()
    json.dumps(foto)
    assert foto["max_lv1"] == 100 and foto["suscritos"] == 1
    assert foto["tickers"]["ABC"]["bid"] == "2.19"
    assert foto["halts"]["ABC"]["k_halts_up"] == 1
    assert foto["halts"]["ABC"]["halt_desde"].startswith("2026-09-25T10:15:00")
