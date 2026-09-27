"""reglas/capital.py: márgenes de Sage por tramo, BP legible, tope corto 1×/0,5×, orden de llegada y exposición corta (libro 2c, R-I-01, R-E-02, R-K-03)."""
from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from app.bot_das.reglas import capital
from app.bot_das.reglas.capital import (
    MOTIVO_BP_AGOTADO, MOTIVO_ENTERA, MOTIVO_NADA_PEDIDO, MOTIVO_PARCIAL_BP, MOTIVO_PARCIAL_TOPE, MOTIVO_SIN_BP,
    MOTIVO_SIN_EQUITY, MOTIVO_TOPE_ALCANZADO, TOPE_CORTO_EQUITY, TOPE_CORTO_EQUITY_ALTO_RIESGO,
    acciones_que_caben, exposicion_corta, liberar_reservas, margen_inicial_corto, margen_mantenimiento,
    requiere_mas_margen, reservar,
)
from app.bot_das.tipos import (
    RECONCILIACION_CADUCA_S, Cotizacion, Cuenta, FaseIntento, IntentoEntrada, Lote, PosicionTicker,
)

D = Decimal
LEIDA_EN = 1000.0
AHORA = 1005.0


def _cuenta(bp: Optional[str] = "10000", equity: Optional[str] = "10000", leida_en: Optional[float] = LEIDA_EN,
            reservado: str = "0") -> Cuenta:
    return Cuenta(bp=None if bp is None else D(bp), equity=None if equity is None else D(equity),
                  leida_en=leida_en, bp_reservado=D(reservado))


def _caben(qty: int, precio: str, cuenta: Optional[Cuenta] = None, tasa: Optional[str] = None,
           exposicion: str = "0", alto_riesgo: bool = False, ahora: float = AHORA, **kw) -> tuple[int, str]:
    return acciones_que_caben(qty, D(precio), cuenta if cuenta is not None else _cuenta(),
                              None if tasa is None else D(tasa), D(exposicion), alto_riesgo, ahora, **kw)


# ── margen inicial de cortos (2c, Reg T de Sage) ─────────────────────────
@pytest.mark.parametrize("precio,qty,tasa,esperado", [
    pytest.param("0.9", 1000, None, "2500", id="2c-0.90-bajo-5-manda-2.50-por-accion"),
    pytest.param("1", 1000, None, "2500", id="2c-ejemplo-del-libro-1000-a-1-exige-2500"),
    pytest.param("0.1234", 1000, None, "2500", id="2c-penny-manda-2.50-por-accion"),
    pytest.param("2.5", 100, None, "250", id="2c-2.50-empate-por-accion-y-valor"),
    pytest.param("3", 1000, None, "3000", id="2c-3-bajo-5-manda-100pct-del-valor"),
    pytest.param("4.99", 100, None, "499", id="2c-4.99-100pct"),
    pytest.param("5", 100, None, "500", id="2c-5-desde-5-manda-5-por-accion"),
    pytest.param("16.66", 100, None, "500", id="2c-16.66-5-por-accion"),
    pytest.param("16.67", 100, None, "500.100", id="2c-16.67-manda-30pct"),
    pytest.param("20", 100, None, "600", id="2c-20-30pct"),
    pytest.param("20", 100, "0", "600", id="SHORTINFO-tasa-0-es-la-de-defecto"),
    pytest.param("20", 100, "100", "2000", id="SHORTINFO-tasa-100-todo-en-efectivo"),
    pytest.param("20", 100, "300", "6000", id="SHORTINFO-tasa-300-HTB"),
    pytest.param("3", 100, "50", "300", id="SHORTINFO-tasa-menor-no-rebaja-el-RegT"),
    pytest.param("3", 0, None, "0", id="2c-cero-acciones-cero-margen"),
])
def test_margen_inicial_corto(precio, qty, tasa, esperado):
    valor = margen_inicial_corto(D(precio), qty, None if tasa is None else D(tasa))
    assert type(valor) is Decimal
    assert valor == D(esperado)


def test_margen_inicial_es_lineal_en_acciones():
    """La base de `acciones_que_caben`: margen(q) = q · margen(1) en todos los tramos y con tasa."""
    for precio in ("0.0001", "0.5", "2.49", "2.5", "4.99", "5", "12.34", "16.67", "99.99"):
        for tasa in (None, D("0"), D("100"), D("250")):
            uno = margen_inicial_corto(D(precio), 1, tasa)
            for q in (1, 7, 100, 12345):
                assert margen_inicial_corto(D(precio), q, tasa) == uno * q


