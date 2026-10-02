"""reglas/vigilancia.py: plan B del vigilante (R-C-07, R-C-08), posición sin lote (R-C-10 4), locates (R-H-02/03), margen (2c), corrección 16 y ping (R-J-05)."""
from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from app.bot_das import tokens as mod_tokens
from app.bot_das.reglas import reconciliacion, vigilancia
from app.bot_das.reglas.vigilancia import (
    PETICION_RELANZAR_EJECUTOR, Foto, actualizar_descubierta_desde, comprobar, compras_repetidas, debe_hacer_ping,
    descubiertas_por_ticker, margen_mantenimiento_corto,
)
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    PLAN_B_DESCUBIERTA_S, PLAN_B_LATIDO_S, Anotar, Avisar, Cancelar, Config, Consultar, Cotizacion, EnviarOrden, EstadoBot,
    EstadoLote, EstadoOrden, EstadoTicker, Fase, Grupo, Lado, Lote, MsgOrden, MsgPos, Nivel, Orden, Origen,
    PedirAlSupervisor, PosicionTicker, Programar, Proposito, Reemplazar, Registro, TipoOrden, en_tick,
)

D = Decimal
RUTA_CONFIG = Path(__file__).parent / "fixtures" / "config_ejemplo.json"
HOY = date(2026, 9, 25)
HORA = datetime(2026, 9, 25, 9, 45, tzinfo=ET)
AHORA = 5000.0
X = "XYZ"
RUTA_STOP = "STOP"


@pytest.fixture(scope="module")
def cfg() -> Config:
    crudo = json.loads(RUTA_CONFIG.read_text(encoding="utf-8"))
    claves = ("schema_version", "config_version", "sha256", "motor_hash", "estrategias_hash", "generado_at", "vigilando",
              "horario", "modo_seguridad", "lista_negra", "pausar_entradas", "locates", "entrada", "salidas", "stops",
              "halts", "exclusiones", "rutas", "tecnicos", "alertas_grupo_a")
    return Config(fase=Fase(crudo["fase"]), estrategias={}, cuenta_das="CUENTA_PRUEBA", **{c: crudo[c] for c in claves})


def tok(seq: int, origen: Origen = Origen.EJECUTOR, dia: date = HOY) -> int:
    return mod_tokens.componer(origen, dia.timetuple().tm_yday, seq)


class TokensVigilante:
    """Lo que el proceso vigilante pasa como `tokens`: GeneradorTokens(Origen.VIGILANTE, hoy).siguiente."""

    def __init__(self) -> None:
        self.gen = mod_tokens.GeneradorTokens(Origen.VIGILANTE, HOY)
        self.usados = 0

    def __call__(self) -> int:
        self.usados += 1
        return self.gen.siguiente()


def lote(id_: str = "L1", nivel: Optional[str] = "10", llenas: int = 100,
         estado: EstadoLote = EstadoLote.ABIERTO) -> Lote:
    return Lote(id=id_, strategy_id=f"s-{id_}", estrategia="E", ticker=X, direccion="Short", pedidas=llenas, llenas=llenas,
                nivel_stop=None if nivel is None else D(nivel), estado=estado)


def stop_das(id_das: int, disparo: str, limite: str, qty: int = 100, token: Optional[int] = None,
             estado: EstadoOrden = EstadoOrden.ACCEPTED, order_src: Optional[str] = "CMDAPI", lado: str = "B") -> MsgOrden:
    """%IORDER de una STOPLMTP tal como la ve la conexión watch («SLP: disparo límite», riesgo 1)."""
    return MsgOrden(cruda="%IORDER …", id=id_das, token=tok(id_das) if token is None else token, ticker=X, lado=lado,
                    tipo=f"SLP: {disparo} {limite}", qty=qty, lvqty=qty, cxlqty=0, precio=D(limite), ruta="STOP",
                    estado=estado, hora="09:45:00", origoid=0, cuenta="CUENTA_PRUEBA", trader="T", order_src=order_src,
                    tif="DAY+", pref="N/A", watch=True)


def nivel_das(id_das: int = 11, qty: int = 100, **kw) -> MsgOrden:
    """El stop ÚNICO del nivel 10 (Jaume 29-sep, R-C-01 v4): disparo 10, límite 15."""
    return stop_das(id_das, "10", "15", qty, **kw)


def pos_das(neta: int, ticker: str = X, avg: str = "9.50") -> MsgPos:
    return MsgPos(cruda="%IPOS …", ticker=ticker, tipo=3 if neta < 0 else 2, qty_cruda=abs(neta), neta=neta, avg=D(avg),
                  init_qty=0, init_precio=D("0"), realizado=D("0"), creada="2026/09/25-09:31:00", no_realizado=None, watch=True)


def cot(last: Optional[str] = "9.80", ask: Optional[str] = "9.81", bid: Optional[str] = "9.79", ticker: str = X) -> Cotizacion:
    return Cotizacion(ticker=ticker, bid=None if bid is None else D(bid), ask=None if ask is None else D(ask),
                      last=None if last is None else D(last))


def foto(neta: Optional[int] = -100, ordenes: tuple[MsgOrden, ...] = (), lotes: Optional[list[Lote]] = None,
         latido: Optional[float] = 1.0, cotizacion: Optional[Cotizacion] = None, gasto: str = "0",
         compras: tuple[Registro, ...] = (), equity: Optional[str] = None, **extra) -> Foto:
    return Foto(posiciones={} if neta is None else {X: pos_das(neta)}, ordenes={m.id: m for m in ordenes},
                lotes={X: [lote()] if lotes is None else lotes}, latido_ejecutor_s=latido,
                cotizaciones={X: cotizacion or cot()}, gasto_locates=D(gasto), compras_locate=list(compras),
                equity=None if equity is None else D(equity), **extra)


