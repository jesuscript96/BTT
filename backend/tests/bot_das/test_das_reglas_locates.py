"""Tests de reglas/locates.py (R-H-01..R-H-05, H6, E9, EP-9; correcciones 1 y 10; riesgos 11, 25, 34, 36).

Sin red, sin DAS, sin reloj real: la máquina se conduce con `%SLRET` y
`%SLOrder` sintéticos y un monotónico inventado; el estado se lleva con el
mismo reductor que usará el decisor (`aplicar_anotaciones` + `gasto_de`).
"""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pytest

from app.bot_das.reglas import locates as L
from app.bot_das.reglas.locates import (
    COMPRA_SIN_RESPUESTA_S,
    ESTADO_BUSCANDO,
    ESTADO_COMPRANDO,
    ESTADO_LOCALIZADO,
    ESTADO_NO_HACE_FALTA,
    ESTADO_OFRECIDO,
    ESTADO_PARADO,
    REUSO_CONSULTAR,
    REUSO_REUTILIZA,
    aplicar_anotaciones,
    asignar_a_lote,
    caducados,
    cantidad_a_localizar,
    clave_temporizador,
    compra_repetida,
    consulta_locates,
    consulta_reuso,
    gasto_comprometido,
    gasto_de,
    paquetes,
    siguiente_paso,
    tope_superado,
    tras_reentrada,
    veredicto_ev,
)
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    Accion,
    Anotar,
    Avisar,
    Consultar,
    Desprogramar,
    EstrategiaConfig,
    Grupo,
    Locate,
    LocateComprar,
    LocateInquire,
    LocateOferta,
    MsgSLOrder,
    MsgSLRet,
    MsgSLReuse,
    Nivel,
    Origen,
    Programar,
)
from app.bot_das.tokens import GeneradorTokens, descomponer

D = Decimal
HOY = date(2026, 9, 25)
X = "XYZ"
CFG = {"tope_gasto_pct_cuenta": 3.0, "hora_limite_intentos": None, "umbral_ultimo_paquete_pct": 30,
       "inquiry_intervalo_s": 3, "ruta_inquire": "ALLROUTEWTTYPE1"}
CLAVE = f"locate_inquire:{X}:est-a"


def estrategia(**cambios: Any) -> EstrategiaConfig:
    base = dict(strategy_id="est-a", name="PM (A)", origen="portfolio", ejecutar=True, avisar_grupo_a=False,
                riesgo_usd=D("300"), riesgos_piramide=[], riesgo_piramide_usd=None, ev_pct=D("4"), ev_rangos=[],
                excluir_ipo=False, al_desactivar="esperar_fin_dia", hora_fin_sesion="11:30",
                ventana_entradas=[{"from_time": "04:00", "to_time": "09:29"}], hora_salida=None,
                accept_reentries=True, max_reentries=-1, niveles_piramide=[], es_rth=False,
                definition_hash="sha256:" + "0" * 64, definition={})
    base.update(cambios)
    return EstrategiaConfig(**base)


def slret(tipo: int, precio: str, tamano: int, ruta: str = "LOC3", notas: str = "", ticker: str = X) -> MsgSLRet:
    return MsgSLRet(cruda=f"%SLRET {tipo} {ticker} {precio} {tamano} {ruta} {notas}", tipo=tipo, ticker=ticker,
                    precio=D(precio), tamano=tamano, ruta=ruta, notas=notas, cuenta="CUENTA_PRUEBA")


def slorder(id_das: int, estado: str, pedidas: int, localizadas: int, precio: str, token: Optional[int],
            ticker: str = X, notas: str = "") -> MsgSLOrder:
    return MsgSLOrder(cruda=f"%SLOrder {id_das} {ticker} {pedidas} ... {estado}", id=id_das, ticker=ticker,
                      pedidas=pedidas, abiertas=max(0, pedidas - localizadas), localizadas=localizadas,
                      precio=D(precio), estado=estado, ruta="LOC3", hora="09:31:00", limite=None, token=token,
                      notas=notas)


def et(hh: int, mm: int) -> datetime:
    return datetime(2026, 9, 25, hh, mm, tzinfo=ET)


class Maquina:
    """Conduce `siguiente_paso` como lo hará el decisor: aplica las anotaciones y suma el gasto del día."""

    def __init__(self, e: Optional[EstrategiaConfig] = None, precio: str = "5", equity: Optional[str] = "100000",
                 cfg: Optional[dict] = None, gasto: str = "0") -> None:
        self.e = e or estrategia()
        self.precio = D(precio)
        self.equity = D(equity) if equity is not None else None
        self.cfg = dict(CFG if cfg is None else cfg)
        self.gasto = D(gasto)
        self.tokens = GeneradorTokens(Origen.EJECUTOR_LOCATE, HOY)
        self.loc: Optional[Locate] = None
        self.historial: list[Accion] = []

    def paso(self, ahora: float, *, ret: Optional[MsgSLRet] = None, orden: Optional[MsgSLOrder] = None,
             qty: Optional[int] = None, deshabilitado: bool = False, **kw: Any) -> list[Accion]:
        acciones = siguiente_paso(self.loc, self.e, X, self.precio, ahora, self.cfg, self.gasto, self.equity,
                                  deshabilitado, ret, self.tokens, qty=qty, orden=orden, **kw)
        self.loc = aplicar_anotaciones(self.loc, acciones)
        self.gasto += gasto_de(acciones)
        self.historial += acciones
        return acciones

    def comprada(self, qty: int, precio_locate: str = "0.02", tamano: Optional[int] = None) -> LocateComprar:
        """Arranca, consulta y compra; devuelve la LocateComprar."""
        self.paso(1000.0, qty=qty)
        acciones = self.paso(1001.0, ret=slret(1, precio_locate, tamano if tamano is not None else 10_000))
        compra = [a for a in acciones if isinstance(a, LocateComprar)]
        assert len(compra) == 1, acciones
        return compra[0]


def tipos_de(acciones: list[Accion]) -> list[str]:
    return [a.tipo if isinstance(a, Anotar) else type(a).__name__ for a in acciones]


# ── paquetes (H6, corrección 10, riesgo 34) ───────────────────────────
@pytest.mark.parametrize("qty, esperado", [
    pytest.param(1230, (12, 1200), id="H6-1230-el-13-al-30pct-no-se-compra"),
    pytest.param(1240, (13, 1240), id="H6-1240-el-13-al-40pct-si"),
    pytest.param(1200, (12, 1200), id="H6-1200-exacto"),
    pytest.param(50, (1, 50), id="H6-50-un-paquete"),
    pytest.param(30, (1, 30), id="H6-30-minimo-un-paquete-pregunta-2"),
    pytest.param(1, (1, 1), id="H6-1-minimo-un-paquete"),
    pytest.param(0, (0, 0), id="H6-0"),
    pytest.param(-100, (0, 0), id="H6-negativo"),
    pytest.param(100, (1, 100), id="H6-100"),
    pytest.param(101, (1, 100), id="H6-101-sacrifica-1"),
    pytest.param(130, (1, 100), id="H6-130-30pct-no"),
    pytest.param(131, (2, 131), id="H6-131-31pct-si"),
    pytest.param(1299, (13, 1299), id="H6-1299"),
])
def test_paquetes_h6(qty: int, esperado: tuple[int, int]) -> None:
    assert paquetes(qty) == esperado


@pytest.mark.parametrize("qty, umbral, esperado", [
    pytest.param(110, 20, (1, 100), id="R-H-01.3-umbral20-110"),
    pytest.param(130, 20, (2, 130), id="R-H-01.3-umbral20-130"),
    pytest.param(1230, "30", (12, 1200), id="H6-umbral-texto"),
    pytest.param(1230, 30.0, (12, 1200), id="H6-umbral-float-del-json"),
    pytest.param(1230, D("29.9"), (13, 1230), id="H6-umbral-decimal"),
    pytest.param(101, 0, (2, 101), id="H6-umbral-0-siempre-arriba"),
    pytest.param(199, 100, (1, 100), id="H6-umbral-100-siempre-abajo"),
])
def test_paquetes_umbral(qty: int, umbral: Any, esperado: tuple[int, int]) -> None:
    assert paquetes(qty, umbral) == esperado


@pytest.mark.parametrize("qty", [1.5, 1230.0, True, "1230", None, D("1230")], ids=lambda v: f"H6-qty-{v!r}")
def test_paquetes_qty_no_int(qty: Any) -> None:
    with pytest.raises(ValueError):
        paquetes(qty)


@pytest.mark.parametrize("umbral", [-1, 101, "x", None, math.nan, True], ids=lambda v: f"H6-umbral-{v!r}")
def test_paquetes_umbral_invalido(umbral: Any) -> None:
    with pytest.raises(ValueError):
        paquetes(1230, umbral)


# ── cantidad_a_localizar (R-H-05, corrección 6, riesgo 25) ─────────────
def fila(sid: Optional[str], acciones: Any, nombre: str = "PM (A)", riesgo: Any = 300.0) -> dict:
    datos = {"nombre": nombre, "riesgo_usd": riesgo, "ev_pct": 4.0, "ev_rangos": [], "acciones": acciones,
             "stop": 5.3, "motivo": None}
    if sid is not None:
        datos["strategy_id"] = sid
    return datos


def test_cantidad_casa_por_strategy_id_y_no_por_nombre() -> None:
    e = estrategia()
    estimacion = [fila("otra", 9999.0, nombre="PM (A)"), fila(None, 7777.0), fila("est-a", 1000.0, nombre="otro")]
    assert cantidad_a_localizar(e, estimacion, D("5")) == 1000


@pytest.mark.parametrize("estimacion", [
    pytest.param([], id="R-H-05-sin-filas"),
    pytest.param(None, id="R-H-05-estimacion-None"),
    pytest.param([fila("otra", 1000.0)], id="R-H-05-solo-otra-estrategia"),
    pytest.param([fila("est-a", 1000.0), fila("est-a", 800.0)], id="riesgo-25-id-repetido-no-compra"),
    pytest.param([fila("est-a", None)], id="R-H-05-acciones-None"),
    pytest.param([fila("est-a", math.nan)], id="R-H-05-acciones-NaN"),
    pytest.param([fila("est-a", math.inf)], id="R-H-05-acciones-inf"),
    pytest.param([fila("est-a", 0.0)], id="R-H-05-acciones-0"),
    pytest.param([fila("est-a", -50.0)], id="R-H-05-acciones-negativas"),
    pytest.param([fila("est-a", True)], id="R-H-05-acciones-bool"),
    pytest.param([fila("est-a", 0.4)], id="R-H-05-acciones-redondean-a-0"),
    pytest.param(["basura", 3], id="R-H-05-filas-no-dict"),
])
def test_cantidad_cero(estimacion: Any) -> None:
    assert cantidad_a_localizar(estrategia(), estimacion, D("5")) == 0


@pytest.mark.parametrize("acciones, esperado", [
    pytest.param(1199.0, 1199, id="injerto-8.2-float-entero"),
    pytest.param(1199.5, 1200, id="injerto-8.2-redondeo-al-par-arriba"),
    pytest.param(1200.5, 1200, id="injerto-8.2-redondeo-al-par-abajo"),
    pytest.param("850", 850, id="injerto-8.2-texto"),
])
def test_cantidad_conversion_acciones(acciones: Any, esperado: int) -> None:
    assert cantidad_a_localizar(estrategia(), [fila("est-a", acciones)], D("5")) == esperado


