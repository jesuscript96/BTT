"""reglas/stops.py: R-C-01 v4 (Jaume 29-sep, stop único: disparo en L, límite L + 50 %), banda (R-F-02), conjunto deseado,
plan idempotente con neteo (R-C-07), limpieza (R-C-11), venta del exceso y protección (R-C-10)."""
from __future__ import annotations

import ast
import itertools
import json
import random
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from app.bot_das.reglas import stops
from app.bot_das.reglas.stops import (
    CLAVE_REPLANIFICAR, CLAVE_VERIFICAR_REPLACE, COMANDO_POSICIONES, REPLANIFICAR_EN_S, TIPO_STOP_EN_ORDER,
    VERIFICAR_REPLACE_EN_S, cantidad_cancelada, conjunto_deseado, descubiertas, inferir_proposito,
    limpieza_tras_fill_stop, nivel_de_stop, niveles, plan, serie_stops, stop_proteccion, tipo_conserva_pp,
)
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    STOP_LIMITE_PCT, STOP_MARGEN_BAJO_LIMIT_UP_PCT,
    Anotar, Avisar, Cancelar, CancelarTicker, Config, Consultar, Cotizacion, EnviarOrden, EstadoLote, EstadoOrden,
    EstadoTicker, Fase, Grupo, InvalidarSerie, Lado, Lote, MsgOrden, MsgOrderAct, Nivel, NivelesStop, Orden, OrdenNueva,
    Origen, PosicionTicker, Programar, Proposito, Reemplazar, StopDeseado, TipoOrden, en_tick,
)

D = Decimal
RUTA_CONFIG = Path(__file__).parent / "fixtures" / "config_ejemplo.json"
HORA = datetime(2026, 9, 25, 9, 30, tzinfo=ET)
X = "XYZ"
RUTA_STOP = "STOP"
VERSION = 7
STOP = Proposito.STOP