def de_tipo(lista, clase) -> list:
    return [a for a in lista if isinstance(a, clase)]


def ordenes_de(acc) -> list:
    return [a for a in acc if isinstance(a, (EnviarOrden, Cancelar, Reemplazar))]


def origen(token: int) -> Origen:
    return mod_tokens.descomponer(token)[0]


def anotacion(acc) -> dict:
    notas = [a for a in acc if isinstance(a, Anotar) and a.tipo == "vigilancia"]
    assert len(notas) == 1
    return notas[0].datos


# ── (a) cerrojo ejecutor↔vigilante (R-C-08.2) ────────────────────────────
@pytest.mark.parametrize("desde", [
    pytest.param(None, id="R-C-08-2-recien-descubierta"),
    pytest.param(AHORA - 4.0, id="R-C-08-2-descubierta-4s"),
    pytest.param(AHORA - PLAN_B_DESCUBIERTA_S, id="R-C-08-2-justo-5s-aun-no"),
])
def test_ejecutor_vivo_no_actua_aunque_falte_un_stop(cfg, desde):
    """Plan B: con el ejecutor vivo el vigilante NO pone nada durante los primeros 5 s aunque falte el stop; solo anota."""
    extra = {"descubierta_desde": {X: desde}} if desde is not None else {}
    tokens = TokensVigilante()
    acc = comprobar(foto(**extra), cfg, AHORA, tokens, HORA, RUTA_STOP, True)
    assert ordenes_de(acc) == [] and tokens.usados == 0
    datos = anotacion(acc)
    assert datos["actua"] is False and datos["faltan"] == ["stop B 100 10.00/15.00"]
    assert datos["latido_ejecutor_s"] == 1.0 and datos["descubiertas"] == 100