@pytest.mark.parametrize("precio,qty,tasa", [
    pytest.param(3.0, 100, None, id="R12-precio-float"),
    pytest.param(D("NaN"), 100, None, id="R12-precio-NaN"),
    pytest.param(D("Infinity"), 100, None, id="R12-precio-inf"),
    pytest.param(D("0"), 100, None, id="precio-cero"),
    pytest.param(D("-1"), 100, None, id="precio-negativo"),
    pytest.param("3", 100, None, id="precio-texto"),
    pytest.param(D("3"), 100.0, None, id="R12-qty-float"),
    pytest.param(D("3"), True, None, id="qty-bool"),
    pytest.param(D("3"), -1, None, id="qty-negativa"),
    pytest.param(D("3"), 100, D("-1"), id="tasa-negativa"),
    pytest.param(D("3"), 100, 100.0, id="R12-tasa-float"),
    pytest.param(D("3"), 100, D("NaN"), id="tasa-NaN"),
])
def test_margen_inicial_corto_rechaza_argumentos_invalidos(precio, qty, tasa):
    with pytest.raises(ValueError):
        margen_inicial_corto(precio, qty, tasa)


# ── margen de mantenimiento (2c, FINRA 4210) ─────────────────────────────
@pytest.mark.parametrize("precio,qty,esperado", [
    pytest.param("0.9", 100, "250", id="2c-0.90-2.50-por-accion"),
    pytest.param("2.49", 100, "250", id="2c-2.49-2.50-por-accion"),
    pytest.param("2.5", 100, "250", id="2c-2.50-100pct"),
    pytest.param("3", 100, "300", id="2c-3-100pct"),
    pytest.param("4.99", 100, "499", id="2c-4.99-100pct"),
    pytest.param("5", 100, "500", id="2c-5-5-por-accion"),
    pytest.param("16.66", 100, "500", id="2c-16.66-5-por-accion"),
    pytest.param("16.67", 100, "500.100", id="2c-16.67-30pct"),
    pytest.param("20", 100, "600", id="2c-20-30pct"),
    pytest.param("20", 0, "0", id="2c-cero-acciones"),
])
def test_margen_mantenimiento(precio, qty, esperado):
    valor = margen_mantenimiento(D(precio), qty)
    assert type(valor) is Decimal
    assert valor == D(esperado)


@pytest.mark.parametrize("precio,qty", [
    pytest.param(20.0, 100, id="R12-precio-float"),
    pytest.param(D("NaN"), 100, id="precio-NaN"),
    pytest.param(D("0"), 100, id="precio-cero"),
    pytest.param(D("20"), 1.5, id="R12-qty-fraccionaria"),
    pytest.param(D("20"), -100, id="qty-negativa"),
])
def test_margen_mantenimiento_rechaza_argumentos_invalidos(precio, qty):
    with pytest.raises(ValueError):
        margen_mantenimiento(precio, qty)


def test_margen_mantenimiento_igual_que_el_del_vigilante():
    """Dos copias de los tramos FINRA (regla de reparto §12): deben dar lo mismo en todos los límites."""
    vigilancia = pytest.importorskip("app.bot_das.reglas.vigilancia")
    for precio in ("0.0001", "0.5", "2.49", "2.5", "4.99", "5", "10", "16.66", "16.67", "30", "250"):
        for qty in (0, 1, 100, 4321):
            assert margen_mantenimiento(D(precio), qty) == vigilancia.margen_mantenimiento_corto(D(precio), qty)


# ── requiere_mas_margen (2c consecuencia 4) ──────────────────────────────
@pytest.mark.parametrize("antes,ahora,esperado", [
    pytest.param("5.20", "4.90", True, id="2c-ejemplo-libro-5.20-a-4.90-del-30-al-100pct"),
    pytest.param("16.67", "16.66", True, id="2c-cruza-16.67-hacia-abajo"),
    pytest.param("2.50", "2.49", True, id="2c-cruza-2.50-hacia-abajo"),
    pytest.param("30", "2", True, id="2c-salta-varios-tramos"),
    pytest.param("4.90", "5.20", False, id="2c-sube-de-precio-menos-exigente"),
    pytest.param("5.20", "5.10", False, id="2c-mismo-tramo"),
    pytest.param("2.49", "0.50", False, id="2c-ya-en-el-tramo-mas-bajo"),
    pytest.param("5", "5", False, id="2c-mismo-precio"),
    pytest.param("5", "4.99", True, id="2c-limite-exacto-5"),
])
def test_requiere_mas_margen(antes, ahora, esperado):
    assert requiere_mas_margen(D(antes), D(ahora)) is esperado