# ── fixtures y constructores ────────────────────────────────────────────
@pytest.fixture(scope="module")
def cfg_json() -> dict:
    return json.loads(RUTA_CONFIG.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cfg_stops(cfg_json) -> dict:
    """El bloque `stops` tal cual sale del JSON (floats): el módulo lo convierte UNA vez con de_float."""
    return cfg_json["stops"]


@pytest.fixture(scope="module")
def config(cfg_json) -> Config:
    """`Config` real de tipos construida desde el fichero de ejemplo (sin depender de config.py, lote B)."""
    claves = ("schema_version", "config_version", "sha256", "motor_hash", "estrategias_hash", "generado_at", "vigilando",
              "horario", "modo_seguridad", "lista_negra", "pausar_entradas", "locates", "entrada", "salidas", "stops",
              "halts", "exclusiones", "rutas", "tecnicos", "alertas_grupo_a")
    return Config(fase=Fase(cfg_json["fase"]), estrategias={}, cuenta_das="CUENTA_PRUEBA",
                  **{clave: cfg_json[clave] for clave in claves})


def lote(id_: str, nivel, llenas: int, estado: EstadoLote = EstadoLote.ABIERTO, direccion: str = "Short",
         ticker: str = X) -> Lote:
    if nivel is None or isinstance(nivel, (Decimal, float)):
        nivel_stop = nivel
    else:
        nivel_stop = D(str(nivel))
    return Lote(id=id_, strategy_id=f"s-{id_}", estrategia=f"E {id_}", ticker=ticker, direccion=direccion,
                pedidas=llenas or 1, llenas=llenas, nivel_stop=nivel_stop, estado=estado)


def posicion(lotes: list[Lote], neta_fills: int, neta_das: Optional[int] = None,
             estado: EstadoTicker = EstadoTicker.NORMAL) -> PosicionTicker:
    return PosicionTicker(ticker=X, lotes={l.id: l for l in lotes}, neta_fills=neta_fills, neta_das=neta_das, estado=estado)


def orden(token: int, proposito: Proposito, stop, precio, qty: int, id_das: Optional[int] = 1, enviada_en: float = 1000.0,
          estado: EstadoOrden = EstadoOrden.ACCEPTED, origen: Origen = Origen.EJECUTOR, nivel=None, llenas: int = 0,
          lvqty: int = 0, lado: Lado = Lado.COMPRA, tipo: TipoOrden = TipoOrden.STOP_LIMITE_PP, ticker: str = X,
          lote_id: Optional[str] = None) -> Orden:
    return Orden(token=token, ticker=ticker, lado=lado, tipo=tipo, qty=qty,
                 precio=None if precio is None else D(str(precio)), stop=None if stop is None else D(str(stop)),
                 ruta=RUTA_STOP, proposito=proposito, lote_id=lote_id, nivel=None if nivel is None else D(str(nivel)),
                 origen=origen, id_das=id_das, estado=estado, lvqty=lvqty, llenas=llenas, enviada_en=enviada_en)


def stop10(qty: int = 100, **kw) -> Orden:
    """El stop del nivel 10 (disparo 10,00, límite 15,00) con el token 100000001 salvo que se diga otro."""
    kw.setdefault("nivel", 10)
    return orden(kw.pop("token", 100000001), STOP, "10.00", "15.00", qty, **kw)


def stop11(qty: int = 40, **kw) -> Orden:
    """El stop del nivel 11 (disparo 11,00, límite 16,50) con el token 100000002 salvo que se diga otro."""
    kw.setdefault("nivel", 11)
    kw.setdefault("id_das", 2)
    return orden(kw.pop("token", 100000002), STOP, "11.00", "16.50", qty, **kw)


def aceptada(env: EnviarOrden, id_das: int, enviada_en: float = 1000.0) -> Orden:
    """Lo que el decisor registraría tras el %ORDER Accepted de una orden enviada por `plan`."""
    o = env.orden
    return Orden(token=o.token, ticker=o.ticker, lado=o.lado, tipo=o.tipo, qty=o.qty, precio=o.precio, stop=o.stop,
                 ruta=o.ruta, proposito=o.proposito, lote_id=o.lote_id, nivel=o.nivel, origen=Origen.EJECUTOR,
                 id_das=id_das, estado=EstadoOrden.ACCEPTED, lvqty=o.qty, enviada_en=enviada_en, version=o.version)


def msg_orden(lado: str, tipo: str, precio, cxlqty: int = 0, qty: int = 100,
              estado: EstadoOrden = EstadoOrden.ACCEPTED) -> MsgOrden:
    return MsgOrden(cruda="%ORDER …", id=77, token=None, ticker=X, lado=lado, tipo=tipo, qty=qty, lvqty=qty - cxlqty,
                    cxlqty=cxlqty, precio=D(str(precio)), ruta="SMAT", estado=estado, hora="09:49:27", origoid=0,
                    cuenta="CUENTA_PRUEBA", trader="T", order_src="CMDAPI", tif="DAY+", pref=None, watch=False)


def msg_act(accion: str, qty: int) -> MsgOrderAct:
    return MsgOrderAct(cruda="%OrderAct …", id=77, accion=accion, lado="B", ticker=X, qty=qty, precio=D("15.00"),
                       ruta="SMAT", hora="09:49:27", notas="", token=None)


def verificar(token: int, qty: int) -> Programar:
    """El `replace_verificar` que acompaña a cada REPLACE (2h.8) con la cantidad ABIERTA buscada."""
    return Programar(CLAVE_VERIFICAR_REPLACE, VERIFICAR_REPLACE_EN_S, {"token": token, "ticker": X, "qty_objetivo": qty})


def de_tipo(acciones, clase) -> list:
    return [a for a in acciones if isinstance(a, clase)]


def sin_float(o: OrdenNueva) -> None:
    for valor in (o.precio, o.stop, o.nivel):
        assert valor is None or type(valor) is Decimal
    assert type(o.qty) is int and type(o.token) is int


def _viva(o: Orden) -> int:
    """Misma cantidad viva que el módulo (D2a-07): min(lvqty, qty − llenas) si DAS dio lvqty; si no, qty − llenas."""
    if o.estado in (EstadoOrden.PARTIAL, EstadoOrden.TRIGGERED) and o.lvqty > 0:
        return max(min(o.lvqty, o.qty - o.llenas), 0)
    return max(o.qty - o.llenas, 0)


def _aplicar(acciones, vivas: list[Orden], ids) -> list[Orden]:
    """DAS de mentira: EnviarOrden → aceptada; Reemplazar → nueva cantidad ABIERTA; Cancelar/CancelarTicker → fuera."""
    vivas = list(vivas)
    for a in acciones:
        if isinstance(a, EnviarOrden):
            vivas.append(aceptada(a, id_das=next(ids)))
        elif isinstance(a, Reemplazar):
            o = next(o for o in vivas if o.id_das == a.id_das)
            o.qty, o.lvqty, o.stop, o.precio = o.llenas + a.qty, a.qty, a.stop, a.precio
        elif isinstance(a, Cancelar):
            vivas = [o for o in vivas if o.id_das != a.id_das]
        elif isinstance(a, CancelarTicker):
            vivas = [o for o in vivas if o.ticker != a.ticker]
        else:
            assert isinstance(a, (InvalidarSerie, Avisar, Anotar)) or (
                isinstance(a, Programar) and (a.clave == CLAVE_VERIFICAR_REPLACE
                                              or a.clave == stops.clave_exceso_verificar(X))), a
    return vivas


def _llenar(o: Orden, qty: int, pos: PosicionTicker, cfg_stops: dict, limit_up=None) -> None:
    """Un fill de un stop de compra (Execute) y lo que hace el decisor (`_reducir_lotes`): llenas, lvqty, estado, la neta de
    fills (corrección 2) y las `llenas` de los lotes del NIVEL del stop (R-C-01 v4); lo que sobre, de los lotes más altos."""
    o.llenas += qty
    o.lvqty = o.qty - o.llenas
    o.estado = EstadoOrden.EXECUTED if o.llenas >= o.qty else EstadoOrden.PARTIAL
    pos.neta_fills += qty
    nivel = nivel_de_stop(o, pos, cfg_stops, limit_up)
    vivos = [l for l in pos.lotes.values() if l.estado not in (EstadoLote.CERRADO, EstadoLote.CANCELADO) and l.llenas > 0]
    propios = [l for l in vivos if nivel is not None and l.nivel_stop == nivel]
    resto = sorted((l for l in vivos if l not in propios), key=lambda l: l.nivel_stop, reverse=True)
    restante = qty
    for l in propios + resto:
        n = min(restante, l.llenas)
        l.llenas -= n
        restante -= n
        if l.llenas == 0:
            l.estado = EstadoLote.CERRADO
        if restante <= 0:
            break


def _cierre(pos: PosicionTicker, qty: int) -> None:
    """Una compra de CIERRE (salida del halt, cierre humano) que llena: la neta sube y el decisor (`_fill_salida`) descuenta los
    lotes; aquí, del nivel más alto. Sus stops NO se han reducido todavía (el REPLACE no ha salido): es la carrera."""
    pos.neta_fills += qty
    restante = qty
    for l in sorted((l for l in pos.lotes.values() if l.llenas > 0), key=lambda l: l.nivel_stop, reverse=True):
        n = min(restante, l.llenas)
        l.llenas -= n
        restante -= n
        if l.llenas == 0:
            l.estado = EstadoLote.CERRADO
        if restante <= 0:
            break


def _mis_stops(vivas: list[Orden], pos: PosicionTicker, cfg: dict, limit_up) -> list[Orden]:
    """Stops de compra NUESTROS vivos del ticker con propósito efectivo STOP (etiqueta propia o inferido)."""
    niveles_lotes = [l.nivel_stop for l in pos.lotes.values()]
    salida = []
    for o in vivas:
        if (o.ticker != X or o.lado is not Lado.COMPRA or o.tipo is not TipoOrden.STOP_LIMITE_PP
                or o.estado not in (EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL) or _viva(o) <= 0):
            continue
        proposito = o.proposito if o.proposito is not Proposito.DESCONOCIDA else inferir_proposito(o, niveles_lotes, cfg,
                                                                                                    limit_up)
        if proposito is STOP:
            salida.append(o)
    return salida


# ── niveles (R-C-01 v4; R-F-02 bajo la banda) ───────────────────────────
def test_niveles_10_son_10_y_15(cfg_stops):
    """R-C-01 v4 (Jaume 29-sep, stop único): disparo EN L y límite L + 50 % SUMADO sobre L (L × 1,50). Sin emergencia."""
    n = niveles(D("10"), cfg_stops)
    assert n == NivelesStop(D("10.00"), D("15.00"), False)
    assert type(n.disparo) is Decimal and type(n.limite) is Decimal and en_tick(n.disparo) and en_tick(n.limite)
    assert cfg_stops["limite_pct"] == 50.0 and set(vars(n)) == {"disparo", "limite", "bajo_banda"}


@pytest.mark.parametrize("L,esperado", [
    pytest.param("10.123", ("10.13", "15.19"), id="R-C-01-v4-redondeo-ARRIBA-al-tick-(limite-sobre-L)"),
    pytest.param("0.5", ("0.5000", "0.7500"), id="R-C-01-v4-pennies-tick-0.0001"),
    pytest.param("0.6", ("0.6000", "0.9000"), id="R-C-01-v4-penny-que-no-llega-a-1"),
    pytest.param("1", ("1.00", "1.50"), id="R-C-01-v4-un-dolar"),
    pytest.param("0.9999", ("0.9999", "1.50"), id="regla-612-el-limite-que-cruza-1-dolar-va-a-centimos"),
    pytest.param("0.9", ("0.9000", "1.35"), id="regla-612-limite-de-un-penny-ya-en-centimos"),
])
def test_niveles_redondean_arriba(cfg_stops, L, esperado):
    n = niveles(D(L), cfg_stops)
    assert (n.disparo, n.limite) == tuple(D(e) for e in esperado)
    assert n.bajo_banda is False and en_tick(n.disparo) and en_tick(n.limite)


def test_niveles_config_vacia_usa_las_constantes_de_tipos():
    """Riesgo 32: sin claves en el bloque `stops` mandan las constantes VIGENTES de tipos (50 / 1,5)."""
    assert (STOP_LIMITE_PCT, STOP_MARGEN_BAJO_LIMIT_UP_PCT) == (D("50"), D("1.5"))
    assert niveles(D("10"), {}) == NivelesStop(D("10.00"), D("15.00"), False)
    assert niveles(D("10"), {"limite_pct": D("50"), "margen_bajo_limit_up_pct": D("1.5")}) == niveles(D("10"), {})
    assert niveles(D("10"), {"limite_pct": None}) == niveles(D("10"), {})                  # null del JSON = defecto


def test_niveles_usan_el_limite_de_la_config():
    """`stops.limite_pct` manda: con 30 el límite es L × 1,30 (el estudio del 29-sep comparó +20/+30/+45/+60)."""
    assert niveles(D("10"), {"limite_pct": 30}) == NivelesStop(D("10.00"), D("13.00"), False)
    assert niveles(D("10"), {"limite_pct": 60.0}).limite == D("16.00")


@pytest.mark.parametrize("L,banda,esperado", [
    pytest.param("10", "10.5", ("10.00", "15.00", False), id="R-F-02-L-lejos-de-la-banda-no-se-toca"),
    pytest.param("10", "10.05", ("9.89", "14.84", True), id="R-F-02-L-a-menos-de-1.5pct-baja-a-banda-menos-1.5pct"),
    pytest.param("10", "9.9", ("9.75", "14.63", True), id="R-F-02-banda-por-debajo-de-L"),
    pytest.param("10", "10.00", ("9.85", "14.78", True), id="R-F-02-banda-igual-a-L-(por-encima-o-coincide)"),
    pytest.param("11", "10.5", ("10.34", "15.51", True), id="R-F-02-limite-sobre-el-recortado"),
])
def test_niveles_bajo_la_banda(cfg_stops, L, banda, esperado):
    """R-F-02 con el stop único: disparo = min(L, banda·(1 − 1,5 %) redondeado abajo) y límite = disparo recortado + 50 %.

    Un L a menos de un 1,5 % de la banda también baja (en v3 lo hacía la emergencia recortada, que saltaba antes que el
    principal): nunca se entra en el halt con el stop pegado a la banda."""
    n = niveles(D(L), cfg_stops, D(banda))
    assert (n.disparo, n.limite, n.bajo_banda) == (D(esperado[0]), D(esperado[1]), esperado[2])


@pytest.mark.parametrize("banda", [None, D("0"), D("-1"), D("NaN"), D("Infinity"), D("16.30"), "no-es-precio"],
                         ids=["None", "cero-fuera-de-RTH", "negativa", "NaN", "inf", "banda-por-encima-de-todo", "texto"])
def test_niveles_sin_banda_util_no_recorta(cfg_stops, banda):
    assert niveles(D("10"), cfg_stops, banda) == NivelesStop(D("10.00"), D("15.00"), False)


def test_niveles_acepta_el_float_del_evento_una_sola_vez(cfg_stops):
    """Injerto A §8.1: un L float (Evento.stop) pasa por de_float → mismos Decimal que con el texto."""
    assert niveles(10.123, cfg_stops) == niveles(D("10.123"), cfg_stops)


@pytest.mark.parametrize("L,cfg,banda", [
    pytest.param(D("0"), {}, None, id="L-cero"),
    pytest.param(D("-5"), {}, None, id="L-negativo"),
    pytest.param(D("NaN"), {}, None, id="L-NaN"),
    pytest.param(None, {}, None, id="A12-L-None"),
    pytest.param(D("10"), {"limite_pct": -1}, None, id="pct-negativo"),
    pytest.param(D("10"), {"limite_pct": "cincuenta"}, None, id="pct-no-numerico"),
    pytest.param(D("10"), {"margen_bajo_limit_up_pct": 100}, D("10.5"), id="R-F-02-margen-que-deja-el-disparo-en-cero"),
])
def test_niveles_rechaza(L, cfg, banda):
    with pytest.raises(ValueError):
        niveles(L, cfg, banda)


def test_niveles_rechaza_una_config_que_no_es_el_bloque_stops(config):
    """Pasar la Config entera en vez de cfg.stops usaría los defectos EN SILENCIO: se lanza TypeError."""
    with pytest.raises(TypeError):
        niveles(D("10"), config)                                            # type: ignore[arg-type]


# ── conjunto deseado (R-C-01 v4, R-B-03, R-C-06/07) ─────────────────────
def test_conjunto_dos_lotes_dos_niveles_un_stop_por_nivel(cfg_stops):
    """R-C-01 v4: UN stop por nivel con la suma de llenas de sus lotes; nada más (sin emergencia sobre el L más alto)."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-100)
    assert conjunto_deseado(pos, cfg_stops, None) == [
        StopDeseado(STOP, D("10"), 60, D("10.00"), D("15.00")),
        StopDeseado(STOP, D("11"), 40, D("11.00"), D("16.50")),
    ]


@pytest.mark.parametrize("neta,esperado", [
    pytest.param(-80, [("10", 60), ("11", 20)], id="R-C-07-neta-capada-recorta-el-nivel-alto"),
    pytest.param(-50, [("10", 50)], id="neta-menor-que-el-primer-nivel-sin-segundo-stop"),
    pytest.param(-100, [("10", 60), ("11", 40)], id="neta-igual-a-la-suma"),
    pytest.param(-130, [("10", 60), ("11", 70)], id="neta-mayor-que-la-suma-el-sobrante-al-nivel-mas-alto"),
    pytest.param(0, [], id="R-C-11-neta-cero-nada"),
    pytest.param(20, [], id="R-C-11-larga-nada-que-cubrir"),
])
def test_conjunto_capa_a_la_neta_de_fills(cfg_stops, neta, esperado):
    """La suma de los stops es EXACTAMENTE lo que queda corto: nunca más (cuenta larga) ni menos (acciones sin stop)."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=neta)
    deseados = conjunto_deseado(pos, cfg_stops, None)
    assert [(str(d.nivel), d.qty) for d in deseados] == esperado
    assert all(d.proposito is STOP for d in deseados)
    assert sum(d.qty for d in deseados) == max(-neta, 0)


def test_conjunto_usa_la_neta_de_fills_y_no_la_de_das(cfg_stops):
    """Corrección 2: la neta operativa es la de fills (neta_das solo reconcilia)."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-70, neta_das=-100)
    assert [d.qty for d in conjunto_deseado(pos, cfg_stops, None)] == [70]


def test_conjunto_mismo_nivel_un_solo_stop_con_la_suma(cfg_stops):
    """R-C-11 (6) / R-B-03: dos estrategias al mismo nivel → una orden con la suma."""
    pos = posicion([lote("A", 10, 60), lote("C", "10.00", 40)], neta_fills=-100)
    assert conjunto_deseado(pos, cfg_stops, None) == [StopDeseado(STOP, D("10"), 100, D("10.00"), D("15.00"))]


@pytest.mark.parametrize("lotes", [
    pytest.param([], id="sin-lotes-(posicion-desconocida-va-por-stop_proteccion)"),
    pytest.param([lote("A", None, 100)], id="A12-lote-sin-nivel"),
    pytest.param([lote("A", D("0"), 100)], id="A12-nivel-cero"),
    pytest.param([lote("A", D("-10"), 100)], id="A12-nivel-negativo"),
    pytest.param([lote("A", D("NaN"), 100)], id="A12-nivel-NaN"),
    pytest.param([lote("A", 10.0, 100)], id="injerto-8.1-nivel-float-no-es-un-precio"),
    pytest.param([lote("A", 10, 100, estado=EstadoLote.CERRADO)], id="lote-cerrado"),
    pytest.param([lote("A", 10, 100, estado=EstadoLote.CANCELADO)], id="lote-cancelado"),
    pytest.param([lote("A", 10, 0, estado=EstadoLote.ABRIENDO)], id="lote-sin-llenas"),
    pytest.param([lote("A", 10, 100, direccion="Long")], id="R-E-01-lote-largo-no-lleva-stop-de-compra"),
])
def test_conjunto_sin_niveles_vivos_es_vacio(cfg_stops, lotes):
    assert conjunto_deseado(posicion(lotes, neta_fills=-100), cfg_stops, None) == []


def test_conjunto_lotes_abriendo_y_cerrando_con_llenas_si_cuentan(cfg_stops):
    """F1.6: el PRIMER fill del intento ya lleva stop (lote ABRIENDO con llenas); un lote CERRANDO aún tiene acciones."""
    pos = posicion([lote("A", 10, 30, estado=EstadoLote.ABRIENDO), lote("B", 11, 20, estado=EstadoLote.CERRANDO)], neta_fills=-50)
    assert [(d.proposito, d.qty) for d in conjunto_deseado(pos, cfg_stops, None)] == [(STOP, 30), (STOP, 20)]


def test_conjunto_pasa_la_banda_a_niveles(cfg_stops):
    """R-F-02 dentro del conjunto: con limit_up 10,05 el stop deseado ya va recortado (9,89 / 14,84)."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100)
    assert conjunto_deseado(pos, cfg_stops, D("10.05")) == [StopDeseado(STOP, D("10"), 100, D("9.89"), D("14.84"))]


def test_conjunto_dos_niveles_recortados_bajo_la_banda_no_compran_dos_veces(cfg_stops):
    """R-F-02 (la D5 de v3 queda sin objeto): banda 10,10 → los niveles 10,20 y 10,50 bajan los dos a 9,94 / 14,91. Son DOS
    órdenes al mismo precio pero con acciones distintas (60 + 40 = la posición): nunca compran dos veces lo mismo."""
    pos = posicion([lote("A", "10.2", 60), lote("B", "10.5", 40)], neta_fills=-100)
    deseados = conjunto_deseado(pos, cfg_stops, D("10.1"))
    assert deseados == [StopDeseado(STOP, D("10.2"), 60, D("9.94"), D("14.91")),
                        StopDeseado(STOP, D("10.5"), 40, D("9.94"), D("14.91"))]
    assert sum(d.qty for d in deseados) == 100


def test_primer_disparo_es_el_del_nivel_mas_bajo_con_acciones(cfg_stops):
    """Interfaz para halts y cisne negro: el primer stop que salta es el menor disparo DESEADO (con la banda, recortado)."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-100)
    assert stops.primer_disparo(pos, cfg_stops, None) == D("10.00")
    assert stops.primer_disparo(pos, cfg_stops, D("10.05")) == D("9.89")
    cerrado = posicion([lote("A", 10, 60, estado=EstadoLote.CERRADO), lote("B", 11, 40)], neta_fills=-40)
    assert stops.primer_disparo(cerrado, cfg_stops, None) == D("11.00")       # el nivel de 10 ya salió
    assert stops.primer_disparo(posicion([lote("A", 10, 100)], neta_fills=0), cfg_stops, None) is None


def test_conjunto_no_muta_la_posicion(cfg_stops):
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-100)
    antes = [(l.id, l.nivel_stop, l.llenas, l.estado) for l in pos.lotes.values()]
    conjunto_deseado(pos, cfg_stops, D("10.5"))
    assert [(l.id, l.nivel_stop, l.llenas, l.estado) for l in pos.lotes.values()] == antes


# ── inferir_proposito (corrección 3 del juez) y nivel_de_stop ───────────
@pytest.mark.parametrize("stop,esperado", [
    pytest.param("10.00", STOP, id="disparo=L->stop"),
    pytest.param("10.01", STOP, id="L+1tick->stop"),
    pytest.param("9.99", STOP, id="L-1tick->stop"),
    pytest.param("10.02", Proposito.STOP_PROTECCION, id="L+2ticks->proteccion"),
    pytest.param("11.00", STOP, id="segundo-nivel->stop"),
    pytest.param("11.30", Proposito.STOP_PROTECCION, id="la-emergencia-de-v3-ya-no-es-un-stop-de-nivel"),
    pytest.param("15.00", Proposito.STOP_PROTECCION, id="el-limite-no-es-un-disparo"),
])
def test_inferir_proposito_por_disparo(cfg_stops, stop, esperado):
    o = orden(200000001, Proposito.DESCONOCIDA, stop, D(stop) * D("1.5"), 100, origen=Origen.VIGILANTE)
    assert inferir_proposito(o, [D("10"), D("11")], cfg_stops) is esperado


def test_inferir_proposito_con_banda_reconoce_el_recortado_y_el_de_antes_de_la_banda(cfg_stops):
    """R-F-02 + R-C-07: con la banda se reconoce el stop recortado (9,89) Y el puesto antes de la banda (10,00): el viejo no
    queda huérfano (plan lo ve distinto del deseado y lo sustituye)."""
    recortado = orden(200000001, Proposito.DESCONOCIDA, "9.89", "14.84", 100, origen=Origen.VIGILANTE)
    assert inferir_proposito(recortado, [D("10")], cfg_stops, limit_up=D("10.05")) is STOP
    assert inferir_proposito(recortado, [D("10")], cfg_stops) is Proposito.STOP_PROTECCION
    viejo = orden(200000002, Proposito.DESCONOCIDA, "10.00", "15.00", 100, origen=Origen.VIGILANTE)
    assert inferir_proposito(viejo, [D("10")], cfg_stops, limit_up=D("10.05")) is STOP


def test_inferir_proposito_usa_el_margen_de_la_banda_de_la_config():
    """El recortado se reconoce con el margen de la config (3 % → 9,74), no con la constante (1,5 % → 9,89)."""
    o = orden(200000001, Proposito.DESCONOCIDA, "9.74", "14.61", 100, origen=Origen.VIGILANTE)
    assert inferir_proposito(o, [D("10")], {"margen_bajo_limit_up_pct": 3.0}, limit_up=D("10.05")) is STOP
    assert inferir_proposito(o, [D("10")], {}, limit_up=D("10.05")) is Proposito.STOP_PROTECCION


@pytest.mark.parametrize("o", [
    pytest.param(orden(1, Proposito.DESCONOCIDA, "10.00", "15.00", 100, lado=Lado.VENTA), id="venta-no-es-stop-de-compra"),
    pytest.param(orden(1, Proposito.DESCONOCIDA, "10.00", "15.00", 100, lado=Lado.CORTO), id="corto-no-es-stop-de-compra"),
    pytest.param(orden(1, Proposito.DESCONOCIDA, None, "10.00", 100, tipo=TipoOrden.LIMITE), id="limite-no-es-stop"),
    pytest.param(orden(1, Proposito.DESCONOCIDA, None, None, 100, tipo=TipoOrden.MERCADO), id="mercado-no-es-stop"),
    pytest.param(msg_orden("S", "SLP: 10.00 15.00", "15.00"), id="MsgOrden-venta"),
    pytest.param(msg_orden("SS", "SLP: 10.00 15.00", "15.00"), id="MsgOrden-corto"),
    pytest.param(msg_orden("B", "L", "10.00"), id="MsgOrden-limite-L-(manual-L348)"),
    pytest.param(msg_orden("B", "Limit", "10.00"), id="MsgOrden-Limit"),
    pytest.param(msg_orden("B", "LMT PostOnly", "10.00"), id="MsgOrden-LMT-PostOnly"),
    pytest.param(msg_orden("B", "M", "10.00"), id="MsgOrden-mercado-M"),
    pytest.param(msg_orden("B", "MKT", "10.00"), id="MsgOrden-MKT"),
    pytest.param(msg_orden("B", "PEG MID", "10.00"), id="MsgOrden-peg"),
    pytest.param(msg_orden("B", "", "10.00"), id="MsgOrden-tipo-vacio"),
    pytest.param("SLP: 10.00 15.00", id="ni-Orden-ni-MsgOrden"),
])
def test_inferir_proposito_no_stop_es_desconocida(cfg_stops, o):
    assert inferir_proposito(o, [D("10")], cfg_stops) is Proposito.DESCONOCIDA


@pytest.mark.parametrize("tipo,precio,esperado", [
    pytest.param("SLP: 10.00 15.00", "15.00", STOP, id="riesgo-1-captura-del-socio-24-sep-disparo-primero"),
    pytest.param("SL: 10.00 15.00", "15.00", STOP, id="2h.8-STOPLMT-sin-P-tras-REPLACE-sigue-siendo-stop"),
    pytest.param("SLP: 11,00 16,50", "16.50", STOP, id="coma-decimal"),
    pytest.param("STOPLMTP", "11.00", STOP, id="sin-numeros-en-el-tipo-usa-precio"),
    pytest.param("STOPLMTP 11.00 16.50", "16.50", STOP, id="palabra-del-manual-L618"),
    pytest.param("slp: 10.00 15.00", "15.00", STOP, id="sin-distinguir-mayusculas"),
    pytest.param("SLP: 15.00 22.50", "22.50", Proposito.STOP_PROTECCION, id="otra-cosa"),
])
def test_inferir_proposito_msg_orden(cfg_stops, tipo, precio, esperado):
    assert inferir_proposito(msg_orden("B", tipo, precio), [D("10"), D("11")], cfg_stops) is esperado


def test_inferir_proposito_msg_orden_coma_de_miles_y_pennies(cfg_stops):
    assert inferir_proposito(msg_orden("B", "SLP: 1,000.00 1,500.00", "1500"), [D("1000")], cfg_stops) is STOP
    assert inferir_proposito(msg_orden("B", "SLP: 0.5000 0.7500", "0.7500"), [D("0.5")], cfg_stops) is STOP


def test_inferir_proposito_patron_de_la_config_reconoce_un_tipo_nuevo(cfg_stops):
    """Riesgo 1 / comprobar_das paso 3: cuando se fije `tipo_esperado_en_order`, ese tipo también cuenta como stop; un patrón roto se ignora."""
    o = msg_orden("B", "LP: 10.00 15.00", "15.00")
    assert inferir_proposito(o, [D("10")], cfg_stops) is Proposito.DESCONOCIDA
    assert inferir_proposito(o, [D("10")], {**cfg_stops, "tipo_esperado_en_order": "^LP"}) is STOP
    assert inferir_proposito(o, [D("10")], {**cfg_stops, "tipo_esperado_en_order": "("}) is Proposito.DESCONOCIDA
    assert TIPO_STOP_EN_ORDER.startswith("^")


def test_inferir_proposito_ignora_niveles_invalidos_y_sin_disparo_es_proteccion(cfg_stops):
    o = orden(1, Proposito.DESCONOCIDA, "10.00", "15.00", 100, origen=Origen.VIGILANTE)
    assert inferir_proposito(o, [D("NaN"), D("0"), None, D("10")], cfg_stops) is STOP
    assert inferir_proposito(o, [D("NaN"), D("0")], cfg_stops) is Proposito.STOP_PROTECCION
    sin_precio = orden(1, Proposito.DESCONOCIDA, None, None, 100, origen=Origen.VIGILANTE)
    assert inferir_proposito(sin_precio, [D("10")], cfg_stops) is Proposito.STOP_PROTECCION


def test_nivel_de_stop_por_su_nivel_o_por_su_disparo(cfg_stops):
    """R-C-01 v4: el fill de un stop se descuenta de los lotes de SU nivel; el del vigilante llega sin `nivel` y se reconoce
    por el disparo (también el recortado bajo la banda). Sin casar con ningún nivel vivo → None."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-100)
    assert nivel_de_stop(stop10(), pos, cfg_stops) == D("10")
    assert nivel_de_stop(stop11(), pos, cfg_stops) == D("11")
    vig = orden(200000001, Proposito.DESCONOCIDA, "11.01", "16.51", 40, origen=Origen.VIGILANTE)
    assert nivel_de_stop(vig, pos, cfg_stops) == D("11")
    recortado = orden(200000002, Proposito.DESCONOCIDA, "10.34", "15.51", 40, origen=Origen.VIGILANTE)
    assert nivel_de_stop(recortado, pos, cfg_stops, D("10.5")) == D("11")
    assert nivel_de_stop(recortado, pos, cfg_stops) is None
    otro = orden(200000003, Proposito.STOP_PROTECCION, "12.50", "18.75", 40)
    assert nivel_de_stop(otro, pos, cfg_stops) is None
    assert nivel_de_stop(stop10(), posicion([], neta_fills=-100), cfg_stops) is None


# ── plan (R-C-01 v4, R-C-04, R-C-06, R-C-07 neteo, corrección 2) ────────
def test_plan_desde_cero_envia_un_stop_por_nivel(cfg_stops, tokens):
    """R-C-01 v4: dos niveles → DOS órdenes (antes eran tres: dos principales y la emergencia)."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-100)
    acciones = plan(pos, [], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [type(a) for a in acciones] == [EnviarOrden, EnviarOrden]
    ordenes = [a.orden for a in acciones]
    assert all(a.serie == serie_stops(X) for a in acciones)
    assert all(o.lado is Lado.COMPRA and o.tipo is TipoOrden.STOP_LIMITE_PP and o.ruta == RUTA_STOP and o.tif == "DAY+"
               and not o.post_only and o.ticker == X and o.version == VERSION for o in ordenes)
    assert [(o.proposito, o.nivel, o.qty, o.stop, o.precio, o.lote_id) for o in ordenes] == [
        (STOP, D("10"), 60, D("10.00"), D("15.00"), "A"),
        (STOP, D("11"), 40, D("11.00"), D("16.50"), "B"),
    ]
    assert len({o.token for o in ordenes}) == 2 and all(100000001 <= o.token <= 199999999 for o in ordenes)
    for o in ordenes:
        sin_float(o)


def test_plan_es_idempotente_dos_veces_cero_acciones(cfg_stops, tokens):
    """§3.16: IDEMPOTENTE. Con las órdenes del primer plan aceptadas, el segundo plan no produce NADA ni gasta tokens (riesgo 11)."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-100)
    primero = plan(pos, [], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    gastados = tokens.ultimo_seq
    vivas = [aceptada(env, id_das=i + 1) for i, env in enumerate(primero)]
    assert plan(pos, vivas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []
    assert plan(pos, vivas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION + 1) == []
    enviando = [aceptada(env, id_das=None) for env in primero]
    for o in enviando:
        o.estado = EstadoOrden.SENDING                       # recién enviadas, sin Accept todavía: no se duplican
    assert plan(pos, enviando, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []
    for estado in (EstadoOrden.HOLD, EstadoOrden.TRIGGERED):  # manual L379-405: Hold = «open, but not sent to the exchange»
        otras = [aceptada(env, id_das=i + 1) for i, env in enumerate(primero)]
        for o in otras:
            o.estado = estado
        assert plan(pos, otras, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []
    assert tokens.ultimo_seq == gastados


def test_plan_adopta_las_ordenes_del_vigilante_por_inferir_proposito(cfg_stops, tokens):
    """R-C-07 plan B (21-sep): el ejecutor ADOPTA el stop del vigilante (propósito DESCONOCIDA, sin `nivel`, a ±1 tick)."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-100)
    vigilante = [
        orden(200000001, Proposito.DESCONOCIDA, "10.01", "15.01", 60, id_das=11, origen=Origen.VIGILANTE),
        orden(200000002, Proposito.DESCONOCIDA, "11.00", "16.50", 40, id_das=12, origen=Origen.VIGILANTE),
    ]
    assert plan(pos, vigilante, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []
    etiquetadas = [orden(200000001, STOP, "10.00", "15.00", 60, id_das=11, origen=Origen.VIGILANTE),
                   orden(200000002, STOP, "11.00", "16.50", 40, id_das=12, origen=Origen.VIGILANTE)]
    assert plan(pos, etiquetadas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []
    assert tokens.ultimo_seq == 0


def test_plan_stop_del_vigilante_con_cantidad_distinta_se_reemplaza_no_se_duplica(cfg_stops, tokens):
    pos = posicion([lote("A", 10, 100)], neta_fills=-100)
    vivas = [orden(200000001, Proposito.DESCONOCIDA, "10.00", "15.00", 80, id_das=11, origen=Origen.VIGILANTE)]
    acciones = plan(pos, vivas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert acciones == [
        Reemplazar(id_das=11, token=200000001, qty=100, stop=D("10.00"), precio=D("15.00"), motivo=acciones[0].motivo,
                   version=VERSION, serie=serie_stops(X)),
        verificar(200000001, 100),
    ]
    assert de_tipo(acciones, EnviarOrden) == []


def test_plan_dos_stops_del_mismo_nivel_cancela_el_mas_nuevo(cfg_stops, tokens):
    """R-C-07 plan B: «sobrantes → cancelar el más nuevo»; siempre exactamente UN stop por nivel."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100)
    vieja = stop10(id_das=5, enviada_en=1000.0)
    nueva = orden(200000009, STOP, "10.00", "15.00", 100, id_das=9, enviada_en=1005.0, origen=Origen.VIGILANTE)
    acciones = plan(pos, [nueva, vieja], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [type(a) for a in acciones] == [Cancelar] and acciones[0].id_das == 9 and acciones[0].token == 200000009
    misma_hora = stop10(token=100000003, id_das=7, enviada_en=1000.0)
    acciones = plan(pos, [misma_hora, vieja], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [a.id_das for a in acciones] == [7]              # misma enviada_en: el id_das mayor es el más nuevo
    tres = stop10(token=100000004, id_das=8, enviada_en=1002.0)
    acciones = plan(pos, [tres, nueva, vieja], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert sorted(a.id_das for a in acciones) == [8, 9] and all(isinstance(a, Cancelar) for a in acciones)


def test_plan_la_mas_nueva_es_la_de_id_das_mayor_aunque_enviada_en_diga_otra_cosa(cfg_stops, tokens):
    """enviada_en es el reloj monotónico de OTRO proceso (o 0.0 si se adoptó): manda el id del servidor; sin id es la más nueva."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100)
    id_alto_reloj_viejo = orden(200000009, STOP, "10.00", "15.00", 100, id_das=9, enviada_en=0.0, origen=Origen.VIGILANTE)
    id_bajo_reloj_nuevo = stop10(token=100000002, id_das=5, enviada_en=5000.0)
    acciones = plan(pos, [id_alto_reloj_viejo, id_bajo_reloj_nuevo], cfg_stops, None, tokens.siguiente, HORA,
                    RUTA_STOP, VERSION)
    assert [(type(a), a.id_das) for a in acciones] == [(Cancelar, 9)]
    sin_id = stop10(token=100000003, id_das=None, enviada_en=0.0, estado=EstadoOrden.SENDING)   # «puede haber salido»
    acciones = plan(pos, [sin_id, id_bajo_reloj_nuevo], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert acciones == [Programar(CLAVE_REPLANIFICAR, REPLANIFICAR_EN_S, {"ticker": X})]   # se conserva la CONFIRMADA


def test_plan_desempata_por_nivel_cuando_dos_stops_comparten_disparo(cfg_stops, tokens):
    """10,201 y 10,209 son niveles distintos con el MISMO disparo (10,21); cada orden casa con SU nivel (sin cruzar cantidades:
    si no, el segundo plan las intercambiaría). Lo mismo con dos niveles recortados bajo la banda al mismo 9,94."""
    pos = posicion([lote("A", "10.201", 60), lote("B", "10.209", 40)], neta_fills=-100)
    deseados = conjunto_deseado(pos, cfg_stops, None)
    assert [(d.nivel, d.disparo, d.qty) for d in deseados] == [(D("10.201"), D("10.21"), 60), (D("10.209"), D("10.21"), 40)]
    p_b = orden(100000001, STOP, "10.21", "15.32", 40, id_das=1, nivel="10.209")   # la MÁS antigua
    p_a = orden(100000002, STOP, "10.21", "15.31", 60, id_das=2, nivel="10.201")
    assert plan(pos, [p_b, p_a], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []
    recortados = posicion([lote("A", "10.2", 60), lote("B", "10.5", 40)], neta_fills=-100)
    r_b = orden(100000001, STOP, "9.94", "14.91", 40, id_das=1, nivel="10.5")
    r_a = orden(100000002, STOP, "9.94", "14.91", 60, id_das=2, nivel="10.2")
    assert plan(recortados, [r_b, r_a], cfg_stops, D("10.1"), tokens.siguiente, HORA, RUTA_STOP, VERSION) == []


CONSULTA = [Consultar(COMANDO_POSICIONES), Programar(CLAVE_REPLANIFICAR, REPLANIFICAR_EN_S, {"ticker": X})]


def test_plan_neta_das_distinta_solo_baja_con_n_minimo_y_pide_get_positions(cfg_stops, tokens):
    """D2a-05 (corrige la corrección 2 / riesgo 8): neta_das −90 ≠ fills −100 → deseado con n = min(100, 90) = 90: el stop de
    150 BAJA a 90 (bajar nunca deja la cuenta larga); GET POSITIONS + stops_plan al final. Con las netas de acuerdo, 100."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100, neta_das=-90)
    vivas = [stop10(150, id_das=5)]
    acciones = plan(pos, vivas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert acciones == [Reemplazar(id_das=5, token=100000001, qty=90, stop=D("10.00"), precio=D("15.00"),
                                   motivo=acciones[0].motivo, version=VERSION, serie=serie_stops(X)),
                        verificar(100000001, 90)] + CONSULTA
    assert tokens.ultimo_seq == 0                            # no se gastó ningún token: no se crea nada
    cuadra = posicion([lote("A", 10, 100)], neta_fills=-100, neta_das=-100)
    assert [(a.id_das, a.qty) for a in de_tipo(plan(cuadra, vivas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP,
                                                    VERSION), Reemplazar)] == [(5, 100)]
    sin_das = posicion([lote("A", 10, 100)], neta_fills=-100, neta_das=None)
    assert [(a.id_das, a.qty) for a in de_tipo(plan(sin_das, vivas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP,
                                                    VERSION), Reemplazar)] == [(5, 100)]


def test_D2a_05_con_las_netas_en_desacuerdo_el_nivel_que_falta_no_se_crea(cfg_stops, tokens):
    """D2a-05: dos niveles, solo vive el stop del de 10: con el %POS atrasado NO se crea el del 11 (podría dejar la cuenta
    larga); se pide GET POSITIONS y, con las netas de acuerdo, se crea."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-100, neta_das=-90)
    assert plan(pos, [stop10(60)], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == CONSULTA
    pos.neta_das = -100
    acciones = plan(pos, [stop10(60)], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [(type(a), a.orden.nivel, a.orden.qty) for a in acciones] == [(EnviarOrden, D("11"), 40)]


@pytest.mark.parametrize("fills,das", [(0, -100), (-100, 0), (-100, 20), (20, -100), (30, 20)],
                         ids=["fills-a-cero-DAS-corto", "DAS-a-cero", "signos-opuestos", "signos-opuestos-2", "las-dos-largas"])
def test_D2a_05_signos_opuestos_o_una_a_cero_solo_consulta(cfg_stops, tokens, fills, das):
    """D2a-05: con signos opuestos o una neta a cero no se toca NADA (ni cancelar con fills a cero y DAS aún corto): solo consultar."""
    pos = posicion([lote("A", 10, 100)], neta_fills=fills, neta_das=das)
    vivas = [stop10(100, id_das=1), stop10(150, token=100000002, id_das=2)]
    assert plan(pos, vivas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == CONSULTA
    assert tokens.ultimo_seq == 0


def test_D2a_05_con_das_mas_corto_nunca_sube_ni_crea(cfg_stops, tokens):
    """D2a-05: fills −120 / DAS −100 → n = 100: con el stop en 100 no hay nada que bajar; con 90 NO sube; sin stop NO lo
    crea. Solo GET POSITIONS: tras el %POS, plan normal."""
    pos = posicion([lote("A", 10, 120)], neta_fills=-120, neta_das=-100)
    for vivas in ([stop10(100)], [stop10(90)], []):
        assert plan(pos, vivas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == CONSULTA
    assert tokens.ultimo_seq == 0


def test_D2a_05_con_banda_nueva_y_netas_en_desacuerdo_no_se_quita_la_unica_cobertura(cfg_stops, tokens):
    """D2a-05: la banda nueva pide el stop del 11 en 10,93 y el vivo está en 11,00; con las netas en desacuerdo el nuevo NO se
    crea, así que el viejo NO se cancela (es la única cobertura de ese nivel). Se espera al GET POSITIONS."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-100, neta_das=-90)
    acciones = plan(pos, [stop10(60), stop11(40)], cfg_stops, D("11.1"), tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert de_tipo(acciones, Cancelar) == [] and de_tipo(acciones, EnviarOrden) == []
    assert acciones[-2:] == CONSULTA
    un_nivel = posicion([lote("A", 10, 100)], neta_fills=-100, neta_das=-90)
    assert plan(un_nivel, [stop10(100)], cfg_stops, D("10.05"), tokens.siguiente, HORA, RUTA_STOP, VERSION) == CONSULTA


def test_D2a_05_un_tp_con_el_pos_atrasado_baja_el_stop_al_instante(cfg_stops, tokens):
    """D2a-05 / R-C-11 (1): tras un TP de 20 el lote queda en 80 y el %POS aún dice −100: el stop BAJA de 100 a 80 AL
    INSTANTE (bajar nunca deja la cuenta larga), sin esperar al GET POSITIONS, que se pide igual."""
    pos = posicion([lote("A", 10, 80)], neta_fills=-80, neta_das=-100)
    acciones = plan(pos, [stop10(100)], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert acciones == [Reemplazar(id_das=1, token=100000001, qty=80, stop=D("10.00"), precio=D("15.00"),
                                   motivo=acciones[0].motivo, version=VERSION, serie=serie_stops(X)),
                        verificar(100000001, 80)] + CONSULTA
    assert tokens.ultimo_seq == 0


def test_plan_cantidad_distinta_reemplaza_con_version_y_serie(cfg_stops, tokens):
    """R-C-07 (bajar tras TP) y riesgo 7: REPLACE con la versión del objetivo + replace_verificar (2h.8); nunca una orden nueva."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-80)
    acciones = plan(pos, [stop10(60), stop11(40)], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [type(a) for a in acciones] == [Reemplazar, Programar]
    assert [(a.id_das, a.qty, a.version, a.serie, a.stop, a.precio) for a in de_tipo(acciones, Reemplazar)] == [
        (2, 20, VERSION, serie_stops(X), D("11.00"), D("16.50"))]
    assert de_tipo(acciones, Programar) == [verificar(100000002, 20)]
    subida = posicion([lote("A", 10, 150)], neta_fills=-150)          # R-C-06: piramidar sube la cantidad
    acciones = plan(subida, [stop10(100)], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [(a.id_das, a.qty) for a in de_tipo(acciones, Reemplazar)] == [(1, 150)]


def test_plan_parcial_usa_lvqty_y_no_reemplaza_lo_que_ya_cuadra(cfg_stops, tokens):
    """Injerto A §8.7: la cantidad viva es lvqty (Partial/Triggered), nunca lo pedido: stop de 100 con 30 llenas y el lote ya
    en 70 → nada que tocar (el stop sigue vivo con lo que le queda: no se cancela como el principal de v3)."""
    pos = posicion([lote("A", 10, 70)], neta_fills=-70)
    for estado in (EstadoOrden.PARTIAL, EstadoOrden.TRIGGERED):
        parcial = stop10(100, estado=estado, llenas=30, lvqty=70)
        assert plan(pos, [parcial], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []
    sin_lvqty = stop10(100, estado=EstadoOrden.PARTIAL, llenas=30)
    assert plan(pos, [sin_lvqty], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []   # qty − llenas


def test_plan_banda_nueva_pone_primero_el_nuevo_y_luego_cancela_el_viejo(cfg_stops, tokens):
    """R-F-02 «cada vez que la banda cambia» + R-C-05 «primero el nuevo, después el viejo»."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100)
    acciones = plan(pos, [stop10(100)], cfg_stops, D("10.05"), tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [type(a) for a in acciones] == [EnviarOrden, Cancelar]
    nueva = acciones[0].orden
    assert (nueva.proposito, nueva.stop, nueva.precio, nueva.qty) == (STOP, D("9.89"), D("14.84"), 100)
    assert acciones[1].id_das == 1


def test_plan_banda_nueva_tambien_mueve_el_stop_adoptado_del_vigilante(cfg_stops, tokens):
    """R-F-02 + R-C-07: el stop del vigilante sin etiqueta puesto ANTES de la banda se reconoce y se sustituye, no queda huérfano."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100)
    vivas = [orden(200000001, Proposito.DESCONOCIDA, "10.00", "15.00", 100, id_das=11, origen=Origen.VIGILANTE)]
    acciones = plan(pos, vivas, cfg_stops, D("10.05"), tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [type(a) for a in acciones] == [EnviarOrden, Cancelar] and acciones[1].id_das == 11
    assert acciones[0].orden.stop == D("9.89")


@pytest.mark.parametrize("ajena", [
    pytest.param(orden(100000009, Proposito.STOP_PROTECCION, "12.50", "18.75", 100, id_das=9), id="R-C-10.4-proteccion-del-ejecutor-intocable"),
    pytest.param(orden(100000009, Proposito.TP_AGREGAR, None, "9.50", 40, id_das=9, tipo=TipoOrden.LIMITE), id="TP-limite-no-es-stop"),
    pytest.param(orden(100000009, STOP, "10.00", "15.00", 100, id_das=9, lado=Lado.VENTA), id="venta"),
    pytest.param(orden(100000009, STOP, "10.00", "15.00", 100, id_das=9, ticker="OTRO"), id="otro-ticker"),
    pytest.param(orden(100000009, STOP, "10.00", "15.00", 100, id_das=9, estado=EstadoOrden.CANCELED), id="cancelada"),
    pytest.param(orden(100000009, STOP, "10.00", "15.00", 100, id_das=9, estado=EstadoOrden.EXECUTED, llenas=100), id="ejecutada"),
    pytest.param(orden(100000009, STOP, "10.00", "15.00", 100, id_das=9, estado=EstadoOrden.REJECTED), id="rechazada"),
    pytest.param(orden(100000009, STOP, "10.00", "15.00", 100, id_das=9, estado=EstadoOrden.CLOSED), id="cerrada"),
    pytest.param(orden(100000009, STOP, "10.00", "15.00", 100, id_das=9, estado=EstadoOrden.DESCONOCIDO), id="estado-desconocido-no-cubre"),
    pytest.param(orden(200000009, Proposito.DESCONOCIDA, "15.00", "22.50", 100, id_das=9, origen=Origen.VIGILANTE), id="del-vigilante-que-no-casa-es-proteccion"),
])
def test_plan_ni_cuenta_ni_cancela_lo_que_no_gestiona(cfg_stops, tokens, ajena):
    """Lo que no gestiona ni cuenta ni se cancela. D2a-10: el stop NUESTRO del vigilante que no casa se avisa (nivel 2) y se anota."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100)
    acciones = plan(pos, [ajena], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    no_reconocido = ajena.origen is Origen.VIGILANTE
    assert [type(a) for a in acciones] == [EnviarOrden] + ([Avisar, Anotar] if no_reconocido else [])
    assert de_tipo(acciones, Cancelar) == [] and de_tipo(acciones, Reemplazar) == []


def test_D2a_10_stop_nuestro_no_reconocido_avisa_al_poner_el_stop_y_no_se_toca(cfg_stops, tokens):
    """D2a-10 / riesgo 1: un stop del vigilante cuyo %ORDER no trae el disparo y da el LÍMITE (15,00) no casa con ningún nivel:
    se infiere protección. plan pone el stop del nivel al lado (posible doble cobertura) → Avisar(2) +
    Anotar("stop_no_reconocido"); la orden rara NO se cancela; con el stop ya puesto el plan siguiente no produce nada."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100)
    raro = orden(200000001, Proposito.DESCONOCIDA, None, "15.00", 100, id_das=11, origen=Origen.VIGILANTE)
    acciones = plan(pos, [raro], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [type(a) for a in acciones] == [EnviarOrden, Avisar, Anotar]
    aviso, nota = acciones[1], acciones[2]
    assert aviso.nivel is Nivel.AVISO and aviso.grupo is Grupo.B and aviso.clave == f"stop_no_reconocido:{X}"
    assert "200000001" in aviso.texto and "15.00" in aviso.texto and "emergencia" not in aviso.texto
    assert nota == Anotar("stop_no_reconocido", {"ticker": X, "tokens": [200000001], "disparos": ["15.00"],
                                                 "regla": "riesgo 1 (D2a-10)"})
    puestas = [aceptada(a, id_das=20 + i) for i, a in enumerate(de_tipo(acciones, EnviarOrden))]
    assert plan(pos, [raro] + puestas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []
    propia = orden(100000009, Proposito.STOP_PROTECCION, "12.50", "18.75", 100, id_das=9)   # R-C-10.4 propia: no es «rara»
    assert de_tipo(plan(pos, [propia], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION), Avisar) == []


def test_D2a_06_un_stop_sin_id_cuenta_vivo_y_se_repone_cuando_el_decisor_lo_descarta(cfg_stops, tokens):
    """D2a-06: el NEWORDER del stop aún en la cola (Sending, sin id) cuenta como vivo: plan no lo duplica. Si el emisor lo
    purga por versión, el decisor lo pasa a CLOSED (`OrdenDescartada`) y el plan siguiente lo REPONE."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100)
    en_cola = stop10(100, id_das=None, estado=EstadoOrden.SENDING)
    assert plan(pos, [en_cola], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []
    en_cola.estado = EstadoOrden.CLOSED                       # «descartada por versión»
    acciones = plan(pos, [en_cola], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [(type(a), a.orden.proposito, a.orden.qty, a.orden.stop) for a in acciones] == [(EnviarOrden, STOP, 100, D("10.00"))]
    assert "OrdenDescartada" in (stops.__doc__ or "")


def test_D2a_07_cantidad_viva_con_lvqty_viejo_tras_el_execute(cfg_stops, tokens):
    """D2a-07: el Execute de 30 llega antes que el %ORDER: PARTIAL qty 100, llenas 30, lvqty aún 100 → vivas 70, no 100.
    Si el lote vuelve a 100 (una entrada que llena en plena subida), descubiertas ve las 30 al aire y plan SUBE el stop."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100)
    s = stop10(100, id_das=2, estado=EstadoOrden.PARTIAL, llenas=30, lvqty=100)
    assert stops._qty_viva(s) == 70
    assert descubiertas(pos, [s]) == 30
    acciones = plan(pos, [s], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [(a.id_das, a.qty) for a in de_tipo(acciones, Reemplazar)] == [(2, 100)]
    for estado in (EstadoOrden.PARTIAL, EstadoOrden.TRIGGERED):   # el %ORDER llegó ANTES que el Execute: manda lvqty
        adoptada = orden(200000002, Proposito.DESCONOCIDA, "10.00", "15.00", 100, id_das=12, estado=estado, llenas=0,
                         lvqty=70, origen=Origen.VIGILANTE)
        assert stops._qty_viva(adoptada) == 70
    llena_del_todo = stop10(100, id_das=3, estado=EstadoOrden.PARTIAL, llenas=100, lvqty=40)
    assert stops._qty_viva(llena_del_todo) == 0               # un lvqty viejo no resucita una orden ya llena


@pytest.mark.parametrize("interruptor,share,aviso", [
    pytest.param(None, 50, True, id="sin-interruptor-share-ABIERTA-y-aviso-2"),
    pytest.param(True, 50, False, id="interruptor-true-share-ABIERTA"),
    pytest.param(False, 80, False, id="interruptor-false-share-TOTAL-llenas-mas-abiertas"),
])
def test_D2a_08_share_del_replace_sobre_una_orden_parcial(cfg_stops, tokens, interruptor, share, aviso):
    """A-02 / D2a-08: el `share` del REPLACE sale de tipos.share_de_replace con `stops.replace_share_es_abierta`; `qty_objetivo` es
    siempre la ABIERTA. Mientras la config no fije el interruptor, un REPLACE sobre una orden con llenas lleva Avisar(2)."""
    cfg = dict(cfg_stops) if interruptor is None else {**cfg_stops, "replace_share_es_abierta": interruptor}
    pos = posicion([lote("A", 10, 50)], neta_fills=-50)
    s = stop10(100, id_das=2, estado=EstadoOrden.PARTIAL, llenas=30, lvqty=70)
    acciones = plan(pos, [s], cfg, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [(a.id_das, a.qty) for a in de_tipo(acciones, Reemplazar)] == [(2, share)]
    assert de_tipo(acciones, Programar) == [verificar(100000001, 50)]
    avisos_ = de_tipo(acciones, Avisar)
    assert bool(avisos_) is aviso
    if aviso:
        assert avisos_[0].nivel is Nivel.AVISO and avisos_[0].clave == "replace_parcial:100000001"
        assert "30 llenas" in avisos_[0].texto and "share=50" in avisos_[0].texto
    sin_fills = stop10(100, id_das=2)                                          # sin llenas: nunca avisa
    assert de_tipo(plan(pos, [sin_fills], cfg, None, tokens.siguiente, HORA, RUTA_STOP, VERSION), Avisar) == []


def test_D2a_09_compras_cierre_baja_el_stop_y_al_quitarla_vuelve(cfg_stops, tokens):
    """D2a-09 / G1A-01 (interfaz para el decisor; test 2 del 29-sep): con la MKT por OPEN del halt viva por 30 de 100 cortas,
    el stop ÚNICO baja a 70 ANTES de que salga la orden (una sola orden que reducir); por las 100, fuera; sin ella (Send_Rej o
    no llenó), vuelve a 100."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100, estado=EstadoTicker.HALT)
    s = stop10(100)
    acciones = plan(pos, [s], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION, compras_cierre=30)
    assert [(type(a), a.id_das, getattr(a, "qty", None)) for a in acciones if not isinstance(a, Programar)] == [
        (Reemplazar, 1, 70)]
    acciones = plan(pos, [s], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION, compras_cierre=100)
    assert [(type(a), a.id_das) for a in acciones] == [(Cancelar, 1)] and de_tipo(acciones, EnviarOrden) == []
    for basura in (0, -5, True, 30.0):                       # 0, negativo, bool o float: como si no hubiera compra de cierre
        assert plan(pos, [s], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION, compras_cierre=basura) == []
    s.qty = 70                                               # tras el Replaced
    acciones = plan(pos, [s], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [(a.id_das, a.qty) for a in de_tipo(acciones, Reemplazar)] == [(1, 100)]
    assert descubiertas(pos, [s]) == 30 and descubiertas(pos, [s], compras_cierre=30) == 0
    assert plan(pos, [], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION, compras_cierre=100) == []
    assert tokens.ultimo_seq == 0


def test_D2a_09_compras_cierre_con_dos_niveles_baja_primero_el_mas_alto(cfg_stops, tokens):
    """D2a-09 con varios niveles: el cierre del halt cubre 50 de 100 → los stops se dimensionan del nivel más bajo al más alto
    (el de 10 conserva sus 60 → 50; el de 11 se cancela): nunca más stops que lo que no cubre la orden de salida."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-100, estado=EstadoTicker.HALT)
    acciones = plan(pos, [stop10(60), stop11(40)], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION,
                    compras_cierre=50)
    assert [(type(a), a.id_das, getattr(a, "qty", None)) for a in acciones if not isinstance(a, Programar)] == [
        (Reemplazar, 1, 50), (Cancelar, 2, None)]


def test_plan_orden_sin_id_das_no_se_puede_tocar_y_reprograma(cfg_stops, tokens):
    pos = posicion([lote("A", 10, 100)], neta_fills=-100)
    enviando = [stop10(80, id_das=None, estado=EstadoOrden.SENDING),
                stop10(100, token=100000003, id_das=None, estado=EstadoOrden.SENDING, enviada_en=1001.0, nivel=None)]
    acciones = plan(pos, enviando, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert acciones == [Programar(CLAVE_REPLANIFICAR, REPLANIFICAR_EN_S, {"ticker": X})]


def test_plan_misma_orden_dos_veces_en_la_lista_no_se_cancela_dos_veces(cfg_stops, tokens):
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-100)
    p, q = stop10(60), stop11(40)
    assert plan(pos, [p, q, q, p], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []


@pytest.mark.parametrize("neta", [0, 20], ids=["R-C-11-2-neta-cero", "R-C-11-3-larga"])
def test_plan_sin_corto_cancela_todos_los_stops_gestionados(cfg_stops, tokens, neta):
    """R-C-11 (2)/(3): sin corto no puede quedar ningún stop de nivel; la protección (R-C-10) y lo ajeno no se tocan."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=neta)
    vivas = [stop10(60), stop11(40),
             orden(100000004, Proposito.STOP_PROTECCION, "12.50", "18.75", 100, id_das=4),
             orden(100000005, STOP, "10.00", "15.00", 100, id_das=5, ticker="OTRO"),
             orden(100000006, STOP, "10.00", "15.00", 100, id_das=6, lado=Lado.VENTA)]
    acciones = plan(pos, vivas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert all(isinstance(a, Cancelar) for a in acciones)
    assert sorted(a.id_das for a in acciones) == [1, 2]
    assert plan(pos, [], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []


@pytest.mark.parametrize("lotes", [
    pytest.param([lote("A", None, 100)], id="A12-lote-sin-nivel"),
    pytest.param([lote("A", D("0"), 100)], id="A12-nivel-cero"),
    pytest.param([lote("A", 10.0, 100)], id="nivel-float"),
])
def test_plan_corto_con_lotes_sin_nivel_avisa_nivel_3_y_no_cancela_nada(cfg_stops, tokens, lotes):
    """R-C-03: sin nivel no hay stop calculable; cancelar lo vivo dejaría el corto desnudo → aviso máximo y NADA más."""
    pos = posicion(lotes, neta_fills=-100)
    acciones = plan(pos, [stop10(100, id_das=2)], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [type(a) for a in acciones] == [Avisar]
    assert acciones[0].nivel is Nivel.MAXIMO and acciones[0].grupo is Grupo.B and acciones[0].clave == f"stops_sin_nivel:{X}"
    assert "A" in acciones[0].texto and "emergencia" not in acciones[0].texto and tokens.ultimo_seq == 0


def test_plan_posicion_sin_lotes_no_toca_nada(cfg_stops, tokens):
    """R-C-10 caso 4: una posición que el bot no reconoce es de la reconciliación; plan no cancela sus stops."""
    pos = posicion([], neta_fills=-100)
    vivas = [stop10(100, id_das=2), orden(100000003, Proposito.STOP_PROTECCION, "12.50", "18.75", 100, id_das=3)]
    assert plan(pos, vivas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []
    cerrados = posicion([lote("A", 10, 100, estado=EstadoLote.CERRADO)], neta_fills=-100)
    assert plan(cerrados, vivas, cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []


def test_E1_04_plan_no_deshace_un_limite_distinto_en_un_halt_de_premercado(cfg_stops, tokens):
    """E1-04 (R-F-06, halts): si el límite de un stop es otro (ensanchado en un halt de PM, o puesto con otra config) sin mover
    el disparo, plan lo sigue casando (por disparo) y NO lo devuelve al de siempre; si hay que cambiar la cantidad, lo conserva."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100, estado=EstadoTicker.HALT)
    s = orden(100000001, STOP, "10.00", "16.00", 100, id_das=1, nivel=10)
    assert plan(pos, [s], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []
    menos = posicion([lote("A", 10, 60)], neta_fills=-60, estado=EstadoTicker.HALT)
    acciones = plan(menos, [s], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [(a.id_das, a.qty, a.stop, a.precio) for a in de_tipo(acciones, Reemplazar)] == [(1, 60, D("10.00"), D("16.00"))]


def test_plan_en_cisne_negro_no_hace_nada(cfg_stops, tokens):
    """R-G-03: en cisne negro el bot NO repone si DAS cancela; los stops se bajan solo con cisne_negro.acciones_durante_bs."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100, estado=EstadoTicker.BS)
    assert plan(pos, [], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []


@pytest.mark.parametrize("estado", [EstadoTicker.PAUSADO, EstadoTicker.HALT, EstadoTicker.CONTROL_HUMANO],
                         ids=["R-B-07-pausado", "R-F-01-halt", "R-D-02-control-humano"])
def test_plan_los_stops_siguen_en_los_demas_estados(cfg_stops, tokens, estado):
    """F8 / F5: pausa, halt y control humano cortan las ENTRADAS, no los stops."""
    pos = posicion([lote("A", 10, 100)], neta_fills=-100, estado=estado)
    assert [type(a) for a in plan(pos, [], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)] == [EnviarOrden]


def test_plan_no_muta_ni_la_posicion_ni_las_vivas(cfg_stops, tokens):
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-80)
    vivas = [stop11(100, id_das=3), orden(100000005, Proposito.STOP_PROTECCION, "11.40", "17.10", 100, id_das=5)]
    foto_pos = [(l.id, l.nivel_stop, l.llenas, l.estado) for l in pos.lotes.values()]
    foto_vivas = [(o.qty, o.estado, o.proposito, o.stop, o.precio, o.llenas, o.lvqty) for o in vivas]
    plan(pos, vivas, cfg_stops, D("10.5"), tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [(l.id, l.nivel_stop, l.llenas, l.estado) for l in pos.lotes.values()] == foto_pos
    assert [(o.qty, o.estado, o.proposito, o.stop, o.precio, o.llenas, o.lvqty) for o in vivas] == foto_vivas


def test_plan_no_depende_del_orden_de_las_vivas(cfg_stops, tokens):
    """Idempotencia de verdad: las 24 permutaciones de las vivas dan las MISMAS acciones (se cancela siempre la más nueva)."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-80)
    vivas = [stop10(60, id_das=1), stop11(40, id_das=2),
             orden(200000009, Proposito.DESCONOCIDA, "11.00", "16.50", 40, id_das=9, origen=Origen.VIGILANTE),
             orden(100000007, STOP, "10.01", "15.01", 60, id_das=7, nivel=10)]
    firmas = set()
    for permutacion in itertools.permutations(vivas):
        acciones = plan(pos, list(permutacion), cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
        firmas.add(tuple(sorted((type(a).__name__, getattr(a, "id_das", 0) or 0, getattr(a, "qty", 0) or 0) for a in acciones)))
    assert firmas == {(("Cancelar", 7, 0), ("Cancelar", 9, 0), ("Programar", 0, 0), ("Reemplazar", 2, 20))}
    assert tokens.ultimo_seq == 0


def test_la_reasignacion_de_v3_no_existe(cfg_stops):
    """Jaume 29-sep (stop único): el precio que pasa el límite de un stop sin llenarlo es cisne negro (R-G-01 v4); ya no se
    reasigna al nivel de arriba ni se recoloca al ask (sería perseguir al precio). Ninguna pieza de v3 sobrevive."""
    for vieja in ("reasignar_principal_rebasado", "_principales_al_ask", "_marcar_principal_consumido"):
        assert not hasattr(stops, vieja), vieja
    assert stops.PROPOSITOS_GESTIONADOS == (STOP,) and stops.PROPOSITOS_STOP == (STOP, Proposito.STOP_PROTECCION)


# ── plan: idempotencia e invariantes sobre escenarios aleatorios (semilla fija) ──
_NIVELES_AZAR = ("0.5", "0.95", "1", "5", "10", "10.2", "10.21", "11")


def _escenario(rnd: random.Random, ids, cfg: dict, tokens):
    lotes = []
    for i in range(rnd.randint(1, 3)):
        lotes.append(lote(f"L{i}", rnd.choice(_NIVELES_AZAR), rnd.randint(1, 400)))
    total = sum(l.llenas for l in lotes)
    neta = -rnd.randint(1, total + 50) if rnd.random() < 0.85 else rnd.choice([0, rnd.randint(1, 60)])
    limit_up = rnd.choice([None, None, D("10.5"), D("12"), D("1.1"), D("0.99"), D("5.02")])
    pos = posicion(lotes, neta_fills=neta)
    base = [aceptada(a, id_das=next(ids)) for a in plan(posicion(lotes, neta_fills=-max(-neta, 1)), [], cfg, limit_up,
                                                          tokens.siguiente, HORA, RUTA_STOP, VERSION)
            if isinstance(a, EnviarOrden)]
    vivas: list[Orden] = []
    for o in base:
        suerte = rnd.random()
        if suerte < 0.15:
            continue                                               # falta → EnviarOrden
        if suerte < 0.30:
            o.qty = max(1, o.qty + rnd.randint(-50, 50))           # otra cantidad → Reemplazar
            o.lvqty = o.qty
        elif suerte < 0.40:
            o.proposito, o.origen, o.nivel = Proposito.DESCONOCIDA, Origen.VIGILANTE, None   # adoptada del vigilante
        elif suerte < 0.50:
            o.stop = o.stop + (D("0.01") if o.stop >= 1 else D("0.0001"))                   # ±1 tick: sigue casando
        vivas.append(o)
        if rnd.random() < 0.15:                                    # duplicada MÁS nueva → se cancela
            copia = Orden(**{**o.__dict__, "token": o.token + 50_000_000, "id_das": next(ids)})
            vivas.append(copia)
    basura = [
        orden(100009001, STOP, "10.00", "15.00", 100, id_das=next(ids), ticker="OTRO"),
        orden(100009002, STOP, "10.00", "15.00", 100, id_das=next(ids), lado=Lado.VENTA),
        orden(100009003, Proposito.STOP_PROTECCION, "99.00", "148.50", 100, id_das=next(ids)),
        orden(100009004, Proposito.TP_AGREGAR, None, "9.50", 40, id_das=next(ids), tipo=TipoOrden.LIMITE),
        orden(100009005, STOP, "10.00", "15.00", 100, id_das=next(ids), estado=EstadoOrden.CANCELED),
    ]
    rnd.shuffle(vivas)
    return pos, vivas + basura, limit_up, {o.id_das for o in basura}


def test_plan_idempotente_e_invariantes_en_300_escenarios_aleatorios(cfg_stops, tokens):
    """Riesgo 11 / R-C-07 / R-C-11: plan + DAS de mentira + plan = [] y, al final, UN stop por nivel deseado con su cantidad y
    la suma de los stops = lo que queda corto (nunca más: cuenta larga; nunca menos: acciones sin stop)."""
    rnd = random.Random(20260929)
    ids = itertools.count(1)
    for _ in range(300):
        pos, vivas, limit_up, basura = _escenario(rnd, ids, cfg_stops, tokens)
        n = -pos.neta
        primero = plan(pos, vivas, cfg_stops, limit_up, tokens.siguiente, HORA, RUTA_STOP, VERSION)
        for a in primero:
            assert not isinstance(a, (Cancelar, Reemplazar)) or a.id_das not in basura, a
            if isinstance(a, EnviarOrden):
                o = a.orden
                assert a.serie == serie_stops(X) and o.version == VERSION and 0 < o.qty <= n and en_tick(o.stop) and en_tick(o.precio)
                assert o.proposito is STOP
                sin_float(o)
            if isinstance(a, Reemplazar):
                assert a.serie == serie_stops(X) and a.version == VERSION and 0 < a.qty <= n
        despues = _aplicar(primero, vivas, ids)
        assert plan(pos, despues, cfg_stops, limit_up, tokens.siguiente, HORA, RUTA_STOP, VERSION) == []
        mias = [o for o in _mis_stops(despues, pos, cfg_stops, limit_up) if o.id_das not in basura]
        if n <= 0:
            assert mias == []
            continue
        deseados = conjunto_deseado(pos, cfg_stops, limit_up)
        assert len(mias) == len(deseados)
        assert sorted((o.stop, _viva(o)) for o in mias) != [] and sum(_viva(o) for o in mias) == n
        assert sorted(_viva(o) for o in mias) == sorted(d.qty for d in deseados)


# ── limpieza tras el fill de un stop (R-C-11, injerto A §8.6) ────────────
def test_limpieza_neta_cero_invalida_la_serie_y_cancela_todo(config, tokens, cotizacion):
    pos = posicion([lote("A", 10, 100)], neta_fills=0)
    acciones = limpieza_tras_fill_stop(pos, [stop11(40)], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 4)
    assert acciones == [InvalidarSerie(serie_stops(X), 4), CancelarTicker(X, acciones[1].motivo)]
    assert tokens.ultimo_seq == 0


def test_limpieza_larga_vende_solo_el_exceso_20_jamas_100(config, tokens, cotizacion):
    """R-C-11 (b): 100 cortas; un cierre (del halt o humano) cubre 20 y el stop de 100 llena entero → larga 20 → se venden 20,
    JAMÁS 100 (riesgo 6). Con el stop único la cuenta aún puede quedar larga (stop + cierre, fill duplicado, dos niveles).

    D2a-04: a bid·(1 − 2 %) redondeado abajo (9,50 → 9,31: vendible, no el bid exacto) y `exceso_verificar:X` a 1 s.
    """
    pos = posicion([lote("A", 10, 100)], neta_fills=20)
    vivas = [stop10(100, estado=EstadoOrden.EXECUTED, llenas=100)]
    acciones = limpieza_tras_fill_stop(pos, vivas, cotizacion(X, "9.50", "9.52", last="9.51"), tokens.siguiente, config, HORA, 4)
    assert [type(a) for a in acciones] == [InvalidarSerie, CancelarTicker, EnviarOrden, Avisar, Anotar, Programar]
    assert acciones[0] == InvalidarSerie(serie_stops(X), 4)
    venta = acciones[2].orden
    assert (venta.lado, venta.qty, venta.tipo, venta.precio, venta.ruta, venta.proposito, venta.version, venta.tif) == (
        Lado.VENTA, 20, TipoOrden.LIMITE, D("9.31"), "SAGEPRO", Proposito.VENTA_EXCESO, 4, "DAY+")
    assert acciones[2].serie is None and venta.post_only is False     # sin serie: un InvalidarSerie posterior no la descarta
    sin_float(venta)
    assert acciones[3].nivel is Nivel.AVISO and acciones[3].grupo is Grupo.B and "20" in acciones[3].texto
    assert acciones[3].clave == f"exceso:{X}:4"                       # un incidente nuevo (otra versión) no lo calla el dedupe
    assert acciones[4].tipo == "incidente" and acciones[4].datos["vendidas"] == 20 and acciones[4].datos["neta"] == 20
    assert acciones[4].datos["referencia"] == "9.50" and acciones[4].datos["precio"] == "9.31"
    assert acciones[5] == Programar(f"exceso_verificar:{X}", 1.0, {"ticker": X, "persecuciones": 0})
    assert all(not (isinstance(a, EnviarOrden) and a.orden.qty == 100) for a in acciones)


def test_limpieza_larga_cuenta_lo_que_dice_das_si_discrepa(config, tokens, cotizacion):
    """Corrección 2: la venta sale por la neta de FILLS (verdad inmediata) y el aviso enseña la de DAS si no cuadra."""
    pos = posicion([lote("A", 10, 100)], neta_fills=20, neta_das=-80)
    acciones = limpieza_tras_fill_stop(pos, [], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 4)
    assert de_tipo(acciones, EnviarOrden)[0].orden.qty == 20
    assert "DAS dice -80" in de_tipo(acciones, Avisar)[0].texto and de_tipo(acciones, Anotar)[0].datos["neta_das"] == -80


def test_limpieza_larga_en_pennies_va_por_la_ruta_de_cruzar_de_la_hora(config, tokens, cotizacion):
    """Pennies: 0,4800 − 2 % = 0,4704 (tick 0,0001, D2a-04) por la ruta de cruzar de la hora."""
    pos = posicion([lote("A", "0.5", 1000)], neta_fills=150)
    acciones = limpieza_tras_fill_stop(pos, [], cotizacion(X, "0.4800", "0.4810"), tokens.siguiente, config, HORA, 2)
    venta = de_tipo(acciones, EnviarOrden)[0].orden
    assert (venta.qty, venta.precio, venta.ruta) == (150, D("0.4704"), "EDGA")       # 09:30 ET ≥ 07:00 → EDGA
    antes_de_las_7 = datetime(2026, 9, 25, 5, 0, tzinfo=ET)
    acciones = limpieza_tras_fill_stop(pos, [], cotizacion(X, "0.4800", "0.4810"), tokens.siguiente, config, antes_de_las_7, 2)
    assert de_tipo(acciones, EnviarOrden)[0].orden.ruta == "MIAX"


def test_limpieza_larga_sin_bid_usa_last_y_sin_nada_avisa_nivel_3_sin_orden(config, tokens):
    """Sin bid, el último precio con el mismo margen; sin ningún precio, aviso nivel 3 y sin orden. R2-STOPS-2: la comprobación a
    1 s se programa IGUAL (con la cuenta larga, SIEMPRE): si al vencer hay precio y sigue larga, se vende tras un CANCEL ALLSYMB."""
    pos = posicion([lote("A", 10, 100)], neta_fills=20)
    solo_last = Cotizacion(ticker=X, last=D("9.4567"))
    acciones = limpieza_tras_fill_stop(pos, [], solo_last, tokens.siguiente, config, HORA, 4)
    assert de_tipo(acciones, EnviarOrden)[0].orden.precio == D("9.26")            # 9,4567·0,98 = 9,2675… → ABAJO (lado permisivo)
    acciones = limpieza_tras_fill_stop(pos, [], Cotizacion(ticker=X, bid=D("0"), last=D("NaN")), tokens.siguiente, config, HORA, 4)
    assert [type(a) for a in acciones] == [InvalidarSerie, CancelarTicker, Avisar, Anotar, Programar]
    assert acciones[2].nivel is Nivel.MAXIMO and "VENDER A MANO" in acciones[2].texto
    assert acciones[-1] == Programar(f"exceso_verificar:{X}", 1.0, {"ticker": X, "persecuciones": 0})
    acciones = limpieza_tras_fill_stop(pos, [], None, tokens.siguiente, config, HORA, 4)
    assert de_tipo(acciones, EnviarOrden) == [] and de_tipo(acciones, Avisar)[0].nivel is Nivel.MAXIMO
    assert de_tipo(acciones, Programar) == [Programar(f"exceso_verificar:{X}", 1.0, {"ticker": X, "persecuciones": 0})]
    # al vencer ya hay precio y la cuenta sigue larga sin venta viva → CANCEL ALLSYMB + venta; la vuelta cuenta
    acciones = stops.verificar_venta_exceso(pos, [], solo_last, tokens.siguiente, config, HORA, 4, 0)
    assert [type(a) for a in acciones] == [CancelarTicker, EnviarOrden, Avisar, Anotar, Programar]
    assert acciones[1].orden.qty == 20 and acciones[-1].datos["persecuciones"] == 1


def test_limpieza_corta_el_stop_que_lleno_en_parte_sigue_vivo_con_lo_que_le_queda(config, tokens, cotizacion):
    """R-C-11 (c) v4: 100 cortas, el stop llena 20 (el decisor ya dejó el lote en 80) → el stop sigue vivo con sus 80 y NO se
    cancela (en v3 se cancelaba el principal porque la emergencia seguía detrás; sin emergencia sería quedarse sin stop)."""
    pos = posicion([lote("A", 10, 80)], neta_fills=-80)
    parcial = stop10(100, estado=EstadoOrden.PARTIAL, llenas=20, lvqty=80)
    acciones = limpieza_tras_fill_stop(pos, [parcial], cotizacion(X, "10.05", "10.07"), tokens.siguiente, config, HORA, 5)
    assert acciones == [InvalidarSerie(serie_stops(X), 5)]
    assert not hasattr(pos.lotes["A"], "principal_consumido")


def test_limpieza_corta_dos_niveles_cada_stop_con_sus_acciones_y_repone_el_que_falta(config, tokens, cotizacion):
    """R-C-11 (c): llena 20 del stop de 10 (lote A de 60 a 40): el de 10 sigue con 40 y el de 11 con 40, sin tocar nada. Si el
    del 11 ya no está (DAS lo canceló), la limpieza lo REPONE (un nivel con acciones nunca queda sin stop)."""
    pos = posicion([lote("A", 10, 40), lote("B", 11, 40)], neta_fills=-80)
    s10 = stop10(60, estado=EstadoOrden.PARTIAL, llenas=20, lvqty=40)
    acciones = limpieza_tras_fill_stop(pos, [s10, stop11(40)], cotizacion(X, "10.05", "10.07"), tokens.siguiente, config,
                                       HORA, 8)
    assert acciones == [InvalidarSerie(serie_stops(X), 8)]
    acciones = limpieza_tras_fill_stop(pos, [s10], cotizacion(X, "10.05", "10.07"), tokens.siguiente, config, HORA, 9)
    assert [type(a) for a in acciones] == [InvalidarSerie, EnviarOrden]
    assert (acciones[1].orden.nivel, acciones[1].orden.qty, acciones[1].orden.stop, acciones[1].orden.precio) == (
        D("11"), 40, D("11.00"), D("16.50"))


@pytest.mark.parametrize("nivel_en_la_orden", [True, False], ids=["orden-propia-con-nivel", "adoptada-del-vigilante-sin-nivel"])
def test_limpieza_con_banda_el_stop_recortado_que_llena_en_parte_se_queda(config, tokens, cotizacion, nivel_en_la_orden):
    """R-F-02 + R-C-11 (c): el stop de 11 recortado a 10,34 llena 20 (lote B de 40 a 20): sigue vivo con 20 (también el del
    vigilante sin etiqueta, que se reconoce por el disparo recortado); el de 10 no se toca."""
    pos = posicion([lote("A", 10, 60), lote("B", 11, 20)], neta_fills=-80)
    s11 = orden(100000002 if nivel_en_la_orden else 200000002, STOP if nivel_en_la_orden else Proposito.DESCONOCIDA,
                "10.34", "15.51", 40, id_das=2, estado=EstadoOrden.PARTIAL, llenas=20, lvqty=20,
                nivel=11 if nivel_en_la_orden else None, origen=Origen.EJECUTOR if nivel_en_la_orden else Origen.VIGILANTE)
    acciones = limpieza_tras_fill_stop(pos, [stop10(60), s11], cotizacion(X, "10.36", "10.38"), tokens.siguiente, config,
                                       HORA, 9, limit_up=D("10.5"))
    assert acciones == [InvalidarSerie(serie_stops(X), 9)]


def test_limpieza_corta_respeta_la_precondicion_de_plan_y_acepta_config_como_dict(cfg_json, tokens, cotizacion):
    """D2a-05: con el %POS atrasado el plan de la limpieza no crea ni sube nada; el stop que cuadra con el mínimo se queda y se
    pide GET POSITIONS."""
    pos = posicion([lote("A", 10, 80)], neta_fills=-80, neta_das=-100)
    parcial = stop10(100, estado=EstadoOrden.PARTIAL, llenas=20, lvqty=80)
    acciones = limpieza_tras_fill_stop(pos, [parcial], cotizacion(X, "10.05", "10.07"), tokens.siguiente, cfg_json, HORA, 3)
    assert acciones == [InvalidarSerie(serie_stops(X), 3)] + CONSULTA


def test_D2a_05_pedidos_en_vuelo_no_se_repiten(cfg_stops, tokens):
    """D2a-05 (interfaz para el decisor): el plan del fill, con el %POS atrasado, ya BAJÓ el stop a 80 y canceló el duplicado;
    cuando llega el %POS que cuadra, el plan con esas peticiones EN VUELO no las repite (sin ellas saldrían REPLACE y CANCEL otra
    vez). Un REPLACE en vuelo a otra cantidad se corrige; lo que no es None ni int ≥ 0 se ignora; el CANCEL en vuelo del único
    stop cuenta como ya cancelado → se repone."""
    pos = posicion([lote("A", 10, 80)], neta_fills=-80, neta_das=-80)
    s = stop10(100, id_das=2, token=100000002)
    duplicado = stop10(100, id_das=3, token=100000003)
    sin = plan(pos, [s, duplicado], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)
    assert [(type(a), a.id_das) for a in sin if isinstance(a, (Reemplazar, Cancelar))] == [(Reemplazar, 2), (Cancelar, 3)]
    assert plan(pos, [s, duplicado], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION,
                pedidos_en_vuelo={100000002: 80, 100000003: None}) == []
    otra = plan(pos, [s, duplicado], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION,
                pedidos_en_vuelo={100000002: 90, 100000003: None})
    assert [(type(a), a.id_das, a.qty) for a in otra if isinstance(a, (Reemplazar, Cancelar))] == [(Reemplazar, 2, 80)]
    assert plan(pos, [s, duplicado], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION,
                pedidos_en_vuelo={100000002: True, 100000003: "x", "100000002": 80}) == sin
    repone = plan(pos, [s], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION, pedidos_en_vuelo={100000002: None})
    assert [(type(a), a.orden.proposito, a.orden.qty) for a in repone] == [(EnviarOrden, STOP, 80)]


def test_D2a_05_limpieza_larga_no_repite_el_cancel_en_vuelo(config, tokens, cotizacion):
    """D2a-05 + D2a-03: con la venta del exceso viva, las compras se cancelan una a una, salvo la que ya tiene el CANCEL en vuelo."""
    pos = posicion([lote("A", 10, 100)], neta_fills=50)
    s10 = stop10(100)
    s11 = stop11(100, estado=EstadoOrden.PARTIAL, llenas=60, lvqty=40)
    acciones = limpieza_tras_fill_stop(pos, [_venta(qty=10), s10, s11], cotizacion(X, "9.50", "9.52"),
                                       tokens.siguiente, config, HORA, 6, pedidos_en_vuelo={100000001: None})
    assert [a.id_das for a in de_tipo(acciones, Cancelar)] == [2]


def test_D2a_09_limpieza_pasa_compras_cierre_a_plan(config, tokens, cotizacion):
    """D2a-09: en un halt con la MKT de salida viva por las 80 que quedan, el fill del stop no deja stops encima de ella."""
    pos = posicion([lote("A", 10, 80)], neta_fills=-80, estado=EstadoTicker.HALT)
    parcial = stop10(100, estado=EstadoOrden.PARTIAL, llenas=20, lvqty=80)
    acciones = limpieza_tras_fill_stop(pos, [parcial], cotizacion(X, "10.05", "10.07"), tokens.siguiente, config,
                                       HORA, 5, compras_cierre=80)
    assert [a.id_das for a in de_tipo(acciones, Cancelar)] == [1]
    assert de_tipo(acciones, Reemplazar) == [] and de_tipo(acciones, EnviarOrden) == []


def test_limpieza_rechaza_una_config_sin_bloques(tokens, cotizacion):
    pos = posicion([lote("A", 10, 100)], neta_fills=-80)
    with pytest.raises(ValueError):
        limpieza_tras_fill_stop(pos, [], cotizacion(X, "10.05", "10.07"), tokens.siguiente, {"stops": {}}, HORA, 3)


def test_limpieza_corta_pasa_la_banda_a_plan(config, tokens, cotizacion):
    pos = posicion([lote("A", 10, 80)], neta_fills=-80)
    parcial = stop10(100, estado=EstadoOrden.PARTIAL, llenas=20, lvqty=80)
    acciones = limpieza_tras_fill_stop(pos, [parcial], cotizacion(X, "10.05", "10.07"), tokens.siguiente, config,
                                       HORA, 5, limit_up=D("10.05"))
    nuevas = de_tipo(acciones, EnviarOrden)
    assert len(nuevas) == 1 and (nuevas[0].orden.stop, nuevas[0].orden.qty) == (D("9.89"), 80)
    assert [a.id_das for a in de_tipo(acciones, Cancelar)] == [1]
    assert acciones[0] == InvalidarSerie(serie_stops(X), 5)


def _vivas_de(vivas: list[Orden]) -> list[tuple[str, int]]:
    return sorted((str(o.nivel), o.qty - o.llenas) for o in vivas
                  if o.estado in (EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL) and o.qty > o.llenas)


def test_recorrido_del_precio_por_los_dos_niveles_nunca_queda_largo_ni_sin_stop(config, tokens, cotizacion):
    """R-C-11 de punta a punta (riesgo 6): el stop de 10 llena 20 → los dos niveles siguen cubiertos; el precio toca 11 y
    llenan los dos stops enteros → posición plana → CancelarTicker."""
    ids = itertools.count(1)
    pos = posicion([lote("A", 10, 60), lote("B", 11, 40)], neta_fills=-100)
    vivas = _aplicar(plan(pos, [], config.stops, None, tokens.siguiente, HORA, RUTA_STOP, 1), [], ids)
    s10, s11 = sorted(vivas, key=lambda o: o.id_das)
    assert _vivas_de(vivas) == [("10", 60), ("11", 40)]
    _llenar(s10, 20, pos, config.stops)                                    # 1) el precio toca 10
    assert (pos.lotes["A"].llenas, pos.neta) == (40, -80)
    acciones = limpieza_tras_fill_stop(pos, vivas, cotizacion(X, "10.04", "10.06", last="10.05"), tokens.siguiente, config,
                                       HORA, 2)
    vivas = _aplicar(acciones, vivas, ids)
    assert _vivas_de(vivas) == [("10", 40), ("11", 40)] and descubiertas(pos, vivas) == 0
    _llenar(s11, 40, pos, config.stops)                                    # 2) el precio toca 11: el de 11 llena entero
    acciones = limpieza_tras_fill_stop(pos, vivas, cotizacion(X, "11.02", "11.05", last="11.03"), tokens.siguiente, config,
                                       HORA, 3)
    vivas = _aplicar(acciones, vivas, ids)
    assert _vivas_de(vivas) == [("10", 40)] and descubiertas(pos, vivas) == 0
    _llenar(s10, 40, pos, config.stops)                                    # 3) el de 10 cierra el resto
    acciones = limpieza_tras_fill_stop(pos, vivas, cotizacion(X, "11.10", "11.12"), tokens.siguiente, config, HORA, 4)
    assert acciones == [InvalidarSerie(serie_stops(X), 4), CancelarTicker(X, acciones[1].motivo)] and pos.neta == 0


def test_fogonazo_dos_niveles_llenan_a_la_vez_con_la_posicion_ya_reducida_se_vende_solo_el_exceso(config, tokens, cotizacion):
    """R-C-11 (b) con el stop único: un TP dejó el lote A en 30 (neta −70) pero su stop aún estaba en 60 (el REPLACE no había
    salido); en el salto llenan los dos stops enteros (60 + 40) → larga 30 → se venden 30, ni 70 ni 100."""
    pos = posicion([lote("A", 10, 30), lote("B", 11, 40)], neta_fills=-70)
    s10, s11 = stop10(60), stop11(40)
    _llenar(s10, 60, pos, config.stops)
    _llenar(s11, 40, pos, config.stops)
    assert pos.neta == 30
    acciones = limpieza_tras_fill_stop(pos, [s10, s11], cotizacion(X, "12.55", "12.60"), tokens.siguiente, config, HORA, 6)
    assert [type(a) for a in acciones] == [InvalidarSerie, CancelarTicker, EnviarOrden, Avisar, Anotar, Programar]
    venta = acciones[2].orden
    assert (venta.lado, venta.qty, venta.precio, venta.proposito) == (Lado.VENTA, 30, D("12.29"), Proposito.VENTA_EXCESO)


# ── venta del exceso: lo que ya está en vuelo (D2a-03) y la persecución (D2a-04) ──
def _venta(qty: int = 20, precio: str = "9.31", id_das: Optional[int] = 9, token: int = 100000009,
           estado: EstadoOrden = EstadoOrden.ACCEPTED, proposito: Proposito = Proposito.VENTA_EXCESO,
           origen: Origen = Origen.EJECUTOR) -> Orden:
    return orden(token, proposito, None, precio, qty, id_das=id_das, estado=estado, lado=Lado.VENTA, tipo=TipoOrden.LIMITE,
                 origen=origen)


def test_D2a_03_con_una_venta_del_exceso_viva_vende_solo_la_diferencia_y_no_cancel_allsymb(config, tokens, cotizacion):
    """D2a-03: larga 10 → S1 de 10 viva; otro print deja la cuenta larga 50 → se venden 40 (no 50) y NO CANCEL ALLSYMB (se
    llevaría S1): se cancelan una a una las COMPRAS vivas con id; S1 sigue; la compra aún sin id la cancela el barrido."""
    pos = posicion([lote("A", 10, 100)], neta_fills=50)
    s1 = _venta(qty=10)
    parcial = stop11(100, estado=EstadoOrden.PARTIAL, llenas=60, lvqty=40)
    s10 = stop10(100)
    enviando = stop10(100, token=100000003, id_das=None, estado=EstadoOrden.SENDING)
    acciones = limpieza_tras_fill_stop(pos, [s1, parcial, s10, enviando], cotizacion(X, "9.50", "9.52"),
                                       tokens.siguiente, config, HORA, 6)
    assert acciones[0] == InvalidarSerie(serie_stops(X), 6)
    assert de_tipo(acciones, CancelarTicker) == []
    assert [a.id_das for a in de_tipo(acciones, Cancelar)] == [1, 2]        # compras con id; la venta S1 NO se toca
    assert [(a.orden.lado, a.orden.qty, a.orden.precio) for a in de_tipo(acciones, EnviarOrden)] == [(Lado.VENTA, 40, D("9.31"))]
    incidente = de_tipo(acciones, Anotar)[0]
    assert (incidente.datos["vendidas"], incidente.datos["en_vuelo"], incidente.datos["neta"]) == (40, 10, 50)
    assert "10 ya se están vendiendo" in de_tipo(acciones, Avisar)[0].texto
    assert de_tipo(acciones, Programar) == [Programar(f"exceso_verificar:{X}", 1.0, {"ticker": X, "persecuciones": 0})]


def test_D2a_03_con_la_venta_viva_que_ya_cubre_la_larga_no_sale_otra(config, tokens, cotizacion):
    """D2a-03: larga 10 con la venta de 10 viva → ninguna orden nueva ni CANCEL ALLSYMB; el incidente (vendidas 0) y, R2-STOPS-2,
    la comprobación a 1 s IGUAL (esa venta puede no llenar)."""
    pos = posicion([lote("A", 10, 100)], neta_fills=10)
    acciones = limpieza_tras_fill_stop(pos, [_venta(qty=10)], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 6)
    assert [type(a) for a in acciones] == [InvalidarSerie, Anotar, Programar]
    assert (acciones[1].datos["vendidas"], acciones[1].datos["en_vuelo"]) == (0, 10)
    assert acciones[2] == Programar(f"exceso_verificar:{X}", 1.0, {"ticker": X, "persecuciones": 0})
    assert tokens.ultimo_seq == 0


def test_D2a_03_lo_que_se_vende_nunca_pasa_de_la_larga(config, tokens, cotizacion):
    """D2a-03 (nunca un corto sin stops): 60 en ventas vivas sobre una larga de 50 → se recorta la MÁS NUEVA (10 → Cancelar);
    con 55 sobre 50, la más nueva baja de 10 a 5 (REPLACE de cantidad, mismo precio). Ninguna venta nueva."""
    pos = posicion([lote("A", 10, 100)], neta_fills=50)
    vieja = _venta(qty=50, id_das=8, token=100000008)
    nueva = _venta(qty=10, precio="9.30", id_das=9, token=100000009)
    acciones = limpieza_tras_fill_stop(pos, [nueva, vieja], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 7)
    assert [(type(a), a.id_das) for a in acciones if isinstance(a, (Cancelar, Reemplazar))] == [(Cancelar, 9)]
    assert de_tipo(acciones, EnviarOrden) == [] and de_tipo(acciones, CancelarTicker) == []
    assert de_tipo(acciones, Anotar)[0].datos["tipo"] == "venta_exceso_de_mas"
    vieja.qty = 45
    acciones = limpieza_tras_fill_stop(pos, [nueva, vieja], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 7)
    assert [(type(a), a.id_das, a.qty, a.precio) for a in de_tipo(acciones, Reemplazar)] == [(Reemplazar, 9, 5, D("9.30"))]
    # R2-STOPS-1: una venta ajena (sin etiqueta) NO está en vuelo: sin VENTA_EXCESO viva, CANCEL ALLSYMB se la lleva y se vende la
    # larga (antes contaba como en vuelo y solo se avisaba: si no llenaba, la cuenta seguía larga sin venta ni comprobación)
    ajena_de_mas = _venta(qty=60, id_das=7, token=200000007, proposito=Proposito.DESCONOCIDA, origen=Origen.VIGILANTE)
    acciones = limpieza_tras_fill_stop(pos, [ajena_de_mas], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 7)
    assert [type(a) for a in acciones] == [InvalidarSerie, CancelarTicker, EnviarOrden, Avisar, Anotar, Programar]
    assert de_tipo(acciones, EnviarOrden)[0].orden.qty == 50 and de_tipo(acciones, Reemplazar) == []


def test_R2_STOPS_1_en_vuelo_solo_la_venta_exceso_ni_la_ajena_ni_la_proteccion_de_un_largo(config, tokens, cotizacion):
    """R2-STOPS-1 (corrige al viejo test D2a-03 «en vuelo cuenta toda venta no stop»): «en vuelo» son SOLO las VENTA_EXCESO.
    La venta del vigilante sin etiqueta (20) NO cuenta → CANCEL ALLSYMB + se venden las 50; una VENTA STOPLMTP (protección de un
    largo, R-C-10.4) tampoco → igual. Con una VENTA_EXCESO de 10 viva y la del vigilante: se cancela la del vigilante por id y se
    venden 40 (nunca las dos a la vez: la cuenta quedaría corta sin stops)."""
    pos = posicion([lote("A", 10, 100)], neta_fills=50)
    vig = _venta(qty=20, id_das=7, token=200000007, proposito=Proposito.DESCONOCIDA, origen=Origen.VIGILANTE)
    acciones = limpieza_tras_fill_stop(pos, [vig], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 8)
    assert [a.orden.qty for a in de_tipo(acciones, EnviarOrden)] == [50] and len(de_tipo(acciones, CancelarTicker)) == 1
    assert de_tipo(acciones, Anotar)[0].datos["en_vuelo"] == 0
    proteccion = orden(100000006, Proposito.STOP_PROTECCION, "7.50", "3.75", 50, id_das=6, lado=Lado.VENTA)
    acciones = limpieza_tras_fill_stop(pos, [proteccion], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 8)
    assert [a.orden.qty for a in de_tipo(acciones, EnviarOrden)] == [50] and len(de_tipo(acciones, CancelarTicker)) == 1
    acciones = limpieza_tras_fill_stop(pos, [vig, _venta(qty=10)], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config,
                                       HORA, 8)
    assert de_tipo(acciones, CancelarTicker) == [] and [a.id_das for a in de_tipo(acciones, Cancelar)] == [7]
    assert [a.orden.qty for a in de_tipo(acciones, EnviarOrden)] == [40]
    assert acciones.index(de_tipo(acciones, Cancelar)[0]) < acciones.index(de_tipo(acciones, EnviarOrden)[0])


def _entrada(proposito: Proposito = Proposito.ENTRADA_AGREGAR, qty: int = 100, precio: str = "10.50", id_das: Optional[int] = 10,
             token: int = 100000010, estado: EstadoOrden = EstadoOrden.ACCEPTED) -> Orden:
    """Una venta CORTA de entrada viva (R-B-01): LMT con lado `SS` (el REAL de `entrada.orden_agregar`), jamás cubre una larga.

    27-sep (director): antes se construía con `S` y el módulo solo miraba `S`; una entrada real (`SS`) no se cancelaba."""
    return orden(token, proposito, None, precio, qty, id_das=id_das, estado=estado, lado=Lado.CORTO, tipo=TipoOrden.LIMITE)


@pytest.mark.parametrize("proposito", [Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE])
def test_R2_STOPS_1_larga_20_con_una_entrada_viva_de_100_la_cancela_y_vende_20(config, tokens, cotizacion, proposito):
    """R2-STOPS-1, el caso del verificador: larga 20 + ENTRADA viva de 100 a 10,50. Antes: [InvalidarSerie, Avisar(3)
    exceso_de_mas, Anotar] (la entrada «cubría» la larga), sin venta, sin cancelar la entrada y sin comprobación. Ahora: la
    entrada se CANCELA (sin VENTA_EXCESO viva, el CANCEL ALLSYMB que va delante se la lleva), se venden 20 a bid·0,98 y
    `exceso_verificar` a 1 s. Con una entrada de 10 se venden también 20 (no 10)."""
    pos = posicion([lote("A", 10, 100)], neta_fills=20)
    entrada = _entrada(proposito)
    acciones = limpieza_tras_fill_stop(pos, [entrada], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 4)
    assert [type(a) for a in acciones] == [InvalidarSerie, CancelarTicker, EnviarOrden, Avisar, Anotar, Programar]
    assert acciones[0] == InvalidarSerie(serie_stops(X), 4)
    venta = acciones[2].orden
    assert (venta.lado, venta.qty, venta.precio, venta.proposito) == (Lado.VENTA, 20, D("9.31"), Proposito.VENTA_EXCESO)
    assert acciones[4].datos["en_vuelo"] == 0 and acciones[4].datos["vendidas"] == 20
    assert acciones[5] == Programar(f"exceso_verificar:{X}", 1.0, {"ticker": X, "persecuciones": 0})
    assert all(not (isinstance(a, Avisar) and a.clave.startswith("exceso_de_mas")) for a in acciones)
    assert [o for o in _aplicar(acciones, [entrada], itertools.count(50)) if o.proposito is proposito] == []   # la entrada, fuera
    acciones = limpieza_tras_fill_stop(pos, [_entrada(proposito, qty=10)], cotizacion(X, "9.50", "9.52"), tokens.siguiente,
                                       config, HORA, 4)
    assert [a.orden.qty for a in de_tipo(acciones, EnviarOrden)] == [20]


def test_R2_STOPS_1_con_la_venta_exceso_viva_la_entrada_se_cancela_una_a_una(config, tokens, cotizacion):
    """R2-STOPS-1: con una VENTA_EXCESO de 10 viva (no CANCEL ALLSYMB, se la llevaría) y la cuenta larga 30: la entrada con id se
    CANCELA por id (junto a las compras), se venden 20 (30 − 10: la entrada no cuenta) y se programa la comprobación. La entrada
    aún SIN id → `Anotar("cancelar_al_tener_id", {token…})` para que el decisor la cancele al llegar su Accept; también en la rama
    del CANCEL ALLSYMB (por si la NEWORDER aún no ha llegado a DAS). La que ya tiene el CANCEL en vuelo no se repite."""
    pos = posicion([lote("A", 10, 100)], neta_fills=30)
    ve = _venta(qty=10)
    s10 = stop10(100)
    entrada = _entrada()
    acciones = limpieza_tras_fill_stop(pos, [ve, s10, entrada], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config,
                                       HORA, 6)
    assert de_tipo(acciones, CancelarTicker) == []
    assert [(a.id_das, a.token) for a in de_tipo(acciones, Cancelar)] == [(1, 100000001), (10, 100000010)]
    assert [(a.orden.lado, a.orden.qty, a.orden.precio) for a in de_tipo(acciones, EnviarOrden)] == [(Lado.VENTA, 20, D("9.31"))]
    assert acciones[-1] == Programar(f"exceso_verificar:{X}", 1.0, {"ticker": X, "persecuciones": 0})
    ultimo_cancel = max(i for i, a in enumerate(acciones) if isinstance(a, Cancelar))
    assert ultimo_cancel < acciones.index(de_tipo(acciones, EnviarOrden)[0])
    # entrada Sending sin id
    sin_id = _entrada(id_das=None, estado=EstadoOrden.SENDING, token=100000011)
    for vivas in ([ve, sin_id], [sin_id]):
        acciones = limpieza_tras_fill_stop(pos, vivas, cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 6)
        notas = [a for a in de_tipo(acciones, Anotar) if a.tipo == "cancelar_al_tener_id"]
        assert [(n.datos["token"], n.datos["ticker"], n.datos["proposito"], n.datos["qty"]) for n in notas] == [
            (100000011, X, "entrada_agregar", 100)]
        assert notas[0].datos["motivo"] and "R2-STOPS-1" in notas[0].datos["regla"]
        assert [a.orden.qty for a in de_tipo(acciones, EnviarOrden)] == [30 - (10 if ve in vivas else 0)]
        assert de_tipo(acciones, Programar)[-1].clave == f"exceso_verificar:{X}"
    # el CANCEL ya en vuelo (D2a-05) no se repite, ni el de la entrada
    acciones = limpieza_tras_fill_stop(pos, [ve, s10, entrada], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config,
                                       HORA, 6, pedidos_en_vuelo={100000010: None})
    assert [a.id_das for a in de_tipo(acciones, Cancelar)] == [1]


def test_R2_STOPS_2_con_lo_que_ya_se_vende_de_mas_tambien_se_programa_la_comprobacion(config, tokens, cotizacion):
    """R2-STOPS-2: larga 20 con VENTA_EXCESO de 30 viva (a_vender < 0) → se recorta a 20 y se programa `exceso_verificar` igual."""
    pos = posicion([lote("A", 10, 100)], neta_fills=20)
    acciones = limpieza_tras_fill_stop(pos, [_venta(qty=30)], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 6)
    assert [(a.id_das, a.qty) for a in de_tipo(acciones, Reemplazar)] == [(9, 20)]
    assert acciones[-1] == Programar(f"exceso_verificar:{X}", 1.0, {"ticker": X, "persecuciones": 0})
    assert de_tipo(acciones, EnviarOrden) == [] and tokens.ultimo_seq == 0


def test_R2_STOPS_2_verificar_sin_venta_exceso_viva_y_con_una_entrada_vende_y_sigue_contando(config, tokens, cotizacion):
    """R2-STOPS-2: al vencer la cuenta sigue larga 20 y solo queda viva una ENTRADA (o una venta ajena): no cuenta como venta del
    exceso → CANCEL ALLSYMB (se la lleva) + venta de 20 con el mismo margen + la vuelta siguiente (persecuciones + 1). A la 3.ª,
    aviso «VENDER A MANO»."""
    pos = posicion([lote("A", 10, 100)], neta_fills=20)
    for viva in (_entrada(), _venta(qty=20, id_das=7, token=200000007, proposito=Proposito.DESCONOCIDA, origen=Origen.VIGILANTE)):
        acciones = stops.verificar_venta_exceso(pos, [viva], cotizacion(X, "9.20", "9.22"), tokens.siguiente, config, HORA, 5, 1)
        assert [type(a) for a in acciones] == [CancelarTicker, EnviarOrden, Avisar, Anotar, Programar]
        assert (acciones[1].orden.qty, acciones[1].orden.precio, acciones[1].orden.proposito) == (20, D("9.01"),
                                                                                                   Proposito.VENTA_EXCESO)
        assert acciones[-1] == Programar(f"exceso_verificar:{X}", 1.0, {"ticker": X, "persecuciones": 2})
        acciones = stops.verificar_venta_exceso(pos, [viva], cotizacion(X, "9.20", "9.22"), tokens.siguiente, config, HORA, 5, 3)
        assert [type(a) for a in acciones] == [Avisar, Anotar] and "ninguna venta viva" in acciones[0].texto


def test_R2_STOPS_1_verificar_con_la_venta_exceso_viva_cancela_la_entrada_que_ya_tiene_id(config, tokens, cotizacion):
    """R2-STOPS-1 en la persecución: la VENTA_EXCESO de 20 sigue viva y aparece una entrada con id (su Accept llegó tras la
    limpieza) → Cancelar por id + REPLACE de la venta al bid nuevo; sin repetir un CANCEL que ya está en vuelo."""
    pos = posicion([lote("A", 10, 100)], neta_fills=20)
    ve, entrada = _venta(), _entrada()
    acciones = stops.verificar_venta_exceso(pos, [entrada, ve], cotizacion(X, "9.20", "9.22"), tokens.siguiente, config, HORA,
                                            5, 0)
    assert [type(a) for a in acciones] == [Cancelar, Reemplazar, Anotar, Programar]
    assert (acciones[0].id_das, acciones[0].token) == (10, 100000010)
    assert (acciones[1].id_das, acciones[1].qty, acciones[1].precio) == (9, 20, D("9.01"))
    assert acciones[2].datos["en_vuelo"] == 20 and acciones[2].datos["tokens"] == [100000009]
    acciones = stops.verificar_venta_exceso(pos, [entrada, ve], cotizacion(X, "9.20", "9.22"), tokens.siguiente, config, HORA,
                                            5, 0, pedidos_en_vuelo={100000010: None})
    assert de_tipo(acciones, Cancelar) == []
    assert tokens.ultimo_seq == 0


def test_R2_STOPS_3_ninguna_venta_de_entrada_cubre_nada(config, cfg_stops, tokens, cotizacion):
    """R2-STOPS-3: ningún camino de stops.py toma una ENTRADA_* (venta corta) como cobertura. Larga: lo vendido es
    max(neta − VENTA_EXCESO vivas, 0) con o sin entradas; corta: `descubiertas` no la cuenta y `plan` ni la cuenta ni la toca."""
    for neta in (5, 20, 60):
        for ve_qty in (0, 10, 20):
            for entradas in ([], [_entrada()], [_entrada(qty=15), _entrada(Proposito.ENTRADA_CRUCE, qty=40, token=100000012,
                                                                           id_das=12)]):
                pos = posicion([lote("A", 10, 100)], neta_fills=neta)
                vivas = entradas + ([_venta(qty=ve_qty)] if ve_qty else [])
                acciones = limpieza_tras_fill_stop(pos, vivas, cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 3)
                vendidas = sum(a.orden.qty for a in de_tipo(acciones, EnviarOrden))
                assert vendidas == max(neta - ve_qty, 0), (neta, ve_qty, len(entradas))
                assert de_tipo(acciones, Programar)[-1].clave == f"exceso_verificar:{X}"
                quedan = _aplicar(acciones, vivas, itertools.count(90))
                assert [o for o in quedan if o.proposito in (Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE)] == []
    corta = posicion([lote("A", 10, 100)], neta_fills=-100)
    assert descubiertas(corta, [_entrada()]) == 100
    assert [type(a) for a in plan(corta, [_entrada()], cfg_stops, None, tokens.siguiente, HORA, RUTA_STOP, VERSION)] == [
        EnviarOrden]


def test_R2_STOPS_1_limpieza_larga_no_depende_del_orden_de_las_vivas(config, tokens, cotizacion):
    """R2-STOPS-1: las 120 permutaciones de [VENTA_EXCESO, entrada con id, entrada sin id, venta ajena, stop] dan las MISMAS
    acciones (mismo orden de los Cancelar, misma venta de 30 = 40 − 10)."""
    pos = posicion([lote("A", 10, 100)], neta_fills=40)
    vivas = [_venta(qty=10), _entrada(), _entrada(Proposito.ENTRADA_CRUCE, id_das=None, estado=EstadoOrden.SENDING, token=100000011),
             _venta(qty=5, id_das=7, token=200000007, proposito=Proposito.DESCONOCIDA, origen=Origen.VIGILANTE),
             stop10(100)]
    firmas = set()
    for permutacion in itertools.permutations(vivas):
        acciones = limpieza_tras_fill_stop(pos, list(permutacion), cotizacion(X, "9.50", "9.52"), lambda: 1, config, HORA, 3)
        firmas.add(tuple((type(a).__name__, getattr(a, "id_das", None), getattr(a, "token", None),
                          a.orden.qty if isinstance(a, EnviarOrden) else None,
                          (a.tipo, a.datos.get("token")) if isinstance(a, Anotar) else None) for a in acciones))
    assert len(firmas) == 1
    (firma,) = firmas
    assert [(t, i) for (t, i, *_r) in firma if t == "Cancelar"] == [("Cancelar", 1), ("Cancelar", 7), ("Cancelar", 10)]
    assert [f[3] for f in firma if f[0] == "EnviarOrden"] == [30]
    assert [f[4][1] for f in firma if f[0] == "Anotar" and f[4][0] == "cancelar_al_tener_id"] == [100000011]


def test_D2a_04_la_venta_del_exceso_sale_vendible_y_programa_la_comprobacion(config, tokens, cotizacion):
    """D2a-04: a bid·(1 − 2 %) redondeado abajo, no al bid exacto; `exceso_verificar:X` a 1 s con 0 persecuciones hechas."""
    assert (stops.VENTA_EXCESO_MARGEN_PCT, stops.VENTA_EXCESO_PERSECUCIONES, stops.EXCESO_VERIFICAR_EN_S) == (D("2"), 3, 1.0)
    assert stops.CLAVE_EXCESO_VERIFICAR == "exceso_verificar" and stops.clave_exceso_verificar(X) == f"exceso_verificar:{X}"
    pos = posicion([lote("A", 10, 100)], neta_fills=20)
    acciones = limpieza_tras_fill_stop(pos, [], cotizacion(X, "10.05", "10.07"), tokens.siguiente, config, HORA, 4)
    venta = de_tipo(acciones, EnviarOrden)[0].orden
    assert venta.precio == D("9.84") and en_tick(venta.precio)                 # 10,05·0,98 = 9,849 → 9,84
    assert acciones[-1] == Programar(stops.clave_exceso_verificar(X), stops.EXCESO_VERIFICAR_EN_S, {"ticker": X, "persecuciones": 0})


def test_D2a_04_verificar_con_el_exceso_ya_vendido_no_hace_nada(config, tokens, cotizacion):
    for neta in (0, -10):
        pos = posicion([lote("A", 10, 100)], neta_fills=neta)
        assert stops.verificar_venta_exceso(pos, [_venta()], cotizacion(X, "9.20", "9.22"), tokens.siguiente, config, HORA, 5,
                                            1) == []


def test_D2a_04_verificar_persigue_al_bid_nuevo_con_el_mismo_margen(config, tokens, cotizacion):
    """D2a-04: la venta de 20 a 9,31 sigue viva y la cuenta larga: el bid cae a 9,20 → REPLACE a 9,01 (mismo 2 %); si el bid no
    bajó, nada que reemplazar pero la vuelta cuenta (Programar con una persecución más)."""
    pos = posicion([lote("A", 10, 100)], neta_fills=20)
    venta = _venta()
    acciones = stops.verificar_venta_exceso(pos, [venta], cotizacion(X, "9.20", "9.22"), tokens.siguiente, config, HORA, 5, 0)
    assert [type(a) for a in acciones] == [Reemplazar, Anotar, Programar]
    r = acciones[0]
    assert (r.id_das, r.token, r.qty, r.precio, r.stop, r.serie, r.version) == (9, 100000009, 20, D("9.01"), None, None, 5)
    assert acciones[1].tipo == "venta_exceso_perseguida" and acciones[1].datos["persecucion"] == 1
    assert acciones[2] == Programar(f"exceso_verificar:{X}", 1.0, {"ticker": X, "persecuciones": 1})
    acciones = stops.verificar_venta_exceso(pos, [venta], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 5, 1)
    assert [type(a) for a in acciones] == [Anotar, Programar] and acciones[1].datos["persecuciones"] == 2
    acciones = stops.verificar_venta_exceso(pos, [venta], None, tokens.siguiente, config, HORA, 5, 2)   # sin cotización: cuenta
    assert [type(a) for a in acciones] == [Anotar, Programar] and acciones[1].datos["persecuciones"] == 3
    assert tokens.ultimo_seq == 0


def test_D2a_04_verificar_con_una_venta_viva_no_abre_otra_por_la_diferencia(config, tokens, cotizacion):
    """D2a-04: larga 50 con solo 20 en vuelo → la vuelta persigue esos 20 pero NO abre otra venta por los 30 (los vende la limpieza
    del fill o el barrido; si aquella no tenía precio ya pidió «vender a mano» y aquí se vendería dos veces)."""
    pos = posicion([lote("A", 10, 100)], neta_fills=50)
    acciones = stops.verificar_venta_exceso(pos, [_venta(qty=20)], cotizacion(X, "9.20", "9.22"), tokens.siguiente, config,
                                            HORA, 5, 0)
    assert de_tipo(acciones, EnviarOrden) == [] and de_tipo(acciones, CancelarTicker) == []
    assert [(a.id_das, a.qty, a.precio) for a in de_tipo(acciones, Reemplazar)] == [(9, 20, D("9.01"))]
    assert tokens.ultimo_seq == 0


def test_D2a_04_tras_tres_persecuciones_aviso_3_vender_a_mano_sin_cancelar_la_venta(config, tokens, cotizacion):
    """D2a-04: tras 3 persecuciones la cuenta sigue LARGA → Avisar(3) «VENDER A MANO: la cuenta está LARGA» y ningún temporizador.
    La venta del bot NO se cancela (el barrido pondría otra); el aviso pide cancelarla antes de vender a mano."""
    pos = posicion([lote("A", 10, 100)], neta_fills=20)
    acciones = stops.verificar_venta_exceso(pos, [_venta()], cotizacion(X, "9.00", "9.02"), tokens.siguiente, config, HORA, 5, 3)
    assert [type(a) for a in acciones] == [Avisar, Anotar]
    aviso = acciones[0]
    assert aviso.nivel is Nivel.MAXIMO and aviso.grupo is Grupo.B and aviso.clave == f"exceso_a_mano:{X}"
    assert "VENDER A MANO: la cuenta está LARGA" in aviso.texto and f"/cancelar_ordenes {X} SI" in aviso.texto
    assert acciones[1].datos["tipo"] == "venta_exceso_sin_llenar" and acciones[1].datos["persecuciones"] == 3
    acciones = stops.verificar_venta_exceso(pos, [], cotizacion(X, "9.00", "9.02"), tokens.siguiente, config, HORA, 5, 3)
    assert [type(a) for a in acciones] == [Avisar, Anotar] and "ninguna venta viva" in acciones[0].texto


def test_D2a_04_verificar_sin_venta_viva_y_aun_larga_vuelve_a_vender(config, tokens, cotizacion):
    """D2a-04: la venta desapareció (Send_Rej o cancelada por DAS) y la cuenta sigue larga → CANCEL ALLSYMB + venta de la neta
    con el mismo margen; la vuelta cuenta para el tope de 3."""
    pos = posicion([lote("A", 10, 100)], neta_fills=20)
    rechazada = _venta(estado=EstadoOrden.REJECTED)
    acciones = stops.verificar_venta_exceso(pos, [rechazada], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 5, 1)
    assert [type(a) for a in acciones] == [CancelarTicker, EnviarOrden, Avisar, Anotar, Programar]
    assert (acciones[1].orden.qty, acciones[1].orden.precio) == (20, D("9.31")) and acciones[-1].datos["persecuciones"] == 2


def test_D2a_04_recorrido_la_venta_no_llena_tres_persecuciones_y_aviso(config, tokens, cotizacion):
    """D2a-04 de punta a punta: limpieza vende 20; el bid cae en cada vuelta → 3 REPLACE; a la 4.ª aviso 3; jamás otra venta."""
    pos = posicion([lote("A", 10, 100)], neta_fills=20)
    acciones = limpieza_tras_fill_stop(pos, [], cotizacion(X, "9.50", "9.52"), tokens.siguiente, config, HORA, 4)
    venta = aceptada(de_tipo(acciones, EnviarOrden)[0], id_das=9)
    programar = de_tipo(acciones, Programar)[0]
    reemplazos = 0
    for bid in ("9.20", "9.00", "8.80", "8.60", "8.40"):
        acciones = stops.verificar_venta_exceso(pos, [venta], cotizacion(X, bid, str(D(bid) + D("0.02"))), tokens.siguiente,
                                                config, HORA, 4, programar.datos["persecuciones"])
        assert de_tipo(acciones, EnviarOrden) == [] and de_tipo(acciones, Cancelar) == []
        for r in de_tipo(acciones, Reemplazar):
            venta.precio = r.precio
            reemplazos += 1
        siguiente = de_tipo(acciones, Programar)
        if not siguiente:
            break
        programar = siguiente[0]
    assert reemplazos == 3 and venta.precio == D("8.62")
    assert de_tipo(acciones, Avisar)[0].nivel is Nivel.MAXIMO


def _stops_de_compra(vivas: list[Orden]) -> list[Orden]:
    return [o for o in vivas if o.ticker == X and o.lado is Lado.COMPRA and o.tipo is TipoOrden.STOP_LIMITE_PP
            and o.estado in (EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL) and _viva(o) > 0]


def test_paseos_aleatorios_del_precio_plan_y_limpieza_juntos(config, tokens):
    """Riesgos 6, 7 y 11 juntos con el stop único: 300 paseos del precio con disparos y fills a trozos (a veces varios en el
    mismo salto), `limpieza` en cada fill (tras descontar el fill de los lotes de su nivel, como el decisor) y el `plan` del
    barrido: tras cada paso UN stop por nivel deseado con su cantidad y la suma = −neta, plan idempotente; si queda larga se
    vende EXACTAMENTE la neta. El precio que pasa el límite de un stop sin llenarlo NO mueve nada (eso es cisne negro).

    R2-STOPS-3: en la mitad de los paseos hay además ventas CORTAS de entrada vivas (ENTRADA_AGREGAR / ENTRADA_CRUCE, con y sin
    id; con su propio azar para no cambiar los paseos) y, en el primer salto que dispara stops, una compra de cierre (la salida
    de un halt) que llena en el MISMO salto que los stops: es como la cuenta queda LARGA con el stop único. `plan` no cuenta ni
    toca las entradas y, si la cuenta queda larga, NO cubren nada (se vende la neta entera), se cancelan (CANCEL ALLSYMB; sin
    id, `cancelar_al_tener_id`) y se programa la comprobación; con una VENTA_EXCESO viva añadida, se cancelan por id y se vende
    max(neta − esa venta, 0)."""
    largas_con_entrada = 0
    pasados = 0
    cierres_en_el_salto = 0
    for semilla in range(300):
        rnd = random.Random(semilla)
        rnd_entradas = random.Random(10_000 + semilla)
        ids = itertools.count(1)
        niveles_base = sorted(rnd.sample(["5", "5.2", "5.5", "6", "6.3"], rnd.randint(1, 3)), key=D)
        pos = posicion([lote(f"L{i}", L, rnd.randint(10, 300)) for i, L in enumerate(niveles_base)], neta_fills=0)
        pos.neta_fills = -sum(l.llenas for l in pos.lotes.values())
        limit_up = rnd.choice([None, None, None, D("6.9"), D("5.8")])
        version = 1
        vivas = _aplicar(plan(pos, [], config.stops, limit_up, tokens.siguiente, HORA, RUTA_STOP, version), [], ids)
        entradas: list[Orden] = []
        if rnd_entradas.random() < 0.5:
            for k in range(rnd_entradas.randint(1, 2)):
                con_id = rnd_entradas.random() < 0.7
                entradas.append(_entrada(rnd_entradas.choice([Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE]),
                                         qty=rnd_entradas.randint(1, 400), precio="4.79",
                                         id_das=(10_000 + k) if con_id else None, token=100_000_500 + k,
                                         estado=EstadoOrden.ACCEPTED if con_id else EstadoOrden.SENDING))
            vivas = vivas + entradas
        precio = D("4.80")
        cierre_hecho = False
        for _ in range(60):
            precio = max(D("4.00"), precio + D(rnd.choice(["-0.08", "-0.03", "0.02", "0.05", "0.1", "0.25", "0.6", "2.5", "4"])))
            ask = precio + D("0.01")
            cot = Cotizacion(ticker=X, bid=precio - D("0.01"), ask=ask, last=precio)
            if entradas and not cierre_hecho and any(o.stop <= precio for o in _stops_de_compra(vivas)):
                cierre_hecho = True
                cierres_en_el_salto += 1
                _cierre(pos, rnd_entradas.randint(1, 50))
            llenadas = []
            for o in _stops_de_compra(vivas):
                if o.stop > precio:
                    continue
                if ask > o.precio and not entradas:
                    pasados += 1                               # disparado y sin llenar: el precio pasó el límite
                    continue
                # con entradas: fogonazo. El salto agrega muchos prints: el precio cruza cada disparo por el camino (el límite
                # era alcanzable al dispararse) y cada stop llena ENTERO → varios niveles a la vez → a veces cuenta LARGA
                trozo = rnd.randint(1, _viva(o))
                _llenar(o, _viva(o) if entradas else trozo, pos, config.stops, limit_up)
                llenadas.append(o)
            for o in llenadas:
                version += 1
                acciones = limpieza_tras_fill_stop(pos, vivas, cot, tokens.siguiente, config, HORA, version,
                                                   limit_up=limit_up)
                assert acciones[0] == InvalidarSerie(serie_stops(X), version)
                if pos.neta > 0:
                    assert [(e.orden.lado, e.orden.qty) for e in de_tipo(acciones, EnviarOrden)] == [(Lado.VENTA, pos.neta)]
                    assert acciones[-1] == Programar(stops.clave_exceso_verificar(X), 1.0, {"ticker": X, "persecuciones": 0})
                    vivas_entradas = [e for e in entradas if e in vivas]
                    if vivas_entradas:
                        largas_con_entrada += 1
                        assert len(de_tipo(acciones, CancelarTicker)) == 1
                        notas = sorted(a.datos["token"] for a in de_tipo(acciones, Anotar) if a.tipo == "cancelar_al_tener_id")
                        assert notas == sorted(e.token for e in vivas_entradas if e.id_das is None)
                        en_vuelo = rnd_entradas.randint(1, pos.neta + 20)
                        con_ve = limpieza_tras_fill_stop(pos, vivas + [_venta(qty=en_vuelo, id_das=20_000, token=100_000_700)],
                                                         cot, tokens.siguiente, config, HORA, version, limit_up=limit_up)
                        assert de_tipo(con_ve, CancelarTicker) == []
                        assert sum(e.orden.qty for e in de_tipo(con_ve, EnviarOrden)) == max(pos.neta - en_vuelo, 0)
                        cancelados = {a.id_das for a in de_tipo(con_ve, Cancelar)}
                        assert {e.id_das for e in vivas_entradas if e.id_das is not None} <= cancelados
                        assert 20_000 not in cancelados or pos.neta < en_vuelo       # la VENTA_EXCESO solo se recorta
                        assert con_ve[-1].clave == stops.clave_exceso_verificar(X)
                    break
                vivas = _aplicar(acciones, vivas, ids)
                if pos.neta == 0:
                    assert _stops_de_compra(vivas) == []
                    break
            if pos.neta >= 0:
                break
            vivas = _aplicar(plan(pos, vivas, config.stops, limit_up, tokens.siguiente, HORA, RUTA_STOP, version), vivas, ids)
            assert plan(pos, vivas, config.stops, limit_up, tokens.siguiente, HORA, RUTA_STOP, version) == []
            mios = _mis_stops(vivas, pos, config.stops, limit_up)
            deseados = conjunto_deseado(pos, config.stops, limit_up)
            assert len(mios) == len(deseados) and sum(_viva(o) for o in mios) == -pos.neta
            assert sorted(_viva(o) for o in mios) == sorted(d.qty for d in deseados)
    assert cierres_en_el_salto >= 10 and largas_con_entrada >= 10              # R2-STOPS-3: el caso nuevo se recorre de verdad
    assert pasados >= 10                                                       # y el del precio por encima del límite también


class _EmisorDeMentira:
    """Lo que hace el emisor del cliente con las series (injerto A §8.6): `invalidar` sube la versión AL INSTANTE y
    al vaciar la cola se descarta todo lo de esa serie con versión menor."""

    def __init__(self) -> None:
        self.vigente: dict[str, int] = {}
        self.cola: list = []
        self.salidas: list = []

    def recibir(self, accion) -> None:
        if isinstance(accion, InvalidarSerie):
            self.vigente[accion.serie] = max(self.vigente.get(accion.serie, 0), accion.version)
        else:
            self.cola.append(accion)

    def vaciar(self) -> None:
        for a in self.cola:
            serie = getattr(a, "serie", None)
            version = a.orden.version if isinstance(a, EnviarOrden) else getattr(a, "version", 0)
            if serie is not None and version < self.vigente.get(serie, 0):
                continue
            self.salidas.append(a)
        self.cola = []


def test_riesgo_7_un_replace_viejo_encolado_no_sale_despues_del_fill(config, tokens, cotizacion):
    """Riesgo 7: REPLACE del stop del 11 a 25 (versión 4) encolado; llega el fill del stop del 10 → limpieza (versión 5), que
    pone el del 11 a sus 40 → el viejo se descarta y solo sale el de la versión 5."""
    emisor = _EmisorDeMentira()
    emisor.recibir(Reemplazar(id_das=2, token=100000002, qty=25, stop=D("11.00"), precio=D("16.50"), motivo="viejo",
                              version=4, serie=serie_stops(X)))
    pos = posicion([lote("A", 10, 40), lote("B", 11, 40)], neta_fills=-80)
    s10 = stop10(60, estado=EstadoOrden.PARTIAL, llenas=20, lvqty=40)
    acciones = limpieza_tras_fill_stop(pos, [s10, stop11(30)], cotizacion(X, "10.05", "10.07"), tokens.siguiente, config,
                                       HORA, 5)
    assert isinstance(acciones[0], InvalidarSerie)
    assert all(a.serie == serie_stops(X) and a.version == 5 for a in de_tipo(acciones, Reemplazar))
    for a in acciones:
        emisor.recibir(a)
    emisor.vaciar()
    replaces = de_tipo(emisor.salidas, Reemplazar)
    assert [(r.qty, r.version) for r in replaces] == [(40, 5)]        # el de 25 nunca sale


# ── tipo_conserva_pp (2h.8, §5.6) ────────────────────────────────────────
@pytest.mark.parametrize("tipo,patron,esperado", [
    pytest.param(None, "^SLP", None, id="2h.8-sin-%ORDER-aun"),
    pytest.param("SLP: 2.97 2.99", "^SLP", True, id="2h.8-conserva-pre/post"),
    pytest.param("SL: 2.97 2.99", "^SLP", False, id="2h.8-REPLACE-lo-volvio-STOPLMT"),
    pytest.param("slp: 2.97 2.99", "^SLP", True, id="sin-distinguir-mayusculas"),
    pytest.param("SLP: 2.97 2.99", "", None, id="sin-patron-configurado-(null-hasta-comprobar_das)"),
    pytest.param("SLP: 2.97 2.99", "   ", None, id="patron-en-blanco"),
    pytest.param("SLP: 2.97 2.99", None, None, id="patron-None"),
    pytest.param("SLP: 2.97 2.99", "(", None, id="patron-que-no-compila"),
    pytest.param("STOPLMTP 2.97 2.99", r"STOPLMTP|SLP", True, id="alternativa"),
])
def test_tipo_conserva_pp(tipo, patron, esperado):
    assert tipo_conserva_pp(tipo, patron) is esperado


# ── descubiertas (R-C-03, plan B) ───────────────────────────────────────
@pytest.mark.parametrize("neta,vivas,esperado", [
    pytest.param(-100, [], 100, id="R-C-03-sin-nada-todo-descubierto"),
    pytest.param(-100, [orden(2, STOP, "10.00", "15.00", 100)], 0, id="stop-aceptado-cubre"),
    pytest.param(-100, [orden(2, STOP, "10.00", "15.00", 100, estado=EstadoOrden.SENDING)], 100, id="Sending-no-es-stop-aceptado"),
    pytest.param(-100, [orden(2, STOP, "10.00", "15.00", 100, estado=EstadoOrden.HOLD)], 0, id="Hold-cubre-(manual-L379)"),
    pytest.param(-30, [orden(2, STOP, "10.00", "15.00", 100, estado=EstadoOrden.PARTIAL, llenas=30, lvqty=70)], 0, id="parcial-usa-lvqty"),
    pytest.param(-100, [orden(2, STOP, "10.00", "15.00", 60)], 40, id="stop-corto-deja-40"),
    pytest.param(-100, [orden(2, STOP, "10.00", "15.00", 60), orden(3, STOP, "11.00", "16.50", 40)], 0, id="R-C-01-v4-cada-nivel-cubre-sus-acciones"),
    pytest.param(-100, [orden(2, Proposito.STOP_PROTECCION, "12.50", "18.75", 100)], 0, id="R-C-10-proteccion-cubre"),
    pytest.param(-100, [orden(2, STOP, "10.00", "15.00", 100, ticker="OTRO")], 100, id="otro-ticker"),
    pytest.param(-100, [orden(2, STOP, "10.00", "15.00", 100, estado=EstadoOrden.CANCELED)], 100, id="cancelada-no-cubre"),
    pytest.param(-100, [orden(2, STOP, "10.00", "15.00", 100, lado=Lado.VENTA)], 100, id="venta-no-cubre-un-corto"),
    pytest.param(-100, [orden(2, Proposito.DESCONOCIDA, "10.00", "15.00", 100, origen=Origen.VIGILANTE)], 0, id="correccion-3-stop-del-vigilante-sin-etiqueta-cubre"),
    pytest.param(-100, [orden(2, Proposito.DESCONOCIDA, "11.30", "16.95", 100, origen=Origen.VIGILANTE)], 0, id="correccion-3-stop-del-vigilante-que-no-casa-cubre-como-proteccion"),
    pytest.param(0, [], 0, id="sin-corto"),
    pytest.param(20, [], 0, id="larga-no-esta-descubierta"),
])
def test_descubiertas(neta, vivas, esperado):
    """R-C-03 v4: cubre TODO stop de compra confirmado (el de cada nivel o una protección); en v3 el principal no cubría
    porque la emergencia llevaba la posición entera."""
    assert descubiertas(posicion([lote("A", 10, 100)], neta_fills=neta), vivas) == esperado


def test_descubiertas_infiere_con_la_config_y_la_banda():
    pos = posicion([lote("A", 10, 100)], neta_fills=-100)
    recortado = orden(3, Proposito.DESCONOCIDA, "9.89", "14.84", 100, origen=Origen.VIGILANTE)
    assert descubiertas(pos, [recortado], {}, D("10.05")) == 0                  # 9,89 = stop recortado bajo la banda
    assert descubiertas(pos, [recortado]) == 0                                  # sin banda es protección: también cubre
    assert descubiertas(pos, [recortado], compras_cierre=100) == 0


# ── stop_proteccion (R-C-10 caso 4) ─────────────────────────────────────
def test_stop_proteccion_corta_compra_25_por_encima_con_limite_del_stop_unico(tokens):
    """R-C-10 (4): disparo last·1,25 y límite disparo + 50 % (el del stop único: la protección es el ÚNICO stop de una posición
    desconocida y un límite estrecho se lo saltaría un fogonazo; en v3 llevaba el +3 % del principal)."""
    o = stop_proteccion(X, 100, True, D("10"), D("25"), tokens.siguiente(), RUTA_STOP, VERSION)
    assert (o.lado, o.tipo, o.stop, o.precio, o.qty, o.proposito, o.nivel, o.lote_id, o.ruta, o.version, o.tif, o.post_only) == (
        Lado.COMPRA, TipoOrden.STOP_LIMITE_PP, D("12.50"), D("18.75"), 100, Proposito.STOP_PROTECCION, D("12.50"), None, RUTA_STOP, VERSION, "DAY+", False)
    sin_float(o)


def test_stop_proteccion_larga_vende_25_por_debajo_con_limite_abajo(tokens):
    o = stop_proteccion(X, 100, False, D("10"), D("25"), tokens.siguiente(), RUTA_STOP, VERSION)
    assert (o.lado, o.stop, o.precio, o.nivel) == (Lado.VENTA, D("7.50"), D("3.75"), D("7.50"))
    sin_float(o)
    suelo = stop_proteccion(X, 100, False, D("10"), D("25"), tokens.siguiente(), RUTA_STOP, VERSION, limite_pct=100)
    assert (suelo.stop, suelo.precio) == (D("7.50"), D("0.01"))                 # un límite ≤ 0 no es un precio: un tick


def test_stop_proteccion_pennies_redondeos_y_pct_de_la_config(tokens):
    o = stop_proteccion(X, 5000, True, D("0.5"), D("25"), tokens.siguiente(), RUTA_STOP, 0)
    assert (o.stop, o.precio) == (D("0.6250"), D("0.9375"))
    o = stop_proteccion(X, 100, True, D("10.01"), D("25"), tokens.siguiente(), RUTA_STOP, 0)
    assert (o.stop, o.precio) == (D("12.52"), D("18.78"))                       # 12,5125 → 12,52; 12,52·1,5 = 18,78
    o = stop_proteccion(X, 100, True, D("10"), 25.0, tokens.siguiente(), RUTA_STOP, 0)   # proteccion_desconocidas_pct del JSON
    assert (o.stop, o.precio) == (D("12.50"), D("18.75"))
    o = stop_proteccion(X, 100, True, D("10"), D("25"), tokens.siguiente(), RUTA_STOP, 0, limite_pct=30.0)   # stops.limite_pct
    assert (o.stop, o.precio) == (D("12.50"), D("16.25"))


@pytest.mark.parametrize("qty,last,pct,limite", [
    pytest.param(0, D("10"), D("25"), None, id="qty-cero"),
    pytest.param(10.0, D("10"), D("25"), None, id="injerto-8.2-qty-float"),
    pytest.param(100, D("0"), D("25"), None, id="last-cero"),
    pytest.param(100, D("NaN"), D("25"), None, id="last-NaN"),
    pytest.param(100, D("10"), D("-1"), None, id="pct-negativo"),
    pytest.param(100, D("10"), D("25"), D("-1"), id="limite-pct-negativo"),
])
def test_stop_proteccion_rechaza(tokens, qty, last, pct, limite):
    with pytest.raises(ValueError):
        stop_proteccion(X, qty, True, last, pct, tokens.siguiente(), RUTA_STOP, 0, limite_pct=limite)


# ── cantidad_cancelada (injerto A §8.7, riesgo 5) ────────────────────────
@pytest.mark.parametrize("mensaje,esperado", [
    pytest.param(msg_act("Canceled", 40), 40, id="injerto-8.7-OrderAct-Canceled-qty"),
    pytest.param(msg_act("canceled", 40), 40, id="sin-distinguir-mayusculas"),
    pytest.param(msg_act("Canceling", 100), 0, id="Canceling-aun-no-confirma-nada"),
    pytest.param(msg_act("Execute", 100), 0, id="Execute-no-es-cancelacion"),
    pytest.param(msg_act("Replaced", 100), 0, id="Replaced-no-es-cancelacion"),
    pytest.param(msg_act("Send_Rej", 100), 0, id="Send_Rej-no-es-cancelacion"),
    pytest.param(msg_act("Canceled", -5), 0, id="nunca-negativa"),
    pytest.param(msg_orden("B", "L", "10.00", cxlqty=60, qty=100, estado=EstadoOrden.CANCELED), 60, id="injerto-8.7-ORDER-cxlqty-no-qty"),
    pytest.param(msg_orden("B", "L", "10.00", cxlqty=0, qty=100), 0, id="ORDER-sin-cancelar"),
])
def test_cantidad_cancelada(mensaje, esperado):
    assert cantidad_cancelada(mensaje) == esperado
    assert cantidad_cancelada(mensaje) != 100 or esperado == 100          # nunca «lo pedido»


def test_cantidad_cancelada_rechaza_otros_tipos():
    with pytest.raises(TypeError):
        cantidad_cancelada("Canceled 40")   # type: ignore[arg-type]


# ── pureza del módulo (documento §3: reglas/* sin reloj, sin I/O, sin logging) ──
def test_modulo_puro_solo_importa_tipos_precios_y_biblioteca_estandar():
    fuente = Path(stops.__file__).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom):
            importados.add(nodo.module)
    assert importados == {"__future__", "re", "collections.abc", "datetime", "decimal", "typing",
                          "app.bot_das.reglas.precios", "app.bot_das.tipos"}
    cuerpo = fuente.split('"""', 2)[2]                                       # fuera la docstring del módulo
    for prohibido in (r"datetime\.now", r"\btime\.", r"os\.environ", r"\bopen\(", r"\bprint\(", r"logging", r"(?<![\w.])float\("):
        assert re.search(prohibido, cuerpo) is None, prohibido              # float( sí como parte de de_float(
    for resto_del_par in ("STOP_PRINCIPAL", "STOP_EMERGENCIA", "principal_consumido", "emergencia_disparo", "emergencia_limite"):
        assert resto_del_par not in cuerpo, resto_del_par                   # Jaume 29-sep: sin restos del par de v3


def test_serie_stops_es_la_del_injerto_8_6():
    assert serie_stops("ABC") == "stops:ABC"


def test_A_06_comando_posiciones_es_el_de_protocolo_cmd_get():
    """A-06 (nombra stops.py): el módulo es PURO y no puede importar protocolo; su literal es EXACTAMENTE cmd_get("POSITIONS")."""
    from app.bot_das import protocolo
    assert COMANDO_POSICIONES == protocolo.cmd_get("POSITIONS") == "GET POSITIONS"