def test_ejecutor_vivo_actua_pasados_5s_descubierta(cfg):
    """Plan B: la posición lleva > 5 s descubierta con el ejecutor vivo → el vigilante repone (con SU token)."""
    acc = comprobar(foto(descubierta_desde={X: AHORA - 5.01}), cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    nuevas = [a.orden for a in de_tipo(acc, EnviarOrden)]
    assert [(o.proposito, o.qty, origen(o.token)) for o in nuevas] == [(Proposito.STOP, 100, Origen.VIGILANTE)]
    assert anotacion(acc)["actua"] is True


def test_ejecutor_vivo_con_la_posicion_cubierta_no_actua_aunque_sobre_cantidad(cfg):
    """R-C-03: con el stop confirmado (aunque con 150, más de las 100 cortas) la posición NO está descubierta: el ajuste lo
    hace el ejecutor; el vigilante solo lo anota."""
    f = foto(ordenes=(nivel_das(qty=150),), descubierta_desde={X: AHORA - 60})
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    datos = anotacion(acc)
    assert ordenes_de(acc) == [] and datos["faltan"] == [] and datos["ajustes"] == ["reemplazar 11 a 100"]
    assert descubiertas_por_ticker(f, cfg, HOY) == {}


def test_R_C_03_agotado_en_el_ejecutor_el_vigilante_repone_el_stop(cfg):
    """Jaume 29-sep (stop único, test 3): tras 5 rechazos el ejecutor deja de reponer y pasa el ticker a CONTROL HUMANO; la
    posición queda SIN stop. El vigilante no mira ese estado: pasados los 5 s de descubierta con el ejecutor VIVO repone el
    stop con SU token, y sigue intentándolo en cada pasada mientras no se vea aceptado (el eco lo deja a cero)."""
    tokens = TokensVigilante()
    f = foto(descubierta_desde={X: AHORA - 30}, estados_ticker={X: EstadoTicker.CONTROL_HUMANO})
    acc = comprobar(f, cfg, AHORA, tokens, HORA, RUTA_STOP, True)
    nuevas = [a.orden for a in de_tipo(acc, EnviarOrden)]
    assert [(o.proposito, o.stop, o.precio, o.qty, origen(o.token)) for o in nuevas] == [
        (Proposito.STOP, D("10.00"), D("15.00"), 100, Origen.VIGILANTE)]
    assert anotacion(acc)["actua"] is True and descubiertas_por_ticker(f, cfg, HOY) == {X: 100}
    rechazado = foto(ordenes=(stop_das(90, "10", "15", token=nuevas[0].token, estado=EstadoOrden.REJECTED),),
                     descubierta_desde={X: AHORA - 31}, estados_ticker={X: EstadoTicker.CONTROL_HUMANO})
    otra = comprobar(rechazado, cfg, AHORA + 1, tokens, HORA, RUTA_STOP, True)
    assert [a.orden.proposito for a in de_tipo(otra, EnviarOrden)] == [Proposito.STOP]     # lo vuelve a intentar
    eco = foto(ordenes=(stop_das(91, "10", "15", token=nuevas[0].token),), estados_ticker={X: EstadoTicker.CONTROL_HUMANO})
    assert comprobar(eco, cfg, AHORA + 2, tokens, HORA, RUTA_STOP, True) == []


@pytest.mark.parametrize("latido", [
    pytest.param(None, id="R-C-07-plan-B-sin-latido"),
    pytest.param(PLAN_B_LATIDO_S + 0.01, id="R-C-07-plan-B-latido-viejo"),
])
def test_ejecutor_muerto_repone_el_stop_de_cada_nivel_con_origen_vigilante(cfg, latido):
    """R-C-07 plan B FIJADO (v4, Jaume 29-sep): ejecutor caído y posición sin stops → el vigilante pone EL stop de cada nivel
    (disparo en L, límite L + 50 %) con SUS tokens; con dos niveles, dos órdenes (nunca el par de v3)."""
    acc = comprobar(foto(latido=latido), cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    nuevas = [a.orden for a in de_tipo(acc, EnviarOrden)]
    assert [(o.proposito, o.stop, o.precio, o.qty, o.lado, o.tipo, origen(o.token)) for o in nuevas] == [
        (Proposito.STOP, D("10.00"), D("15.00"), 100, Lado.COMPRA, TipoOrden.STOP_LIMITE_PP, Origen.VIGILANTE)]
    dos = comprobar(foto(neta=-100, lotes=[lote(llenas=60), lote("L2", "11", 40)], latido=latido), cfg, AHORA,
                    TokensVigilante(), HORA, RUTA_STOP, True)
    assert [(a.orden.nivel, a.orden.stop, a.orden.precio, a.orden.qty) for a in de_tipo(dos, EnviarOrden)] == [
        (D("10"), D("10.00"), D("15.00"), 60), (D("11"), D("11.00"), D("16.50"), 40)]
    assert all(en_tick(o.stop) and en_tick(o.precio) for o in nuevas)
    assert isinstance(acc[0], Anotar) and acc[0].tipo == "vigilancia"   # write-ahead: la nota va ANTES de las órdenes


def test_latido_justo_en_el_limite_es_ejecutor_vivo(cfg):
    acc = comprobar(foto(latido=PLAN_B_LATIDO_S), cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert ordenes_de(acc) == []


def test_ejecutor_muerto_con_todo_en_orden_no_hace_nada(cfg):
    """Todo cuadra: ni órdenes ni nota (el diario no se llena cada segundo)."""
    acc = comprobar(foto(ordenes=(nivel_das(),), latido=None), cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert acc == []


def test_lo_que_pone_el_vigilante_lo_adopta_el_ejecutor(cfg):
    """R-C-07 neteo: el stop del vigilante, visto por el ejecutor en su reconciliación, satisface el deseado (0 órdenes nuevas)."""
    acc = comprobar(foto(latido=None), cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    vistas = {}
    for i, a in enumerate(de_tipo(acc, EnviarOrden)):
        o = a.orden
        vistas[100 + i] = MsgOrden(cruda="%ORDER …", id=100 + i, token=o.token, ticker=X, lado="B",
                                   tipo=f"SLP: {o.stop} {o.precio}", qty=o.qty, lvqty=o.qty, cxlqty=0, precio=o.precio,
                                   ruta="STOP", estado=EstadoOrden.ACCEPTED, hora="09:45:01", origoid=0,
                                   cuenta="CUENTA_PRUEBA", trader="T", order_src="CMDAPI", tif="DAY+", pref="N/A",
                                   watch=False)
    estado = EstadoBot(fase=Fase.SOMBRA, dia=HOY)
    estado.posiciones[X] = PosicionTicker(ticker=X, lotes={"L1": lote()}, neta_fills=-100)
    ds = reconciliacion.comparar(estado, {X: pos_das(-100)}, vistas, HOY, cfg)
    assert [(d.ticker, d.caso) for d in ds] == [(X, 1)]


# ── (b) sobrantes ────────────────────────────────────────────────────────
def test_dos_stops_del_mismo_nivel_cancela_el_nuevo(cfg):
    """R-C-07 plan B: «sobrantes → cancelar el más nuevo»: dos stops del nivel → Cancelar el de id mayor, nada nuevo."""
    f = foto(ordenes=(nivel_das(12), nivel_das(40, token=tok(3, Origen.VIGILANTE))), latido=None)
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert [(c.id_das, c.token) for c in de_tipo(acc, Cancelar)] == [(40, tok(3, Origen.VIGILANTE))]
    assert not de_tipo(acc, EnviarOrden) and anotacion(acc)["sobran"] == ["cancelar 40"]


def test_stop_con_otra_cantidad_se_reemplaza_sin_temporizadores(cfg):
    """R-C-07: el stop viejo (150) se ajusta a −neta; el `replace_verificar` del ejecutor no sale del vigilante."""
    f = foto(ordenes=(nivel_das(12, qty=150),), latido=None)
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert [(r.id_das, r.qty) for r in de_tipo(acc, Reemplazar)] == [(12, 100)]
    assert not de_tipo(acc, Programar) and not de_tipo(acc, Consultar)


def test_orden_manual_nunca_se_toca(cfg):
    """R-K-02: un stop MANUAL (Montage) en el mismo disparo no cuenta ni se cancela: el vigilante pone el suyo."""
    manual = replace(nivel_das(50, order_src="Montage"), token=None)
    acc = comprobar(foto(ordenes=(manual,), latido=None), cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert not de_tipo(acc, Cancelar)
    assert [(a.orden.proposito, a.orden.qty) for a in de_tipo(acc, EnviarOrden)] == [(Proposito.STOP, 100)]


def test_cisne_negro_no_se_repone(cfg):
    """R-G-03: con el ticker en cisne negro según el diario, el vigilante no repone (el protocolo es del humano)."""
    f = foto(latido=None, estados_ticker={X: EstadoTicker.BS})
    assert ordenes_de(comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)) == []


# ── (c) posición sin lote en ningún diario ───────────────────────────────
def test_posicion_sin_lote_proteccion_y_nivel_3(cfg):
    """R-C-10 (4): posición que no está en ningún diario → STOPLMTP de protección al 25 % del último (límite + 50 %, el del
    stop único) + Avisar(3)."""
    f = foto(neta=-200, lotes=[], latido=None, cotizacion=cot(last="8.00"))
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    proteccion = [a.orden for a in de_tipo(acc, EnviarOrden)]
    assert [(o.proposito, o.lado, o.qty, o.stop, o.precio, o.lote_id, origen(o.token)) for o in proteccion] == [
        (Proposito.STOP_PROTECCION, Lado.COMPRA, 200, D("10.00"), D("15.00"), None, Origen.VIGILANTE)]
    assert [(a.nivel, a.grupo) for a in de_tipo(acc, Avisar)] == [(Nivel.MAXIMO, Grupo.B)]


def test_posicion_sin_lote_con_ejecutor_vivo_la_protege_el_ejecutor(cfg):
    f = foto(neta=-200, lotes=[], latido=1.0)
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert ordenes_de(acc) == [] and not de_tipo(acc, Avisar) and anotacion(acc)["actua"] is False


def test_proteccion_pendiente_no_se_duplica(cfg):
    """Riesgo 11: lo que el vigilante acaba de mandar (aún sin eco por watch) viaja en `pendientes` y cubre."""
    acc = comprobar(foto(neta=-200, lotes=[], latido=None, cotizacion=cot(last="8.00")), cfg, AHORA, TokensVigilante(),
                    HORA, RUTA_STOP, True)
    o = de_tipo(acc, EnviarOrden)[0].orden
    pendiente = Orden(token=o.token, ticker=X, lado=o.lado, tipo=o.tipo, qty=o.qty, precio=o.precio, stop=o.stop,
                      ruta=o.ruta, proposito=o.proposito, lote_id=None, nivel=o.nivel, origen=Origen.VIGILANTE)
    segunda = comprobar(foto(neta=-200, lotes=[], latido=None, pendientes=[pendiente]), cfg, AHORA + 1, TokensVigilante(),
                        HORA, RUTA_STOP, True)
    assert segunda == []


def test_lotes_sin_nivel_se_tratan_como_sin_lote(cfg):
    """A12: si ningún lote tiene nivel válido nadie puede calcular su stop → protección para no dejarla desnuda."""
    f = foto(lotes=[lote(nivel=None)], latido=None, cotizacion=cot(last="8.00"))
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert [a.orden.proposito for a in de_tipo(acc, EnviarOrden)] == [Proposito.STOP_PROTECCION]


def test_sin_precio_avisa_para_ponerla_a_mano(cfg):
    f = Foto(posiciones={X: pos_das(-100, avg="0")}, ordenes={}, lotes={}, latido_ejecutor_s=None, cotizaciones={},
             gasto_locates=D("0"), compras_locate=[], equity=None)
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert not de_tipo(acc, EnviarOrden) and any("A MANO" in a.texto for a in de_tipo(acc, Avisar))


def test_larga_desconocida_proteccion_de_venta(cfg):
    f = foto(neta=100, lotes=[], latido=None, cotizacion=cot(last="8.00"))
    o = de_tipo(comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True), EnviarOrden)[0].orden
    assert (o.lado, o.stop, o.precio, o.qty) == (Lado.VENTA, D("6.00"), D("3.00"), 100)


# ── huérfanas y cuenta larga (R-C-11) ────────────────────────────────────
def test_plana_con_stops_huerfanos_los_cancela_si_el_ejecutor_esta_muerto(cfg):
    f_muerto = foto(neta=0, ordenes=(nivel_das(11), nivel_das(12)), latido=None)
    acc = comprobar(f_muerto, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert sorted(c.id_das for c in de_tipo(acc, Cancelar)) == [11, 12]
    f_vivo = foto(neta=0, ordenes=(nivel_das(11), nivel_das(12)), latido=1.0)
    acc = comprobar(f_vivo, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert ordenes_de(acc) == [] and anotacion(acc)["sobran"] == ["cancelar 11", "cancelar 12"]


def test_cuenta_larga_el_vigilante_no_vende_solo_avisa_y_no_compra_mas(cfg):
    """E2c-02 (antes «el vigilante no vende»): con el ejecutor MUERTO y la cuenta LARGA 20 con lotes cortos, el vigilante
    vende SOLO el exceso (20) con SU token, tras cancelar todas las compras (R-C-11 (3): «ejecutor + vigilante»)."""
    tokens = TokensVigilante()
    acc = comprobar(foto(neta=20, ordenes=(nivel_das(12),), latido=None), cfg, AHORA, tokens, HORA, RUTA_STOP, True)
    ventas = [a.orden for a in de_tipo(acc, EnviarOrden)]
    assert [(o.lado, o.qty, o.proposito, origen(o.token)) for o in ventas] == [
        (Lado.VENTA, 20, Proposito.VENTA_EXCESO, Origen.VIGILANTE)]
    assert ventas[0].precio == D("9.59")                                   # D2a-04: bid 9,79 · (1 − 2 %) abajo
    tipos = [type(a).__name__ for a in acc]
    assert tipos.index("CancelarTicker") < tipos.index("EnviarOrden")       # ninguna compra viva antes de vender
    assert not any(type(a).__name__ in ("Programar", "Consultar", "InvalidarSerie") for a in acc)
    assert any(a.nivel is Nivel.MAXIMO and "VENDER A MANO" in a.texto for a in de_tipo(acc, Avisar))
    assert anotacion(acc)["actua"] is True
    assert acc.index(next(a for a in acc if isinstance(a, Anotar) and a.tipo == "vigilancia")) < tipos.index("EnviarOrden")


def test_E2c_02_con_la_venta_en_marcha_no_vende_otra_vez(cfg):
    """La venta del exceso que el vigilante acaba de mandar (pendiente) se descuenta: nunca vende dos veces."""
    tokens = TokensVigilante()
    primera = comprobar(foto(neta=20, latido=None), cfg, AHORA, tokens, HORA, RUTA_STOP, True)
    venta = de_tipo(primera, EnviarOrden)[0].orden
    pendiente = Orden(token=venta.token, ticker=X, lado=Lado.VENTA, tipo=TipoOrden.LIMITE, qty=venta.qty,
                      precio=venta.precio, stop=None, ruta=venta.ruta, proposito=Proposito.VENTA_EXCESO, lote_id=None,
                      nivel=None, origen=Origen.VIGILANTE, estado=EstadoOrden.SENDING)
    segunda = comprobar(foto(neta=20, latido=None, pendientes=[pendiente]), cfg, AHORA + 1, tokens, HORA, RUTA_STOP, True)
    assert not de_tipo(segunda, EnviarOrden) and tokens.usados == 1


def test_E2c_02_con_el_ejecutor_vivo_no_vende(cfg):
    acc = comprobar(foto(neta=20, ordenes=(nivel_das(12),), latido=1.0), cfg, AHORA, TokensVigilante(), HORA,
                    RUTA_STOP, True)
    assert ordenes_de(acc) == [] and anotacion(acc)["actua"] is False


def test_E2c_02_sin_conexion_de_accion_no_vende_y_pide_relanzar(cfg):
    acc = comprobar(foto(neta=20, latido=None), cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, False)
    assert ordenes_de(acc) == [] and not de_tipo(acc, vigilancia.CancelarTicker)
    assert de_tipo(acc, PedirAlSupervisor) == [PedirAlSupervisor(PETICION_RELANZAR_EJECUTOR)]


# ── E2c-04: con el ejecutor vivo no se anota lo mismo cada segundo ─────────
def test_E2c_04_misma_propuesta_se_anota_una_vez(cfg):
    f = foto(ordenes=(nivel_das(qty=60),))                                  # el stop con 60 de 100; ejecutor vivo
    acc1, firmas = vigilancia.comprobar_con_firmas(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert len([a for a in acc1 if isinstance(a, Anotar) and a.tipo == "vigilancia"]) == 1 and X in firmas
    # pasada siguiente con la firma anterior: nada que anotar (el latido cambia, la propuesta no)
    f2 = replace(foto(ordenes=(nivel_das(qty=60),), latido=1.7), anotado=firmas)
    acc2, firmas2 = vigilancia.comprobar_con_firmas(f2, cfg, AHORA + 1, TokensVigilante(), HORA, RUTA_STOP, True)
    assert not [a for a in acc2 if isinstance(a, Anotar) and a.tipo == "vigilancia"] and firmas2 == firmas
    # cambia la propuesta (ahora falta el stop entero): se anota
    f3 = replace(foto(ordenes=()), anotado=firmas)
    acc3, _ = vigilancia.comprobar_con_firmas(f3, cfg, AHORA + 2, TokensVigilante(), HORA, RUTA_STOP, True)
    assert len([a for a in acc3 if isinstance(a, Anotar) and a.tipo == "vigilancia"]) == 1
    # sin `anotado` (llamador antiguo) se anota como antes, y `comprobar` sigue devolviendo solo las acciones
    assert anotacion(comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True))["firma"] == firmas[X]


def test_E2c_04_lo_que_hace_el_vigilante_se_anota_siempre(cfg):
    """Write-ahead (§8): cuando actúa, se anota antes de sus órdenes aunque la firma sea la misma."""
    f = foto(latido=None)
    _, firmas = vigilancia.comprobar_con_firmas(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    acc = vigilancia.comprobar_con_firmas(replace(f, anotado=firmas), cfg, AHORA + 1, TokensVigilante(), HORA,
                                          RUTA_STOP, True)[0]
    assert de_tipo(acc, EnviarOrden) and anotacion(acc)["actua"] is True


# ── (g) corrección 16: sin conexión de acción ────────────────────────────
def test_puede_enviar_false_pide_relanzar_el_ejecutor(cfg):
    """Corrección 16 / riesgo 31: hay que reponer y no se puede enviar → Avisar(3) + PedirAlSupervisor, sin órdenes."""
    acc = comprobar(foto(latido=None), cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, False)
    assert ordenes_de(acc) == []
    assert de_tipo(acc, PedirAlSupervisor) == [PedirAlSupervisor(PETICION_RELANZAR_EJECUTOR)]
    assert PETICION_RELANZAR_EJECUTOR == "relanzar ejecutor"
    assert any(a.nivel is Nivel.MAXIMO for a in de_tipo(acc, Avisar))
    datos = anotacion(acc)
    assert datos["bloqueado"] is True and datos["actua"] is False and datos["puede_enviar"] is False


def test_puede_enviar_false_sin_nada_que_enviar_no_pide_nada(cfg):
    acc = comprobar(foto(ordenes=(nivel_das(),), latido=1.0), cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, False)
    assert not de_tipo(acc, PedirAlSupervisor)


# ── (d) locates: R-H-02 y R-H-03 ─────────────────────────────────────────
def reg(seq: int, tipo: str, estado: Optional[str] = None, id_das: Optional[int] = None, sid: str = "s1",
        ticker: str = X, dia: date = HOY) -> Registro:
    datos = {"ticker": ticker, "strategy_id": sid}
    if estado is not None:
        datos["estado"] = estado
    if id_das is not None:
        datos["id_das"] = id_das
    return Registro(v=1, seq=seq, t=f"{dia.isoformat()}T09:{10 + seq:02d}:00.000-04:00", proceso="ejecutor", tipo=tipo,
                    datos=datos)


@pytest.mark.parametrize("registros,repetida", [
    pytest.param([reg(1, "locate_intencion"), reg(2, "locate_estado", "Located", 5), reg(3, "locate_estado", "Located", 9)],
                 True, id="R-H-02-dos-Located-una-peticion-deshabilitar"),
    pytest.param([reg(2, "locate_estado", "Located", 5), reg(3, "locate_estado", "Located", 9)],
                 True, id="R-H-02-dos-Located-sin-peticiones"),
    pytest.param([reg(1, "locate_intencion"), reg(2, "locate_estado", "Located", 5), reg(3, "locate_estado", "buscando"),
                  reg(4, "locate_intencion"), reg(5, "locate_estado", "Located", 9)],
                 False, id="R-H-04-parcial-y-segunda-compra-PEDIDA"),
    pytest.param([reg(1, "locate_intencion"), reg(2, "locate_estado", "Located", 5), reg(3, "locate_estado", "Located", 5)],
                 False, id="R-H-02-mismo-Located-actualizado-no-es-compra"),
    pytest.param([reg(1, "locate_intencion"), reg(2, "locate_estado", "Located", 5),
                  reg(3, "locate_estado", "Located", 9, sid="s2")], False, id="R-H-02-otra-estrategia-es-otra-cuenta"),
    pytest.param([reg(1, "locate_estado", "Located", 5, dia=HOY - timedelta(days=1)), reg(2, "locate_estado", "Located", 9)],
                 False, id="R-H-02-el-de-ayer-no-cuenta"),
])
def test_compras_repetidas(registros, repetida):
    assert bool(compras_repetidas(registros, HOY)) is repetida


def test_dos_located_mismo_dia_deshabilita_los_locates(cfg):
    """R-H-02: dos compras Located no pedidas del mismo ticker-estrategia-día → Avisar(3) + Anotar(locates_deshabilitar)."""
    compras = (reg(1, "locate_intencion"), reg(2, "locate_estado", "Located", 5), reg(3, "locate_estado", "Located", 9))
    f = foto(ordenes=(nivel_das(),), compras=compras)
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    avisos = [a for a in de_tipo(acc, Avisar) if a.clave == "vigilante_locates"]
    assert len(avisos) == 1 and avisos[0].nivel is Nivel.MAXIMO
    anotadas = [a for a in de_tipo(acc, Anotar) if a.tipo == "locates_deshabilitar"]
    assert len(anotadas) == 1 and anotadas[0].datos["motivos"] == ["R-H-02"]
    assert anotadas[0].datos["repetidas"] == [{"ticker": X, "strategy_id": "s1", "compras": 2, "pedidas": 1}]
    # ya deshabilitados: no se repite cada segundo
    ya = foto(ordenes=(nivel_das(),), compras=compras, locates_deshabilitados=True)
    assert comprobar(ya, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True) == []


@pytest.mark.parametrize("gasto,equity,deshabilita", [
    pytest.param("250.01", "15000", True, id="R-H-03-gasto-supera-los-250"),
    pytest.param("250", "15000", False, id="R-H-03-justo-250-no-supera"),
    pytest.param("5000", None, True, id="R-H-03-sin-equity-tambien-se-evalua"),
    pytest.param("300", "1000000", True, id="R-H-03-el-equity-ya-no-cuenta"),
])
def test_tope_de_locates_en_dolares(cfg, gasto, equity, deshabilita):
    """Decisión 60 (Jaume 2-oct): la red R-H-03 del vigilante compara con el tope FIJO del cuadro (250 $), sin equity."""
    f = foto(ordenes=(nivel_das(),), gasto=gasto, equity=equity)
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    anotadas = [a for a in de_tipo(acc, Anotar) if a.tipo == "locates_deshabilitar"]
    assert bool(anotadas) is deshabilita
    if deshabilita:
        assert anotadas[0].datos["motivos"] == ["R-H-03"] and D(anotadas[0].datos["tope"]) == D("250")


def test_decision_50_con_el_corte_del_dia_hecho_el_gasto_por_encima_no_dispara_r_h_03(cfg):
    """Decisión 50 (Jaume 1-oct): si el ejecutor ya cortó el día por el tope (`locates_tope_global`), un gasto algo por
    encima es una compra que DAS ya había servido antes de cancelarla: la red R-H-03 del vigilante no repite el aviso
    máximo. R-H-02 (compra repetida no pedida) sigue igual."""
    f = foto(ordenes=(nivel_das(),), gasto="301", equity="15000", locates_tope_dia=True)
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert not [a for a in de_tipo(acc, Anotar) if a.tipo == "locates_deshabilitar"]
    compras = (reg(1, "locate_intencion"), reg(2, "locate_estado", "Located", 5), reg(3, "locate_estado", "Located", 9))
    f2 = foto(ordenes=(nivel_das(),), gasto="301", equity="15000", compras=compras, locates_tope_dia=True)
    anotadas = [a for a in de_tipo(comprobar(f2, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True), Anotar)
                if a.tipo == "locates_deshabilitar"]
    assert len(anotadas) == 1 and anotadas[0].datos["motivos"] == ["R-H-02"]


# ── (e) margen 2c ────────────────────────────────────────────────────────
@pytest.mark.parametrize("precio,qty,esperado", [
    pytest.param("0.50", 1000, "2500", id="2c-menos-de-2-50-son-2-50-por-accion"),
    pytest.param("2.49", 100, "250", id="2c-2-49"),
    pytest.param("2.50", 100, "250", id="2c-2-50-es-el-100pct"),
    pytest.param("4.99", 100, "499", id="2c-4-99-100pct"),
    pytest.param("5.00", 100, "500", id="2c-5-son-5-por-accion"),
    pytest.param("16.66", 100, "500", id="2c-16-66-aun-5-por-accion"),
    pytest.param("16.67", 100, "500.1", id="2c-16-67-es-el-30pct"),
    pytest.param("20", 100, "600", id="2c-20-30pct"),
])
def test_margen_mantenimiento_corto(precio, qty, esperado):
    valor = margen_mantenimiento_corto(D(precio), qty)
    assert type(valor) is Decimal and valor == D(esperado)


def test_margen_igual_que_capital_si_existe():
    """Dos copias de los tramos FINRA (regla de reparto §12): si `reglas.capital` existe, deben dar lo mismo."""
    capital = pytest.importorskip("app.bot_das.reglas.capital")
    for precio in ("0.5", "2.49", "2.5", "4.99", "5", "16.66", "16.67", "30"):
        assert margen_mantenimiento_corto(D(precio), 100) == capital.margen_mantenimiento(D(precio), 100)


@pytest.mark.parametrize("equity,avisa", [
    pytest.param("3000", True, id="2c-margen-2500-supera-0-8-x-3000"),
    pytest.param("3125", False, id="2c-margen-2500-justo-0-8-x-3125-no"),
    pytest.param(None, False, id="2c-sin-equity-no-se-evalua"),
])
def test_aviso_de_margen(cfg, equity, avisa):
    f = Foto(posiciones={X: pos_das(-1000)}, ordenes={}, lotes={X: [lote(llenas=1000, nivel="2.20")]},
             latido_ejecutor_s=1.0, cotizaciones={X: cot(last="2.00", ask="2.01", bid="1.99")}, gasto_locates=D("0"),
             compras_locate=[], equity=None if equity is None else D(equity))
    f = replace(f, ordenes={1: stop_das(1, "2.2", "3.3", 1000)})
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    margen = [a for a in de_tipo(acc, Avisar) if a.clave == "vigilante_margen"]
    assert bool(margen) is avisa and all(a.nivel is Nivel.AVISO for a in margen)


# ── (f) R-C-08 (a): el precio pasó el nivel sin fill → SOLO aviso ────────
def test_precio_paso_el_limite_del_stop_de_un_nivel_solo_avisa(cfg):
    """R-C-08 (a) v4: el ask (15,41) pasó el límite del stop de 10 (15,00) sin fill → aviso 2; el vigilante no cierra."""
    f = foto(ordenes=(nivel_das(),), cotizacion=cot(last="15.40", ask="15.41", bid="15.39"))
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert ordenes_de(acc) == []
    avisos = de_tipo(acc, Avisar)
    assert [(a.nivel, a.clave) for a in avisos] == [(Nivel.AVISO, f"vigilante_nivel:{X}:10")]
    assert "solo avisa" in avisos[0].texto and "stop de 10" in avisos[0].texto


def test_precio_bajo_el_limite_del_stop_no_avisa(cfg):
    """Con el precio entre el disparo (10) y el límite (15) el stop puede llenar: nada que avisar (en v3 el límite era 10,30)."""
    f = foto(ordenes=(nivel_das(),), cotizacion=cot(last="10.40", ask="10.41", bid="10.39"))
    assert not de_tipo(comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True), Avisar)


@pytest.mark.parametrize("latido,estado,avisa_bs", [
    pytest.param(None, EstadoTicker.NORMAL, True, id="R-G-01-ejecutor-muerto-el-vigilante-informa"),
    pytest.param(1.0, EstadoTicker.NORMAL, False, id="R-G-01-ejecutor-vivo-informa-el-ejecutor"),
    pytest.param(None, EstadoTicker.BS, False, id="R-G-01-ya-en-cisne-negro"),
])
def test_cisne_negro_con_el_ejecutor_caido(cfg, latido, estado, avisa_bs):
    """R-C-08 / R-G-01 v4: pasado el límite del stop (15) se asume cisne negro: el vigilante NO cierra, avisa (si nadie más
    lo hace)."""
    f = foto(ordenes=(nivel_das(),), latido=latido, cotizacion=cot(last="17", ask="17.01", bid="16.99"),
             estados_ticker={X: estado})
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert ordenes_de(acc) == []
    assert any(a.clave == f"vigilante_bs:{X}" and a.nivel is Nivel.MAXIMO for a in de_tipo(acc, Avisar)) is avisa_bs


# ── contabilidad de «descubierta desde» ──────────────────────────────────
def test_descubiertas_por_ticker_y_seguimiento(cfg):
    f = foto(ordenes=(nivel_das(qty=60),))
    assert descubiertas_por_ticker(f, cfg, HOY) == {X: 40}
    sending = foto(ordenes=(nivel_das(estado=EstadoOrden.SENDING),))
    assert descubiertas_por_ticker(sending, cfg, HOY) == {X: 100}   # R-C-03: «stop aceptado»; Sending no cubre
    cubierta = foto(ordenes=(nivel_das(),))
    assert descubiertas_por_ticker(cubierta, cfg, HOY) == {}
    desconocida = foto(neta=-50, lotes=[])
    assert descubiertas_por_ticker(desconocida, cfg, HOY) == {X: 50}
    seguimiento = actualizar_descubierta_desde({}, {X: 100}, 10.0)
    assert seguimiento == {X: 10.0}
    seguimiento = actualizar_descubierta_desde(seguimiento, {X: 100, "ABC": 5}, 11.0)
    assert seguimiento == {X: 10.0, "ABC": 11.0}
    assert actualizar_descubierta_desde(seguimiento, {"ABC": 5, X: 0}, 12.0) == {"ABC": 11.0}


def test_posicion_ausente_de_la_foto_no_se_toca(cfg):
    assert comprobar(foto(neta=None, latido=None), cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True) == []


# ── R-J-05: ping externo ─────────────────────────────────────────────────
@pytest.mark.parametrize("watch,latido,ventana,esperado", [
    pytest.param(True, 0.5, True, True, id="R-J-05-todo-bien-pinga"),
    pytest.param(True, PLAN_B_LATIDO_S, True, True, id="R-J-05-latido-en-el-limite-pinga"),
    pytest.param(True, 0.5, False, False, id="R-J-05-fuera-de-ventana-no-se-pinga"),
    pytest.param(False, 0.5, True, False, id="R-J-05-watch-caida-silencio-es-alarma"),
    pytest.param(True, None, True, False, id="R-J-05-sin-latido-del-ejecutor"),
    pytest.param(True, PLAN_B_LATIDO_S + 0.1, True, False, id="R-J-05-ejecutor-colgado"),
    pytest.param(True, -1.0, True, False, id="R-J-05-latido-imposible"),
])
def test_debe_hacer_ping(watch, latido, ventana, esperado):
    assert debe_hacer_ping(watch, latido, ventana) is esperado


def test_debe_hacer_ping_umbral_propio():
    assert debe_hacer_ping(True, 8.0, True, max_latido_s=10.0) is True


# ── pureza ───────────────────────────────────────────────────────────────
def test_modulo_puro_solo_importa_lo_permitido():
    arbol = ast.parse(Path(vigilancia.__file__).read_text(encoding="utf-8"))
    permitidos = {"__future__", "html", "collections.abc", "dataclasses", "datetime", "decimal", "typing",
                  "app.bot_das.reglas", "app.bot_das.reglas.precios", "app.bot_das.tipos"}   # html: D2-08
    modulos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom):
            modulos.add(nodo.module)
        elif isinstance(nodo, ast.Import):
            modulos.update(a.name for a in nodo.names)
    assert modulos <= permitidos, modulos - permitidos
    llamadas = {nodo.func.attr if isinstance(nodo.func, ast.Attribute) else getattr(nodo.func, "id", "")
                for nodo in ast.walk(arbol) if isinstance(nodo, ast.Call)}
    assert not llamadas & {"now", "today", "monotonic", "time", "open", "print", "getenv", "sleep"}


def test_comprobar_no_muta_la_foto(cfg):
    lotes = [lote()]
    f = foto(lotes=lotes, latido=None)
    antes = (lotes[0].llenas, lotes[0].nivel_stop, lotes[0].estado, dict(f.ordenes))
    comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert (lotes[0].llenas, lotes[0].nivel_stop, lotes[0].estado, dict(f.ordenes)) == antes


def test_plan_b_idempotente_tras_el_eco_de_das(cfg):
    """Riesgo 11: lo que el vigilante repuso, devuelto por watch como Accepted, deja la siguiente pasada a cero."""
    tokens = TokensVigilante()
    acc = comprobar(foto(latido=None), cfg, AHORA, tokens, HORA, RUTA_STOP, True)
    eco = tuple(stop_das(200 + i, str(a.orden.stop), str(a.orden.precio), a.orden.qty, token=a.orden.token)
                for i, a in enumerate(de_tipo(acc, EnviarOrden)))
    assert len(eco) == 1                                                      # UN stop por nivel (v4)
    assert comprobar(foto(ordenes=eco, latido=None), cfg, AHORA + 1, tokens, HORA, RUTA_STOP, True) == []


# ── D10 (Jaume 30-sep): el vigilante también se fía del stop del humano ──
def _manual(qty: int) -> MsgOrden:
    return replace(stop_das(60, "10", "10.5", qty=qty, order_src="Montage"), token=None)


def test_D10_sin_lote_con_stop_manual_que_cubre_todo_no_protege_ni_avisa(cfg):
    """D10: posición sin lote (-200) con un stop manual vivo de 200 → ni protección ni aviso, ni con el ejecutor muerto;
    y no cuenta como descubierta para el plan B."""
    f = foto(neta=-200, lotes=[], ordenes=(_manual(200),), latido=None, cotizacion=cot(last="8.00"))
    assert comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True) == []
    assert descubiertas_por_ticker(f, cfg, HOY) == {}


def test_D10_sin_lote_con_stop_manual_que_cubre_parte_avisa_sin_proteger(cfg):
    """D10: el stop manual cubre 120 de 200 → ninguna protección; con el ejecutor muerto, aviso 2 «cubre 120 de 200»;
    con el ejecutor vivo solo se anota (el aviso lo da su reconciliación)."""
    tokens = TokensVigilante()
    muerto = comprobar(foto(neta=-200, lotes=[], ordenes=(_manual(120),), latido=None, cotizacion=cot(last="8.00")),
                       cfg, AHORA, tokens, HORA, RUTA_STOP, True)
    assert not de_tipo(muerto, EnviarOrden) and tokens.usados == 0
    avisos = de_tipo(muerto, Avisar)
    assert [a.nivel for a in avisos] == [Nivel.AVISO] and f"el stop manual de {X} cubre 120 de 200" in avisos[0].texto
    vivo = comprobar(foto(neta=-200, lotes=[], ordenes=(_manual(120),), latido=1.0,
                          descubierta_desde={X: AHORA - 60}), cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert not de_tipo(vivo, EnviarOrden) and not de_tipo(vivo, Avisar) and "D10" in anotacion(vivo)["motivo"]


def test_D10_sin_lote_sin_stop_manual_protege_como_hoy(cfg):
    """D10: sin stop del humano, lo de siempre: protección de 200 + aviso 3."""
    f = foto(neta=-200, lotes=[], latido=None, cotizacion=cot(last="8.00"))
    acc = comprobar(f, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert [(a.orden.proposito, a.orden.qty) for a in de_tipo(acc, EnviarOrden)] == [(Proposito.STOP_PROTECCION, 200)]