def test_requiere_mas_margen_rechaza_float():
    with pytest.raises(ValueError):
        requiere_mas_margen(5.2, D("4.9"))
    with pytest.raises(ValueError):
        requiere_mas_margen(D("5.2"), 4.9)


# ── acciones_que_caben: BP y tope corto (R-I-01, 2c, R-K-03) ─────────────
@pytest.mark.parametrize("qty,precio,cuenta,tasa,exposicion,alto_riesgo,esperado", [
    pytest.param(1000, "1", _cuenta(), None, "0", False, (1000, MOTIVO_ENTERA),
                 id="R-I-01-libre-mayor-que-lo-pedido-entra-entera"),
    pytest.param(5000, "1", _cuenta(), None, "0", False, (4000, MOTIVO_PARCIAL_BP),
                 id="2c-ejemplo-libro-10k-a-1-caben-4000"),
    pytest.param(3000, "5", _cuenta(bp="40000"), None, "0", False, (2000, MOTIVO_PARCIAL_TOPE),
                 id="2c-tope-corto-1x-equity"),
    pytest.param(3000, "5", _cuenta(bp="40000"), None, "0", True, (1000, MOTIVO_PARCIAL_TOPE),
                 id="2c-tope-corto-0.5x-alto-riesgo"),
    pytest.param(3000, "5", _cuenta(bp="40000"), None, "9500", False, (100, MOTIVO_PARCIAL_TOPE),
                 id="2c-tope-descuenta-la-exposicion-abierta"),
    pytest.param(3000, "5", _cuenta(bp="40000"), None, "10000", False, (0, MOTIVO_TOPE_ALCANZADO),
                 id="2c-tope-alcanzado-no-entra"),
    pytest.param(3000, "5", _cuenta(bp="40000"), None, "12000", False, (0, MOTIVO_TOPE_ALCANZADO),
                 id="2c-tope-superado-no-entra"),
    pytest.param(1000, "1", _cuenta(bp="1000", reservado="1000"), None, "0", False, (0, MOTIVO_BP_AGOTADO),
                 id="R-I-01-sin-capital-libre-no-entra"),
    pytest.param(1000, "1", _cuenta(bp="-50"), None, "0", False, (0, MOTIVO_BP_AGOTADO),
                 id="R-I-01-BP-negativo-no-entra"),
    pytest.param(1000, "1", _cuenta(bp="2"), None, "0", False, (0, MOTIVO_BP_AGOTADO),
                 id="R-I-01-no-cabe-ni-una-accion"),
    pytest.param(1000, "20", _cuenta(), None, "0", False, (500, MOTIVO_PARCIAL_TOPE),
                 id="2c-20-dolares-tope-1x-500-acciones"),
    pytest.param(1000, "20", _cuenta(), "100", "0", False, (500, MOTIVO_PARCIAL_BP),
                 id="SHORTINFO-tasa-100-limita-por-BP-empate-nombra-BP"),
    pytest.param(1000, "20", _cuenta(), "300", "0", False, (166, MOTIVO_PARCIAL_BP),
                 id="SHORTINFO-tasa-300-limita-mas"),
    pytest.param(1000, "0.1234", _cuenta(), None, "0", False, (1000, MOTIVO_ENTERA),
                 id="2c-penny-2.50-por-accion-cabe"),
    pytest.param(5000, "0.1234", _cuenta(bp="11111.11"), None, "0", False, (4444, MOTIVO_PARCIAL_BP),
                 id="2c-penny-floor-multiplo-de-una-accion"),
    pytest.param(0, "1", _cuenta(), None, "0", False, (0, MOTIVO_NADA_PEDIDO), id="R-I-01-nada-pedido"),
    pytest.param(1000, "1", _cuenta(equity="-100"), None, "0", False, (0, MOTIVO_TOPE_ALCANZADO),
                 id="2c-equity-negativo-no-entra"),
])
def test_acciones_que_caben(qty, precio, cuenta, tasa, exposicion, alto_riesgo, esperado):
    resultado = _caben(qty, precio, cuenta, tasa, exposicion, alto_riesgo)
    assert resultado == esperado
    assert type(resultado[0]) is int