@pytest.mark.parametrize("precio", [D("0"), D("-1"), D("NaN"), None], ids=lambda v: f"R-H-05-precio-{v!r}")
def test_cantidad_precio_invalido(precio: Any) -> None:
    assert cantidad_a_localizar(estrategia(), [fila("est-a", 1000.0)], precio) == 0


def test_cantidad_entrada_mas_piramides_add_con_riesgo_por_nivel() -> None:
    """R-H-05 FIJADA: entrada + TODAS sus «add» con el riesgo de cada nivel del cuadro (§4.4b)."""
    niveles = [{"action": "add"}, {"action": "reduce"}, {"action": "add"}, {}, {"action": "REDUCE"}, "basura"]
    e = estrategia(niveles_piramide=niveles, riesgos_piramide=[D("150"), None, None],
                   riesgo_piramide_usd=D("60"))
    # 1000 acciones con 300 $ → 3,333 acc/$: nivel 0 → 150 $ = 500; reduce fuera; nivel 2 (casilla vacía) → global
    # 60 $ = 200; nivel 3 (sin casilla, acción por defecto «add») → 200; «REDUCE» y basura fuera.
    assert cantidad_a_localizar(e, [fila("est-a", 1000.0)], D("5")) == 1900


def test_cantidad_piramide_sin_riesgo_de_piramide_usa_el_de_entrada() -> None:
    e = estrategia(niveles_piramide=[{"action": "add"}], riesgos_piramide=[None], riesgo_piramide_usd=None)
    assert cantidad_a_localizar(e, [fila("est-a", 1000.0)], D("5")) == 2000


def test_cantidad_fila_sin_riesgo_usa_el_de_la_estrategia() -> None:
    e = estrategia(niveles_piramide=[{"action": "add"}], riesgos_piramide=[D("150")])
    assert cantidad_a_localizar(e, [fila("est-a", 1000.0, riesgo=None)], D("5")) == 1500


def test_cantidad_piramide_redondeo_al_par() -> None:
    e = estrategia(niveles_piramide=[{"action": "add"}], riesgos_piramide=[D("100")])
    # 1001 acciones · 100/300 = 333,666… → 334
    assert cantidad_a_localizar(e, [fila("est-a", 1001.0)], D("5")) == 1001 + 334


# ── veredicto_ev (R-H-01, H6, R-H-05, corrección 1) ───────────────────
def test_veredicto_basico_1230_cobra_12_paquetes() -> None:
    """Jaume 29-sep: con el locate a 0,07 las 30 acciones extra ganan 30·5·4 % = 6 < 7 → el paquete 13 no se compra."""
    v = veredicto_ev(estrategia(), D("5"), 1230, D("0.07"), D("0"))
    assert (v["paquetes"], v["qty_ajustada"], v["qty_comprar"]) == (12, 1200, 1200)
    assert v["coste_nuevo"] == D("84") and v["coste_total"] == D("84")
    assert v["fade_pct"] == D("1.4") and v["ev_pct"] == D("4") and v["margen_pct"] == D("2.6")
    assert v["entra"] is True and v["ev_origen"] == "completo" and v["motivo"] is None
    for clave in ("ev_pct", "fade_pct", "margen_pct", "coste_nuevo", "coste_total"):
        assert isinstance(v[clave], Decimal), clave


def test_veredicto_1240_cobra_13_paquetes_y_usa_1240() -> None:
    v = veredicto_ev(estrategia(), D("5"), 1240, D("0.02"), D("0"))
    assert (v["paquetes"], v["qty_ajustada"], v["qty_comprar"]) == (13, 1240, 1300)
    assert v["coste_nuevo"] == D("26")
    assert v["fade_pct"] == D("26") * 100 / (D("1240") * D("5"))


