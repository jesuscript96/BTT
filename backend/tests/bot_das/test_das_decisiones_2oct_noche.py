"""Tests de lo REAL del 2-oct (primeras órdenes de prueba contra DAS) y de las decisiones 64-67 de Jaume.

QUÉ PRUEBA.
  * 64 órdenes madre/hija de SMAT: la hija pasa a ser LA orden viva del token
    (CANCEL/REPLACE van a su id, el REPLACE de un stop disparado va como
    LÍMITE), nunca se cuentan las dos, la madre «Triggered» con lvqty 0 no
    se cancela ni se reemplaza (se espera a la hija), la reconciliación las
    empareja (`fusionar_madres_hijas`) y no las toma por ajenas, el diario
    las rehace tras un reinicio, «CANCEL Error : order not open» es benigno
    y un stop que DAS cancela una y otra vez («RT:Cxl-by-Venue») no se
    repone en bucle.
  * 65 el stop que NO se ejecuta 5 s dentro de su banda: aviso máximo y
    compra límite de respaldo YA con el stop puesto; el stop se cancela
    cuando DAS ACEPTA la compra; no aplica con fills avanzando, en halt, en
    cisne negro ni con el ticker en control humano o pausado; rechazada →
    el stop se queda; resto sin llenar → el stop vuelve; si llenan los dos,
    la venta del exceso; una vez por episodio.
  * 66 rutas de PRUEBAS: el %SLRET de TESTSL se ignora aunque sea el más
    barato y nunca sale un SLNEWORDER por ella; un cuadro con una ruta de
    órdenes de pruebas no carga.
  * 67 /ayuda (y /help).
  * El simulador hace lo real: SMAT con madre/hija, «SLP:<disparo>»,
    «CANCEL Error : order not open», TIF «DAY» por SAGE*, %POS antes del
    Execute.

POR QUÉ APARTE. Son los hallazgos del DAS real del 2-oct y las decisiones que
salieron de ellos; usan los mismos dobles que test_das_decisor (Banco).
"""
from __future__ import annotations

import copy
import dataclasses
import json
import types
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.bot_das import comandos, config as mod_config, protocolo
from app.bot_das import decisor as mod_decisor
from app.bot_das.diario import a_json_seguro, memoria_decisor, reconstruir
from app.bot_das.reglas import reconciliacion, stops, vigilancia
from app.bot_das.simulador_das import (
    LINEA_CANCEL_NO_ABIERTA,
    RUTA_HIJA_SMAT,
    Emparejador,
    LibroSimulado,
)
from app.bot_das.reloj import ET, RelojSimulado
from app.bot_das.tipos import (
    Anotar,
    Avisar,
    Cancelar,
    Config,
    Consultar,
    DeDAS,
    EnviarOrden,
    EstadoOrden,
    EstadoTicker,
    Lado,
    LocateComprar,
    MsgOrden,
    MsgPos,
    Nivel,
    Proposito,
    Reemplazar,
    Registro,
    SenalRecibida,
    Senal,
    TipoOrden,
)
from test_das_decisor import (  # noqa: F401 — `banco` es un fixture
    CUENTA,
    HOY,
    SID,
    STOPS,
    TICKER,
    Banco,
    _a_halt,
    abrir_posicion,
    anotaciones,
    banco,
    cfg_con,
    salida,
)

D = Decimal
SIN_LIQUIDEZ = ("4.40", "4.50", "4.45")          # en la banda del stop (disparo 4,00, límite 6,00) y sin ask


def _stop(b: Banco):
    (stop,) = b.enviadas(*STOPS)
    return b.orden(stop.token)


def _disparar_sin_llenar(b: Banco) -> None:
    """El último pasa el disparo (4,00) y el ask no tiene tamaño: el stop SMAT dispara (madre + hija) y no llena."""
    b.cotizar(TICKER, *SIN_LIQUIDEZ, tam_ask=0)
    b.tic_das()


def _lineas(b: Banco, marca: int = 0) -> list[str]:
    return b.canal.enviadas()[marca:]


def _avisos(acciones: list, prefijo: str) -> list[Avisar]:
    return [a for a in acciones if isinstance(a, Avisar) and (a.clave or "").startswith(prefijo)]


def _registros(b: Banco) -> list[Registro]:
    regs: list[Registro] = []
    for a in b.historial:
        if isinstance(a, Anotar):
            tipo, datos = a.tipo, a.datos
        elif isinstance(a, EnviarOrden):
            o = a.orden
            tipo = "orden_intencion"
            datos = {"token": o.token, "ticker": o.ticker, "lado": o.lado.value, "tipo_orden": o.tipo.value,
                     "qty": o.qty, "precio": o.precio, "stop": o.stop, "ruta": o.ruta, "post_only": o.post_only,
                     "tif": o.tif, "pref": o.pref, "proposito": o.proposito.value, "lote_id": o.lote_id,
                     "nivel": o.nivel, "version": o.version, "origen": 1, "serie": a.serie}
        else:
            continue
        regs.append(Registro(v=1, seq=len(regs) + 1, t="t", proceso="ejecutor", tipo=tipo, datos=a_json_seguro(datos)))
    return regs


# ═══════════════════════════════ el simulador hace lo real ═══════════════════════════════
@pytest.fixture
def emp() -> Emparejador:
    from datetime import datetime
    libro = LibroSimulado()
    libro.cotizar("SOFI", D("16.00"), D("16.04"), last=D("16.01"))
    return Emparejador(libro, RelojSimulado(datetime(2026, 10, 2, 5, 13, tzinfo=ET)))


def _parsear(lineas: list[str]) -> list:
    return [protocolo.parsear(x) for x in lineas]


def test_simulador_limite_por_smat_madre_triggered_e_hija(emp: Emparejador) -> None:
    """Caso b real: la madre se acepta, la hija nace por ARCA con el MISMO token y origoid = madre, la madre queda
    Triggered con lvqty 0 y el CANCEL a la madre contesta «CANCEL Error : order not open»."""
    salida_ = emp.recibir("NEWORDER 127599002 B SOFI SMAT 1 11.19 PostOnly TIF=DAY+")
    ordenes = [m for m in _parsear(salida_) if isinstance(m, MsgOrden)]
    madre, hija = ordenes[0].id, ordenes[-1].id
    assert [(m.id, m.estado.value, m.ruta) for m in ordenes] == [
        (madre, "Sending", "SMAT"), (madre, "Accepted", "SMAT"), (hija, "Sending", RUTA_HIJA_SMAT),
        (madre, "Triggered", "SMAT"), (hija, "Accepted", RUTA_HIJA_SMAT)]
    assert all(m.token == 127599002 for m in ordenes) and hija > madre
    assert ordenes[2].origoid == madre and ordenes[4].origoid == madre and ordenes[4].tif == "DAY"
    assert ordenes[3].lvqty == 0
    assert emp.recibir(f"CANCEL {madre}") == [LINEA_CANCEL_NO_ABIERTA]
    canceladas = [m for m in _parsear(emp.recibir(f"CANCEL {hija}")) if isinstance(m, MsgOrden)]
    assert canceladas[-1].estado is EstadoOrden.CANCELED