@pytest.mark.parametrize("cuenta,ahora,esperado", [
    pytest.param(_cuenta(), AHORA, (1000, MOTIVO_ENTERA), id="R-K-03-BP-de-hace-5-s"),
    pytest.param(_cuenta(), LEIDA_EN + RECONCILIACION_CADUCA_S, (1000, MOTIVO_ENTERA),
                 id="R-K-03-BP-de-30-s-exactos-aun-vale"),
    pytest.param(_cuenta(), LEIDA_EN + RECONCILIACION_CADUCA_S + 0.01, (0, MOTIVO_SIN_BP),
                 id="R-K-03-BP-viejo-mas-de-30-s-no-entra"),
    pytest.param(_cuenta(), LEIDA_EN + 3600.0, (0, MOTIVO_SIN_BP), id="R-K-03-BP-de-hace-una-hora"),
    pytest.param(_cuenta(leida_en=None), AHORA, (0, MOTIVO_SIN_BP), id="R-I-01-BP-nunca-leido"),
    pytest.param(_cuenta(bp=None), AHORA, (0, MOTIVO_SIN_BP), id="R-I-01-sin-valor-de-BP"),
    pytest.param(_cuenta(), LEIDA_EN - 0.5, (0, MOTIVO_SIN_BP), id="R-I-01-lectura-en-el-futuro-no-legible"),
    pytest.param(_cuenta(equity=None), AHORA, (0, MOTIVO_SIN_EQUITY), id="2c-sin-equity-no-hay-tope-no-entra"),
    pytest.param(_cuenta(bp=None, equity=None), AHORA, (0, MOTIVO_SIN_BP), id="R-I-01-sin-BP-manda-sobre-equity"),
])
def test_acciones_que_caben_bp_legible(cuenta, ahora, esperado):
    assert _caben(1000, "1", cuenta, ahora=ahora) == esperado


def test_acciones_que_caben_max_edad_configurable():
    """R-K-03: los 30 s son el defecto; el decisor puede pasar `tecnicos.reconciliacion_fallida_s`."""
    assert _caben(1000, "1", _cuenta(), ahora=LEIDA_EN + 10.0, max_edad_s=5.0) == (0, MOTIVO_SIN_BP)
    assert _caben(1000, "1", _cuenta(), ahora=LEIDA_EN + 10.0, max_edad_s=10.0) == (1000, MOTIVO_ENTERA)


def test_acciones_que_caben_no_muta_la_cuenta():
    """Pura: dimensionar no reserva (lo hace `reservar` con la cantidad FINAL)."""
    cuenta = _cuenta(reservado="100")
    antes = (cuenta.bp, cuenta.equity, cuenta.leida_en, cuenta.bp_reservado)
    _caben(1000, "1", cuenta)
    assert (cuenta.bp, cuenta.equity, cuenta.leida_en, cuenta.bp_reservado) == antes


@pytest.mark.parametrize("precio", ["0.0001", "0.0999", "0.7777", "1", "2.49", "2.5", "3.33", "4.99", "5", "7.13",
                                    "16.66", "16.67", "33.33"])
@pytest.mark.parametrize("tasa", [None, "100", "175"])
@pytest.mark.parametrize("bp", ["1", "999.99", "10000", "12345.67"])
def test_acciones_que_caben_es_el_maximo_exacto_por_bp(precio, tasa, bp):
    """2c consecuencia 1: lo que cabe por BP es el MÁXIMO q con margen(q) ≤ BP libre (ni una acción más ni una menos)."""
    cuenta = _cuenta(bp=bp, equity="1000000000", reservado="0.5")
    t = None if tasa is None else D(tasa)
    qty, motivo = acciones_que_caben(10**9, D(precio), cuenta, t, D("0"), False, AHORA)
    libre = D(bp) - D("0.5")
    assert margen_inicial_corto(D(precio), qty, t) <= libre
    assert margen_inicial_corto(D(precio), qty + 1, t) > libre
    assert motivo == (MOTIVO_PARCIAL_BP if qty > 0 else MOTIVO_BP_AGOTADO)