def test_veredicto_no_usa_locates_gate_evaluar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Corrección 1 / riesgo 34: `evaluar` cobra ceil(qty/100); aquí no se toca."""
    import app.services.locates_gate as gate

    def prohibido(*_a: Any, **_k: Any) -> None:
        raise AssertionError("veredicto_ev no debe usar locates_gate.evaluar")

    monkeypatch.setattr(gate, "evaluar", prohibido)
    monkeypatch.setattr(gate, "paquetes_marginales", prohibido)
    assert veredicto_ev(estrategia(), D("5"), 1230, D("0.07"), D("0"))["paquetes"] == 12


def test_veredicto_usa_ev_fijo_para_precio_con_floats(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.locates_gate as gate
    assert L.ev_fijo_para_precio is gate.ev_fijo_para_precio
    llamadas: list[tuple] = []

    def espia(ev: Any, rangos: Any, precio: Any) -> tuple[float, str]:
        llamadas.append((ev, rangos, precio))
        return 6.1, "rango"

    monkeypatch.setattr(L, "ev_fijo_para_precio", espia)
    e = estrategia(ev_rangos=[{"lo": 1.0, "hi": 5.0, "ev_pct": 6.1}])
    v = veredicto_ev(e, D("2.5"), 1000, D("0.01"), D("0"))
    assert llamadas == [(4.0, e.ev_rangos, 2.5)]
    assert all(type(x) is float for x in (llamadas[0][0], llamadas[0][2]))
    assert v["ev_pct"] == D("6.1") and v["ev_origen"] == "rango"


@pytest.mark.parametrize("precio, ev, origen, entra", [
    pytest.param("0.5", "1", "rango", False, id="R-H-01-ev-tramo-0.5-1-no-entra"),
    pytest.param("2", "8", "rango", True, id="R-H-01-ev-tramo-1-5-entra"),
    pytest.param("7", "4", "completo", True, id="R-H-01-ev-fuera-de-tramo-completo"),
])
def test_veredicto_ev_por_tramo(precio: str, ev: str, origen: str, entra: bool) -> None:
    e = estrategia(ev_rangos=[{"lo": 0, "hi": 1, "ev_pct": 1.0}, {"lo": 1, "hi": 5, "ev_pct": 8.0}])
    # locate a 3 % del precio: fade 3 % en los tres casos
    precio_locate = D(precio) * D("0.03")
    v = veredicto_ev(e, D(precio), 1000, precio_locate, D("0"))
    assert v["fade_pct"] == D("3")
    assert (v["ev_pct"], v["ev_origen"], v["entra"]) == (D(ev), origen, entra)


def test_veredicto_coste_total_rechaza_la_segunda_compra() -> None:
    """R-H-05 / R-H-01.4: la ampliación paga el TOTAL; sola compensaría, con lo ya pagado no."""
    e = estrategia()
    sola = veredicto_ev(e, D("1"), 300, D("0.05"), D("0"), ya_localizadas=200)
    assert sola["paquetes"] == 1 and sola["coste_nuevo"] == D("5") and sola["entra"] is True
    con_total = veredicto_ev(e, D("1"), 300, D("0.05"), D("20"), ya_localizadas=200)
    assert con_total["coste_total"] == D("25")
    assert con_total["fade_pct"] == D("25") * 100 / D("300")
    assert con_total["entra"] is False and con_total["motivo"] == "el EV no compensa el coste total"


@pytest.mark.parametrize("disponibles, paq, usable, comprar", [
    pytest.param(250, 2, 200, 200, id="R-H-04-se-compra-lo-que-hay"),
    pytest.param(300, 3, 300, 300, id="R-H-04-hay-todo"),
    pytest.param(10_000, 3, 300, 300, id="R-H-04-hay-de-sobra"),
])
def test_veredicto_disponibles(disponibles: int, paq: int, usable: int, comprar: int) -> None:
    v = veredicto_ev(estrategia(), D("5"), 300, D("0.01"), D("0"), disponibles=disponibles)
    assert (v["paquetes"], v["qty_ajustada"], v["qty_comprar"], v["entra"]) == (paq, usable, comprar, True)


def test_veredicto_menos_de_un_paquete_disponible_no_entra() -> None:
    v = veredicto_ev(estrategia(), D("5"), 300, D("0.01"), D("0"), disponibles=50)
    assert (v["paquetes"], v["entra"], v["motivo"]) == (0, False, "sin paquetes de 100 disponibles")


def test_veredicto_minimo_de_la_ruta() -> None:
    """R-H-01 + SLRouteMinCharge: si acciones·precio < mínimo, se cobra el mínimo."""
    v = veredicto_ev(estrategia(), D("5"), 100, D("0.01"), D("0"), minimo_cargo=D("5"))
    assert v["coste_nuevo"] == D("5") and v["fade_pct"] == D("1")


def test_veredicto_nada_que_localizar() -> None:
    v = veredicto_ev(estrategia(), D("5"), 1230, D("0.07"), D("24"), ya_localizadas=1200)
    assert (v["paquetes"], v["qty_comprar"], v["entra"], v["motivo"]) == (0, 0, False, "nada que localizar")
    assert v["coste_nuevo"] == D("0") and v["coste_total"] == D("24")


def test_veredicto_ev_cero_nunca_entra_y_locate_gratis_con_ev_si() -> None:
    assert veredicto_ev(estrategia(ev_pct=D("0")), D("5"), 100, D("0"), D("0"))["entra"] is False
    assert veredicto_ev(estrategia(), D("5"), 100, D("0"), D("0"))["entra"] is True


@pytest.mark.parametrize("args", [
    pytest.param((D("0"), 100, D("0.01"), D("0")), id="precio-0"),
    pytest.param((5.0, 100, D("0.01"), D("0")), id="precio-float"),
    pytest.param((D("NaN"), 100, D("0.01"), D("0")), id="precio-NaN"),
    pytest.param((D("5"), 100.0, D("0.01"), D("0")), id="qty-float"),
    pytest.param((D("5"), 100, D("-0.01"), D("0")), id="precio-locate-negativo"),
    pytest.param((D("5"), 100, 0.01, D("0")), id="precio-locate-float"),
    pytest.param((D("5"), 100, D("0.01"), D("-1")), id="coste-negativo"),
])
def test_veredicto_entradas_invalidas(args: tuple) -> None:
    with pytest.raises(ValueError):
        veredicto_ev(estrategia(), *args)


def test_veredicto_ya_localizadas_negativas() -> None:
    with pytest.raises(ValueError):
        veredicto_ev(estrategia(), D("5"), 100, D("0.01"), D("0"), ya_localizadas=-1)


# ── tope_superado (R-H-03) ────────────────────────────────────────────
@pytest.mark.parametrize("gasto, coste, equity, pct, esperado", [
    pytest.param("0", "300", "10000", D("3"), False, id="R-H-03-justo-en-el-tope-se-permite"),
    pytest.param("0", "300.01", "10000", D("3"), True, id="R-H-03-un-centimo-de-mas"),
    pytest.param("250", "60", "10000", D("3"), True, id="R-H-03-acumulado-del-dia"),
    pytest.param("250", "50", "10000", 3.0, False, id="R-H-03-pct-float-del-json"),
    pytest.param("0", "10", None, D("3"), True, id="R-H-03-sin-equity-no-se-compra"),
    pytest.param("0", "10", "0", D("3"), True, id="R-H-03-equity-cero"),
    pytest.param("0", "10", "-5", D("3"), True, id="R-H-03-equity-negativa"),
    pytest.param("0", "0", "10000", D("0"), False, id="R-H-03-tope-0-y-coste-0"),
    pytest.param("0", "1", "10000", "0", True, id="R-H-03-tope-0"),
])
def test_tope_superado(gasto: str, coste: str, equity: Optional[str], pct: Any, esperado: bool) -> None:
    assert tope_superado(D(gasto), D(coste), D(equity) if equity is not None else None, pct) is esperado


@pytest.mark.parametrize("args", [
    pytest.param((D("-1"), D("1"), D("100"), D("3")), id="gasto-negativo"),
    pytest.param((D("0"), D("-1"), D("100"), D("3")), id="coste-negativo"),
    pytest.param((D("0"), D("1"), D("100"), D("-3")), id="pct-negativo"),
    pytest.param((0.0, D("1"), D("100"), D("3")), id="gasto-float"),
    pytest.param((D("0"), D("1"), D("NaN"), D("3")), id="equity-NaN"),
])
def test_tope_superado_invalido(args: tuple) -> None:
    with pytest.raises(ValueError):
        tope_superado(*args)


# ── compra_repetida (R-H-02) ──────────────────────────────────────────
def loc(sid: str = "est-a", ticker: str = X, **cambios: Any) -> Locate:
    return replace(Locate(ticker=ticker, strategy_id=sid, pedidas=1000), **cambios)


@pytest.mark.parametrize("registro, id_das, esperado", [
    pytest.param(None, 7, False, id="R-H-02-sin-registro"),
    pytest.param(loc(compras=0, estado=ESTADO_COMPRANDO), 7, False, id="R-H-02-primera-compra"),
    pytest.param(loc(compras=1, estado=ESTADO_LOCALIZADO, id_das=7), 8, True, id="R-H-02-segundo-located-no-pedido"),
    pytest.param(loc(compras=1, estado=ESTADO_LOCALIZADO, id_das=7), None, True, id="R-H-02-sin-id"),
    pytest.param(loc(compras=1, estado=ESTADO_LOCALIZADO, id_das=7), 7, False, id="R-H-02-duplicado-mismo-id"),
    pytest.param(loc(compras=1, estado=ESTADO_COMPRANDO, id_das=7), 8, False, id="R-H-04-parcial-pedido"),
    pytest.param(loc(compras=1, estado="Waiting", id_das=8), 8, False, id="R-H-04-en-curso"),
    pytest.param(loc(compras=2, estado=ESTADO_BUSCANDO, id_das=7), 9, True, id="R-H-02-buscando-no-pidio"),
    pytest.param(loc(compras=1, estado=ESTADO_PARADO, id_das=7), 9, True, id="R-H-02-parado-no-pidio"),
])
def test_compra_repetida(registro: Optional[Locate], id_das: Optional[int], esperado: bool) -> None:
    locates = {} if registro is None else {(X, "est-a"): registro}
    assert compra_repetida(locates, X, "est-a", id_das=id_das) is esperado


def test_compra_repetida_mira_solo_su_clave() -> None:
    locates = {(X, "otra"): loc("otra", compras=1, estado=ESTADO_LOCALIZADO, id_das=1),
               ("ABC", "est-a"): loc(ticker="ABC", compras=1, estado=ESTADO_LOCALIZADO, id_das=1)}
    assert compra_repetida(locates, X, "est-a", id_das=5) is False


# ── asignar_a_lote (E9) ───────────────────────────────────────────────
def test_asignar_primero_a_la_estrategia_de_la_senal() -> None:
    locates = {(X, "est-a"): loc(pedidas=1000, localizadas=1000), (X, "est-b"): loc("est-b", pedidas=500,
                                                                                   localizadas=500)}
    assert asignar_a_lote(locates, X, 800, "est-a") == [("est-a", 800)]


def test_asignar_sobrantes_de_la_siguiente_sin_quitarle_lo_suyo() -> None:
    """E9: si faltan, los SOBRANTES de las demás (H6: «sobran 60»), nunca lo que otra compró para sí."""
    locates = {
        (X, "est-a"): loc(pedidas=1240, localizadas=1200, usadas=0),
        (X, "est-c"): loc("est-c", pedidas=1240, localizadas=1300, comprado_en=50.0),       # sobran 60
        (X, "est-b"): loc("est-b", pedidas=100, localizadas=200, comprado_en=10.0),         # sobran 100
        (X, "est-d"): loc("est-d", pedidas=500, localizadas=500),                           # sin sobrante
        ("ABC", "est-z"): loc("est-z", ticker="ABC", pedidas=0, localizadas=10_000),        # otro ticker
    }
    assert asignar_a_lote(locates, X, 1240, "est-a") == [("est-a", 1200), ("est-b", 40)]
    assert asignar_a_lote(locates, X, 1400, "est-a") == [("est-a", 1200), ("est-b", 100), ("est-c", 60)]


def test_asignar_sobrante_de_otra_que_ya_uso_lo_suyo() -> None:
    locates = {(X, "est-b"): loc("est-b", pedidas=1240, localizadas=1300, usadas=1240)}
    assert asignar_a_lote(locates, X, 500, "est-a") == [("est-b", 60)]


@pytest.mark.parametrize("qty, esperado", [
    pytest.param(0, [], id="E9-qty-0"),
    pytest.param(-5, [], id="E9-qty-negativa"),
])
def test_asignar_sin_qty(qty: int, esperado: list) -> None:
    assert asignar_a_lote({(X, "est-a"): loc(localizadas=100)}, X, qty, "est-a") == esperado


def test_asignar_sin_locates_devuelve_vacio() -> None:
    assert asignar_a_lote({}, X, 100, "est-a") == []
    assert asignar_a_lote({(X, "est-a"): loc(localizadas=300, usadas=300)}, X, 100, "est-a") == []


def test_asignar_etb_no_necesita_locate() -> None:
    locates = {(X, "est-b"): loc("est-b", estado=ESTADO_NO_HACE_FALTA)}
    assert asignar_a_lote(locates, X, 700, "est-a") == [("est-a", 700)]


def test_asignar_qty_no_int() -> None:
    with pytest.raises(ValueError):
        asignar_a_lote({}, X, 10.0, "est-a")


# ── caducados (R-H-05) ────────────────────────────────────────────────
def test_caducados_solo_los_no_usados_en_orden() -> None:
    locates = {
        ("ZZZ", "est-a"): loc(ticker="ZZZ", localizadas=100, usadas=0),
        (X, "est-b"): loc("est-b", localizadas=300, usadas=300),
        (X, "est-a"): loc(localizadas=1300, usadas=1240),
        ("AAA", "est-a"): loc(ticker="AAA", estado=ESTADO_NO_HACE_FALTA),
        ("BBB", "est-a"): loc(ticker="BBB", localizadas=0),
    }
    assert [(c.ticker, c.strategy_id) for c in caducados(locates)] == [(X, "est-a"), ("ZZZ", "est-a")]


# ── tras_reentrada (EP-9, R-D-04) ─────────────────────────────────────
def reuso(si: bool, ticker: str = X) -> MsgSLReuse:
    return MsgSLReuse(cruda=f"$SLReuseQueryRet {ticker} {'Yes' if si else 'No'}", ticker=ticker, reutilizable=si)


@pytest.mark.parametrize("registro, respuesta, esperado", [
    pytest.param(loc(estado=ESTADO_LOCALIZADO), reuso(True), REUSO_REUTILIZA, id="EP-9-Yes-reutiliza"),
    pytest.param(loc(estado=ESTADO_LOCALIZADO), reuso(False), ESTADO_BUSCANDO, id="EP-9-No-vuelve-a-buscar"),
    pytest.param(loc(estado=ESTADO_LOCALIZADO), None, REUSO_CONSULTAR, id="EP-9-sin-respuesta-consultar"),
    pytest.param(loc(estado=ESTADO_NO_HACE_FALTA), reuso(False), ESTADO_NO_HACE_FALTA, id="EP-9-etb"),
    pytest.param(loc(estado=ESTADO_LOCALIZADO), reuso(True, "xyz"), REUSO_REUTILIZA, id="EP-9-mayusculas"),
])
def test_tras_reentrada(registro: Locate, respuesta: Optional[MsgSLReuse], esperado: str) -> None:
    assert tras_reentrada(registro, respuesta) == esperado


def test_tras_reentrada_otro_ticker() -> None:
    with pytest.raises(ValueError):
        tras_reentrada(loc(), reuso(True, "ABC"))


def test_consulta_reuso_literal_del_manual() -> None:
    assert consulta_reuso(X) == Consultar("SLReuseQuery XYZ")
    with pytest.raises(ValueError):
        consulta_reuso("X Y")


def test_tras_reentrada_no_recompra_si_el_total_no_compensa() -> None:
    """EP-9 No → buscando: la recompra pasa por el EV con el coste TOTAL (R-D-04)."""
    m = Maquina(precio="1")
    m.comprada(300, precio_locate="0.03")                            # 9 $ / 300 acciones a 1 $ = 3 % < 4 %
    m.paso(1002.0, orden=slorder(70, "Located", 300, 300, "0.03", m.loc.token))
    assert m.loc.coste == D("9")
    assert tras_reentrada(m.loc, reuso(False)) == ESTADO_BUSCANDO
    m.loc = replace(m.loc, estado=ESTADO_BUSCANDO, usadas=300)     # lo que hace el decisor
    assert tipos_de(m.paso(1010.0)) == ["locate_inquire", "LocateInquire", "Programar"]
    acciones = m.paso(1011.0, ret=slret(1, "0.03", 1000))
    # sola la recompra daría 3 %; con el total, 9 + 9 = 18 $ sobre 300 acciones a 1 $ = 6 % > EV 4 %
    assert tipos_de(acciones) == ["locate_inquire"]
    assert acciones[0].datos["coste_total"] == D("18") and acciones[0].datos["entra"] is False


# ── la máquina: siguiente_paso (R-H-01..04, H6, EP-9, manual L1648-1838) ─
def test_maquina_arranca_consultando_cada_3_s() -> None:
    m = Maquina()
    acciones = m.paso(1000.0, qty=1200)
    assert tipos_de(acciones) == ["locate_inquire", "LocateInquire", "Programar"]
    assert acciones[1] == LocateInquire(X, 1200, "ALLROUTEWTTYPE1")
    assert acciones[2] == Programar(CLAVE, 3.0, {"ticker": X, "strategy_id": "est-a"})
    assert (m.loc.estado, m.loc.pedidas, m.loc.ultimo_inquire_en) == (ESTADO_BUSCANDO, 1200, 1000.0)
    # temporizador que llega antes de tiempo: solo reprograma lo que falta
    assert m.paso(1001.0) == [Programar(CLAVE, 2.0, {"ticker": X, "strategy_id": "est-a"})]
    # a los 3 s: otra consulta
    assert tipos_de(m.paso(1003.0)) == ["locate_inquire", "LocateInquire", "Programar"]
    assert m.loc.ultimo_inquire_en == 1003.0


def test_maquina_sin_qty_ni_locate_no_hace_nada() -> None:
    m = Maquina()
    assert m.paso(1000.0) == []
    assert m.paso(1000.0, qty=0) == []
    assert m.paso(1000.0, qty=-10) == []


def test_maquina_compra_cuando_el_ev_compensa_y_hasta_entonces_solo_anota() -> None:
    """R-H-01: se sigue actualizando HASTA encontrar un precio con ventaja; entonces se compra y se deja de consultar."""
    m = Maquina()
    m.paso(1000.0, qty=1200)
    caro = m.paso(1001.0, ret=slret(1, "0.25", 5000))               # fade 5 % > EV 4 %
    assert tipos_de(caro) == ["locate_inquire"] and caro[0].datos["entra"] is False
    assert m.loc.estado == ESTADO_BUSCANDO
    acciones = m.paso(1004.0, ret=slret(1, "0.02", 5000))
    assert tipos_de(acciones) == ["locate_intencion", "LocateComprar", "Programar"]   # write-ahead primero
    compra = acciones[1]
    assert (compra.ticker, compra.qty, compra.ruta) == (X, 1200, "LOC3")
    partes = descomponer(compra.token)
    assert partes is not None and partes[0] is Origen.EJECUTOR_LOCATE and partes[1] == 268
    datos = acciones[0].datos
    assert datos["token"] == compra.token and datos["estado"] == ESTADO_COMPRANDO
    assert (datos["paquetes"], datos["qty_comprar"], datos["qty_ajustada"]) == (12, 1200, 1200)
    assert datos["coste_nuevo"] == D("24") and datos["entra"] is True
    # E2-04: en vez de desprogramar, el temporizador vigila la compra (30 s sin %SLOrder → aviso); la intención
    # anota la hora de la compra
    assert acciones[2] == Programar(CLAVE, COMPRA_SIN_RESPUESTA_S, {"ticker": X, "strategy_id": "est-a"})
    assert datos["ultimo_inquire_en"] == 1004.0
    assert (m.loc.estado, m.loc.token) == (ESTADO_COMPRANDO, compra.token)


def test_maquina_compra_paquetes_enteros_1240_compra_1300() -> None:
    """H6: «se compran las 100 y sobran 60»; H-7: locates siempre ≥ 100."""
    m = Maquina()
    assert m.comprada(1240).qty == 1300
    m2 = Maquina()
    assert m2.comprada(30).qty == 100


def test_maquina_completa_located_y_cerrojo() -> None:
    m = Maquina()
    compra = m.comprada(1200)
    # con la compra en curso: ni consultas ni compras (R-H-02)
    assert m.paso(1002.0, ret=slret(1, "0.01", 5000)) == []
    assert m.paso(1003.0) == []
    pendiente = m.paso(1002.5, orden=slorder(70, "Pending", 1200, 0, "0", compra.token))
    assert tipos_de(pendiente) == ["locate_estado"] and m.loc.estado == "Pending" and m.loc.id_das == 70
    assert m.paso(1002.6, orden=slorder(70, "Pending", 1200, 0, "0", compra.token)) == []
    m.paso(1002.7, orden=slorder(70, "Waiting", 1200, 0, "0", compra.token))
    assert m.loc.estado == "Waiting"
    hecho = m.paso(1003.0, orden=slorder(70, "Located", 1200, 1200, "0.02", compra.token))
    assert tipos_de(hecho) == ["locate_estado", "Consultar", "Desprogramar"]
    assert hecho[1] == Consultar("SLReuseQuery XYZ")                               # EP-9
    datos = hecho[0].datos
    assert (datos["estado"], datos["localizadas"], datos["coste_nuevo"], datos["coste_total"]) == (
        ESTADO_LOCALIZADO, 1200, D("24"), D("24"))
    assert (m.loc.estado, m.loc.localizadas, m.loc.coste, m.loc.compras) == (ESTADO_LOCALIZADO, 1200, D("24"), 1)
    assert m.gasto == D("24")
    # cerrojo R-H-02: nada más para esta acción y esta estrategia
    assert m.paso(1010.0) == []
    assert m.paso(1011.0, ret=slret(1, "0.001", 5000)) == []
    assert m.paso(1012.0, qty=5000) == []
    # un GET LOCATES repite el Located: duplicado, ni se cobra ni cuenta como compra
    assert m.paso(1013.0, orden=slorder(70, "Located", 1200, 1200, "0.02", compra.token)) == []
    assert (m.gasto, m.loc.compras) == (D("24"), 1)
    assert compra_repetida({(X, "est-a"): m.loc}, X, "est-a", id_das=70) is False
    assert compra_repetida({(X, "est-a"): m.loc}, X, "est-a", id_das=71) is True


def test_maquina_parcial_sigue_buscando_el_resto_con_coste_total() -> None:
    """R-H-04 + Recompra FIJADA: se compra lo que hay, se busca el resto INMEDIATAMENTE y paga el total."""
    m = Maquina(precio="1")
    compra = m.comprada(300, precio_locate="0.01", tamano=200)
    assert compra.qty == 200
    parcial = m.paso(1002.0, orden=slorder(70, "Located", 200, 200, "0.01", compra.token))
    assert tipos_de(parcial) == ["locate_estado", "Consultar", "locate_estado", "LocateInquire", "Programar"]
    assert parcial[3] == LocateInquire(X, 100, "ALLROUTEWTTYPE1")
    assert (m.loc.estado, m.loc.localizadas, m.loc.coste, m.loc.compras) == (ESTADO_BUSCANDO, 200, D("2"), 1)
    # la segunda compra se decide con el coste TOTAL: 2 + 100 · 0,01 = 3 $ sobre 300 acciones a 1 $ = 1 %
    acciones = m.paso(1003.0, ret=slret(1, "0.01", 100, ruta="LOC7"))
    assert tipos_de(acciones) == ["locate_intencion", "LocateComprar", "Programar"]          # E2-04
    assert acciones[0].datos["coste_total"] == D("3") and acciones[0].datos["fade_pct"] == D("1")
    segunda = acciones[1]
    assert (segunda.qty, segunda.ruta) == (100, "LOC7") and segunda.token != compra.token
    # llega un duplicado de la PRIMERA orden mientras la segunda está en curso: no es nuestra (otro token)
    assert m.paso(1003.5, orden=slorder(70, "Located", 200, 200, "0.01", compra.token)) == []
    m.paso(1004.0, orden=slorder(71, "Located", 100, 100, "0.01", segunda.token))
    assert (m.loc.estado, m.loc.localizadas, m.loc.coste, m.loc.compras) == (ESTADO_LOCALIZADO, 300, D("3"), 2)
    assert m.gasto == D("3")
    assert m.paso(1010.0) == []                                                     # cubierto: cerrojo


def test_R_H_04_parcial_deja_de_buscar_el_resto_pasado_el_tope_y_opera_con_lo_localizado() -> None:
    """Ensayo 28-sep: la ruta dio 800 de 8.772 y el bot consultó cada 3 s durante horas (903 consultas). Tras un
    parcial, el resto se busca `PARCIAL_BUSCAR_MAX_S` (60 s); después Located con lo que hay y sin temporizador."""
    from app.bot_das.reglas.locates import PARCIAL_BUSCAR_MAX_S
    m = Maquina(precio="1")
    compra = m.comprada(300, precio_locate="0.01", tamano=200)
    m.paso(1002.0, orden=slorder(70, "Located", 200, 200, "0.01", compra.token))
    assert m.loc.estado == ESTADO_BUSCANDO and m.loc.comprado_en == 1002.0
    dentro = m.paso(1002.0 + PARCIAL_BUSCAR_MAX_S - 1)                # aún dentro del tope: sigue consultando
    assert any(isinstance(a, LocateInquire) for a in dentro) or any(isinstance(a, Programar) for a in dentro)
    fuera = m.paso(1002.0 + PARCIAL_BUSCAR_MAX_S + 1)
    assert tipos_de(fuera) == ["locate_estado", "Desprogramar"]
    assert "parcial aceptado" in fuera[0].datos["motivo"]
    assert (m.loc.estado, m.loc.localizadas) == (ESTADO_LOCALIZADO, 200)
    assert m.paso(1100.0) == []                                         # Located: cerrojo, no se vuelve a consultar


def test_maquina_parcial_rechaza_la_segunda_compra_si_el_total_no_compensa() -> None:
    m = Maquina(precio="1")
    compra = m.comprada(300, precio_locate="0.03", tamano=200)                     # 6 $ / 200 = 3 %
    m.paso(1002.0, orden=slorder(70, "Located", 200, 200, "0.03", compra.token))
    # sola, 100 · 0,03 = 3 $ / 100 acciones = 3 % < 4 %; con el total: 9 $ / 300 = 3 % → entra;
    # a 0,07: 6 + 7 = 13 $ / 300 = 4,33 % > 4 % → NO
    acciones = m.paso(1003.0, ret=slret(1, "0.07", 100))
    assert tipos_de(acciones) == ["locate_inquire"]
    assert acciones[0].datos["entra"] is False and acciones[0].datos["coste_total"] == D("13")
    assert m.loc.estado == ESTADO_BUSCANDO


def test_maquina_oferta_aceptada_si_el_ev_sigue_bien() -> None:
    m = Maquina()
    compra = m.comprada(1200)
    acciones = m.paso(1002.0, orden=slorder(80, "Offered", 1200, 0, "0.02", compra.token))
    assert tipos_de(acciones) == ["locate_estado", "LocateOferta"]
    assert acciones[1] == LocateOferta(80, True)
    assert (m.loc.estado, m.loc.id_das) == (ESTADO_OFRECIDO, 80)
    assert m.paso(1002.1, orden=slorder(80, "Offered", 1200, 0, "0.02", compra.token)) == []   # repetida
    otra = m.paso(1002.2, orden=slorder(81, "Offered", 1200, 0, "0.02", compra.token))
    assert otra[0] == LocateOferta(81, False)                                        # nunca dos ofertas
    m.paso(1003.0, orden=slorder(80, "Located", 1200, 1200, "0.02", compra.token))
    assert (m.loc.estado, m.loc.localizadas, m.gasto) == (ESTADO_LOCALIZADO, 1200, D("24"))


@pytest.mark.parametrize("pedidas, precio", [
    pytest.param(1200, "0.30", id="F9-oferta-cara-reject"),
    pytest.param(1300, "0.02", id="F9-oferta-con-mas-acciones-reject"),
])
def test_maquina_oferta_rechazada_vuelve_a_buscar(pedidas: int, precio: str) -> None:
    m = Maquina()
    compra = m.comprada(1200)
    acciones = m.paso(1002.0, orden=slorder(80, "Offered", pedidas, 0, precio, compra.token))
    assert tipos_de(acciones) == ["LocateOferta", "locate_estado", "Programar"]
    assert acciones[0] == LocateOferta(80, False)
    assert m.loc.estado == ESTADO_BUSCANDO
    # el «Closed» de la oferta rechazada llega después: tardío, se ignora
    assert m.paso(1002.5, orden=slorder(80, "Closed", pedidas, 0, precio, compra.token)) == []
    assert m.loc.estado == ESTADO_BUSCANDO


def test_maquina_already_shortable_no_hace_falta() -> None:
    m = Maquina()
    m.paso(1000.0, qty=1200)
    acciones = m.paso(1001.0, ret=slret(2, "0", 0, notas="AlreadyShortable"))
    assert tipos_de(acciones) == ["locate_estado", "Desprogramar"]
    assert m.loc.estado == ESTADO_NO_HACE_FALTA
    assert m.paso(1004.0) == [] and m.paso(1005.0, ret=slret(1, "0.01", 5000)) == []
    assert asignar_a_lote({(X, "est-a"): m.loc}, X, 1230, "est-a") == [("est-a", 1230)]


def test_maquina_fallo_tipo_2_en_busqueda_sigue_buscando() -> None:
    m = Maquina()
    m.paso(1000.0, qty=1200)
    acciones = m.paso(1001.0, ret=slret(2, "0", 0, notas="Not available"))
    assert tipos_de(acciones) == ["locate_inquire"] and acciones[0].datos["fallo"] == "Not available"
    assert m.loc.estado == ESTADO_BUSCANDO


def test_maquina_sin_disponibles_sigue_buscando() -> None:
    m = Maquina()
    m.paso(1000.0, qty=1200)
    assert tipos_de(m.paso(1001.0, ret=slret(1, "0.01", 0))) == ["locate_inquire"]
    assert tipos_de(m.paso(1002.0, ret=slret(1, "0.01", 50))) == ["locate_inquire"]      # < 1 paquete
    assert m.loc.estado == ESTADO_BUSCANDO


def test_maquina_fallo_tipo_2_durante_la_compra_avisa_sin_darla_por_perdida() -> None:
    m = Maquina()
    compra = m.comprada(1200)
    acciones = m.paso(1002.0, ret=slret(2, "0", 0, notas="Route error"))
    assert tipos_de(acciones) == ["locate_estado", "Avisar"]
    assert acciones[1].nivel is Nivel.AVISO and acciones[1].grupo is Grupo.B
    assert m.loc.estado == ESTADO_COMPRANDO                     # ni recompra ni la da por perdida
    m.paso(1003.0, orden=slorder(70, "Located", 1200, 1200, "0.02", compra.token))
    assert (m.loc.estado, m.gasto) == (ESTADO_LOCALIZADO, D("24"))


def test_maquina_already_shortable_durante_la_compra() -> None:
    m = Maquina()
    m.comprada(1200)
    m.paso(1002.0, ret=slret(2, "0", 0, notas="Already Shortable"))
    assert m.loc.estado == ESTADO_NO_HACE_FALTA


@pytest.mark.parametrize("estado_das", ["Rejected", "Declined", "Canceled", "Closed"])
def test_maquina_fallo_de_la_ruta_para_y_avisa(estado_das: str) -> None:
    """H16 (por definir): un rechazo de la ruta no se reintenta en bucle (riesgo 11); lo ve el humano."""
    m = Maquina()
    compra = m.comprada(1200)
    acciones = m.paso(1002.0, orden=slorder(70, estado_das, 1200, 0, "0", compra.token, notas="no inventory"))
    assert tipos_de(acciones) == ["locate_estado", "Avisar", "Desprogramar"]
    assert acciones[1].nivel is Nivel.AVISO and "no inventory" in acciones[1].texto
    assert m.loc.estado == ESTADO_PARADO
    assert m.paso(1005.0) == [] and m.paso(1006.0, ret=slret(1, "0.001", 5000)) == []


def test_maquina_cerrada_con_parte_localizada_cobra_lo_localizado() -> None:
    m = Maquina()
    compra = m.comprada(1200)
    acciones = m.paso(1002.0, orden=slorder(70, "Canceled", 1200, 400, "0.02", compra.token))
    assert tipos_de(acciones) == ["locate_estado", "Consultar", "locate_estado", "Avisar", "Desprogramar"]
    assert (m.loc.estado, m.loc.localizadas, m.gasto, m.loc.compras) == (ESTADO_PARADO, 400, D("8"), 1)


def test_maquina_located_tardio_de_una_compra_propia_se_cobra() -> None:
    """El dinero ya se gastó: un Located de NUESTRA compra que llega tras «parado» se contabiliza."""
    m = Maquina()
    compra = m.comprada(1200)
    m.paso(1002.0, orden=slorder(70, "Rejected", 1200, 0, "0", compra.token))
    assert m.loc.estado == ESTADO_PARADO
    tarde = m.paso(1003.0, orden=slorder(71, "Located", 1200, 1200, "0.02", compra.token))
    assert tipos_de(tarde) == ["locate_estado", "Consultar", "Desprogramar"]
    assert (m.loc.estado, m.loc.localizadas, m.gasto) == (ESTADO_LOCALIZADO, 1200, D("24"))


def test_maquina_located_sin_acciones_para() -> None:
    m = Maquina()
    compra = m.comprada(1200)
    acciones = m.paso(1002.0, orden=slorder(70, "Located", 1200, 0, "0.02", compra.token))
    assert tipos_de(acciones) == ["locate_estado", "Avisar", "Desprogramar"]
    assert m.loc.estado == ESTADO_PARADO and m.gasto == D("0")


def test_maquina_slorder_ajeno_se_ignora() -> None:
    m = Maquina()
    compra = m.comprada(1200)
    assert m.paso(1002.0, orden=slorder(70, "Located", 1200, 1200, "0.02", compra.token + 1)) == []
    assert m.paso(1002.0, orden=slorder(70, "Located", 1200, 1200, "0.02", None)) == []   # sin id conocido
    assert m.paso(1002.0, orden=slorder(70, "Located", 1200, 1200, "0.02", compra.token, ticker="ABC")) == []
    assert m.loc.estado == ESTADO_COMPRANDO and m.gasto == D("0")


def test_maquina_slorder_sin_token_casa_por_id() -> None:
    m = Maquina()
    compra = m.comprada(1200)
    m.paso(1002.0, orden=slorder(70, "Waiting", 1200, 0, "0", compra.token))
    m.paso(1003.0, orden=slorder(70, "Located", 1200, 1200, "0.02", None))
    assert (m.loc.estado, m.gasto) == (ESTADO_LOCALIZADO, D("24"))


def test_maquina_estado_das_desconocido_se_registra_sin_cambiar() -> None:
    m = Maquina()
    compra = m.comprada(1200)
    acciones = m.paso(1002.0, orden=slorder(70, "Raro", 1200, 0, "0", compra.token))
    assert tipos_de(acciones) == ["locate_estado"] and "estado" not in acciones[0].datos
    assert m.loc.estado == ESTADO_COMPRANDO


def test_maquina_tope_3_pct_no_compra_y_avisa() -> None:
    """R-H-03: 3 % de 1.000 $ = 30 $; con 10 $ gastados, una compra de 24 $ pasaría a 34 $.

    E2-06: el tope por gasto YA PAGADO para el locate («parado») y avisa UNA vez: antes seguía «buscando» y el aviso
    (Telegram + correo) se repetía cada 60 s todo el día.
    """
    m = Maquina(equity="1000", gasto="10")
    m.paso(1000.0, qty=1200)
    acciones = m.paso(1001.0, ret=slret(1, "0.02", 5000))
    assert tipos_de(acciones) == ["locate_estado", "Desprogramar", "Avisar"]
    assert acciones[2].clave == "locates_tope" and acciones[2].nivel is Nivel.AVISO
    assert m.loc.estado == ESTADO_PARADO and m.loc.coste == D("0")       # la previsión NO es gasto pagado
    assert acciones[0].datos["coste_nuevo_previsto"] == D("24") and "coste_total" not in acciones[0].datos
    # E2-06: dos %SLRET seguidos por encima del tope → un solo aviso
    assert m.paso(1004.0, ret=slret(1, "0.02", 5000)) == []
    assert m.paso(1007.0) == []
    assert sum(isinstance(a, Avisar) for a in m.historial) == 1


def test_maquina_tope_justo_en_el_limite_compra() -> None:
    """R-H-03: «que haga SUPERAR»: 10 $ + 20 $ = 30 $ justo en el tope sí compra."""
    m = Maquina(equity="1000", gasto="10")
    m.paso(1000.0, qty=1200)
    assert "LocateComprar" in tipos_de(m.paso(1001.0, ret=slret(1, "0.0166", 5000)))


def test_E2_02_dos_estrategias_a_la_vez_no_superan_el_tope() -> None:
    """E2-02: equity 10.000 (tope 300 $), coste 200 $ cada una; la segunda con la primera en «comprando» → tope.

    Sin contar el gasto COMPROMETIDO, las dos compraban y el total (400 $) superaba el 3 %.
    """
    a = Maquina(e=estrategia(strategy_id="est-a"), equity="8000")         # tope 3 % = 240 $
    b = Maquina(e=estrategia(strategy_id="est-b"), equity="8000")
    compra_a = a.comprada(1000, precio_locate="0.15")                        # 10 paquetes · 100 · 0,15 = 150 $
    assert compra_a.qty == 1000 and a.loc.estado == ESTADO_COMPRANDO
    registro = {(X, "est-a"): a.loc}
    assert gasto_comprometido(registro) == D("150")
    b.paso(1000.0, qty=1000)
    # sin el registro (llamador antiguo) la segunda compraría: 150 + 150 = 300 $ > 240 $
    assert "LocateComprar" in tipos_de(siguiente_paso(
        b.loc, b.e, X, b.precio, 1001.0, b.cfg, b.gasto, b.equity, False, slret(1, "0.15", 10_000), b.tokens))
    acciones = b.paso(1001.0, ret=slret(1, "0.15", 10_000), locates={**registro, (X, "est-b"): b.loc})
    assert "LocateComprar" not in tipos_de(acciones)
    assert tipos_de(acciones) == ["locate_inquire"]                           # solo lo comprometido: sin aviso
    assert acciones[0].datos["gasto_en_curso_otros"] == D("150")
    assert b.loc.estado == ESTADO_BUSCANDO                                    # si la de A falla, B podrá comprar
    # A falla (Rejected, sin localizar): lo comprometido desaparece y B compra
    a.paso(1002.0, orden=slorder(70, "Rejected", 1000, 0, "0", compra_a.token))
    acciones = b.paso(1004.0, ret=slret(1, "0.15", 10_000), locates={(X, "est-a"): a.loc, (X, "est-b"): b.loc})
    assert "LocateComprar" in tipos_de(acciones)


def test_E2_04_compra_sin_respuesta_avisa_una_vez_y_nunca_recompra() -> None:
    """E2-04: «comprando» sin %SLOrder: a los 30 s GET LOCATES + Avisar(2) + parado; nunca otra LocateComprar."""
    m = Maquina()
    compra = m.comprada(1200)                                                # compra a t = 1001
    assert m.paso(1001.0 + COMPRA_SIN_RESPUESTA_S - 0.1) == []               # aún dentro del plazo: cerrojo
    acciones = m.paso(1001.0 + COMPRA_SIN_RESPUESTA_S)                        # salta el temporizador
    assert tipos_de(acciones) == ["locate_estado", "Consultar", "Avisar", "Desprogramar"]
    assert acciones[1] == consulta_locates() == Consultar("GET LOCATES")
    assert acciones[2].nivel is Nivel.AVISO and acciones[2].clave == f"locate_sin_respuesta:{X}:est-a"
    assert m.loc.estado == ESTADO_PARADO
    assert m.paso(1100.0) == [] and m.paso(1101.0, ret=slret(1, "0.001", 5000)) == []
    assert sum(isinstance(a, LocateComprar) for a in m.historial) == 1                  # riesgo 11: nunca recompra
    # si por fin llega el Located de ESA compra (por su token), se cobra: el dinero ya se gastó
    m.paso(1102.0, orden=slorder(70, "Located", 1200, 1200, "0.02", compra.token))
    assert (m.loc.estado, m.gasto) == (ESTADO_LOCALIZADO, D("24"))


def test_E2_04_tras_un_reinicio_la_compra_cuenta_desde_ahora() -> None:
    """El diario no guarda la hora de la compra: sin ella se ancla a ahora (+ Programar) y a los 30 s avisa."""
    loc = replace(Locate(ticker=X, strategy_id="est-a", pedidas=1200), estado=ESTADO_COMPRANDO, token=123)
    m = Maquina()
    m.loc = loc
    acciones = m.paso(5000.0)
    assert tipos_de(acciones) == ["locate_inquire", "Programar"] and m.loc.ultimo_inquire_en == 5000.0
    assert acciones[1] == Programar(CLAVE, COMPRA_SIN_RESPUESTA_S, {"ticker": X, "strategy_id": "est-a"})
    assert m.paso(5010.0) == []
    assert "Avisar" in tipos_de(m.paso(5030.0))


def test_E2_04_located_tardio_por_token_no_es_compra_repetida() -> None:
    """Un Located que llega tras el «parado» por silencio, con el token de NUESTRA compra, no es R-H-02."""
    loc = replace(Locate(ticker=X, strategy_id="est-a", pedidas=1200), estado=ESTADO_PARADO, token=555, compras=1,
                  id_das=70)
    registro = {(X, "est-a"): loc}
    assert compra_repetida(registro, X, "est-a", id_das=71) is True               # sin token: como antes
    assert compra_repetida(registro, X, "est-a", id_das=71, token=555) is False
    assert compra_repetida(registro, X, "est-a", id_das=71, token=556) is True


def test_E2_08_recompra_de_un_resto_pequeno_no_compra_otro_paquete() -> None:
    """E2-08: 1.220 localizadas de 1.240 → falta 20 que no compensan (Jaume 29-sep: 20·5·4 % = 4 < 100·0,05 = 5):
    no se compran 100 para usar 20."""
    v = veredicto_ev(estrategia(), D("5"), 1240, D("0.05"), D("12"), ya_localizadas=1220)
    assert (v["paquetes"], v["qty_comprar"], v["qty_ajustada"], v["entra"]) == (0, 0, 1220, False)
    assert "umbral" in v["motivo"]
    # un resto que SÍ compensa se compra (40 de 100: 40·5·4 % = 8 ≥ 5)
    v2 = veredicto_ev(estrategia(), D("5"), 1240, D("0.05"), D("12"), ya_localizadas=1200)
    assert (v2["paquetes"], v2["qty_comprar"], v2["qty_ajustada"]) == (1, 100, 1240)
    # sin nada cubierto, el mínimo de un paquete sigue (H-7: locates siempre ≥ 100)
    v3 = veredicto_ev(estrategia(), D("5"), 20, D("0.01"), D("0"))
    assert (v3["paquetes"], v3["qty_comprar"]) == (1, 100)


def test_E2_08_la_maquina_no_sigue_buscando_un_resto_pequeno() -> None:
    """Un Located parcial que deja un resto que no compensa (Jaume 29-sep: 20·5·4 % = 4 < 100·0,05) cierra la
    búsqueda (sin bucle de consultas)."""
    m = Maquina()
    compra = m.comprada(1240)                                                # compra 1.300
    hecho = m.paso(1002.0, orden=slorder(70, "Located", 1300, 1220, "0.05", compra.token))
    assert tipos_de(hecho) == ["locate_estado", "Consultar", "Desprogramar"]
    assert m.paso(1010.0) == []


def test_A_06_consultas_con_protocolo():
    """A-06: SLReuseQuery y GET LOCATES salen de protocolo.cmd_* (nombre cerrado, símbolo validado)."""
    from app.bot_das import protocolo
    assert consulta_reuso(X) == Consultar(protocolo.cmd_sl_reuse(X))
    assert consulta_locates() == Consultar(protocolo.cmd_get("LOCATES"))


def test_D2_08_avisos_de_locates_escapan_el_html() -> None:
    """D2-08: un «<» o «&» del texto de DAS o del nombre no puede perder el aviso (Telegram con parse_mode HTML)."""
    m = Maquina(e=estrategia(name="A&B <x>"))
    compra = m.comprada(1200)
    acciones = m.paso(1002.0, orden=slorder(70, "Rejected", 1200, 0, "0", compra.token, notas="Qty > <Max> & co"))
    texto = next(a for a in acciones if isinstance(a, Avisar)).texto
    assert "A&amp;B &lt;x&gt;" in texto and "Qty &gt; &lt;Max&gt; &amp; co" in texto and "<Max>" not in texto


def test_E2_02_gasto_comprometido_suma_pagado_y_en_curso() -> None:
    pagado = replace(Locate(ticker=X, strategy_id="p", pedidas=1000), estado=ESTADO_LOCALIZADO, localizadas=1000,
                     coste=D("50"))
    en_curso = replace(Locate(ticker=X, strategy_id="c", pedidas=1200), estado="Pending", precio_accion=D("0.02"))
    oferta = replace(Locate(ticker="ABC", strategy_id="o", pedidas=300), estado="Offered", precio_accion=D("0.10"),
                     localizadas=100, coste=D("5"))
    parado = replace(Locate(ticker=X, strategy_id="z", pedidas=500), estado=ESTADO_PARADO, precio_accion=D("1"))
    registro = {(X, "p"): pagado, (X, "c"): en_curso, ("ABC", "o"): oferta, (X, "z"): parado}
    # 50 + 5 pagados; en curso: 12 paquetes · 100 · 0,02 = 24 y 2 paquetes · 100 · 0,10 = 20
    assert gasto_comprometido(registro) == D("99")
    assert gasto_comprometido(registro, excluir=(X, "c")) == D("75")
    assert gasto_comprometido({}) == D("0")


def test_maquina_sin_equity_no_compra_ni_avisa() -> None:
    m = Maquina(equity=None)
    m.paso(1000.0, qty=1200)
    acciones = m.paso(1001.0, ret=slret(1, "0.02", 5000))
    assert tipos_de(acciones) == ["locate_inquire"] and "sin equity" in acciones[0].datos["motivo"]


def test_maquina_sin_precio_de_la_accion_no_compra() -> None:
    m = Maquina()
    m.paso(1000.0, qty=1200)
    m.precio = None
    acciones = m.paso(1001.0, ret=slret(1, "0.02", 5000))
    assert tipos_de(acciones) == ["locate_inquire"] and "sin precio" in acciones[0].datos["motivo"]


def test_maquina_minimo_de_la_ruta_entra_en_el_ev() -> None:
    m = Maquina(precio="1")
    m.paso(1000.0, qty=100)
    acciones = m.paso(1001.0, ret=slret(1, "0.001", 5000), minimo_cargo=D("5"))      # 0,10 $ → 5 $ = 5 %
    assert tipos_de(acciones) == ["locate_inquire"] and acciones[0].datos["coste_nuevo"] == D("5")


def test_maquina_hora_limite() -> None:
    """R-H-01.5: pasada la hora límite de intentos, se deja de buscar."""
    cfg = {**CFG, "hora_limite_intentos": "09:00"}
    m = Maquina(cfg=cfg)
    assert tipos_de(m.paso(1000.0, qty=1200, ahora_et=et(8, 59))) == ["locate_inquire", "LocateInquire",
                                                                      "Programar"]
    acciones = m.paso(1003.0, ahora_et=et(9, 0))
    assert tipos_de(acciones) == ["locate_estado", "Desprogramar"] and m.loc.estado == ESTADO_PARADO
    assert m.paso(1004.0, ret=slret(1, "0.001", 5000), ahora_et=et(9, 1)) == []


def test_maquina_hora_limite_rechaza_la_oferta() -> None:
    cfg = {**CFG, "hora_limite_intentos": "09:00"}
    m = Maquina(cfg=cfg)
    m.paso(1000.0, qty=1200, ahora_et=et(8, 58))
    compra = [a for a in m.paso(1001.0, ret=slret(1, "0.02", 5000), ahora_et=et(8, 58))
              if isinstance(a, LocateComprar)][0]
    acciones = m.paso(1002.0, orden=slorder(80, "Offered", 1200, 0, "0.02", compra.token), ahora_et=et(9, 0))
    assert tipos_de(acciones) == ["LocateOferta", "locate_estado", "Desprogramar"]
    assert acciones[0] == LocateOferta(80, False) and m.loc.estado == ESTADO_PARADO


def test_maquina_hora_limite_convierte_a_et() -> None:
    from datetime import timezone
    cfg = {**CFG, "hora_limite_intentos": "09:00"}
    m = Maquina(cfg=cfg)
    m.paso(1000.0, qty=1200, ahora_et=datetime(2026, 9, 25, 12, 59, tzinfo=timezone.utc))   # 08:59 ET
    assert m.loc.estado == ESTADO_BUSCANDO
    m.paso(1003.0, ahora_et=datetime(2026, 9, 25, 13, 0, tzinfo=timezone.utc))            # 09:00 ET
    assert m.loc.estado == ESTADO_PARADO


@pytest.mark.parametrize("ahora_et", [None, datetime(2026, 9, 25, 9, 0)], ids=["sin-ahora_et", "naive"])
def test_maquina_hora_limite_exige_ahora_et_aware(ahora_et: Optional[datetime]) -> None:
    with pytest.raises(ValueError):
        Maquina(cfg={**CFG, "hora_limite_intentos": "09:00"}).paso(1000.0, qty=1200, ahora_et=ahora_et)


def test_maquina_deshabilitada_no_hace_nada() -> None:
    """R-H-02 / R-H-03: con el módulo deshabilitado por el vigilante, ni consultas, ni compras, ni ofertas."""
    m = Maquina()
    assert m.paso(1000.0, qty=1200, deshabilitado=True) == []
    compra = m.comprada(1200)
    assert m.paso(1002.0, ret=slret(1, "0.01", 5000), deshabilitado=True) == []
    assert m.paso(1002.0, orden=slorder(70, "Offered", 1200, 0, "0.02", compra.token), deshabilitado=True) == []


def test_maquina_tokens_como_callable_y_de_otro_origen() -> None:
    m = Maquina()
    m.tokens = GeneradorTokens(Origen.EJECUTOR_LOCATE, HOY).siguiente
    assert m.comprada(1200).token == 326800001
    malo = Maquina()
    malo.tokens = GeneradorTokens(Origen.EJECUTOR, HOY)
    malo.paso(1000.0, qty=1200)
    with pytest.raises(ValueError):
        malo.paso(1001.0, ret=slret(1, "0.02", 5000))


def test_maquina_no_gasta_token_sin_comprar() -> None:
    m = Maquina()
    m.paso(1000.0, qty=1200)
    m.paso(1001.0, ret=slret(1, "0.50", 5000))
    assert m.tokens.ultimo_seq == 0


def test_maquina_slret_de_otro_ticker_se_ignora() -> None:
    m = Maquina()
    m.paso(1000.0, qty=1200)
    assert m.paso(1001.0, ret=slret(1, "0.02", 5000, ticker="ABC")) == []


def test_maquina_nada_que_localizar_deja_de_consultar() -> None:
    m = Maquina()
    m.loc = Locate(ticker=X, strategy_id="est-a", pedidas=300, localizadas=300, compras=1, estado=ESTADO_BUSCANDO)
    acciones = m.paso(1000.0)
    assert tipos_de(acciones) == ["locate_inquire", "Desprogramar"]


@pytest.mark.parametrize("cfg", [
    pytest.param({**CFG, "ruta_inquire": "ALLROUTE"}, id="5.22-ALLROUTE-crea-Offered"),
    pytest.param({**CFG, "ruta_inquire": "allroute"}, id="5.22-allroute"),
    pytest.param({**CFG, "ruta_inquire": ""}, id="ruta-vacia"),
    pytest.param({**CFG, "ruta_inquire": "A B"}, id="ruta-con-espacio"),
    pytest.param({**CFG, "hora_limite_intentos": "9:00"}, id="hora-mal-formada"),
    pytest.param({**CFG, "hora_limite_intentos": "24:00"}, id="hora-fuera-de-rango"),
    pytest.param({**CFG, "umbral_ultimo_paquete_pct": 101}, id="umbral-fuera"),
    pytest.param({**CFG, "tope_gasto_pct_cuenta": -1}, id="tope-negativo"),
    pytest.param({**CFG, "inquiry_intervalo_s": 0}, id="intervalo-0"),
    pytest.param(None, id="sin-bloque"),
])
def test_maquina_config_imposible(cfg: Any) -> None:
    with pytest.raises(ValueError):
        siguiente_paso(None, estrategia(), X, D("5"), 1000.0, cfg, D("0"), D("1000"), False, None,
                       GeneradorTokens(Origen.EJECUTOR_LOCATE, HOY), qty=1200)


def test_maquina_config_por_defecto() -> None:
    acciones = siguiente_paso(None, estrategia(), X, D("5"), 1000.0, {}, D("0"), D("1000"), False, None,
                              GeneradorTokens(Origen.EJECUTOR_LOCATE, HOY), qty=1200)
    assert acciones[1] == LocateInquire(X, 1200, "ALLROUTEWTTYPE1") and acciones[2].en_s == 3.0


def test_maquina_locate_de_otro_par() -> None:
    with pytest.raises(ValueError):
        siguiente_paso(loc(ticker="ABC"), estrategia(), X, D("5"), 1000.0, CFG, D("0"), D("1000"), False, None,
                       GeneradorTokens(Origen.EJECUTOR_LOCATE, HOY))
    with pytest.raises(ValueError):
        siguiente_paso(loc("otra"), estrategia(), X, D("5"), 1000.0, CFG, D("0"), D("1000"), False, None,
                       GeneradorTokens(Origen.EJECUTOR_LOCATE, HOY))


def test_maquina_escalonada_segunda_estrategia_con_su_propio_ev() -> None:
    """R-H-05 FIJADA: cada estrategia compra lo suyo con SU EV; la primera no condiciona a la segunda."""
    a = Maquina(e=estrategia())
    b = Maquina(e=estrategia(strategy_id="est-b", name="PM (B)", ev_pct=D("1")))
    assert a.comprada(1000).qty == 1000
    b.paso(1000.0, qty=500)
    acciones = b.paso(1001.0, ret=slret(1, "0.10", 5000))                           # fade 2 % > EV 1 %
    assert tipos_de(acciones) == ["locate_inquire"]
    assert acciones[0].datos["strategy_id"] == "est-b"
    assert clave_temporizador(X, "est-b") == "locate_inquire:XYZ:est-b"


# ── el reductor (H-2: el mismo estado en caliente y releído) ──────────
def test_aplicar_anotaciones_ignora_lo_que_no_es_suyo() -> None:
    base = loc(estado=ESTADO_BUSCANDO)
    acciones = [Avisar(Nivel.INFO, Grupo.B, "x"), Anotar("lote", {"ticker": X, "strategy_id": "est-a"}),
                Anotar("locate_estado", {"ticker": "ABC", "strategy_id": "est-a", "estado": "Located"}),
                Anotar("locate_estado", {"ticker": X, "strategy_id": "otra", "estado": "Located"})]
    assert aplicar_anotaciones(base, acciones) == base
    assert aplicar_anotaciones(None, acciones[:2]) is None


def test_aplicar_anotaciones_compras_solo_al_entrar_en_located() -> None:
    datos = {"ticker": X, "strategy_id": "est-a", "estado": "Located", "coste_nuevo": D("5"), "coste_total": D("5"),
             "localizadas": 100, "qty_ajustada": 100}
    nuevo = aplicar_anotaciones(None, [Anotar("locate_estado", datos)])
    assert (nuevo.compras, nuevo.coste, nuevo.localizadas, nuevo.pedidas) == (1, D("5"), 100, 100)
    otra_vez = aplicar_anotaciones(nuevo, [Anotar("locate_estado", {**datos, "usadas": 100,
                                                                     "coste_nuevo": D("0")})])
    assert (otra_vez.compras, otra_vez.usadas, otra_vez.coste) == (1, 100, D("5"))
    assert gasto_de([Anotar("locate_estado", datos), Anotar("locate_estado", {**datos, "estado": "buscando"}),
                     Anotar("locate_inquire", datos)]) == D("5")


def test_la_prevision_de_coste_no_cuenta_como_pagada() -> None:
    """Regresión: el `coste_total` PREVISTO de una consulta, una intención o una oferta no es dinero gastado."""
    m = Maquina()
    compra = m.comprada(1200)
    assert m.loc.coste == D("0") and m.gasto == D("0")
    oferta = m.paso(1002.0, orden=slorder(80, "Offered", 1200, 0, "0.02", compra.token))
    assert "coste_total" not in oferta[0].datos and oferta[0].datos["coste_total_previsto"] == D("24")
    assert m.loc.coste == D("0") and m.gasto == D("0")
    m.paso(1003.0, orden=slorder(80, "Located", 1200, 1200, "0.02", compra.token))
    assert (m.loc.coste, m.gasto) == (D("24"), D("24"))


def test_el_diario_reconstruye_el_mismo_locate() -> None:
    """H-2 / F13: lo anotado por la máquina, releído por `diario.reconstruir`, da el mismo locate y el mismo gasto."""
    diario = pytest.importorskip("app.bot_das.diario")
    m = Maquina(precio="1")
    compra = m.comprada(300, precio_locate="0.01", tamano=200)
    m.paso(1002.0, orden=slorder(70, "Pending", 200, 0, "0", compra.token))
    m.paso(1003.0, orden=slorder(70, "Located", 200, 200, "0.01", compra.token))
    segunda = [a for a in m.paso(1004.0, ret=slret(1, "0.01", 100)) if isinstance(a, LocateComprar)][0]
    m.paso(1005.0, orden=slorder(71, "Offered", 100, 0, "0.01", segunda.token))
    m.paso(1006.0, orden=slorder(71, "Located", 100, 100, "0.01", segunda.token))
    anotaciones = [a for a in m.historial if isinstance(a, Anotar)]
    registros = []
    for seq, a in enumerate(anotaciones, start=1):
        datos = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in a.datos.items()}
        registros.append(diario.Registro(v=1, seq=seq, t=f"2026-09-25T09:31:{seq:02d}.000-04:00",
                                         proceso="ejecutor", tipo=a.tipo, datos=datos))
    estado = diario.reconstruir(registros, HOY)
    releido = estado.locates[(X, "est-a")]
    campos = ("estado", "pedidas", "localizadas", "coste", "compras", "token", "id_das")
    assert {c: getattr(releido, c) for c in campos} == {c: getattr(m.loc, c) for c in campos}
    assert estado.gasto_locates_dia == m.gasto == D("3")


def test_aplicar_anotaciones_pedidas_no_bajan() -> None:
    base = loc(pedidas=1240)
    nuevo = aplicar_anotaciones(base, [Anotar("locate_intencion", {"ticker": X, "strategy_id": "est-a",
                                                                   "qty": 1300, "qty_ajustada": 200,
                                                                   "token": 326800001})])
    assert (nuevo.pedidas, nuevo.estado, nuevo.token) == (1240, ESTADO_COMPRANDO, 326800001)


# ── pureza (§3: reglas/* sin I/O, reloj, logging ni entorno) ──────────
def test_modulo_puro() -> None:
    fuente = Path(L.__file__).read_text(encoding="utf-8")
    for prohibido in ("import time", "datetime.now", "import logging", "os.environ", "getenv", "httpx",
                      "import socket", "evaluar(", "float(round"):
        assert prohibido not in fuente, prohibido


# ── Jaume 29-sep: regla MARGINAL del último paquete ─────────────────────
@pytest.mark.parametrize("qty, precio_locate, esperado", [
    pytest.param(113, "0.01", (2, 113), id="113-locate-0.01-paga-el-paquete"),
    pytest.param(113, "0.05", (1, 100), id="113-locate-0.05-no"),
    pytest.param(113, "0.15", (1, 100), id="113-locate-0.15-no"),
    pytest.param(160, "0.01", (2, 160), id="160-locate-0.01"),
    pytest.param(160, "0.05", (2, 160), id="160-locate-0.05"),
    pytest.param(160, "0.15", (1, 100), id="160-locate-0.15-12-menor-que-15"),
    pytest.param(100, "0.15", (1, 100), id="100-exacto-sin-resto"),
    pytest.param(30, "0.15", (1, 30), id="30-minimo-un-paquete-H-7"),
    pytest.param(0, "0.01", (0, 0), id="0"),
    pytest.param(-5, "0.01", (0, 0), id="negativo"),
])
def test_paquetes_marginal_tabla_jaume_29_sep(qty: int, precio_locate: str, esperado: tuple[int, int]) -> None:
    """Jaume 29-sep: el último paquete se compra si extra · precio · EV/100 ≥ 100 · precio del locate (EV 4 %, 5 $)."""
    assert L.paquetes_marginal(qty, D("5"), D("4"), D(precio_locate)) == esperado


def test_paquetes_marginal_limite_exacto_compra() -> None:
    """En el límite exacto se compra: 25 extra · 5 $ · 4 % = 5 = 100 · 0,05."""
    assert L.paquetes_marginal(125, D("5"), D("4"), D("0.05")) == (2, 125)
    assert L.paquetes_marginal(124, D("5"), D("4"), D("0.05")) == (1, 100)


@pytest.mark.parametrize("qty", [113, 130, 131, 160, 1230, 1240])
def test_paquetes_marginal_sin_precio_de_locate_cae_al_umbral(qty: int) -> None:
    """Sin precio del locate (primera consulta sin %SLRET), o sin precio o EV, → la regla del 30 % de siempre."""
    assert L.paquetes_marginal(qty, D("5"), D("4"), None) == paquetes(qty)
    assert L.paquetes_marginal(qty, None, D("4"), D("0.01")) == paquetes(qty)
    assert L.paquetes_marginal(qty, D("5"), None, D("0.01")) == paquetes(qty)


def test_paquetes_marginal_rechaza_valores_imposibles() -> None:
    with pytest.raises(ValueError):
        L.paquetes_marginal(113, D("0"), D("4"), D("0.01"))
    with pytest.raises(ValueError):
        L.paquetes_marginal(113, D("5"), D("4"), D("-0.01"))
    with pytest.raises(ValueError):
        L.paquetes_marginal(113.0, D("5"), D("4"), D("0.01"))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        L.paquetes_marginal(113, D("5"), D("4"), D("0.01"), umbral_ultimo_pct=101)


@pytest.mark.parametrize("precio_locate, paq, usable", [
    pytest.param("0.01", 2, 113, id="compensa"),
    pytest.param("0.05", 1, 100, id="no-compensa"),
])
def test_veredicto_ev_usa_la_regla_marginal_en_el_ultimo_paquete(precio_locate: str, paq: int, usable: int) -> None:
    """Jaume 29-sep: `veredicto_ev` decide el último paquete con el precio de ESE locate; el EV global, como siempre."""
    v = veredicto_ev(estrategia(), D("5"), 113, D(precio_locate), D("0"))
    assert (v["paquetes"], v["qty_ajustada"], v["qty_comprar"]) == (paq, usable, paq * 100)
    assert v["fade_pct"] == D(paq * 100) * D(precio_locate) * 100 / (D(usable) * D("5"))


def test_veredicto_ev_1230_con_locate_barato_compra_el_13() -> None:
    """Antes el paquete 13 de 1.230 (30 %) no se compraba; ahora sí si las 30 extra lo pagan: 30·5·4 % = 6 ≥ 2."""
    v = veredicto_ev(estrategia(), D("5"), 1230, D("0.02"), D("0"))
    assert (v["paquetes"], v["qty_ajustada"], v["qty_comprar"]) == (13, 1230, 1300)


def test_maquina_primera_consulta_con_el_30_y_despues_marginal() -> None:
    """Jaume 29-sep: la primera consulta (sin precio de locate) pide con el umbral del 30 % (113 → 100); con el
    %SLRET a 0,01 el último paquete compensa y se compran 200 para usar 113."""
    m = Maquina()
    primera = m.paso(1000.0, qty=113)
    assert [a.qty for a in primera if isinstance(a, LocateInquire)] == [100]
    compra = [a for a in m.paso(1001.0, ret=slret(1, "0.01", 10_000)) if isinstance(a, LocateComprar)]
    assert [c.qty for c in compra] == [200]
    caro = Maquina()
    caro.paso(1000.0, qty=113)
    compra_cara = [a for a in caro.paso(1001.0, ret=slret(1, "0.05", 10_000)) if isinstance(a, LocateComprar)]
    assert [c.qty for c in compra_cara] == [100]


# ── Jaume 29-sep: locates por FASES (la parte pura) ─────────────────────
def _en_fase(m: Maquina, fase: str, precio_senal: Optional[str] = "5", qty: int = 100) -> None:
    """Arranca la máquina (primera consulta) y la pone en `fase` con la referencia «a tiro» dada."""
    m.paso(1000.0, qty=qty)
    datos: dict = {"ticker": X, "strategy_id": "est-a", "fase": fase}
    if precio_senal is not None:
        datos["precio_senal"] = D(precio_senal)
    m.loc = aplicar_anotaciones(m.loc, [Anotar("locate_estado", datos)])


@pytest.mark.parametrize("fase", ["B", "C_piramide"])
def test_intento_unico_a_tiro_y_compensa_compra(fase: str) -> None:
    m = Maquina()
    _en_fase(m, fase)
    acciones = m.paso(1001.0, ret=slret(1, "0.01", 10_000))
    assert [a.qty for a in acciones if isinstance(a, LocateComprar)] == [100]


@pytest.mark.parametrize("precio, a_tiro", [
    pytest.param("4.85", True, id="justo-el-3pct-esta-a-tiro"),
    pytest.param("4.84", False, id="mas-del-3pct-no"),
])
def test_intento_unico_mira_el_3_pct_de_la_entrada(precio: str, a_tiro: bool) -> None:
    """Jaume 29-sep: «a tiro» = precio actual ≥ precio de la señal · (1 − 3 %) (el 3 % de R-B-01); 5 · 0,97 = 4,85."""
    m = Maquina(precio=precio)
    _en_fase(m, L.FASE_SENAL, precio_senal="5")
    acciones = m.paso(1001.0, ret=slret(1, "0.01", 10_000))
    assert bool([a for a in acciones if isinstance(a, LocateComprar)]) is a_tiro
    if not a_tiro:
        assert m.loc.estado == ESTADO_PARADO and "a tiro" in acciones[0].datos["motivo"]
        assert "Desprogramar" in tipos_de(acciones)


def test_intento_unico_con_otro_tope_a_tiro() -> None:
    """El tope «a tiro» es el `entrada.tope_caida_bid_pct` que pase el decisor (aquí 5 %: 4,80 está a tiro)."""
    m = Maquina(precio="4.80")
    _en_fase(m, L.FASE_SENAL)
    acciones = m.paso(1001.0, ret=slret(1, "0.01", 10_000), tope_a_tiro_pct=5)
    assert [a.qty for a in acciones if isinstance(a, LocateComprar)] == [100]


@pytest.mark.parametrize("ret", [
    pytest.param(slret(1, "0.50", 10_000), id="no-compensa"),
    pytest.param(slret(1, "0.01", 0), id="sin-tamano"),
    pytest.param(slret(2, "0", 0, notas="NoInventory"), id="fallo-de-la-ruta"),
])
def test_intento_unico_sin_compra_para_la_pareja(ret: MsgSLRet) -> None:
    """Jaume 29-sep: en B / C_piramide el %SLRET que no acaba en compra deja la pareja PARADA (un solo intento)."""
    m = Maquina()
    _en_fase(m, L.FASE_SENAL)
    acciones = m.paso(1001.0, ret=ret)
    assert m.loc.estado == ESTADO_PARADO and not [a for a in acciones if isinstance(a, LocateComprar)]
    assert m.paso(1010.0) == []                                   # terminal: sin más consultas


@pytest.mark.parametrize("fase", ["A", "C"])
def test_fases_A_y_C_siguen_buscando_sin_mirar_a_tiro(fase: str) -> None:
    """En A (radar) y C (dentro) un %SLRET que no compensa solo se anota y se sigue buscando; «a tiro» no cuenta."""
    m = Maquina(precio="3")
    _en_fase(m, fase, precio_senal="5")
    assert m.loc.estado == ESTADO_BUSCANDO
    m.paso(1001.0, ret=slret(1, "0.50", 10_000))
    assert m.loc.estado == ESTADO_BUSCANDO
    acciones = m.paso(1004.0, ret=slret(1, "0.01", 10_000))
    assert [a.qty for a in acciones if isinstance(a, LocateComprar)] == [100]      # 3 < 5 · 0,97 y compra igual


def test_intento_unico_oferta_rechazada_para_la_pareja() -> None:
    """Una oferta (ruta tipo 1) que ya no compensa en el intento único → Reject y PARADO (no vuelve a buscar)."""
    m = Maquina()
    _en_fase(m, L.FASE_SENAL)
    compra = [a for a in m.paso(1001.0, ret=slret(1, "0.01", 10_000)) if isinstance(a, LocateComprar)][0]
    acciones = m.paso(1002.0, orden=slorder(70, "Offered", 100, 0, "0.50", compra.token))
    assert LocateOferta(70, False) in acciones and m.loc.estado == ESTADO_PARADO


def test_intento_unico_sin_nada_que_compense_acaba_sin_consultar() -> None:
    """C_piramide con el resto que no compensa (precio del locate ya conocido) → parado sin consultar."""
    m = Maquina()
    m.loc = Locate(ticker=X, strategy_id="est-a", pedidas=170, localizadas=150, usadas=100, estado=ESTADO_BUSCANDO,
                   precio_accion=D("0.05"), fase=L.FASE_PIRAMIDE, precio_senal=D("5"))
    acciones = m.paso(1000.0, en_uso_vivo=100)                   # falta 20: 20 · 5 · 4 % = 4 < 100 · 0,05
    assert m.loc.estado == ESTADO_PARADO and not [a for a in acciones if isinstance(a, LocateInquire)]


def test_intento_unico_resto_sin_precio_conocido_consulta_un_paquete() -> None:
    """Sin precio de locate conocido el resto de 20 (≤ 30 %) se consulta igual en el intento: decide el %SLRET."""
    m = Maquina()
    m.loc = Locate(ticker=X, strategy_id="est-a", pedidas=170, localizadas=150, usadas=100, estado=ESTADO_BUSCANDO,
                   fase=L.FASE_PIRAMIDE, precio_senal=D("5"))
    acciones = m.paso(1000.0, en_uso_vivo=100)
    assert [a.qty for a in acciones if isinstance(a, LocateInquire)] == [100]
    compra = m.paso(1001.0, ret=slret(1, "0.01", 10_000), en_uso_vivo=100)       # 20 · 5 · 4 % = 4 ≥ 1
    assert [a.qty for a in compra if isinstance(a, LocateComprar)] == [100]


def test_en_uso_vivo_cuenta_como_cubierto_en_la_fase_C() -> None:
    """Jaume 29-sep: lo que usan los lotes vivos de la pareja cubre N: con 150 localizadas, 100 en la entrada y N = 170
    faltan 20 (no 120), y sin `en_uso_vivo` se volverían a comprar las 100 de la entrada."""
    loc = Locate(ticker=X, strategy_id="est-a", pedidas=170, localizadas=150, usadas=100, estado=ESTADO_BUSCANDO,
                 precio_accion=D("0.01"), fase=L.FASE_DENTRO)
    con = Maquina()
    con.loc = loc
    assert [a.qty for a in con.paso(1000.0, en_uso_vivo=100) if isinstance(a, LocateInquire)] == [100]
    sin = Maquina()
    sin.loc = loc
    assert [a.qty for a in sin.paso(1000.0) if isinstance(a, LocateInquire)] == [200]


def test_reductor_aplica_fase_precio_senal_y_N_recalculada() -> None:
    """El reductor (el mismo que el diario) aplica `fase`, `precio_senal` (None la borra) y `pedidas_n` (manda)."""
    loc = aplicar_anotaciones(None, [Anotar("locate_estado", {"ticker": X, "strategy_id": "est-a", "qty": 113,
                                                              "estado": "buscando"})])
    assert (loc.fase, loc.precio_senal, loc.pedidas) == ("A", None, 113)
    loc = aplicar_anotaciones(loc, [Anotar("locate_estado", {"ticker": X, "strategy_id": "est-a", "fase": "B",
                                                             "precio_senal": D("3.45"), "pedidas_n": 90})])
    assert (loc.fase, loc.precio_senal, loc.pedidas) == ("B", D("3.45"), 90)
    loc = aplicar_anotaciones(loc, [Anotar("locate_estado", {"ticker": X, "strategy_id": "est-a", "fase": "raro",
                                                             "precio_senal": None})])
    assert (loc.fase, loc.precio_senal) == ("B", None)


def test_la_pedida_original_sobrevive_al_ajuste_de_H6() -> None:
    """Jaume 29-sep: `qty_pedida` guarda la N original (113) aunque la primera consulta, sin precio, ajuste a 100."""
    m = Maquina()
    m.paso(1000.0, qty=113)
    assert m.loc.pedidas == 113