def test_simulador_stop_smat_una_orden_hasta_disparar_y_luego_hija(emp: Emparejador) -> None:
    """Caso a real: «SLP:24» con el límite en price; REPLACE conserva id y tipo; al disparar, madre + hija límite."""
    m = [x for x in _parsear(emp.recibir("NEWORDER 127599001 B SOFI SMAT 1 STOPLMTP 24 36 TIF=DAY+"))
         if isinstance(x, MsgOrden)]
    assert (m[-1].tipo, m[-1].precio, m[-1].estado.value) == ("SLP:24", D("36"), "Accepted")
    r = [x for x in _parsear(emp.recibir(f"REPLACE {m[-1].id} 2 STOPLMT 24 36")) if isinstance(x, MsgOrden)]
    assert (r[-1].id, r[-1].tipo, r[-1].qty) == (m[-1].id, "SLP:24", 2)
    emp.libro.cotizar("SOFI", D("24.00"), D("24.10"), last=D("24.05"))
    tras = _parsear(emp.tic())
    ordenes = [x for x in tras if isinstance(x, MsgOrden)]
    assert any(o.id == m[-1].id and o.estado is EstadoOrden.TRIGGERED and o.lvqty == 0 for o in ordenes)
    hijas = [o for o in ordenes if o.origoid == m[-1].id]
    assert hijas and hijas[0].tipo == "L" and hijas[0].precio == D("36")
    assert emp.libro.posiciones()["SOFI"] == 2                       # la hija llenó al ask (24,10 ≤ 36)


def test_simulador_sagepro_tif_day_y_pos_antes_del_execute(emp: Emparejador) -> None:
    """Casos c y e reales: por SAGEPRO el Accepted vuelve con TIF «DAY»; el %POS llega antes que el Execute."""
    lineas = emp.recibir("NEWORDER 127601100 B SOFI SAGEPRO 1 16.04 TIF=DAY+")
    msgs = _parsear(lineas)
    aceptada = [x for x in msgs if isinstance(x, MsgOrden) and x.estado is EstadoOrden.ACCEPTED]
    assert aceptada and aceptada[0].tif == "DAY"
    tipos = [type(x).__name__ for x in msgs]
    assert tipos.index("MsgPos") < tipos.index("MsgTrade")
    assert lineas.index(next(x for x in lineas if x.startswith("%POS"))) < lineas.index(
        next(x for x in lineas if " Execute " in x))


def test_simulador_edga_conserva_day_mas(emp: Emparejador) -> None:
    m = [x for x in _parsear(emp.recibir("NEWORDER 127600721 B SOFI EDGA 1 11.2 TIF=DAY+")) if isinstance(x, MsgOrden)]
    assert m[-1].tif == "DAY+"


# ═══════════════════════════════ decisión 64: madre/hija de SMAT ═══════════════════════════════
def test_64_fusionar_madres_hijas_una_sola_orden_con_el_tipo_de_la_madre() -> None:
    p = protocolo.Parser(lambda t: True)
    madre = p.parsear("%ORDER 2070 126800001 XYZ B SLP:4 100 0 0 6 SMAT Triggered 09:31:00 0 C U CMDAPI DAY+ N/A")
    hija = p.parsear("%ORDER 2071 126800001 XYZ B L 100 80 0 6 ARCA Partial 09:31:00 2070 C U CMDAPI DAY N/A")
    otra = p.parsear("%ORDER 2072 126800009 XYZ B L 5 5 0 3 SAGEPRO Accepted 09:31:00 0 C U CMDAPI DAY N/A")
    fusion = reconciliacion.fusionar_madres_hijas({m.id: m for m in (madre, hija, otra)})
    assert sorted(fusion) == [2071, 2072]
    assert fusion[2071].tipo == "SLP:4" and fusion[2071].lvqty == 80 and fusion[2071].ruta == "ARCA"
    assert reconciliacion.fusionar_madres_hijas([madre]) == {2070: madre}       # sin hija: la madre tal cual
    o = reconciliacion.orden_de_msg(fusion[2071], HOY, None, {})
    assert (o.tipo, o.stop, o.precio, o.id_das, o.id_madre) == (TipoOrden.STOP_LIMITE_PP, D("4"), D("6"), 2071, 2070)


def test_64_stop_disparado_con_hija_la_hija_es_la_orden_viva(banco: Banco) -> None:
    """El stop SMAT dispara sin llenar: la hija es la orden viva (id), se cuenta UNA vez y el stop no se repone."""
    b = banco
    abrir_posicion(b)
    o = _stop(b)
    madre = o.id_das
    marca = b.marca()
    _disparar_sin_llenar(b)
    assert o.id_madre == madre and o.id_das > madre and o.estado is EstadoOrden.ACCEPTED
    assert anotaciones(b.desde(marca), "orden_hija")
    assert mod_decisor._qty_viva(o) == 100
    assert stops.descubiertas(b.pos(), b.decisor._ordenes_ticker(TICKER), b.decisor.cfg.stops) == 0
    b.avanzar(2)
    assert not b.enviadas(*STOPS, desde=marca)                         # nunca otro stop ni otra compra
    assert not [x for x in _lineas(b) if x.startswith(f"CANCEL {madre}")]


def test_64_stop_disparado_con_hija_a_medio_llenar_replace_y_cancel_van_a_la_hija(banco: Banco) -> None:
    """La hija llena 20: posición −80, ni REPLACE ni otra compra. Un TP de 50 que llena baja el stop: el REPLACE va a
    la HIJA como LÍMITE («REPLACE hija 30 6»), no a la madre ni como STOPLMT; al quedar plana, el CANCEL va a la hija."""
    b = banco
    abrir_posicion(b)
    o = _stop(b)
    madre = o.id_das
    b.cotizar(TICKER, "4.40", "4.50", "4.45", tam_ask=20)
    b.tic_das()
    assert b.pos().neta_fills == -80 and o.llenas == 20 and o.id_madre == madre
    assert mod_decisor._qty_viva(o) == 80
    hija = o.id_das
    assert not [x for x in _lineas(b) if x.startswith(f"REPLACE {madre} ") or x == f"CANCEL {madre}"]
    decisor = b.decisor
    acciones = decisor._absorber([Reemplazar(id_das=madre, token=o.token, qty=30, stop=o.stop, precio=o.precio,
                                             motivo="prueba")])
    (r,) = [a for a in acciones if isinstance(a, Reemplazar)]
    assert (r.id_das, r.stop, r.precio, r.qty) == (hija, None, D("6.00"), 30)
    acciones = decisor._absorber([Cancelar(id_das=madre, token=o.token, motivo="prueba")])
    assert [a.id_das for a in acciones if isinstance(a, Cancelar)] == [hija]