def test_acciones_que_caben_tope_es_nominal_exacto():
    """2c consecuencia 2: q·precio + exposición ≤ tope y (q+1)·precio lo supera."""
    for precio in ("0.0123", "1.01", "4.99", "6.66", "17"):
        for alto in (False, True):
            qty, motivo = acciones_que_caben(10**9, D(precio), _cuenta(bp="1000000000"), None, D("1234.56"), alto,
                                             AHORA)
            tope = D("10000") * (TOPE_CORTO_EQUITY_ALTO_RIESGO if alto else TOPE_CORTO_EQUITY) - D("1234.56")
            assert qty * D(precio) <= tope < (qty + 1) * D(precio)
            assert motivo == MOTIVO_PARCIAL_TOPE


@pytest.mark.parametrize("kw", [
    pytest.param({"qty_pedida": 100.0}, id="R12-qty-float"),
    pytest.param({"qty_pedida": -1}, id="qty-negativa"),
    pytest.param({"qty_pedida": True}, id="qty-bool"),
    pytest.param({"precio": 1.0}, id="R12-precio-float"),
    pytest.param({"precio": D("0")}, id="precio-cero"),
    pytest.param({"tasa_simbolo": D("-5")}, id="tasa-negativa"),
    pytest.param({"exposicion_corta_usd": D("-1")}, id="exposicion-negativa"),
    pytest.param({"exposicion_corta_usd": 0.0}, id="R12-exposicion-float"),
    pytest.param({"alto_riesgo": 1}, id="alto-riesgo-no-bool"),
    pytest.param({"ahora": float("nan")}, id="ahora-NaN"),
    pytest.param({"ahora": None}, id="ahora-None"),
    pytest.param({"max_edad_s": -1.0}, id="max-edad-negativa"),
    pytest.param({"cuenta": Cuenta(bp=10000.0, equity=D("10000"), leida_en=LEIDA_EN)}, id="R12-bp-float"),
    pytest.param({"cuenta": Cuenta(bp=D("10000"), equity=10000.0, leida_en=LEIDA_EN)}, id="R12-equity-float"),
    pytest.param({"cuenta": Cuenta(bp=D("10000"), equity=D("10000"), leida_en=LEIDA_EN,
                                   bp_reservado=D("-1"))}, id="reserva-negativa"),
])
def test_acciones_que_caben_rechaza_argumentos_invalidos(kw):
    args = {"qty_pedida": 100, "precio": D("1"), "cuenta": _cuenta(), "tasa_simbolo": None,
            "exposicion_corta_usd": D("0"), "alto_riesgo": False, "ahora": AHORA}
    args.update(kw)
    with pytest.raises(ValueError):
        acciones_que_caben(**args)


# ── orden de llegada (R-E-02) y reservas ─────────────────────────────────
def test_orden_de_llegada_cabe_1_5_la_segunda_recibe_el_resto():
    """R-E-02: dos señales de 1.000 a 1 $ (2.500 $ cada una) con BP para 1,5: la primera entera, la segunda el resto, la tercera nada."""
    cuenta = _cuenta(bp="3750")
    precio = D("1")
    qty1, motivo1 = acciones_que_caben(1000, precio, cuenta, None, D("0"), False, AHORA)
    assert (qty1, motivo1) == (1000, MOTIVO_ENTERA)
    reservar(cuenta, margen_inicial_corto(precio, qty1, None))
    assert cuenta.bp_reservado == D("2500")

    qty2, motivo2 = acciones_que_caben(1000, precio, cuenta, None, D("0"), False, AHORA + 0.1)
    assert (qty2, motivo2) == (500, MOTIVO_PARCIAL_BP)
    reservar(cuenta, margen_inicial_corto(precio, qty2, None))
    assert cuenta.bp_reservado == D("3750")

    assert acciones_que_caben(1000, precio, cuenta, None, D("0"), False, AHORA + 0.2) == (0, MOTIVO_BP_AGOTADO)

    # llega el MsgBP: DAS ya descuenta lo consumido y las reservas se sueltan
    cuenta.bp, cuenta.leida_en = D("0"), AHORA + 1.0
    liberar_reservas(cuenta)
    assert cuenta.bp_reservado == D("0")
    assert acciones_que_caben(1000, precio, cuenta, None, D("0"), False, AHORA + 1.5) == (0, MOTIVO_BP_AGOTADO)