def test_64_replace_real_sobre_la_hija_lo_acepta_el_simulador(banco: Banco) -> None:
    """De punta a punta: con la hija viva, una salida que llena reduce el stop → «REPLACE hija N precio» (LÍMITE) y el
    simulador (la hija es una límite) lo acepta: ningún ReplaceRej."""
    b = banco
    abrir_posicion(b)
    _disparar_sin_llenar(b)
    o = _stop(b)
    hija = o.id_das
    marca = len(b.canal.enviadas())
    tp = salida()
    b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id="tp-64", evento=tp, momento=tp.momento,
                                   recibida_en=b.ahora())))
    (tp_orden,) = b.enviadas(Proposito.TP_AGREGAR)
    tp = b.orden(tp_orden.token)
    # el TP llena (un Execute sintético: con el ask a su precio también llenaría la hija, que compra hasta 6,00)
    b.dar([f"%OrderAct {tp.id_das} Execute Buy {TICKER} 50 {tp_orden.precio} SAGEREB 09:31:00  {tp.token}"])
    assert b.pos().neta_fills == -50
    reemplazos = [x for x in _lineas(b, marca) if x.startswith("REPLACE")]
    assert reemplazos and all(x.startswith(f"REPLACE {hija} ") and "STOPLMT" not in x for x in reemplazos)
    assert not anotaciones(b.historial, "replace_sin_pp")
    assert not [a for a in b.historial if isinstance(a, Anotar) and a.tipo == "orden_act"
                and a.datos.get("accion") == "ReplaceRej"]
    assert mod_decisor._qty_viva(o) == 50 and tp_orden.qty == 50


def test_64_madre_disparada_sin_hija_no_se_cancela_y_espera(banco: Banco) -> None:
    """DAS deja la madre «Triggered» con lvqty 0 y la hija aún no llega: cuenta UNA vez (100), no se le manda CANCEL
    (DAS diría «order not open»); el CANCEL sale contra la hija en cuanto llega. Sin hija, GET ORDERS a los 2 s y aviso 2."""
    b = banco
    abrir_posicion(b)
    o = _stop(b)
    madre = o.id_das
    b.das_contesta = False
    b.dar([f"%ORDER {madre} {o.token} {TICKER} B SLP:4 100 0 0 6 SMAT Triggered 09:31:00 0 {CUENTA} TRPRUEBA CMDAPI "
           f"DAY+ N/A"])
    assert b.decisor._madre_sin_hija(o) and mod_decisor._qty_viva(o) == 100
    marca = len(b.canal.enviadas())
    b.comando(f"/cancelar_ordenes {TICKER} SI")
    assert not [x for x in _lineas(b, marca) if x == f"CANCEL {madre}"]
    assert o.token in b.decisor._cancelar_al_aceptar
    b.avanzar(4.5)
    assert anotaciones(b.historial, "orden_hija_sin_ver")
    assert _avisos(b.historial, f"hija_sin_ver:{o.token}")[0].nivel is Nivel.AVISO
    hija = madre + 50
    b.dar([f"%ORDER {hija} {o.token} {TICKER} B L 100 100 0 6 ARCA Accepted 09:31:01 {madre} {CUENTA} TRPRUEBA "
           f"CMDAPI DAY N/A"])
    assert o.id_das == hija and o.id_madre == madre
    assert f"CANCEL {hija}" in _lineas(b, marca)


def test_64_replace_a_una_madre_sin_hija_se_rehace_con_la_hija(banco: Banco) -> None:
    b = banco
    abrir_posicion(b)
    o = _stop(b)
    madre = o.id_das
    b.dar([f"%ORDER {madre} {o.token} {TICKER} B SLP:4 100 0 0 6 SMAT Triggered 09:31:00 0 {CUENTA} TRPRUEBA CMDAPI "
           f"DAY+ N/A"])
    acciones = b.decisor._absorber([Reemplazar(id_das=madre, token=o.token, qty=50, stop=o.stop, precio=o.precio,
                                               motivo="prueba")])
    assert not [a for a in acciones if isinstance(a, Reemplazar)] and anotaciones(acciones, "replace_esperando_hija")
    marca = b.marca()
    b.dar([f"%ORDER {madre + 7} {o.token} {TICKER} B L 100 100 0 6 ARCA Accepted 09:31:01 {madre} {CUENTA} TRPRUEBA "
           f"CMDAPI DAY N/A"])
    assert anotaciones(b.desde(marca), "orden_hija") and anotaciones(b.desde(marca), "stop_plan") is not None


def test_64_cancel_error_order_not_open_es_benigno_sin_bucle(banco: Banco) -> None:
    b = banco
    abrir_posicion(b)
    marca = b.marca()
    acciones = b.procesar(DeDAS(protocolo.parsear("CANCEL Error : order not open ")), bombear=False)
    (nota,) = anotaciones(acciones, "das_error_orden")
    assert nota.datos["no_abierta"] is True and not [a for a in acciones if isinstance(a, Avisar)]
    assert [a.comando for a in acciones if isinstance(a, Consultar)] == ["GET ORDERS"]
    otra = b.procesar(DeDAS(protocolo.parsear("CANCEL Error : order not open")), bombear=False)
    assert not [a for a in otra if isinstance(a, Consultar)]          # como mucho una consulta por segundo
    assert not [a for a in b.desde(marca) if isinstance(a, (Cancelar, EnviarOrden))]