def test_orden_de_llegada_sin_reparto_proporcional():
    """R-E-02: la primera no se recorta para «hacer sitio» a la segunda aunque lleguen en el mismo instante."""
    cuenta = _cuenta(bp="2500")
    qty1, _ = acciones_que_caben(1000, D("1"), cuenta, None, D("0"), False, AHORA)
    reservar(cuenta, margen_inicial_corto(D("1"), qty1, None))
    qty2, _ = acciones_que_caben(1000, D("1"), cuenta, None, D("0"), False, AHORA)
    assert (qty1, qty2) == (1000, 0)


def test_reservar_acumula_y_liberar_suelta_todo():
    cuenta = _cuenta()
    reservar(cuenta, D("100.50"))
    reservar(cuenta, D("0"))
    reservar(cuenta, D("99.50"))
    assert cuenta.bp_reservado == D("200.00")
    assert type(cuenta.bp_reservado) is Decimal
    liberar_reservas(cuenta)
    assert cuenta.bp_reservado == D("0")
    assert type(cuenta.bp_reservado) is Decimal
    liberar_reservas(cuenta)
    assert cuenta.bp_reservado == D("0")


@pytest.mark.parametrize("margen", [
    pytest.param(D("-1"), id="R-E-02-reserva-negativa-inflaria-el-BP"),
    pytest.param(100.0, id="R12-float"),
    pytest.param(D("NaN"), id="NaN"),
    pytest.param(None, id="None"),
])
def test_reservar_rechaza_margen_invalido(margen):
    cuenta = _cuenta()
    with pytest.raises(ValueError):
        reservar(cuenta, margen)
    assert cuenta.bp_reservado == D("0")


# ── exposicion_corta (2c consecuencia 2) ─────────────────────────────────
def _cot(ticker: str, bid: Optional[str] = None, ask: Optional[str] = None, last: Optional[str] = None) -> Cotizacion:
    return Cotizacion(ticker=ticker, bid=None if bid is None else D(bid), ask=None if ask is None else D(ask),
                      last=None if last is None else D(last))


def _cot_de(cots: dict[str, Cotizacion]):
    return lambda t: cots.get(t)


def _intento(ticker: str, qty_total: int, llenas: int, precio_senal: str = "3.00",
             fase: FaseIntento = FaseIntento.AGREGANDO) -> IntentoEntrada:
    return IntentoEntrada(ticker=ticker, lotes=["l1"], qty_total=qty_total, bid_senal=D(precio_senal),
                          ask_senal=D(precio_senal), precio_senal=D(precio_senal), t_cierre_vela=0.0, t_limite=60.0,
                          fase=fase, llenas=llenas)


def _lote(lote_id: str, llenas: int, precio_medio: str) -> Lote:
    return Lote(id=lote_id, strategy_id="s", estrategia="e", ticker="XYZ", direccion="short", pedidas=llenas,
                llenas=llenas, precio_medio=D(precio_medio))


def test_exposicion_corta_vacia_es_cero():
    valor = exposicion_corta({}, _cot_de({}))
    assert valor == D("0") and type(valor) is Decimal


def test_exposicion_corta_valora_al_precio_mas_alto_de_la_cotizacion():
    posiciones = {"XYZ": PosicionTicker(ticker="XYZ", neta_fills=-1000)}
    assert exposicion_corta(posiciones, _cot_de({"XYZ": _cot("XYZ", "2.00", "2.02", "2.01")})) == D("2020.00")
    assert exposicion_corta(posiciones, _cot_de({"XYZ": _cot("XYZ", bid="1.50")})) == D("1500.00")


def test_exposicion_corta_suma_tickers_e_ignora_largos():
    posiciones = {
        "AAA": PosicionTicker(ticker="AAA", neta_fills=-100),
        "BBB": PosicionTicker(ticker="BBB", neta_fills=-200),
        "CCC": PosicionTicker(ticker="CCC", neta_fills=50),     # exceso largo (R-C-11 b): no es exposición corta
        "DDD": PosicionTicker(ticker="DDD"),
    }
    cots = {"AAA": _cot("AAA", "1", "1"), "BBB": _cot("BBB", "5", "5"), "CCC": _cot("CCC", "9", "9")}
    assert exposicion_corta(posiciones, _cot_de(cots)) == D("1100")


def test_exposicion_corta_toma_la_neta_mas_corta_fills_o_das():
    """R-K-02: una posición humana (neta_das más corta que los fills) cuenta; un %POS atrasado no la rebaja."""
    cots = _cot_de({"XYZ": _cot("XYZ", "2", "2")})
    humano = {"XYZ": PosicionTicker(ticker="XYZ", neta_fills=-100, neta_das=-300)}
    atrasado = {"XYZ": PosicionTicker(ticker="XYZ", neta_fills=-300, neta_das=-100)}
    assert exposicion_corta(humano, cots) == D("600")
    assert exposicion_corta(atrasado, cots) == D("600")


def test_exposicion_corta_cuenta_lo_pendiente_del_intento_vivo():
    """R-E-02 del lado del tope: 400 llenas + 600 aún pedidas = 1.000 cortas; un intento TERMINADO no cuenta."""
    cots = _cot_de({"XYZ": _cot("XYZ", "3", "3")})
    vivo = {"XYZ": PosicionTicker(ticker="XYZ", neta_fills=-400, intento=_intento("XYZ", 1000, 400))}
    assert exposicion_corta(vivo, cots) == D("3000")
    cruzando = {"XYZ": PosicionTicker(ticker="XYZ", neta_fills=-400,
                                      intento=_intento("XYZ", 1000, 400, fase=FaseIntento.CRUZANDO))}
    assert exposicion_corta(cruzando, cots) == D("3000")
    terminado = {"XYZ": PosicionTicker(ticker="XYZ", neta_fills=-400,
                                       intento=_intento("XYZ", 1000, 400, fase=FaseIntento.TERMINADO))}
    assert exposicion_corta(terminado, cots) == D("1200")


def test_exposicion_corta_sin_cotizacion_usa_avg_lotes_o_senal():
    sin_cot = _cot_de({})
    con_avg = {"XYZ": PosicionTicker(ticker="XYZ", neta_fills=-100, avg_das=D("4.00"))}
    assert exposicion_corta(con_avg, sin_cot) == D("400.00")
    con_lotes = {"XYZ": PosicionTicker(ticker="XYZ", neta_fills=-400,
                                       lotes={"a": _lote("a", 100, "2.00"), "b": _lote("b", 300, "4.00")})}
    assert exposicion_corta(con_lotes, sin_cot) == D("1400")      # medio ponderado 3,50 × 400
    solo_intento = {"XYZ": PosicionTicker(ticker="XYZ", intento=_intento("XYZ", 500, 0, precio_senal="2.50"))}
    assert exposicion_corta(solo_intento, sin_cot) == D("1250.00")
    cot_vacia = _cot_de({"XYZ": Cotizacion(ticker="XYZ")})
    assert exposicion_corta(con_avg, cot_vacia) == D("400.00")


def test_exposicion_corta_sin_ningun_precio_lanza():
    with pytest.raises(ValueError):
        exposicion_corta({"XYZ": PosicionTicker(ticker="XYZ", neta_fills=-100)}, _cot_de({}))


def test_exposicion_corta_alimenta_el_tope_de_acciones_que_caben():
    """F1 paso 3: exposición abierta 9.000 $ + nueva a 5 $ con equity 10.000 → caben 200."""
    posiciones = {"AAA": PosicionTicker(ticker="AAA", neta_fills=-3000)}
    expo = exposicion_corta(posiciones, _cot_de({"AAA": _cot("AAA", "2.99", "3.00")}))
    assert expo == D("9000.00")
    assert _caben(1000, "5", _cuenta(bp="40000"), exposicion=str(expo)) == (200, MOTIVO_PARCIAL_TOPE)


# ── pureza del módulo (§3: reglas/* sin I/O, sin reloj, sin logging) ─────
def test_capital_es_puro_por_sus_imports():
    arbol = ast.parse(Path(capital.__file__).read_text(encoding="utf-8"))
    modulos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos.update(a.name for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom):
            modulos.add(nodo.module)
    assert modulos <= {"__future__", "collections.abc", "decimal", "typing", "app.bot_das.tipos"}


def test_motivos_distintos_y_estables():
    motivos = [MOTIVO_ENTERA, MOTIVO_PARCIAL_BP, MOTIVO_PARCIAL_TOPE, MOTIVO_SIN_BP, MOTIVO_SIN_EQUITY,
               MOTIVO_BP_AGOTADO, MOTIVO_TOPE_ALCANZADO, MOTIVO_NADA_PEDIDO]
    assert len(set(motivos)) == len(motivos)
    assert MOTIVO_SIN_BP == "sin BP"           # §3.21 lo fija literal
    assert (TOPE_CORTO_EQUITY, TOPE_CORTO_EQUITY_ALTO_RIESGO) == (D("1"), D("0.5"))   # 2c