def test_64_reconciliacion_al_arrancar_con_madre_e_hija(cfg: Config, tmp_path: Path) -> None:
    """Reinicio con el stop SMAT disparado (madre Triggered + hija viva): el diario rehace la hija, el GET ORDERS
    las empareja, ni caso 4 (ajena) ni pausa, ni un stop nuevo; la hija sigue siendo la orden viva."""
    b1 = Banco(cfg, tmp_path)
    b1.preparar()
    abrir_posicion(b1)
    _disparar_sin_llenar(b1)
    o1 = _stop(b1)
    regs = _registros(b1)
    estado = reconstruir(regs, HOY)
    o_diario = estado.ordenes[o1.token]
    assert (o_diario.id_das, o_diario.id_madre) == (o1.id_das, o1.id_madre)
    b2 = Banco(cfg, tmp_path / "relanzado", estado=estado, memoria=memoria_decisor(regs, HOY))
    b2.reloj, b2.mercado._reloj, b2.referencia._reloj = b1.reloj, b1.reloj, b1.reloj
    b2.libro, b2.das = b1.libro, b1.das
    b2.preparar(locates=(), cotizaciones=((TICKER, *SIN_LIQUIDEZ),))
    b2.cotizar(TICKER, *SIN_LIQUIDEZ, tam_ask=0)
    b2.avanzar(3)
    casos = [a.datos["casos"] for a in anotaciones(b2.historial, "reconciliacion")]
    assert casos and all(c.get(TICKER) == reconciliacion.CASO_COINCIDE for c in casos)
    assert b2.pos().estado is not EstadoTicker.CONTROL_HUMANO
    assert not b2.enviadas(*STOPS) and not b2.enviadas()
    assert b2.orden(o1.token).id_das == o1.id_das


def test_64_reconciliacion_pura_madre_e_hija_no_son_dos_ni_ajenas(cfg: Config) -> None:
    from test_das_decisor import _estado_con_lote
    estado = _estado_con_lote()
    p = protocolo.Parser(lambda t: True)
    tok = 126800001
    madre = p.parsear(f"%ORDER 70 {tok} XYZ B SLP:4 100 0 0 6 SMAT Triggered 09:31:00 0 {CUENTA} T CMDAPI DAY+ N/A")
    hija = p.parsear(f"%ORDER 71 {tok} XYZ B L 100 100 0 6 ARCA Accepted 09:31:00 70 {CUENTA} T CMDAPI DAY N/A")
    pos = protocolo.parsear(f"%POS XYZ 3 100 3.45 0 0 0 2026/09/25-09:31:00 0")
    assert isinstance(pos, MsgPos)
    (d,) = reconciliacion.comparar(estado, {TICKER: pos}, {70: madre, 71: hija}, HOY, cfg)
    assert d.caso == reconciliacion.CASO_COINCIDE and len(d.vivas) == 1 and d.vivas[0].id_das == 71


def test_64_vigilancia_con_madre_e_hija_cubierta_y_sin_tocar_la_madre(cfg: Config) -> None:
    """El vigilante (ejecutor MUERTO) ve madre Triggered + hija: la posición está cubierta UNA vez (ni descubierta ni
    sobrante) y no manda nada: ni CANCEL a la madre ni otro stop."""
    from test_das_reglas_vigilancia import AHORA, HORA, RUTA_STOP, TokensVigilante, foto, nivel_das
    madre = dataclasses.replace(nivel_das(11), estado=EstadoOrden.TRIGGERED, lvqty=0)
    hija = dataclasses.replace(nivel_das(11), id=12, tipo="L", ruta="ARCA", origoid=11)
    f = foto(ordenes=(madre, hija), latido=None)
    assert vigilancia.descubiertas_por_ticker(f, cfg, HOY) == {}
    acciones = vigilancia.comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert not [a for a in acciones if isinstance(a, (Cancelar, Reemplazar, EnviarOrden))]


def test_64_diario_no_vuelve_al_id_de_la_madre() -> None:
    from app.bot_das.diario import TIPO_ORDEN_HIJA
    tok = 126800001

    def reg(seq: int, tipo: str, **datos) -> Registro:
        return Registro(v=1, seq=seq, t="t", proceso="ejecutor", tipo=tipo, datos=datos)
    regs = [reg(1, "orden_intencion", token=tok, ticker=TICKER, lado="B", tipo_orden="STOPLMTP", qty=100,
                precio="6", stop="4", ruta="SMAT", proposito="stop", lote_id=None, nivel="4", version=1, origen=1),
            reg(2, "orden_estado", token=tok, id=70, estado="Accepted", qty=100, lvqty=100, cxlqty=0),
            reg(3, TIPO_ORDEN_HIJA, token=tok, ticker=TICKER, id_madre=70, id_hija=71, llenas_antes=0),
            reg(4, "orden_estado", token=tok, id=71, estado="Accepted", qty=100, lvqty=100, cxlqty=0),
            reg(5, "orden_act", token=tok, id=70, accion="Canceled", notas=""),
            reg(6, "orden_estado", token=tok, id=70, estado="Triggered", qty=100, lvqty=0, cxlqty=0)]
    o = reconstruir(regs, HOY).ordenes[tok]
    assert (o.id_das, o.id_madre, o.estado) == (71, 70, EstadoOrden.ACCEPTED)


@pytest.mark.parametrize("veces, repone", [(1, True), (3, False)])
def test_64_stop_cancelado_por_el_mercado_no_se_repone_en_bucle(banco: Banco, veces: int, repone: bool) -> None:
    """Caso d («RT:Cxl-by-Venue»): DAS cancela el stop sin pedirlo. La 1.ª vez se repone (R-C-04); a la 3.ª en 60 s
    NO se repone más y aviso MÁXIMO con el motivo de DAS (sin bucle de reenvíos por la misma ruta)."""
    b = banco
    abrir_posicion(b)
    for _ in range(veces):
        o = _stop(b) if len(b.enviadas(*STOPS)) == 1 else b.orden(b.enviadas(*STOPS)[-1].token)
        marca = b.marca()
        b.dar([f"%OrderAct {o.id_das} Canceled Buy {TICKER} 100 4 SMAT 09:31:00 RT:Cxl-by-Venue {o.token}",
               f"%ORDER {o.id_das} {o.token} {TICKER} B SLP:4 100 0 100 6 SMAT Canceled 09:31:00 0 {CUENTA} TRPRUEBA "
               f"CMDAPI DAY+ N/A"])
        b.das.libro._ordenes[o.id_das].estado = "Canceled"
    nuevos = b.enviadas(*STOPS, desde=marca)
    (aviso,) = _avisos(b.desde(marca), f"stop_cancelado:{TICKER}")
    assert "RT:Cxl-by-Venue" in aviso.texto
    if repone:
        assert len(nuevos) == 1 and aviso.nivel is Nivel.AVISO
    else:
        assert nuevos == [] and aviso.nivel is Nivel.MAXIMO and "A MANO" in aviso.texto
        b.avanzar(3)
        assert b.enviadas(*STOPS, desde=marca) == []


def test_64_salida_cancelada_por_el_mercado_no_se_reenvia_en_bucle(banco: Banco) -> None:
    """Caso d con una SALIDA: el TP que agrega lo cancela el mercado («RT:Cxl-by-Venue»). No se reenvía al momento por
    la misma ruta; a los 60 s pasa UNA vez a su cruce (con su persecución acotada) y el stop sigue cubriendo."""
    b = banco
    abrir_posicion(b)
    tp_ev = salida()
    b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id="tp-venue", evento=tp_ev, momento=tp_ev.momento,
                                   recibida_en=b.ahora())))
    (tp,) = b.enviadas(Proposito.TP_AGREGAR)
    o = b.orden(tp.token)
    marca = b.marca()
    b.libro._ordenes[o.id_das].estado = "Canceled"
    b.dar([f"%OrderAct {o.id_das} Canceled Buy {TICKER} {tp.qty} {tp.precio} {tp.ruta} 09:31:00 RT:Cxl-by-Venue "
           f"{tp.token}"])
    assert o.estado is EstadoOrden.CANCELED and o.notas == "RT:Cxl-by-Venue"
    b.avanzar(5)
    assert not b.enviadas(Proposito.TP_AGREGAR, Proposito.TP_CRUCE, desde=marca)
    b.avanzar(70)
    assert len(b.enviadas(Proposito.TP_CRUCE, desde=marca)) <= 1
    assert not b.enviadas(Proposito.TP_AGREGAR, desde=marca)
    assert sum(x.qty for x in b.enviadas(*STOPS)) >= 50


# ═══════════════════════════════ decisión 65: stop que no se ejecuta ═══════════════════════════════
def _respaldos(b: Banco, desde: int = 0):
    return b.enviadas(Proposito.STOP_RESPALDO, desde=desde)


def test_65_dispara_a_los_5_s_compra_con_el_stop_puesto_y_cancela_al_aceptar(banco: Banco) -> None:
    b = banco
    abrir_posicion(b)
    o = _stop(b)
    _disparar_sin_llenar(b)
    b.avanzar(4)
    assert not _respaldos(b)
    marca = b.marca()
    b.avanzar(1.5)
    (r,) = _respaldos(b)
    # 65 bis: límite = min(último 4,45 × 1,19 = 5,2955 → 5,30, techo 4,00 × 1,50 = 6,00)
    assert (r.lado, r.tipo, r.qty, r.precio, r.ruta) == (Lado.COMPRA, TipoOrden.LIMITE, 100, D("5.30"), "SAGEPRO")
    (aviso,) = _avisos(b.desde(marca), f"stop_sin_ejecutar:{TICKER}")
    assert aviso.nivel is Nivel.MAXIMO and "NO se está ejecutando" in aviso.texto and "4.45" in aviso.texto
    tras = b.desde(marca)
    i_envio = next(i for i, a in enumerate(tras) if isinstance(a, EnviarOrden) and a.orden.token == r.token)
    i_acepta = next(i for i, a in enumerate(tras) if isinstance(a, Anotar) and a.tipo == "stop_respaldo_aceptado")
    i_cancel = next(i for i, a in enumerate(tras) if isinstance(a, Cancelar) and a.token == o.token)
    assert i_envio < i_acepta < i_cancel                                # el stop se cancela tras ACEPTAR la compra
    assert o.estado is EstadoOrden.CANCELED
    b.cotizar(TICKER, "4.40", "4.50", "4.45")
    b.tic_das()
    assert b.pos().neta_fills == 0 and not b.enviadas(Proposito.VENTA_EXCESO)
    b.avanzar(10)
    assert len(_respaldos(b)) == 1 and not b.enviadas(*STOPS, desde=marca)


def test_65_no_dispara_con_fills_del_stop_avanzando(banco: Banco) -> None:
    b = banco
    abrir_posicion(b)
    for _ in range(6):
        b.cotizar(TICKER, "4.40", "4.50", "4.45", tam_ask=10)       # la hija llena 10 en cada tic
        b.avanzar(2)
    assert not _respaldos(b) and b.pos().neta_fills < -30


@pytest.mark.parametrize("como", ["control_humano", "pausar", "cisne_negro"])
def test_65_no_aplica_en_control_humano_pausa_o_cisne_negro(banco: Banco, como: str) -> None:
    b = banco
    abrir_posicion(b)
    if como == "cisne_negro":
        b.cotizar(TICKER, "6.40", "6.50", "6.45", tam_ask=0)       # por encima del límite: R-G-01 (aviso y humano)
        assert b.pos().estado is EstadoTicker.BS
    else:
        b.comando(f"/{como} {TICKER}")
        _disparar_sin_llenar(b)
    b.avanzar(12)
    assert not _respaldos(b)


def test_65_no_aplica_en_halt(banco: Banco) -> None:
    b = banco
    abrir_posicion(b)
    _a_halt(b, ta="H", tat="09:30:30", cot=SIN_LIQUIDEZ)
    b.avanzar(12)
    assert not _respaldos(b)


def test_65_apagada_con_null(cfg: Config, tmp_path: Path) -> None:
    b = Banco(cfg_con(cfg, stops={**cfg.stops, "sin_ejecutar_s": None}), tmp_path)
    b.preparar()
    abrir_posicion(b)
    _disparar_sin_llenar(b)
    b.avanzar(12)
    assert not _respaldos(b)


def test_65_compra_rechazada_el_stop_se_queda(banco: Banco) -> None:
    b = banco
    b.rechazar[Proposito.STOP_RESPALDO] = "Rechazo de prueba"
    abrir_posicion(b)
    o = _stop(b)
    _disparar_sin_llenar(b)
    marca = b.marca()
    b.avanzar(6)
    assert len(_respaldos(b)) == 1
    (aviso,) = _avisos(b.desde(marca), f"stop_respaldo_rechazado:{TICKER}")
    assert aviso.nivel is Nivel.MAXIMO and "Rechazo de prueba" in aviso.texto
    assert not [a for a in b.desde(marca) if isinstance(a, Cancelar) and a.token == o.token]
    assert o.estado in (EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL)
    b.avanzar(20)
    assert len(_respaldos(b)) == 1                                      # una sola vez por episodio


def test_65_resto_sin_llenar_repone_el_stop(banco: Banco) -> None:
    b = banco
    abrir_posicion(b)
    _disparar_sin_llenar(b)
    b.avanzar(6)
    (r,) = _respaldos(b)
    respaldo = b.orden(r.token)
    marca = b.marca()
    b.libro._ordenes[respaldo.id_das].estado = "Canceled"
    b.dar([f"%OrderAct {respaldo.id_das} Canceled Buy {TICKER} 100 {r.precio} {r.ruta} 09:31:00 RT:Cxl-by-client "
           f"{r.token}"])                                               # el humano la quita en DAS sin llenar
    assert anotaciones(b.desde(marca), "stop_respaldo_resto")
    assert [(x.qty, x.stop) for x in b.enviadas(*STOPS, desde=marca)] == [(100, D("4.00"))]
    assert not _respaldos(b, desde=marca)


# ── 64 bis / 65 bis (DAS real 2-oct, tarde): stop MUERTO y respaldo que persigue ──
def _con_topes(b: Banco, broker: str | None = None, mercado: str | None = None) -> None:
    b.das.tope_broker_pct = D(broker) if broker else None
    b.das.tope_mercado_pct = D(mercado) if mercado else None


@pytest.mark.parametrize("broker, mercado, motivo, precios_respaldo", [
    pytest.param("20", None, "CF:LastTrade", ["5.30"], id="hija-rechazada-por-el-broker"),
    # el mercado (tope × 1,10) cancela también la de +19 % (5,30): media banda, 4,45 × 1,095 → 4,88
    pytest.param(None, "10", "R081", ["5.30", "4.88"], id="hija-cancelada-por-el-mercado"),
])
def test_64_bis_stop_muerto_respaldo_al_instante(banco: Banco, broker, mercado, motivo: str,
                                                 precios_respaldo: list) -> None:
    """Casos 1 y 2 reales: el stop dispara (último 4,45) y su hija (límite 6,00) la rechaza el bróker (> último ×
    1,20) o la cancela el mercado (> último × 1,10): stop MUERTO → respaldo AL INSTANTE (sin esperar 5 s), sin
    reponer el stop (R-C-03 no) y la compra cuenta desde ya; luego llena y la posición queda plana."""
    b = banco
    abrir_posicion(b)
    o = _stop(b)
    _con_topes(b, broker, mercado)
    marca = b.marca()
    _disparar_sin_llenar(b)
    assert o.estado in (EstadoOrden.REJECTED, EstadoOrden.CANCELED) and o.id_madre is not None
    (muerto,) = anotaciones(b.desde(marca), "stop_muerto")
    respaldos = _respaldos(b, desde=marca)
    assert [r.precio for r in respaldos] == [D(x) for x in precios_respaldo] and respaldos[-1].qty == 100
    notas = " ".join(str(a.datos.get("notas")) for a in b.desde(marca) if isinstance(a, Anotar)
                     and a.tipo in ("stop_muerto", "stop_muerto_motivo", "orden_act"))
    assert motivo in notas and muerto.datos["id_madre"] == o.id_madre
    assert b.decisor._compras_cierre(TICKER) == 100
    b.avanzar(5)
    assert not b.enviadas(*STOPS, desde=marca) and not anotaciones(b.historial, "stop_reintento")
    assert len(_respaldos(b)) == len(precios_respaldo)
    b.cotizar(TICKER, "4.40", "4.50", "4.45")
    b.tic_das()
    assert b.pos().neta_fills == 0


def test_65_bis_cancelada_por_precio_lejos_reintenta_con_media_banda(banco: Banco) -> None:
    """El mercado cancela la compra de respaldo (R081, tope último × 1,10): se reintenta UNA vez con la mitad de banda
    (4,45 × 1,095 = 4,873 → 4,88) y aviso 2."""
    b = banco
    abrir_posicion(b)
    _disparar_sin_llenar(b)
    _con_topes(b, mercado="10")
    b.avanzar(6)
    precios_ = [r.precio for r in _respaldos(b)]
    assert precios_ == [D("5.30"), D("4.88")]
    assert _avisos(b.historial, f"stop_respaldo_mitad:{TICKER}")[0].nivel is Nivel.AVISO
    assert b.orden(_respaldos(b)[-1].token).estado is EstadoOrden.ACCEPTED


def test_65_bis_rechazada_por_el_broker_reintenta_con_media_banda_una_sola_vez(banco: Banco) -> None:
    """Tope del bróker último × 1,02: la de +19 % y la de +9,5 % son rechazadas («CF:LastTrade»): solo UN reintento y
    después aviso MÁXIMO (el stop se queda: no se canceló porque DAS no aceptó ninguna compra)."""
    b = banco
    abrir_posicion(b)
    o = _stop(b)
    _disparar_sin_llenar(b)
    _con_topes(b, broker="2")
    b.avanzar(8)
    assert [r.precio for r in _respaldos(b)] == [D("5.30"), D("4.88")]
    (aviso,) = _avisos(b.historial, f"stop_respaldo_rechazado:{TICKER}")
    assert aviso.nivel is Nivel.MAXIMO and "CF:LastTrade" in aviso.texto
    assert o.estado in (EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL)          # la hija del stop sigue viva


def test_65_bis_persigue_al_ultimo_hasta_el_techo(cfg: Config, tmp_path: Path) -> None:
    """La compra de respaldo sube a min(último × 1,08, techo) cada segundo; con `stops.techo_pct` 30 el techo es
    5,20; si el último pasa el techo, aviso MÁXIMO y no se persigue más."""
    b = Banco(cfg_con(cfg, stops={**cfg.stops, "techo_pct": 30, "banda_pct": 8}), tmp_path)
    b.preparar()
    abrir_posicion(b)
    _disparar_sin_llenar(b)
    b.avanzar(6)
    (r,) = _respaldos(b)
    assert r.precio == D("4.81")
    b.cotizar(TICKER, "4.55", "4.65", "4.60", tam_ask=0)
    b.avanzar(1.5)
    assert b.orden(r.token).precio == D("4.97")                          # 4,60 × 1,08 = 4,968 → 4,97
    b.cotizar(TICKER, "4.85", "4.95", "4.90", tam_ask=0)
    b.avanzar(1.5)
    assert b.orden(r.token).precio == D("5.20")                          # 4,90 × 1,08 = 5,29 → techo 5,20
    marca = b.marca()
    b.cotizar(TICKER, "5.25", "5.35", "5.30", tam_ask=0)
    b.avanzar(3)
    assert _avisos(b.desde(marca), f"stop_respaldo_techo:{TICKER}")[0].nivel is Nivel.MAXIMO
    assert not [a for a in b.desde(marca) if isinstance(a, Reemplazar) and a.token == r.token]
    assert b.orden(r.token).precio == D("5.20")


def _banco_limite_corto(cfg: Config, tmp_path: Path) -> Banco:
    """Stop con límite +9 % (4,36) y techo del respaldo +50 % (6,00): lo que Jaume pondrá en producción."""
    b = Banco(cfg_con(cfg, stops={**cfg.stops, "limite_pct": 9, "techo_pct": 50}), tmp_path)
    b.preparar()
    abrir_posicion(b)
    return b


def test_65_c_stop_disparado_y_precio_sobre_su_limite_respaldo_al_instante(cfg: Config, tmp_path: Path) -> None:
    """(c) Jaume 2-oct noche: el stop (límite 4,36) dispara y el ask (4,50) está por encima de su límite con acciones
    sin llenar → el respaldo sale AL INSTANTE (sin los 5 s) a min(4,45 × 1,19, 6,00) = 5,30; NO es cisne negro (el
    techo es 6,00); al aceptarse, se cancela la hija del stop; con liquidez llena y queda plana."""
    b = _banco_limite_corto(cfg, tmp_path)
    o = _stop(b)
    assert o.precio == D("4.36")
    marca = b.marca()
    _disparar_sin_llenar(b)
    b.avanzar(0.5)
    (r,) = _respaldos(b, desde=marca)
    assert r.precio == D("5.30") and r.qty == 100
    assert b.pos().estado is not EstadoTicker.BS
    (aviso,) = _avisos(b.desde(marca), f"stop_sin_ejecutar:{TICKER}")
    assert "por encima de su límite 4.36" in aviso.texto and aviso.nivel is Nivel.MAXIMO
    assert o.estado is EstadoOrden.CANCELED and anotaciones(b.desde(marca), "stop_respaldo_aceptado")
    b.cotizar(TICKER, "4.40", "4.50", "4.45")
    b.tic_das()
    assert b.pos().neta_fills == 0


def test_65_c_por_encima_del_techo_es_cisne_negro_sin_respaldo(cfg: Config, tmp_path: Path) -> None:
    b = _banco_limite_corto(cfg, tmp_path)
    b.cotizar(TICKER, "6.40", "6.50", "6.45", tam_ask=0)
    b.tic_das()
    b.avanzar(6)
    assert b.pos().estado is EstadoTicker.BS and not _respaldos(b)


def test_65_bis_hojas_del_cuadro() -> None:
    assert mod_config.validar(_cuadro(stops__banda_pct=4, stops__techo_pct=20)) == []
    assert mod_config.validar(_cuadro(stops__banda_pct=0))
    assert mod_config.validar(_cuadro(stops__techo_pct=None))


def test_64_bis_catalogo_precio_demasiado_lejos() -> None:
    from app.bot_das.reglas import rechazos
    catalogo = rechazos.cargar_catalogo(rechazos.RUTA_CATALOGO)
    for texto in ("RT:CF:LastTrade 19.188000 20.000000 23.940000 15.970000 15.990000 ref#114796[Route#3066]",
                  "RT:Ven: R081: Price Too Far Outside"):
        assert rechazos.clasificar(texto, catalogo).clave == "precio_demasiado_lejos"


def test_simulador_topes_reales_del_broker_y_del_mercado(emp: Emparejador) -> None:
    """Casos 1-3 reales: la hija de un stop SMAT a +50 % la rechaza el bróker (CF:LastTrade), a +19 % la cancela el
    mercado (R081) y a +9 % llena."""
    emp.tope_broker_pct, emp.tope_mercado_pct = D("20"), D("10")
    for token, limite, final in ((127604630, "23.94", EstadoOrden.REJECTED), (127600120, "19", EstadoOrden.CANCELED),
                                 (127600130, "17.4", EstadoOrden.EXECUTED)):
        emp.libro.cotizar("SOFI", D("15.97"), D("15.99"), last=D("15.95"))
        emp.recibir(f"NEWORDER {token} B SOFI SMAT 1 STOPLMTP 15.96 {limite} TIF=DAY+")
        emp.libro.cotizar("SOFI", D("15.97"), D("15.99"), last=D("15.99"))
        msgs = _parsear(emp.tic())
        hijas = [m for m in msgs if isinstance(m, MsgOrden) and m.origoid]
        assert hijas[-1].estado is final, (limite, hijas)
        madre = [m for m in msgs if isinstance(m, MsgOrden) and not m.origoid][-1]
        assert madre.estado is EstadoOrden.TRIGGERED and madre.lvqty == 0


def test_65_llenan_los_dos_venta_del_exceso(banco: Banco) -> None:
    """La compra de respaldo se acepta pero el CANCEL del stop no llega a DAS a tiempo: llenan los dos (200 para 100
    cortas) → cuenta LARGA 100 → la venta del exceso de siempre la deja plana."""
    b = banco
    abrir_posicion(b)
    _disparar_sin_llenar(b)
    o = _stop(b)
    hija = o.id_das
    original = b.das._manejadores["CANCEL"]

    def cancel_mudo(self, p):
        if len(p) == 2 and p[1] == str(hija):
            return []
        return original(p)

    b.das._manejadores["CANCEL"] = types.MethodType(cancel_mudo, b.das)
    b.avanzar(6)
    assert len(_respaldos(b)) == 1
    marca = b.marca()
    b.cotizar(TICKER, "4.40", "4.50", "4.45")
    b.tic_das()
    b.avanzar(3)
    assert b.enviadas(Proposito.VENTA_EXCESO, desde=marca)
    assert b.pos().neta_fills == 0


def test_65_nuevo_episodio_si_baja_del_disparo_y_vuelve(banco: Banco) -> None:
    b = banco
    b.rechazar[Proposito.STOP_RESPALDO] = "Rechazo de prueba"
    abrir_posicion(b)
    _disparar_sin_llenar(b)
    b.avanzar(6)
    assert len(_respaldos(b)) == 1
    b.cotizar(TICKER, "3.80", "3.82", "3.81", tam_ask=0)
    b.avanzar(1)
    _disparar_sin_llenar(b)
    b.avanzar(6)
    assert len(_respaldos(b)) == 2


def test_65_memoria_del_diario_una_vez_por_episodio() -> None:
    def reg(seq: int, **datos) -> Registro:
        return Registro(v=1, seq=seq, t="t", proceso="ejecutor", tipo="stop_sin_ejecutar", datos=datos)
    assert memoria_decisor([reg(1, ticker=TICKER, fase="respaldo")], HOY).sin_ejecutar == {TICKER}
    assert memoria_decisor([reg(1, ticker=TICKER, fase="respaldo"), reg(2, ticker=TICKER, fase="fin")],
                           HOY).sin_ejecutar == set()


# ═══════════════════════════════ decisión 66: rutas de pruebas ═══════════════════════════════
def test_66_slret_de_testsl_ignorado_aunque_sea_mas_barato(cfg: Config, tmp_path: Path) -> None:
    b = Banco(cfg, tmp_path)
    b.preparar(locates=())
    original = b.das._manejadores["SLPRICEINQUIRE"]

    def con_testsl(self, p):
        return [f"%SLRET 1 {p[1]} 0.0001 {p[2]} TESTSL  {CUENTA}"] + original(p)

    b.das._manejadores["SLPRICEINQUIRE"] = types.MethodType(con_testsl, b.das)
    estimacion = [{"strategy_id": SID, "acciones": 1000.0, "riesgo_usd": 300.0}]
    b.procesar(SenalRecibida(Senal(clase="radar", ticker=TICKER, id=None, estimacion=estimacion,
                                   precio_radar=D("3.45"), recibida_en=b.ahora())))
    b.avanzar(1)
    compras = [a for a in b.historial if isinstance(a, LocateComprar)]
    assert compras and all(c.ruta == "LOCSIM" for c in compras)
    assert anotaciones(b.historial, "slret_ruta_excluida")
    assert not [x for x in b.canal.enviadas() if x.startswith("SLNEWORDER") and "TESTSL" in x]


def test_66_red_final_ningun_slneworder_por_ruta_de_pruebas(banco: Banco) -> None:
    salida_ = banco.decisor._finalizar([LocateComprar(TICKER, 100, "testsl", 312345678)])
    assert not [a for a in salida_ if isinstance(a, LocateComprar)]
    assert anotaciones(salida_, "locate_ruta_excluida")


FIXTURE = Path(__file__).parent / "fixtures" / "config_ejemplo.json"


def _cuadro(**cambios) -> dict:
    crudo = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for ruta, valor in cambios.items():
        bloque, *resto = ruta.split("__")
        destino = crudo[bloque]
        for parte in resto[:-1]:
            destino = destino[parte]
        destino[resto[-1]] = valor
    crudo.pop("sha256", None)
    crudo["sha256"] = mod_config.hash_canonico(crudo)
    return crudo


@pytest.mark.parametrize("ruta, valor", [
    ("rutas__stop", "TESTC"), ("rutas__cruzar__ge_1", "SAGETEST"), ("rutas__agregar__lt_1", "sagetestp"),
    ("stops__ruta", "TEST"), ("halts__ruta_reapertura", "TESTSL")])
def test_66_cuadro_con_ruta_de_pruebas_no_carga(ruta: str, valor: str) -> None:
    errores = mod_config.validar(_cuadro(**{ruta: valor}))
    assert any("ruta de PRUEBAS" in e and "decisión 66" in e for e in errores), errores


def test_66_y_65_hojas_opcionales(cfg: Config) -> None:
    assert cfg.locates["rutas_excluidas"] == ["TESTSL"] and cfg.stops["sin_ejecutar_s"] == 5.0
    assert mod_config.validar(_cuadro(stops__sin_ejecutar_s=None)) == []
    assert mod_config.validar(_cuadro(stops__sin_ejecutar_s=0)) == []
    assert mod_config.validar(_cuadro(stops__sin_ejecutar_s=-1))
    assert mod_config.validar(_cuadro(locates__rutas_excluidas=["TESTSL", "OTRA"])) == []
    assert mod_config.validar(_cuadro(locates__rutas_excluidas="TESTSL"))


# ═══════════════════════════════ comprobar_das con lo real ═══════════════════════════════
def test_comprobar_das_paso_3_propone_un_patron_y_paso_5_cancela_la_hija() -> None:
    from app.bot_das.herramientas import comprobar_das as cd
    assert cd.patron_tipo_stop("SLP:24") == "^SLP" and cd.patron_tipo_stop("SLP: 2.97 2.99") == "^SLP"
    p = protocolo.Parser(lambda t: True)
    tok = 126899002
    lineas = [f"%ORDER 2286 {tok} SOFI B L 1 1 0 11.19 SMAT Accepted 05:13:24 0 C U CMDAPI DAY+ N/A",
              f"%ORDER 2287 {tok} SOFI B L 1 1 0 11.19 ARCA Sending 05:13:24 2286 C U CMDAPI DAY+ N/A",
              f"%ORDER 2286 {tok} SOFI B L 1 0 0 11.19 SMAT Triggered 05:13:24 0 C U CMDAPI DAY+ N/A",
              f"%ORDER 2287 {tok} SOFI B L 1 1 0 11.19 ARCA Accepted 05:13:24 2286 C U CMDAPI DAY N/A"]
    viva = cd._orden_viva_por_token([p.parsear(x) for x in lineas], tok)
    assert (viva.id, viva.estado, viva.origoid) == (2287, EstadoOrden.ACCEPTED, 2286)
    sola_madre = cd._orden_viva_por_token([p.parsear(lineas[2])], tok)
    assert sola_madre.id == 2286


# ═══════════════════════════════ decisión 67: /ayuda ═══════════════════════════════
def test_67_ayuda_nombra_todos_los_comandos_de_uso() -> None:
    partes = comandos.partes_ayuda()
    texto = "\n".join(partes)
    agrupados = {n for _g, lista in comandos.AYUDA_GRUPOS for n, _q in lista}
    assert agrupados == set(comandos.USO), set(comandos.USO) ^ agrupados
    for nombre, uso in comandos.USO.items():
        assert comandos._esc(uso) in texto, nombre
    assert "decisión 62" in texto and "Pide «SI»" in texto and "Pide /confirmar ID" in texto
    assert all(comandos._unidades(p) <= comandos.AYUDA_MAX_UNIDADES for p in partes)


def test_67_ayuda_se_parte_en_varios_mensajes_si_no_cabe() -> None:
    partes = comandos.partes_ayuda(maximo=600)
    assert len(partes) > 1 and all(comandos._unidades(p) <= 600 for p in partes)
    assert "\n".join(partes).count("•") == len(comandos.USO)


@pytest.mark.parametrize("texto", ["/ayuda", "/help", "/help@MiBot", "/AYUDA algo"])
def test_67_ayuda_y_help_contestan_sin_ordenes(banco: Banco, texto: str) -> None:
    marca = banco.marca()
    acciones = banco.comando(texto)
    respuestas = [a for a in acciones if isinstance(a, Avisar)]
    assert respuestas and "/cerrar_todo SI" in "".join(a.texto for a in respuestas)
    assert not [a for a in banco.desde(marca) if isinstance(a, (EnviarOrden, Cancelar, Reemplazar))]
