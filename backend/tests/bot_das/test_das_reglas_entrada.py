"""Tests de `app.bot_das.reglas.entrada` (documento §10, fila `test_das_reglas_entrada.py`).

QUÉ HACE. Tabla de los 16 motivos de `evaluar_senal` (una fila por motivo y
sus variantes, con el estado mínimo que dispara SOLO esa comprobación) más
el orden fijo; `t_cierre_vela` contra la fixture `AM_recorte`; la frontera
float → int (`qty_de_evento`); `qty_final`; la máquina de la entrada v3
(`abrir_intento`, `orden_agregar`, `sumar_senal`, `al_vencer`,
`resto_a_cruzar`, `orden_cruce`, `repartir_fill`, `acumular_fill`,
`cerrar_intento`); B13, B19 con SSR, modo de seguridad en los bordes y el
diario degradado.

POR QUÉ ESTÁ AQUÍ. Las reglas de dinero se prueban sin DAS ni reloj: todo
es puro. El `Evento` es el REAL del bot de alertas (misma forma que viaja
picklada) y la config sale de `fixtures/config_ejemplo.json` construida a
mano, así el test no depende de `config.py` (otro lote).

LAS TRAMPAS.
  * Cada fila cambia UNA cosa del escenario base, que da `ok`: si el motivo
    esperado sale, las comprobaciones anteriores pasaron (orden fijo).
  * `ahora` es monotónico (frescura de la cotización) y `ahora_et` aware ET
    (caducidad): el escenario los lleva separados a propósito.
"""
from __future__ import annotations

import ast
import dataclasses
import gzip
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
import pytest

from app.bot_das.reglas import entrada as ent
from app.bot_das.reglas.entrada import (
    MOTIVO_BOT_PAUSADO,
    MOTIVO_CADUCADA,
    MOTIVO_CANCELAR_SUMA,
    MOTIVO_DEGRADADO,
    MOTIVO_DISTANCIA_BID,
    MOTIVO_ESTRATEGIA,
    MOTIVO_EXCLUIDA,
    MOTIVO_FIN_BID_CAYO,
    MOTIVO_FIN_LLENA,
    MOTIVO_FIN_SIN_COTIZACION,
    MOTIVO_HALT,
    MOTIVO_LADO,
    MOTIVO_MODO_SEGURIDAD,
    MOTIVO_NIVEL_STOP, MOTIVO_NIVEL_DISTINTO,
    MOTIVO_OK,
    MOTIVO_REENTRADA,
    MOTIVO_REPETIDA,
    MOTIVO_RETRASO,
    MOTIVO_SIN_ACCIONES,
    MOTIVO_SIN_COTIZACION,
    MOTIVO_TICKER_BLOQUEADO,
    MOTIVOS_EN_ORDEN,
    MOTIVOS_SIN_AVISO,
    Veredicto,
    abrir_intento,
    acumular_fill,
    al_vencer,
    cerrar_intento,
    es_piramide_add,
    es_piramide_reduce,
    evaluar_senal,
    fill_peor_de_lo_permitido,
    nivel_de_senal,
    orden_agregar,
    orden_cruce,
    qty_de_evento,
    qty_final,
    repartir_fill,
    resto_a_cruzar,
    segundos_hasta_limite,
    sumar_senal,
    t_cierre_vela,
)
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    Cancelar,
    Config,
    Cotizacion,
    EstadoBot,
    EstadoLote,
    EstadoSimbolo,
    EstadoTicker,
    EstrategiaConfig,
    Fase,
    FaseIntento,
    IntentoEntrada,
    Lado,
    Locate,
    Lote,
    PosicionTicker,
    Proposito,
    Senal,
    TipoOrden,
    en_tick,
    tick_de,
)
from app.services.bot_alerts_engine import Evento

FIXTURES = Path(__file__).parent / "fixtures"
TICKER = "XYZ"
SID = "prueba-1"
D = Decimal
MOMENTO = pd.Timestamp("2026-09-25 09:30:00")            # naive ET, INICIO de la vela (feed l.177-187)
CIERRE = datetime(2026, 9, 25, 9, 31, tzinfo=ET)         # la vela 09:30 cierra a las 09:31 ET
AHORA_ET = CIERRE + timedelta(milliseconds=500)
AHORA = 5000.0                                           # monotónico
TOKEN = 100_268_001


# ── constructores ──────────────────────────────────────────────────────
def _config_base() -> Config:
    datos = json.loads((FIXTURES / "config_ejemplo.json").read_text(encoding="utf-8"))
    e = datos["estrategias"][0]
    d = e["definition"]
    rm = d["risk_management"]
    estrategia = EstrategiaConfig(
        strategy_id=e["strategy_id"], name=e["name"], origen=e["origen"], ejecutar=e["ejecutar"],
        avisar_grupo_a=e["avisar_grupo_a"], riesgo_usd=D(str(e["riesgo_usd"])), riesgos_piramide=[],
        riesgo_piramide_usd=None, ev_pct=D(str(e["ev_pct"])), ev_rangos=list(e["ev_rangos"]),
        excluir_ipo=e["excluir_ipo"], al_desactivar=e["al_desactivar"], hora_fin_sesion=d["custom_end_time"],
        ventana_entradas=list(d["entry_logic"]["entry_time_windows"]), hora_salida=None,
        accept_reentries=rm["accept_reentries"], max_reentries=rm["max_reentries"],
        niveles_piramide=list(d["pyramiding"]["levels"]), es_rth=False,
        definition_hash=e["definition_hash"], definition=d,
    )
    return Config(
        schema_version=datos["schema_version"], config_version=datos["config_version"], sha256=datos["sha256"],
        motor_hash=datos["motor_hash"], estrategias_hash=datos["estrategias_hash"],
        generado_at=datos["generado_at"], fase=Fase(datos["fase"]), vigilando=datos["vigilando"],
        horario=datos["horario"], modo_seguridad=datos["modo_seguridad"], lista_negra=datos["lista_negra"],
        pausar_entradas=datos["pausar_entradas"], locates=datos["locates"], entrada=datos["entrada"],
        salidas=datos["salidas"], stops=datos["stops"], halts=datos["halts"], exclusiones=datos["exclusiones"],
        rutas=datos["rutas"], tecnicos=datos["tecnicos"], alertas_grupo_a=datos["alertas_grupo_a"],
        estrategias={estrategia.strategy_id: estrategia}, cuenta_das="CUENTA_PRUEBA",
    )


def _evento(**cambios) -> Evento:
    base = dict(tipo="entrada", ticker=TICKER, strategy_id=SID, estrategia="PM (A) prueba", momento=MOMENTO,
                precio=3.45, direccion="Short", acciones=1200.0, stop=3.80, distancia_stop=0.35, riesgo_usd=300.0)
    base.update(cambios)
    return Evento(**base)


def _senal(evento: Optional[Evento] = None, **cambios) -> Senal:
    ev = evento if evento is not None else _evento()
    base = dict(clase="evento", ticker=ev.ticker, id=f"{ev.ticker}|{ev.strategy_id}|2026-09-25 09:30:00|entrada",
                evento=ev, momento=ev.momento, recibida_en=AHORA, origen="grabacion")
    base.update(cambios)
    return Senal(**base)


def _cot(bid="3.44", ask="3.46", last="3.45", volumen: Optional[int] = 1_000_000, vwap="3.40",
         edad: Optional[float] = 0.2, ticker: str = TICKER) -> Cotizacion:
    return Cotizacion(ticker=ticker, bid=None if bid is None else D(bid), ask=None if ask is None else D(ask),
                      last=None if last is None else D(last), volumen=volumen,
                      vwap=None if vwap is None else D(vwap),
                      actualizada_en=None if edad is None else AHORA - edad)


def _lote(id_: str, pedidas: int, **kw) -> Lote:
    base = dict(id=id_, strategy_id=SID, estrategia="PM (A) prueba", ticker=TICKER, direccion="Short",
                pedidas=pedidas)
    base.update(kw)
    return Lote(**base)


def _intento(**cambios) -> IntentoEntrada:
    base = dict(ticker=TICKER, lotes=["a", "b"], qty_total=1000, bid_senal=D("10.00"), ask_senal=D("10.04"),
                precio_senal=D("10.02"), t_cierre_vela=CIERRE.timestamp(), t_limite=CIERRE.timestamp() + 60,
                cfg_congelada=dict(_config_base().entrada))
    base.update(cambios)
    return IntentoEntrada(**base)


@dataclasses.dataclass
class Escenario:
    """Una señal que ENTRA: cada test cambia una sola cosa."""
    estado: EstadoBot
    cfg: Config
    senal: Senal
    cot: Optional[Cotizacion]
    simb: EstadoSimbolo
    exclusion: Optional[str] = None
    franja: str = "RTH"
    ahora: float = AHORA
    ahora_et: datetime = AHORA_ET
    diario_degradado: bool = False
    es_reapertura: bool = False

    def evaluar(self) -> Veredicto:
        return evaluar_senal(self.estado, self.cfg, self.senal, self.cot, self.simb, self.exclusion, self.franja,
                             self.ahora, self.ahora_et, self.diario_degradado, es_reapertura=self.es_reapertura)

    def pos(self) -> PosicionTicker:
        return self.estado.posiciones.setdefault(TICKER, PosicionTicker(ticker=TICKER))

    def evento(self, **cambios) -> None:
        self.senal = dataclasses.replace(self.senal, evento=dataclasses.replace(self.senal.evento, **cambios))

    def estrategia(self, **cambios) -> None:
        nueva = dataclasses.replace(self.cfg.estrategias[SID], **cambios)
        self.cfg = dataclasses.replace(self.cfg, estrategias={SID: nueva})

    def bloque(self, nombre: str, **cambios) -> None:
        self.cfg = dataclasses.replace(self.cfg, **{nombre: {**getattr(self.cfg, nombre), **cambios}})

    def config(self, **cambios) -> None:
        self.cfg = dataclasses.replace(self.cfg, **cambios)

    def lote_previo(self, id_: str, **kw) -> Lote:
        base = dict(llenas=1200, precio_medio=D("3.40"), nivel_stop=D("3.80"), estado=EstadoLote.CERRADO,
                    version_estrategia=self.cfg.estrategias[SID].definition_hash)
        base.update(kw)
        lote = _lote(id_, 1200, **base)
        self.pos().lotes[id_] = lote
        return lote


def _escenario() -> Escenario:
    estado = EstadoBot(fase=Fase.SOMBRA, dia=date(2026, 9, 25))
    estado.locates[(TICKER, SID)] = Locate(ticker=TICKER, strategy_id=SID, pedidas=1200, localizadas=1200,
                                           estado="hecho")
    return Escenario(estado=estado, cfg=_config_base(), senal=_senal(), cot=_cot(), simb=EstadoSimbolo(ticker=TICKER))


@pytest.fixture
def esc() -> Escenario:
    return _escenario()


# ── evaluar_senal: escenario base y tabla de los 16 motivos ─────────────
def test_escenario_base_entra_con_todas_las_acciones(esc: Escenario) -> None:
    assert esc.evaluar() == Veredicto(ok=True, motivo=MOTIVO_OK, qty=1200)


def test_motivos_son_17_distintos_y_en_el_orden_del_documento() -> None:
    assert len(MOTIVOS_EN_ORDEN) == 17
    assert len(set(MOTIVOS_EN_ORDEN)) == 17
    assert MOTIVO_OK not in MOTIVOS_EN_ORDEN
    assert MOTIVOS_EN_ORDEN == (
        MOTIVO_REPETIDA, MOTIVO_BOT_PAUSADO, MOTIVO_ESTRATEGIA, MOTIVO_TICKER_BLOQUEADO, MOTIVO_LADO,
        MOTIVO_EXCLUIDA, MOTIVO_HALT, MOTIVO_SIN_COTIZACION, MOTIVO_MODO_SEGURIDAD, MOTIVO_RETRASO,
        MOTIVO_DISTANCIA_BID, MOTIVO_NIVEL_STOP, MOTIVO_NIVEL_DISTINTO, MOTIVO_CADUCADA, MOTIVO_REENTRADA,
        MOTIVO_DEGRADADO, MOTIVO_SIN_ACCIONES,
    )


def _pausa_ticker(estado_ticker: EstadoTicker) -> Callable[[Escenario], None]:
    def cambio(e: Escenario) -> None:
        e.pos().estado = estado_ticker
    return cambio


def _cambiar_cot(**campos) -> Callable[[Escenario], None]:
    def cambio(e: Escenario) -> None:
        for nombre, valor in campos.items():
            setattr(e.cot, nombre, valor)
    return cambio


def _lote_vivo_misma_estrategia(e: Escenario) -> None:
    e.lote_previo("base-viva", estado=EstadoLote.ABIERTO)


def _solo_locate_de_otra(e: Escenario, *, ticker: str = TICKER, pedidas: int = 1200, localizadas: int = 5000,
                         usadas: int = 0, estado_loc: str = "hecho") -> None:
    """E9 (D1-02, G1A-07): la estrategia de la señal NO tiene locate propio; otra estrategia sí."""
    e.estado.locates.clear()
    e.estado.locates[(ticker, "otra")] = Locate(ticker=ticker, strategy_id="otra", pedidas=pedidas,
                                                localizadas=localizadas, usadas=usadas, estado=estado_loc)


def _encender_b20bis(e: Escenario, pct: float = 5.0) -> None:
    """Decisión 11 (Jaume 30-sep): B20 bis APAGADA por defecto; los tests de la 11 la encienden con un número."""
    e.bloque("entrada", distancia_max_ultimo_bid_pct=pct)


# (id que cita la regla, cambio sobre el escenario base, motivo esperado)
FILAS_MOTIVOS: list[tuple[str, Callable[[Escenario], None], str]] = [
    ("1-R-A-05-repetida", lambda e: e.estado.senales_vistas.add(e.senal.id), MOTIVO_REPETIDA),
    ("2-R-M-03-no-vigilando", lambda e: setattr(e.estado, "vigilando", False), MOTIVO_BOT_PAUSADO),
    ("2-R-M-03-cuadro-no-vigilando", lambda e: e.config(vigilando=False), MOTIVO_BOT_PAUSADO),
    ("2-R-M-03-pausa-global", lambda e: setattr(e.estado, "pausa_global", True), MOTIVO_BOT_PAUSADO),
    ("2-R-D-02-control-humano", lambda e: setattr(e.estado, "control_humano", True), MOTIVO_BOT_PAUSADO),
    ("2-R-M-04-pausar-entradas", lambda e: e.config(pausar_entradas=True), MOTIVO_BOT_PAUSADO),
    ("3-CM2-estrategia-ausente", lambda e: e.evento(strategy_id="otra"), MOTIVO_ESTRATEGIA),
    ("3-CM2-ejecutar-false", lambda e: e.estrategia(ejecutar=False), MOTIVO_ESTRATEGIA),
    ("3-multicuenta-otra-cuenta", lambda e: e.evento(cuenta="OTRA"), MOTIVO_ESTRATEGIA),
    ("4-R-B-07-pausado", _pausa_ticker(EstadoTicker.PAUSADO), MOTIVO_TICKER_BLOQUEADO),
    ("4-R-G-03-cisne-negro", _pausa_ticker(EstadoTicker.BS), MOTIVO_TICKER_BLOQUEADO),
    ("4-A7-sin-simbolo", _pausa_ticker(EstadoTicker.SIN_SIMBOLO), MOTIVO_TICKER_BLOQUEADO),
    ("4-R-D-02-control-humano-ticker", _pausa_ticker(EstadoTicker.CONTROL_HUMANO), MOTIVO_TICKER_BLOQUEADO),
    ("5-R-E-01-largo-sin-posicion", lambda e: e.evento(direccion="Long"), MOTIVO_LADO),
    ("5-R-E-01-largo-con-corto-vivo",
     lambda e: (e.lote_previo("otro", strategy_id="otra", estado=EstadoLote.ABIERTO), e.evento(direccion="Long")),
     MOTIVO_LADO),
    ("5-R-E-01-corto-con-lote-largo",
     lambda e: e.lote_previo("largo", strategy_id="otra", direccion="Long", estado=EstadoLote.ABIERTO), MOTIVO_LADO),
    ("5-R-E-01-corto-con-neta-larga", lambda e: setattr(e.pos(), "neta_fills", 20), MOTIVO_LADO),
    ("6-R-A-03-spac", lambda e: setattr(e, "exclusion", "spac"), MOTIVO_EXCLUIDA),
    ("6-A12-sin-ficha", lambda e: setattr(e, "exclusion", "sin_ficha"), MOTIVO_EXCLUIDA),
    ("7-R-F-04b-halt-H", lambda e: setattr(e.simb, "ta", "H"), MOTIVO_HALT),
    ("7-R-F-04b-pausa-P", lambda e: setattr(e.simb, "ta", "P"), MOTIVO_HALT),
    ("7-B18-ticker-en-halt", _pausa_ticker(EstadoTicker.HALT), MOTIVO_HALT),
    ("8-R-B-01-sin-cotizacion", lambda e: setattr(e, "cot", None), MOTIVO_SIN_COTIZACION),
    ("8-R-B-01-sin-bid", _cambiar_cot(bid=None), MOTIVO_SIN_COTIZACION),
    ("8-R-B-01-sin-ask", _cambiar_cot(ask=None), MOTIVO_SIN_COTIZACION),
    ("8-R-B-01-sin-ultimo", _cambiar_cot(last=None), MOTIVO_SIN_COTIZACION),
    ("8-R-B-01-bid-cero", _cambiar_cot(bid=D("0")), MOTIVO_SIN_COTIZACION),
    ("8-R-B-01-libro-cruzado", _cambiar_cot(bid=D("3.47")), MOTIVO_SIN_COTIZACION),
    ("8-R-B-01-vieja", _cambiar_cot(actualizada_en=AHORA - 5.001), MOTIVO_SIN_COTIZACION),
    ("8-R-B-01-sin-marca", _cambiar_cot(actualizada_en=None), MOTIVO_SIN_COTIZACION),
    ("9-R-I-04-modo-seguridad", lambda e: e.bloque("modo_seguridad", activo=True), MOTIVO_MODO_SEGURIDAD),
    ("10-R-A-01-ultimo-arriba", _cambiar_cot(last=D("3.49"), ask=D("3.50")), MOTIVO_RETRASO),
    ("10-R-A-01-ultimo-abajo", _cambiar_cot(last=D("3.41"), bid=D("3.40")), MOTIVO_RETRASO),
    ("11-B20bis-bid-lejos", lambda e: (_encender_b20bis(e), _cambiar_cot(bid=D("3.27"))(e)), MOTIVO_DISTANCIA_BID),
    ("12-A12-sin-stop", lambda e: e.evento(stop=None), MOTIVO_NIVEL_STOP),
    ("12b-otro-nivel-vivo", lambda e: e.lote_previo("otra", strategy_id="otra", estado=EstadoLote.ABIERTO, nivel_stop=D("4.50")),
     MOTIVO_NIVEL_DISTINTO),
    ("12-A12-stop-nan", lambda e: e.evento(stop=float("nan")), MOTIVO_NIVEL_STOP),
    ("12-R-C-09-stop-igual-ultimo", lambda e: e.evento(stop=3.45), MOTIVO_NIVEL_STOP),
    ("12-R-C-09-stop-bajo-ultimo", lambda e: e.evento(stop=3.30), MOTIVO_NIVEL_STOP),
    ("13-R-B-04-caducada", lambda e: setattr(e, "ahora_et", CIERRE + timedelta(seconds=60, milliseconds=1)),
     MOTIVO_CADUCADA),
    ("14-R-G-03-sin-reentrada-hasta-sigue", lambda e: setattr(e.pos(), "sin_reentrada_hasta_sigue", True),
     MOTIVO_REENTRADA),
    ("14-R-D-04-accept-false", lambda e: (e.lote_previo("previa"), e.estrategia(accept_reentries=False)),
     MOTIVO_REENTRADA),
    ("14-R-D-04-max-0", lambda e: (e.lote_previo("previa"), e.estrategia(max_reentries=0)), MOTIVO_REENTRADA),
    ("14-R-D-04-lote-base-vivo", _lote_vivo_misma_estrategia, MOTIVO_REENTRADA),
    ("14-R-E-03-version-vieja-viva",
     lambda e: e.lote_previo("vieja", estado=EstadoLote.ABIERTO, version_estrategia="sha256:vieja"),
     MOTIVO_REENTRADA),
    ("14-R-E-03-version-vieja-esperar-fin-dia",
     lambda e: e.lote_previo("vieja", version_estrategia="sha256:vieja"), MOTIVO_REENTRADA),
    ("15-correccion4-diario-degradado", lambda e: setattr(e, "diario_degradado", True), MOTIVO_DEGRADADO),
    ("15-R-J-03-feed", lambda e: e.estado.modo_degradado.add("feed"), MOTIVO_DEGRADADO),
    ("15-R-J-03-das", lambda e: e.estado.modo_degradado.add("das"), MOTIVO_DEGRADADO),
    ("15-R-K-03-reconciliacion", lambda e: e.estado.modo_degradado.add("reconciliacion"), MOTIVO_DEGRADADO),
    ("16-R-H-04-sin-locate", lambda e: e.estado.locates.clear(), MOTIVO_SIN_ACCIONES),
    ("16-R-H-04-locates-gastados", lambda e: setattr(e.estado.locates[(TICKER, SID)], "usadas", 1200),
     MOTIVO_SIN_ACCIONES),
    ("16-E9-D1-02-otra-sin-sobrante", lambda e: _solo_locate_de_otra(e, pedidas=1200, localizadas=1200),
     MOTIVO_SIN_ACCIONES),
    ("16-E9-D1-02-locate-de-otro-ticker", lambda e: _solo_locate_de_otra(e, ticker="OTRO", localizadas=5000),
     MOTIVO_SIN_ACCIONES),
    ("16-acciones-none", lambda e: e.evento(acciones=None), MOTIVO_SIN_ACCIONES),
    ("16-acciones-0.4", lambda e: e.evento(acciones=0.4), MOTIVO_SIN_ACCIONES),
]


@pytest.mark.parametrize("cambio, motivo", [(c, m) for _, c, m in FILAS_MOTIVOS],
                         ids=[i for i, _, _ in FILAS_MOTIVOS])
def test_evaluar_senal_un_motivo_por_fila(esc: Escenario, cambio, motivo: str) -> None:
    cambio(esc)
    v = esc.evaluar()
    assert not v.ok
    assert v.motivo == motivo
    assert v.qty == 0
    assert v.guardar_para_reapertura is (motivo == MOTIVO_HALT)
    assert v.avisar is (motivo not in MOTIVOS_SIN_AVISO)


def test_las_filas_cubren_los_17_motivos() -> None:
    assert {m for _, _, m in FILAS_MOTIVOS} == set(MOTIVOS_EN_ORDEN)


# Un cambio por comprobación, compatibles entre sí: aplicando del i-ésimo al último, gana el i-ésimo.
CAMBIO_POR_COMPROBACION: list[Callable[[Escenario], None]] = [
    lambda e: e.estado.senales_vistas.add(e.senal.id),
    lambda e: setattr(e.estado, "vigilando", False),
    lambda e: e.estrategia(ejecutar=False),
    _pausa_ticker(EstadoTicker.PAUSADO),
    lambda e: e.evento(direccion="Long"),
    lambda e: setattr(e, "exclusion", "spac"),
    lambda e: setattr(e.simb, "ta", "H"),
    lambda e: setattr(e.cot, "actualizada_en", AHORA - 60),
    lambda e: e.bloque("modo_seguridad", activo=True),
    lambda e: setattr(e.cot, "last", D("3.50")),
    lambda e: (_encender_b20bis(e), setattr(e.cot, "bid", D("3.20"))),
    lambda e: e.evento(stop=None),
    lambda e: e.lote_previo("otra", strategy_id="otra", estado=EstadoLote.ABIERTO, nivel_stop=D("4.50")),
    lambda e: setattr(e, "ahora_et", CIERRE + timedelta(seconds=120)),
    lambda e: setattr(e.pos(), "sin_reentrada_hasta_sigue", True),
    lambda e: setattr(e, "diario_degradado", True),
    lambda e: e.estado.locates.clear(),
]


@pytest.mark.parametrize("i", range(17), ids=[f"orden-fijo-{i + 1}" for i in range(17)])
def test_orden_fijo_la_primera_que_falla_decide(i: int) -> None:
    e = _escenario()
    for cambio in CAMBIO_POR_COMPROBACION[i:]:
        cambio(e)
    assert e.evaluar().motivo == MOTIVOS_EN_ORDEN[i]


@pytest.mark.parametrize("i", range(17), ids=[f"solo-{i + 1}" for i in range(17)])
def test_cada_cambio_solo_dispara_su_comprobacion(i: int) -> None:
    e = _escenario()
    CAMBIO_POR_COMPROBACION[i](e)
    assert e.evaluar().motivo == MOTIVOS_EN_ORDEN[i]


# ── bordes de cada comprobación ────────────────────────────────────────
@pytest.mark.parametrize("last, dolares, entra", [
    ("4.99", 2_000_000, False),
    ("5.00", 2_000_000, True),
    ("5.00", 1_990_000, False),
    ("5.00", 2_000_000, True),
], ids=["R-I-04-4,99$", "R-I-04-5,00$", "R-I-04-1,99M$", "R-I-04-2,00M$"])
def test_modo_seguridad_bordes(esc: Escenario, last: str, dolares: int, entra: bool) -> None:
    esc.bloque("modo_seguridad", activo=True)
    esc.evento(precio=float(last), stop=5.60)
    esc.cot = _cot(bid="4.98", ask="5.01", last=last, volumen=dolares // 5, vwap="5.00")
    v = esc.evaluar()
    assert v.ok is entra
    assert v.motivo == (MOTIVO_OK if entra else MOTIVO_MODO_SEGURIDAD)


@pytest.mark.parametrize("volumen, vwap", [(None, "5.00"), (400_000, None), (400_000, "0")],
                         ids=["R-I-04-sin-volumen", "R-I-04-sin-vwap", "R-I-04-vwap-cero"])
def test_modo_seguridad_sin_dato_no_entra(esc: Escenario, volumen, vwap) -> None:
    esc.bloque("modo_seguridad", activo=True)
    esc.evento(precio=6.0, stop=6.60)
    esc.cot = _cot(bid="5.99", ask="6.01", last="6.00", volumen=volumen, vwap=vwap)
    assert esc.evaluar().motivo == MOTIVO_MODO_SEGURIDAD


def test_modo_seguridad_apagado_no_filtra(esc: Escenario) -> None:
    esc.cot = _cot(volumen=None, vwap=None)
    assert esc.evaluar().ok


@pytest.mark.parametrize("last, entra", [("3.4845", True), ("3.4155", True), ("3.4846", False)],
                         ids=["R-A-01-1%-exacto-arriba", "R-A-01-1%-exacto-abajo", "R-A-01-pasado"])
def test_retraso_borde_del_1_por_ciento(esc: Escenario, last: str, entra: bool) -> None:
    esc.cot = _cot(bid="3.41", ask="3.49", last=last)
    assert esc.evaluar().ok is entra


@pytest.mark.parametrize("valor", [None, "ausente"], ids=["D1-09-null-es-el-defecto", "D1-09-ausente-es-el-defecto"])
def test_D1_09_retraso_null_no_apaga_el_filtro(esc: Escenario, valor) -> None:
    """D1-09: `retraso_max_senal_pct` null (config «num?») o ausente = 1 % del libro; R-A-01 no se apaga en silencio."""
    if valor == "ausente":
        esc.cfg = dataclasses.replace(esc.cfg, entrada={k: v for k, v in esc.cfg.entrada.items()
                                                        if k != "retraso_max_senal_pct"})
    else:
        esc.bloque("entrada", retraso_max_senal_pct=None)
    esc.cot = _cot(bid="3.41", ask="3.49", last="3.4845")          # +1 % exacto: pasa
    assert esc.evaluar().ok
    esc.cot = _cot(bid="3.41", ask="3.49", last="3.4846")          # un pelo más: descarta
    assert esc.evaluar().motivo == MOTIVO_RETRASO
    esc.bloque("entrada", retraso_max_senal_pct=2.0)               # un número sí cambia el umbral
    assert esc.evaluar().ok


def test_D1_03_reapertura_salta_el_retraso(esc: Escenario) -> None:
    """D1-03 (R-F-04 b): en la reapertura el último está a +4 % del precio de ANTES del halt y la señal entra.

    El filtro de la reapertura es `halts.senal_guardada_valida` (primera vela
    < X %); la 10 (R-A-01) es para el retraso del bot o del feed. Fuera de la
    reapertura, la misma cotización se descarta por retraso.
    """
    esc.cot = _cot(bid="3.58", ask="3.60", last="3.59")            # señal a 3,45, stop 3,80: +4,06 %
    esc.ahora_et = CIERRE + timedelta(minutes=7)                   # reabre ~minuto después de un LULD de 5 min
    esc.es_reapertura = True
    assert esc.evaluar() == Veredicto(ok=True, motivo=MOTIVO_OK, qty=1200)
    esc.es_reapertura = False
    esc.ahora_et = AHORA_ET
    assert esc.evaluar().motivo == MOTIVO_RETRASO


def test_D1_03_reapertura_mantiene_las_demas_comprobaciones(esc: Escenario) -> None:
    """D1-03: saltar la 10 no salta la 11 (B20 bis) ni la 12 (nivel del stop sobre el último)."""
    _encender_b20bis(esc)                                          # decisión 11: apagada por defecto; aquí, encendida
    esc.es_reapertura = True
    esc.ahora_et = CIERRE + timedelta(minutes=7)
    esc.cot = _cot(bid="3.40", ask="3.90", last="3.85")            # stop 3,80 ≤ último 3,85 y bid a −11,7 %
    assert esc.evaluar().motivo == MOTIVO_DISTANCIA_BID
    esc.cot = _cot(bid="3.84", ask="3.86", last="3.85")
    assert esc.evaluar().motivo == MOTIVO_NIVEL_STOP


def test_D1_12_frescura_por_defecto_es_la_constante_de_tipos() -> None:
    """D1-12: la comprobación 8 usa `tipos.COTIZACION_FRESCA_MAX_S` (la misma que mercado_das), no un 5.0 suelto."""
    import inspect
    from app.bot_das import tipos
    defecto = inspect.signature(evaluar_senal).parameters["max_edad_cot_s"].default
    assert defecto is tipos.COTIZACION_FRESCA_MAX_S


def test_D1_12_frescura_borde(esc: Escenario) -> None:
    from app.bot_das.tipos import COTIZACION_FRESCA_MAX_S
    esc.cot = _cot(edad=COTIZACION_FRESCA_MAX_S)                    # justo en el límite: vale
    assert esc.evaluar().ok
    esc.cot = _cot(edad=COTIZACION_FRESCA_MAX_S + 0.001)
    assert esc.evaluar().motivo == MOTIVO_SIN_COTIZACION


def test_b20bis_borde_exacto_pasa_y_null_la_apaga(esc: Escenario) -> None:
    _encender_b20bis(esc)                                          # con número sigue descartando (decisión 11)
    esc.cot = _cot(bid="3.2775", ask="3.46", last="3.45")          # (3,45 − 3,2775) / 3,45 = 5 % exacto
    assert esc.evaluar().ok
    esc.cot = _cot(bid="3.27", ask="3.46", last="3.45")
    assert esc.evaluar().motivo == MOTIVO_DISTANCIA_BID
    esc.bloque("entrada", distancia_max_ultimo_bid_pct=None)       # null = apagada (decisión 11, Jaume 30-sep)
    assert esc.evaluar().ok


@pytest.mark.parametrize("valor", [None, "ausente"], ids=["decision-11-null", "decision-11-ausente"])
def test_decision_11_b20bis_apagada_por_defecto(esc: Escenario, valor) -> None:
    """Decisión 11 (Jaume 30-sep: «la quito porque ya tenemos el 3 %»): la guarda B20 bis arranca APAGADA.

    La fixture trae `null` y el defecto del libro (`tipos.ENTRADA_DISTANCIA_ULTIMO_BID_PCT`) es None: un bid
    a −11 % del último ya no descarta por la 11; el filtro de dinero es el tope del 3 % de la entrada v3.
    """
    from app.bot_das import tipos
    assert tipos.ENTRADA_DISTANCIA_ULTIMO_BID_PCT is None
    assert esc.cfg.entrada["distancia_max_ultimo_bid_pct"] is None
    if valor == "ausente":
        esc.cfg = dataclasses.replace(esc.cfg, entrada={k: v for k, v in esc.cfg.entrada.items()
                                                        if k != "distancia_max_ultimo_bid_pct"})
    esc.cot = _cot(bid="3.07", ask="3.46", last="3.45")
    assert esc.evaluar().ok


def test_caducidad_borde_y_reapertura(esc: Escenario) -> None:
    esc.ahora_et = CIERRE + timedelta(seconds=60)                  # 60 s exactos: aún vale (R-B-04)
    assert esc.evaluar().ok
    esc.ahora_et = CIERRE + timedelta(seconds=600)
    assert esc.evaluar().motivo == MOTIVO_CADUCADA
    esc.es_reapertura = True                                       # R-F-04 b: la guardada no caduca por reloj
    assert esc.evaluar().ok


def test_reapertura_no_salta_la_repetida(esc: Escenario) -> None:
    esc.es_reapertura = True
    esc.estado.senales_vistas.add(esc.senal.id)
    assert esc.evaluar().motivo == MOTIVO_REPETIDA


def test_diario_degradado_no_entra(esc: Escenario) -> None:
    esc.diario_degradado = True
    v = esc.evaluar()
    assert (v.ok, v.motivo, v.avisar) == (False, MOTIVO_DEGRADADO, True)


def test_ssr_no_filtra_la_entrada_F10(esc: Escenario) -> None:
    esc.simb.ssr = True
    assert esc.evaluar().ok


def test_premercado_sin_excepciones_B11(esc: Escenario) -> None:
    esc.franja = "RTH"
    rth = esc.evaluar()
    esc.franja = "premercado"
    assert esc.evaluar() == rth
    esc.ahora_et = CIERRE + timedelta(seconds=90)
    esc.franja = "premercado"
    assert esc.evaluar().motivo == MOTIVO_CADUCADA


def test_halt_guarda_la_senal_sin_avisar(esc: Escenario) -> None:
    esc.simb.ta = "H"
    assert esc.evaluar() == Veredicto(ok=False, motivo=MOTIVO_HALT, guardar_para_reapertura=True, avisar=False)


@pytest.mark.parametrize("localizadas, usadas, estado_loc, qty", [
    (500, 0, "hecho", 500),
    (1200, 700, "hecho", 500),
    (0, 0, "no_hace_falta", 1200),
    (5000, 0, "hecho", 1200),
], ids=["R-H-04-parcial", "R-H-04-libres", "ETB-no-hace-falta", "R-H-04-sobran"])
def test_locates_libres_limitan_la_qty(esc: Escenario, localizadas, usadas, estado_loc, qty) -> None:
    loc = esc.estado.locates[(TICKER, SID)]
    loc.localizadas, loc.usadas, loc.estado = localizadas, usadas, estado_loc
    v = esc.evaluar()
    assert (v.ok, v.qty) == (True, qty)
    assert type(v.qty) is int


@pytest.mark.parametrize("sobrante_de, qty", [
    (dict(pedidas=1200, localizadas=5000), 1200),
    (dict(pedidas=300, localizadas=1000, usadas=300), 700),
    (dict(pedidas=0, localizadas=0, estado_loc="no_hace_falta"), 1200),
], ids=["D1-02-E9-sobrante-de-otra-entra", "G1B-11-A-1000-usadas-300-B-sin-registro-700",
        "G1A-07-ETB-en-el-registro-de-otra-entra"])
def test_E9_sin_locate_propio_usa_sobrantes_y_ETB(esc: Escenario, sobrante_de: dict, qty: int) -> None:
    """D1-02 / G1A-07 / G1B-11: la comprobación 16 aplica la MISMA regla que `locates.asignar_a_lote` (E9)."""
    from app.bot_das.reglas.locates import asignar_a_lote
    _solo_locate_de_otra(esc, **sobrante_de)
    v = esc.evaluar()
    assert (v.ok, v.motivo, v.qty) == (True, MOTIVO_OK, qty)
    assert sum(n for _, n in asignar_a_lote(esc.estado.locates, TICKER, 1200, SID)) == qty


def test_E9_propio_mas_sobrante_de_otra(esc: Escenario) -> None:
    """D1-02: propio con 500 libres + 400 sobrantes de otra → 900 (antes: solo las 500 propias)."""
    loc = esc.estado.locates[(TICKER, SID)]
    loc.localizadas, loc.usadas = 1200, 700
    esc.estado.locates[(TICKER, "otra")] = Locate(ticker=TICKER, strategy_id="otra", pedidas=600, localizadas=1000,
                                                  estado="hecho")
    assert esc.evaluar() == Veredicto(ok=True, motivo=MOTIVO_OK, qty=900)


# R-D-04 con paridad del backtester (portfolio_sim.py «Re-entry logic», bot_alerts_engine `_puede_reentrar`;
# Jaume 30-sep): accept_reentries false → cero reentradas SIEMPRE; con true, −1 → sin tope, N ≥ 0 → hasta N.
@pytest.mark.parametrize("previas, accept, maximo, entra", [
    (1, True, -1, True),
    (1, False, -1, False),
    (1, True, 0, False),
    (1, False, 0, False),
    (1, True, 1, True),
    (1, False, 1, False),      # 30-sep: apagado manda (antes D1-04 dejaba entrar con N = 1)
    (2, True, 1, False),
    (2, True, 2, True),
    (3, True, -1, True),
    (2, False, 1, False),
    (2, False, 3, False),      # 30-sep: apagado + N = 3 → no (antes entraba)
    (1, False, 2, False),      # 30-sep: apagado + N = 2 → cero reentradas
    (1, True, -2, False),      # valor imposible: lo conservador es no reentrar
], ids=["R-D-04--1-true", "R-D-04--1-false", "R-D-04-0-true", "R-D-04-0-false", "R-D-04-1-true",
        "R-D-04-1-false-apagado-manda", "R-D-04-2a-con-tope-1", "R-D-04-2a-con-tope-2", "R-D-04-sin-tope-numerico",
        "D1-04-2a-tope-1-accept-false", "D1-04-3a-tope-3-accept-false", "30sep-apagado-N2-no", "R-D-04-menos-2-no"])
def test_reentradas_tabla(esc: Escenario, previas: int, accept: bool, maximo: int, entra: bool) -> None:
    for n in range(previas):
        esc.lote_previo(f"previa-{n}")
    esc.estrategia(accept_reentries=accept, max_reentries=maximo)
    v = esc.evaluar()
    assert v.ok is entra
    assert v.motivo == (MOTIVO_OK if entra else MOTIVO_REENTRADA)


def test_entrada_cancelada_sin_fill_no_cuenta_como_reentrada(esc: Escenario) -> None:
    esc.lote_previo("cancelada", llenas=0, estado=EstadoLote.CANCELADO)
    esc.estrategia(max_reentries=0)
    assert esc.evaluar().ok


def test_r_e_03_cerrar_y_reiniciar_deja_entrar_a_la_version_nueva(esc: Escenario) -> None:
    esc.lote_previo("vieja", version_estrategia="sha256:vieja")
    esc.estrategia(al_desactivar="cerrar_y_reiniciar")
    assert esc.evaluar().ok
    esc.lote_previo("vieja-viva", version_estrategia="sha256:vieja", estado=EstadoLote.ABIERTO)
    assert esc.evaluar().motivo == MOTIVO_REENTRADA


def test_otra_estrategia_con_lote_vivo_no_es_reentrada(esc: Escenario) -> None:
    esc.lote_previo("otra-viva", strategy_id="otra", estado=EstadoLote.ABIERTO)
    assert esc.evaluar().ok


def _reentrada_backtester(previas: int, accept: bool, maximo: int) -> bool:
    """Referencia: el if/elif de `portfolio_sim.py` «Re-entry logic» (total_trades = entradas previas; 30-sep).

    Única diferencia a propósito: max_reentries < −1 (imposible desde la UI)
    no reentra (lo conservador), donde el backtester no pondría tope.
    """
    if not accept:
        return previas == 0
    if maximo >= 0:
        return previas <= maximo
    if maximo == -1:
        return True
    return previas == 0


@pytest.mark.parametrize("accept", [True, False], ids=["accept-true", "accept-false"])
@pytest.mark.parametrize("maximo", [-2, -1, 0, 1, 2, 3], ids=lambda m: f"max{m}")
@pytest.mark.parametrize("previas", [0, 1, 2, 3], ids=lambda p: f"previas{p}")
def test_D1_04_paridad_entrada_salidas_y_backtester(previas: int, accept: bool, maximo: int) -> None:
    """D1-04 / D2-salidas-rechazos-11: la comprobación 14 y `salidas.puede_reentrar` dicen lo mismo en toda la
    rejilla, y los dos coinciden con el backtester: una sola fuente de verdad para R-D-04."""
    from app.bot_das.reglas.salidas import puede_reentrar
    e = _escenario()
    for n in range(previas):
        e.lote_previo(f"previa-{n}")
    e.estrategia(accept_reentries=accept, max_reentries=maximo)
    entra = e.evaluar().ok
    permitida, _ = puede_reentrar(e.cfg.estrategias[SID], None, e.estado.posiciones.get(TICKER))
    assert entra is permitida
    assert entra is _reentrada_backtester(previas, accept, maximo)


def test_D1_04_la_guarda_de_entrada_llama_a_puede_reentrar(esc: Escenario, monkeypatch) -> None:
    """D1-04: la comprobación 14 DELEGA en `salidas.puede_reentrar` (no hay una segunda implementación)."""
    llamadas = []

    def falsa(e, lote_anterior, pos):
        llamadas.append((e.strategy_id, lote_anterior, pos.ticker))
        return False, "vetada por la prueba"

    esc.lote_previo("previa")
    monkeypatch.setattr(ent, "puede_reentrar", falsa)
    assert esc.evaluar().motivo == MOTIVO_REENTRADA
    assert llamadas == [(SID, None, TICKER)]


# ── pirámides (D13) ────────────────────────────────────────────────────
def _piramide(e: Escenario, **cambios) -> None:
    base = dict(tipo="piramide", stop=None, distancia_stop=None, nivel=1, accion_piramide="add",
                acciones=300.0, entrada_idx=7, posicion_total=1500.0)
    base.update(cambios)
    e.evento(**base)
    e.senal = dataclasses.replace(e.senal, id=f"{TICKER}|{SID}|2026-09-25 09:30:00|piramide|1")


@pytest.mark.parametrize("feed, last, entra", [
    ({"close": 2.6627}, "2.6627", True),     # ensayo LXEH 04:50: nivel 2,4562, cierre 2,6627, último = cierre → entra
    ({"close": 2.6627}, "2.75", False),      # el último se alejó > 1 % del CIERRE → tardía
    (None, "2.75", True),                    # sin cierre en la señal no se mide (R-B-04 y R-B-01 siguen protegiendo)
], ids=["R-A-01-piramide-contra-el-cierre", "R-A-01-piramide-tardia-vs-cierre", "R-A-01-piramide-sin-cierre-no-mide"])
def test_R_A_01_piramide_mide_el_retraso_contra_el_cierre_de_la_vela(esc: Escenario, feed, last, entra) -> None:
    """Ensayo 28-sep (LXEH 04:50): `Evento.precio` de una pirámide es el precio del NIVEL (apertura de la vela del
    añadido), no el último; medir R-A-01 contra él descartaba toda pirámide en un tramo rápido. Se mide contra
    `Senal.feed["close"]`, que la fuente rellena con el cierre de la vela."""
    esc.lote_previo("base", estado=EstadoLote.ABIERTO, entrada_idx=7, nivel_stop=D("3.90"))
    _piramide(esc, precio=2.4562)
    esc.senal = dataclasses.replace(esc.senal, feed=feed)
    esc.cot = _cot(bid=str(D(last) - D("0.01")), ask=str(D(last) + D("0.01")), last=last)
    v = esc.evaluar()
    assert v.ok is entra and (entra or v.motivo == MOTIVO_RETRASO)


def test_piramide_add_usa_el_nivel_de_su_lote_base_y_no_es_reentrada(esc: Escenario) -> None:
    esc.lote_previo("base", estado=EstadoLote.ABIERTO, entrada_idx=7, nivel_stop=D("3.90"))
    _piramide(esc)
    v = esc.evaluar()
    assert (v.ok, v.qty) == (True, 300)
    assert nivel_de_senal(esc.estado, esc.senal.evento) == D("3.90")


@pytest.mark.parametrize("preparar", [
    lambda e: None,
    lambda e: e.lote_previo("base", estado=EstadoLote.ABIERTO, entrada_idx=8),
    lambda e: (e.lote_previo("b1", estado=EstadoLote.ABIERTO, entrada_idx=None),
               e.lote_previo("b2", estado=EstadoLote.ABIERTO, entrada_idx=None)),
    lambda e: e.lote_previo("base", estado=EstadoLote.CERRADO, entrada_idx=7),
], ids=["D13-sin-base", "D13-otra-entrada", "D13-base-ambigua", "D13-base-cerrada"])
def test_piramide_sin_base_viva_no_entra(esc: Escenario, preparar) -> None:
    preparar(esc)
    _piramide(esc)
    assert esc.evaluar().motivo == MOTIVO_NIVEL_STOP


def test_piramide_respeta_el_veto_de_reentrada(esc: Escenario) -> None:
    esc.lote_previo("base", estado=EstadoLote.ABIERTO, entrada_idx=7)
    esc.pos().sin_reentrada_hasta_sigue = True
    _piramide(esc)
    assert esc.evaluar().motivo == MOTIVO_REENTRADA


@pytest.mark.parametrize("tipo, accion, es_add, es_reduce", [
    ("piramide", "add", True, False),
    ("piramide", "reduce", False, True),
    ("piramide", "lot_stop", False, True),
    ("piramide", "lot_tp", False, True),
    ("piramide", None, False, False),
    ("entrada", None, False, False),
    ("salida", None, False, False),
], ids=["D13-add", "D13-reduce", "D13-lot_stop", "D13-lot_tp", "D13-sin-accion", "D13-entrada", "D13-salida"])
def test_es_piramide_add_reduce(tipo, accion, es_add, es_reduce) -> None:
    ev = _evento(tipo=tipo, accion_piramide=accion)
    assert es_piramide_add(ev) is es_add
    assert es_piramide_reduce(ev) is es_reduce


# ── señales mal formadas → ValueError (H-5: el decisor pausa el ticker) ──
@pytest.mark.parametrize("romper", [
    lambda e: setattr(e, "senal", dataclasses.replace(e.senal, clase="radar")),
    lambda e: setattr(e, "senal", dataclasses.replace(e.senal, id=None)),
    lambda e: setattr(e, "senal", dataclasses.replace(e.senal, evento=None)),
    lambda e: e.evento(precio=None),
    lambda e: e.evento(precio=0.0),
    lambda e: e.evento(tipo="salida", motivo="TP"),
    lambda e: e.evento(tipo="piramide", accion_piramide="reduce"),
    lambda e: e.evento(ticker="ABC"),
    lambda e: setattr(e, "senal", dataclasses.replace(e.senal, momento=None, evento=dataclasses.replace(
        e.senal.evento, momento=None))),
    lambda e: setattr(e, "ahora_et", datetime(2026, 9, 25, 9, 31)),
    lambda e: setattr(e, "cot", _cot(ticker="ABC")),
    lambda e: setattr(e, "simb", EstadoSimbolo(ticker="ABC")),
], ids=["H-5-no-evento", "R-A-05-sin-id", "H-5-sin-evento", "H-5-precio-none", "H-5-precio-cero",
        "H-5-salida", "H-5-reduce", "H-5-ticker-distinto", "riesgo18-sin-momento", "riesgo13-ahora-naive",
        "H-5-cot-de-otro", "H-5-simbolo-de-otro"])
def test_senal_mal_formada_lanza(esc: Escenario, romper) -> None:
    romper(esc)
    with pytest.raises(ValueError):
        esc.evaluar()


# ── t_cierre_vela (R-B-04, riesgo 13) ──────────────────────────────────
@pytest.mark.parametrize("momento", [
    pd.Timestamp("2026-09-25 09:30:00"),
    datetime(2026, 9, 25, 9, 30),
    "2026-09-25 09:30:00",
    " 2026-09-25T09:30:00 ",
    datetime(2026, 9, 25, 9, 30, tzinfo=ET),
    datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc),
    pd.Timestamp("2026-09-25 13:30:00", tz="UTC"),
], ids=["R-B-04-pd-naive", "R-B-04-datetime-naive", "R-B-04-str", "R-B-04-str-iso-T", "R-B-04-aware-ET",
        "R-B-04-aware-UTC", "R-B-04-pd-aware"])
def test_t_cierre_vela_inicio_mas_60(momento) -> None:
    assert t_cierre_vela(momento) == CIERRE.timestamp()


def test_t_cierre_vela_en_horario_de_invierno() -> None:
    assert t_cierre_vela("2026-12-01 09:30:00") == datetime(2026, 12, 1, 14, 31, tzinfo=timezone.utc).timestamp()


@pytest.mark.parametrize("malo", [None, "", "ayer", 1790343000, 1790343000.0, pd.NaT, date(2026, 9, 25)],
                         ids=["none", "vacia", "texto", "int", "float", "NaT", "date"])
def test_t_cierre_vela_rechaza_lo_que_no_es_fecha(malo) -> None:
    with pytest.raises(ValueError):
        t_cierre_vela(malo)


def test_t_cierre_vela_contra_la_fixture_am_recorte() -> None:
    """La vela llega ~1 s después de su CIERRE (timestamp = inicio = campo `s`): si fuera el fin, llegaría 61 s tarde."""
    filas = []
    with gzip.open(FIXTURES / "AM_recorte.jsonl.gz", "rt", encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                filas.append(json.loads(linea))
    assert len(filas) >= 40
    for fila in filas:
        recibida = fila["_r"] / 1000
        for momento in (fila["timestamp"], pd.Timestamp(fila["timestamp"])):
            retraso = recibida - t_cierre_vela(momento)
            assert 0 < retraso < 5, (fila["sym"], fila["timestamp"], retraso)


# ── qty_de_evento y qty_final ──────────────────────────────────────────
@pytest.mark.parametrize("acciones, esperado", [
    (1199.0, 1199), (None, 0), (0.4, 0), (0.5, 0), (1.5, 2), (2.5, 2), (1200, 1200), (D("300"), 300),
    (0, 0), (0.0, 0), (-5.0, 0), (float("nan"), 0), (float("inf"), 0), (True, 0), ("abc", 0), ("1200", 1200),
], ids=["injerto8.2-1199.0", "none", "0.4", "0.5-al-par", "1.5-al-par", "2.5-al-par", "int", "decimal",
        "cero", "cero-float", "negativo", "nan", "inf", "bool", "texto", "texto-numero"])
def test_qty_de_evento(acciones, esperado) -> None:
    resultado = qty_de_evento(acciones)
    assert resultado == esperado
    assert type(resultado) is int


@pytest.mark.parametrize("args, esperado", [
    ((1200, 1200, 1200, None, None), (1200, D("0"))),
    ((1200, 500, 1200, None, None), (500, D("0"))),
    ((1200, 1200, 800, None, None), (800, D("0"))),
    ((1200, 1200, 1200, None, 100_000), (1200, D("0.012"))),
    ((1200, 1200, 1200, None, 0), (1200, D("0"))),
    ((1200, 1200, 1200, D("0.005"), 100_000), (500, D("0.005"))),
    ((1200, 1200, 1200, D("0.05"), 100_000), (1200, D("0.012"))),
    ((1200, 1200, 1200, D("0.005"), None), (1200, D("0"))),
    ((1200, -3, 1200, None, None), (0, D("0"))),
    ((1200, 1200, 0, None, 50_000), (0, D("0"))),
], ids=["R-B-05-sin-tope", "R-H-04-locates", "R-I-01-capital", "R-B-05-fraccion-medida", "R-B-05-sin-volumen",
        "R-B-05-tope-activo", "R-B-05-tope-holgado", "R-B-05-tope-sin-volumen", "negativo-a-cero",
        "R-E-02-sin-capital"])
def test_qty_final(args, esperado) -> None:
    qty, fraccion = qty_final(*args)
    assert (qty, fraccion) == esperado
    assert type(qty) is int and isinstance(fraccion, Decimal)


@pytest.mark.parametrize("args", [
    (1200.0, 1200, 1200, None, None),
    (1200, True, 1200, None, None),
    (1200, 1200, 1200, None, 1000.0),
    (1200, 1200, 1200, D("-0.1"), 1000),
], ids=["qty-float", "bool", "volumen-float", "fraccion-negativa"])
def test_qty_final_rechaza_tipos(args) -> None:
    with pytest.raises(ValueError):
        qty_final(*args)


# ── abrir_intento, segundos_hasta_limite ───────────────────────────────
def test_abrir_intento_suma_lotes_y_congela_la_config() -> None:
    cfg = _config_base()
    pos = PosicionTicker(ticker=TICKER)
    cot = _cot(bid="10.00", ask="10.04", last="10.02")
    intento = abrir_intento(pos, [_lote("a", 600), _lote("b", 400)], cot, D("10.02"), CIERRE.timestamp(), cfg, AHORA)
    assert intento.lotes == ["a", "b"]
    assert intento.qty_total == 1000
    assert (intento.bid_senal, intento.ask_senal, intento.precio_senal) == (D("10.00"), D("10.04"), D("10.02"))
    assert intento.t_cierre_vela == CIERRE.timestamp()
    assert intento.t_limite == CIERRE.timestamp() + 60
    assert intento.fase is FaseIntento.AGREGANDO
    assert intento.cfg_congelada == cfg.entrada
    cfg.entrada["tope_caida_bid_pct"] = 50.0                       # riesgo 21: la config viva cambia...
    assert intento.cfg_congelada["tope_caida_bid_pct"] == 3.0      # ...el intento conserva la suya


@pytest.mark.parametrize("lotes, cot", [
    ([], _cot()),
    ([_lote("a", 600), _lote("a", 400)], _cot()),
    ([_lote("a", 600, ticker="ABC")], _cot()),
    ([_lote("a", 0)], _cot()),
    ([_lote("a", 600)], _cot(bid=None)),
    ([_lote("a", 600)], _cot(bid="0")),
    ([_lote("a", 600)], _cot(bid="3.47", ask="3.46")),
    ([_lote("a", 600)], _cot(ticker="ABC")),
], ids=["sin-lotes", "repetidos", "otro-ticker", "pedidas-0", "sin-bid", "R-B-01-bid-cero-anularia-el-tope",
        "libro-cruzado", "cot-de-otro"])
def test_abrir_intento_rechaza(lotes, cot) -> None:
    with pytest.raises(ValueError):
        abrir_intento(PosicionTicker(ticker=TICKER), lotes, cot, D("3.45"), CIERRE.timestamp(), _config_base(), AHORA)


def test_segundos_hasta_limite_en_epoch() -> None:
    intento = _intento()
    assert segundos_hasta_limite(intento, CIERRE + timedelta(seconds=15)) == pytest.approx(45.0)
    assert segundos_hasta_limite(intento, CIERRE + timedelta(seconds=90)) == 0.0
    with pytest.raises(ValueError):
        segundos_hasta_limite(intento, datetime(2026, 9, 25, 9, 31, 15))


# ── orden_agregar (R-B-01 v3, B19) ─────────────────────────────────────
HORA_RTH = datetime(2026, 9, 25, 9, 31, tzinfo=ET)
HORA_PM_TEMPRANO = datetime(2026, 9, 25, 6, 30, tzinfo=ET)


def test_orden_agregar_punto_medio_arriba_postonly_ruta_agregar() -> None:
    intento = _intento()
    o = orden_agregar(intento, _cot(bid="10.00", ask="10.05", last="10.02"), _config_base(), TOKEN, HORA_RTH,
                      nivel=D("11.00"))
    assert (o.lado, o.tipo, o.ticker, o.qty) == (Lado.CORTO, TipoOrden.LIMITE, TICKER, 1000)
    assert o.precio == D("10.03")                                  # (10,00 + 10,05)/2 = 10,025 → arriba 10,03
    assert (o.post_only, o.tif, o.ruta) == (True, "DAY+", "SAGEREB")
    assert (o.proposito, o.lote_id, o.nivel, o.token) == (Proposito.ENTRADA_AGREGAR, "a", D("11.00"), TOKEN)


@pytest.mark.parametrize("bid, ask, precio, ruta", [
    ("3.44", "3.45", "3.45", "SAGEREB"),
    ("3.44", "3.46", "3.45", "SAGEREB"),
    ("3.45", "3.45", "3.46", "SAGEREB"),
    ("0.5012", "0.5020", "0.5016", "MIAX"),
    ("0.9999", "0.9999", "1.0000", "SAGEREB"),
], ids=["R-B-01-spread-1-tick-al-ask", "R-B-01-spread-2-ticks-bid+1", "R-B-01-bloqueado-bid+1",
        "R-B-01-penny-MIAX", "regla612-cruza-el-dolar"])
def test_orden_agregar_precios_y_rutas(bid, ask, precio, ruta) -> None:
    o = orden_agregar(_intento(), _cot(bid=bid, ask=ask, last=bid), _config_base(), TOKEN, HORA_RTH)
    assert o.precio == D(precio)
    assert o.ruta == ruta
    assert en_tick(o.precio)


@pytest.mark.parametrize("bid, ask", [("3.44", "3.45"), ("3.44", "3.46"), ("3.44", "3.44"), ("3.44", "3.90"),
                                      ("0.1234", "0.1235")],
                         ids=["B19-1-tick", "B19-2-ticks", "B19-bloqueado", "B19-ancho", "B19-penny"])
def test_b19_con_ssr_el_precio_ya_esta_sobre_el_bid(bid, ask) -> None:
    b = D(bid)
    o = orden_agregar(_intento(), _cot(bid=bid, ask=ask, last=bid), _config_base(), TOKEN, HORA_RTH)
    assert o.precio >= b + tick_de(b)


def test_orden_agregar_tras_parcial_lleva_solo_lo_pendiente_y_respeta_postonly_congelado() -> None:
    congelada = dict(_config_base().entrada, post_only=False)
    o = orden_agregar(_intento(llenas=400, cfg_congelada=congelada), _cot(bid="10.00", ask="10.04"),
                      _config_base(), TOKEN, HORA_RTH)
    assert o.qty == 600
    assert o.post_only is False


@pytest.mark.parametrize("cambios", [
    dict(fase=FaseIntento.CRUZANDO),
    dict(token_agregar=TOKEN),
    dict(token_cruce=TOKEN),
    dict(llenas=1000),
], ids=["fase-cruzando", "riesgo4-orden-viva", "riesgo4-cruce-vivo", "nada-pendiente"])
def test_orden_agregar_rechaza(cambios) -> None:
    with pytest.raises(ValueError):
        orden_agregar(_intento(**cambios), _cot(bid="10.00", ask="10.04"), _config_base(), TOKEN, HORA_RTH)


# ── sumar_senal (R-B-03) ───────────────────────────────────────────────
def test_sumar_senal_cancela_la_viva_y_conserva_t_limite() -> None:
    original = _intento(token_agregar=TOKEN)
    nuevo, acciones = sumar_senal(original, _lote("c", 500), id_das_viva=555)
    assert acciones == [Cancelar(id_das=555, token=TOKEN, motivo=MOTIVO_CANCELAR_SUMA)]
    assert nuevo.lotes == ["a", "b", "c"]
    assert nuevo.qty_total == 1500
    assert nuevo.t_limite == original.t_limite
    assert nuevo.bid_senal == original.bid_senal
    assert nuevo.fase is FaseIntento.CANCELANDO
    assert original.lotes == ["a", "b"] and original.qty_total == 1000   # puro: el de entrada no cambia
    assert original.fase is FaseIntento.AGREGANDO


def test_sumar_senal_sin_id_das_aun_marca_cancelando_sin_accion() -> None:
    nuevo, acciones = sumar_senal(_intento(token_agregar=TOKEN), _lote("c", 500))
    assert acciones == []
    assert nuevo.fase is FaseIntento.CANCELANDO


@pytest.mark.parametrize("cambios, fase", [
    (dict(fase=FaseIntento.CANCELANDO, token_agregar=TOKEN), FaseIntento.CANCELANDO),
    (dict(), FaseIntento.AGREGANDO),
    (dict(fase=FaseIntento.CRUZANDO), FaseIntento.CRUZANDO),
], ids=["R-B-03-ya-cancelando", "R-B-03-sin-orden-viva", "R-B-03-cruzando-sin-orden"])
def test_sumar_senal_sin_nada_que_cancelar(cambios, fase) -> None:
    nuevo, acciones = sumar_senal(_intento(**cambios), _lote("c", 500), id_das_viva=555)
    assert acciones == []
    assert nuevo.fase is fase
    assert nuevo.qty_total == 1500


def test_sumar_senal_cancela_el_cruce_vivo() -> None:
    nuevo, acciones = sumar_senal(_intento(fase=FaseIntento.CRUZANDO, token_cruce=TOKEN + 1), _lote("c", 500),
                                  id_das_viva=777)
    assert acciones == [Cancelar(id_das=777, token=TOKEN + 1, motivo=MOTIVO_CANCELAR_SUMA)]
    assert nuevo.fase is FaseIntento.CANCELANDO


@pytest.mark.parametrize("intento, lote", [
    (_intento(fase=FaseIntento.TERMINADO), _lote("c", 500)),
    (_intento(), _lote("a", 500)),
    (_intento(), _lote("c", 500, ticker="ABC")),
    (_intento(), _lote("c", 0)),
], ids=["terminado", "lote-repetido", "otro-ticker", "pedidas-0"])
def test_sumar_senal_rechaza(intento, lote) -> None:
    with pytest.raises(ValueError):
        sumar_senal(intento, lote)


# ── al_vencer, resto_a_cruzar, orden_cruce (R-B-01 v3 pasos 2 y 3) ──────
@pytest.mark.parametrize("bid, fase, motivo", [
    ("9.71", FaseIntento.CRUZANDO, None),
    ("9.70", FaseIntento.CRUZANDO, None),
    ("9.69", FaseIntento.TERMINADO, MOTIVO_FIN_BID_CAYO),
    ("10.20", FaseIntento.CRUZANDO, None),
], ids=["R-B-01-bid-2,9%-cruza", "R-B-01-bid-3%-exacto-cruza", "R-B-01-bid-3,1%-no", "R-B-01-bid-subio"])
def test_al_vencer_tope_del_3(bid, fase, motivo) -> None:
    assert al_vencer(_intento(llenas=400), _cot(bid=bid, ask="10.30", last=bid), _config_base()) == (fase, motivo)


def test_al_vencer_orden_viva_primero_cancela() -> None:
    assert al_vencer(_intento(token_agregar=TOKEN), _cot(bid="9.00", ask="9.10"), _config_base()) == \
        (FaseIntento.CANCELANDO, None)


def test_al_vencer_lleno_o_sin_cotizacion() -> None:
    assert al_vencer(_intento(llenas=1000), None, _config_base()) == (FaseIntento.TERMINADO, MOTIVO_FIN_LLENA)
    assert al_vencer(_intento(), None, _config_base()) == (FaseIntento.TERMINADO, MOTIVO_FIN_SIN_COTIZACION)
    assert al_vencer(_intento(), _cot(bid=None), _config_base()) == \
        (FaseIntento.TERMINADO, MOTIVO_FIN_SIN_COTIZACION)


def test_al_vencer_usa_la_config_congelada() -> None:
    congelada = dict(_config_base().entrada, tope_caida_bid_pct=5.0)
    assert al_vencer(_intento(cfg_congelada=congelada), _cot(bid="9.60", ask="9.70"), _config_base()) == \
        (FaseIntento.CRUZANDO, None)


def test_resto_a_cruzar_solo_tras_canceled() -> None:
    assert resto_a_cruzar(_intento(llenas=400, token_agregar=TOKEN)) == 0      # Cancel pedido, Canceled sin llegar
    assert resto_a_cruzar(_intento(llenas=400, token_cruce=TOKEN)) == 0
    assert resto_a_cruzar(_intento(llenas=400)) == 600                         # Canceled confirmado: token a None
    assert resto_a_cruzar(_intento(llenas=1000)) == 0
    assert resto_a_cruzar(_intento(llenas=1100)) == 0


@pytest.mark.parametrize("canceladas", [0, 600, 9999], ids=["D1-11-canceladas-0", "D1-11-canceladas-600",
                                                             "D1-11-canceladas-acumuladas"])
def test_D1_11_resto_a_cruzar_no_depende_de_canceladas(canceladas: int) -> None:
    """D1-11: `resto_a_cruzar` usa SOLO qty_total − llenas y los tokens; `IntentoEntrada.canceladas` no entra.

    La garantía del riesgo 5 (no cruzar de más) es del DECISOR: suelta el
    token solo con la orden cuadrada (terminal y llenas + canceladas ≥
    pedidas, `_soltar_cuadrados`) y suma cada fill a `llenas`. `canceladas`
    es ACUMULADO de todas las órdenes del intento (tras un R-B-03 incluye la
    orden reiniciada), así que no sirve de tope: un min() con él cruzaría de
    menos o de más según la historia. Con token vivo, 0 pase lo que pase.
    """
    assert resto_a_cruzar(_intento(llenas=400, canceladas=canceladas)) == 600
    assert resto_a_cruzar(_intento(llenas=400, canceladas=canceladas, token_agregar=TOKEN)) == 0


@pytest.mark.parametrize("bid, precio", [("10.00", "9.95"), ("3.00", "2.98"), ("3.33", "3.31"), ("0.5000", "0.4975")],
                         ids=["R-B-01-10$", "R-B-01-3$-redondeo-abajo", "R-B-01-3,33$", "R-B-01-penny"])
def test_orden_cruce_a_bid_por_0995_redondeado_abajo(bid, precio) -> None:
    b = D(bid)
    intento = _intento(fase=FaseIntento.CRUZANDO, llenas=400, bid_senal=b)
    o = orden_cruce(intento, 600, _cot(bid=bid, ask=bid, last=bid), _config_base(), TOKEN, HORA_RTH, nivel=D("12"))
    assert o is not None
    assert o.precio == D(precio)
    assert o.precio <= b * D("0.995")
    assert en_tick(o.precio)
    assert (o.lado, o.tipo, o.qty, o.post_only, o.tif) == (Lado.CORTO, TipoOrden.LIMITE, 600, False, "DAY+")
    assert (o.proposito, o.lote_id, o.nivel) == (Proposito.ENTRADA_CRUCE, "a", D("12"))


@pytest.mark.parametrize("bid, hora, ruta", [
    ("10.00", HORA_RTH, "SAGEPRO"),
    ("0.5000", HORA_PM_TEMPRANO, "MIAX"),
    ("0.5000", datetime(2026, 9, 25, 7, 0, tzinfo=ET), "EDGA"),
], ids=["rutas-ge1-SAGEPRO", "rutas-penny-antes-0700-MIAX", "rutas-penny-desde-0700-EDGA"])
def test_orden_cruce_ruta_por_tramo_y_hora(bid, hora, ruta) -> None:
    intento = _intento(fase=FaseIntento.CRUZANDO, bid_senal=D(bid))
    o = orden_cruce(intento, 1000, _cot(bid=bid, ask=bid, last=bid), _config_base(), TOKEN, hora)
    assert o is not None and o.ruta == ruta


def test_orden_cruce_none_si_el_bid_cayo_o_no_hay_bid() -> None:
    intento = _intento(fase=FaseIntento.CRUZANDO)
    assert orden_cruce(intento, 1000, _cot(bid="9.69", ask="9.80"), _config_base(), TOKEN, HORA_RTH) is None
    assert orden_cruce(intento, 1000, None, _config_base(), TOKEN, HORA_RTH) is None
    assert orden_cruce(intento, 1000, _cot(bid="9.70", ask="9.80"), _config_base(), TOKEN, HORA_RTH) is not None


def test_orden_cruce_con_ssr_va_a_bid_mas_un_tick_B19() -> None:
    intento = _intento(fase=FaseIntento.CRUZANDO)
    o = orden_cruce(intento, 1000, _cot(bid="9.90", ask="9.95"), _config_base(), TOKEN, HORA_RTH, ssr=True)
    assert o is not None and o.precio == D("9.91")


@pytest.mark.parametrize("cambios, resto", [
    (dict(fase=FaseIntento.AGREGANDO), 600),
    (dict(fase=FaseIntento.CRUZANDO, token_agregar=TOKEN), 600),
    (dict(fase=FaseIntento.CRUZANDO), 601),
    (dict(fase=FaseIntento.CRUZANDO), 0),
    (dict(fase=FaseIntento.CRUZANDO), 600.0),
], ids=["fase-agregando", "riesgo5-cancel-sin-confirmar", "riesgo5-resto-mayor-que-pendiente", "resto-0",
        "resto-float"])
def test_orden_cruce_rechaza(cambios, resto) -> None:
    with pytest.raises(ValueError):
        orden_cruce(_intento(llenas=400, **cambios), resto, _cot(bid="10.00", ask="10.04"), _config_base(), TOKEN,
                    HORA_RTH)


# ── repartir_fill, acumular_fill, cerrar_intento (R-B-02, R-B-03) ──────
def test_repartir_fill_400_de_1000_entre_600_y_400() -> None:
    assert repartir_fill([_lote("a", 600), _lote("b", 400)], 400, D("3.45")) == [("a", 240), ("b", 160)]


@pytest.mark.parametrize("pedidas, llenas, qty, esperado", [
    ([100, 100, 100], [0, 0, 0], 100, [34, 33, 33]),
    ([1, 1, 1], [0, 0, 0], 2, [1, 1, 0]),
    ([600, 400], [590, 0], 100, [10, 90]),
    ([700, 300], [0, 0], 1, [1, 0]),
    ([333, 333, 334], [0, 0, 0], 1000, [333, 333, 334]),
], ids=["R-B-03-resto-al-primero", "R-B-03-resto-con-capacidad", "R-B-03-capacidad-agotada", "R-B-03-una-accion",
        "R-B-03-completo"])
def test_repartir_fill_con_resto(pedidas, llenas, qty, esperado) -> None:
    lotes = [_lote(f"l{i}", p, llenas=ll) for i, (p, ll) in enumerate(zip(pedidas, llenas))]
    reparto = repartir_fill(lotes, qty, D("1.00"))
    assert [n for _, n in reparto] == esperado
    assert [i for i, _ in reparto] == [lote.id for lote in lotes]


def test_repartir_fill_suma_exacta_y_nunca_pasa_de_lo_pedido() -> None:
    for pedidas in ([600, 400], [7, 11, 13], [1, 999], [250, 250, 250, 250], [3, 3, 3, 1]):
        total = sum(pedidas)
        for qty in range(1, total + 1):
            lotes = [_lote(f"l{i}", p) for i, p in enumerate(pedidas)]
            reparto = repartir_fill(lotes, qty, D("2.50"))
            assert sum(n for _, n in reparto) == qty
            assert all(0 <= n <= p for (_, n), p in zip(reparto, pedidas))
            assert all(type(n) is int for _, n in reparto)


def test_repartir_fill_en_varios_fills_llena_exactamente_lo_pedido() -> None:
    lotes = [_lote("a", 600), _lote("b", 400)]
    for qty in (137, 263, 1, 599):
        reparto = dict(repartir_fill(lotes, qty, D("3.45")))
        lotes = [acumular_fill(lote, reparto[lote.id], D("3.45")) if reparto[lote.id] else lote for lote in lotes]
    assert [lote.llenas for lote in lotes] == [600, 400]


@pytest.mark.parametrize("lotes, qty, precio", [
    ([], 100, D("1")),
    ([_lote("a", 100)], 0, D("1")),
    ([_lote("a", 100)], 101, D("1")),
    ([_lote("a", 100, llenas=100)], 1, D("1")),
    ([_lote("a", 100)], 50, D("0")),
    ([_lote("a", 100)], 50, 3.45),
    ([_lote("a", 100)], 50.0, D("1")),
], ids=["sin-lotes", "qty-0", "sobrellenado", "ya-lleno", "precio-0", "precio-float", "qty-float"])
def test_repartir_fill_rechaza(lotes, qty, precio) -> None:
    with pytest.raises(ValueError):
        repartir_fill(lotes, qty, precio)


def test_acumular_fill_precio_medio_ponderado_exacto() -> None:
    lote = _lote("a", 600)
    uno = acumular_fill(lote, 240, D("3.45"))
    dos = acumular_fill(uno, 160, D("3.44"))
    assert (dos.llenas, dos.precio_medio) == (400, D("3.446"))
    assert (lote.llenas, lote.precio_medio) == (0, D("0"))                  # puro
    with pytest.raises(ValueError):
        acumular_fill(dos, 201, D("3.40"))
    with pytest.raises(ValueError):
        acumular_fill(dos, 0, D("3.40"))


def test_cerrar_intento_cero_parcial_y_completo() -> None:
    intento = _intento()
    a, b = _lote("a", 600), _lote("b", 400)
    assert [lote.estado for lote in cerrar_intento(intento, [a, b])] == [EstadoLote.CANCELADO] * 2
    a1 = acumular_fill(a, 240, D("3.45"))
    cerrados = cerrar_intento(intento, [a1, b])
    assert [lote.estado for lote in cerrados] == [EstadoLote.ABIERTO, EstadoLote.CANCELADO]
    assert (cerrados[0].llenas, cerrados[0].precio_medio) == (240, D("3.45"))
    completos = cerrar_intento(intento, [acumular_fill(a, 600, D("3.45")), acumular_fill(b, 400, D("3.44"))])
    assert [lote.estado for lote in completos] == [EstadoLote.ABIERTO] * 2
    assert a.estado is EstadoLote.ABRIENDO                                  # puro


def test_cerrar_intento_respeta_lotes_ya_cerrados_y_rechaza_ajenos() -> None:
    intento = _intento()
    cerrado = _lote("a", 600, llenas=600, estado=EstadoLote.CERRADO)
    assert cerrar_intento(intento, [cerrado]) == [cerrado]
    with pytest.raises(ValueError):
        cerrar_intento(intento, [_lote("z", 100)])


# ── B13 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("fill, peor", [("9.65", False), ("9.6499", True), ("9.64", True), ("9.70", False),
                                        ("10.10", False)],
                         ids=["B13-en-el-suelo", "B13-un-pelo-peor", "B13-peor", "B13-dentro", "B13-mejor-que-ultimo"])
def test_fill_peor_de_lo_permitido(fill, peor) -> None:
    assert fill_peor_de_lo_permitido(D(fill), D("10.00"), D("3.5")) is peor


def test_fill_peor_de_lo_permitido_rechaza_basura() -> None:
    with pytest.raises(ValueError):
        fill_peor_de_lo_permitido(D("0"), D("10"), D("3"))
    with pytest.raises(ValueError):
        fill_peor_de_lo_permitido(D("9"), D("10"), D("-1"))
    with pytest.raises(ValueError):
        fill_peor_de_lo_permitido(D("9"), D("10"), D("3"), cruce_pct=D("-0.5"))


@pytest.mark.parametrize("fill, bid_senal, peor", [
    ("1.00", "1.04", False),     # D1-05: bid 1,01 (−2,88 %) → cruce 1,00: legal, no avisa
    ("0.99", "1.04", True),      # un tick por debajo del peor cruce legal
    ("1.29", "1.34", False),     # G1B-19: bid 1,30 (−2,99 %) → cruce 1,2935 → 1,29: legal
    ("1.28", "1.34", True),
    ("9.65", "10.00", False),    # 10 $: bid 9,70 → 9,6515 → 9,65
    ("9.64", "10.00", True),
    ("0.4825", "0.5000", False),  # penny (tick 0,0001): bid 0,4850 → 0,482575 → 0,4825
    ("0.4824", "0.5000", True),
], ids=["D1-05-1,04-cruce-legal", "D1-05-1,04-un-tick-peor", "G1B-19-1,34-cruce-legal", "G1B-19-1,34-peor",
        "D1-05-10$-legal", "D1-05-10$-peor", "D1-05-penny-legal", "D1-05-penny-peor"])
def test_D1_05_fill_peor_cuenta_el_redondeo_del_cruce(fill: str, bid_senal: str, peor: bool) -> None:
    """D1-05 / G1B-19: con `cruce_pct` el suelo es el PEOR cruce legal (bid mínimo al tick, × (1 − 0,5 %) abajo)."""
    assert fill_peor_de_lo_permitido(D(fill), D(bid_senal), D("3"), cruce_pct=D("0.5")) is peor


def test_D1_05_el_suelo_coincide_con_orden_cruce() -> None:
    """D1-05: un cruce hecho por `orden_cruce` con el bid más bajo permitido NUNCA avisa, y uno de un tick menos sí."""
    for bid_senal in ("1.04", "1.34", "2.17", "3.33", "10.00", "0.5000", "0.1234"):
        b = D(bid_senal)
        intento = _intento(fase=FaseIntento.CRUZANDO, llenas=400, bid_senal=b)
        bid_min = ent.redondear_arriba(b * D("0.97"))
        o = orden_cruce(intento, 600, _cot(bid=str(bid_min), ask=str(bid_min), last=str(bid_min)), _config_base(),
                        TOKEN, HORA_RTH)
        assert o is not None, bid_senal
        assert fill_peor_de_lo_permitido(o.precio, b, D("3"), cruce_pct=D("0.5")) is False
        assert fill_peor_de_lo_permitido(o.precio - tick_de(o.precio), b, D("3"), cruce_pct=D("0.5")) is True


def test_D1_05_con_ssr_el_suelo_es_bid_mas_un_tick() -> None:
    """D1-05 + B19: con SSR el cruce va a bid + 1 tick; bid mínimo 1,01 → suelo 1,02."""
    assert fill_peor_de_lo_permitido(D("1.02"), D("1.04"), D("3"), cruce_pct=D("0.5"), ssr=True) is False
    assert fill_peor_de_lo_permitido(D("1.01"), D("1.04"), D("3"), cruce_pct=D("0.5"), ssr=True) is True


def test_D1_05_sin_cruce_pct_la_forma_antigua_no_cambia() -> None:
    """D1-05: el llamador que aún pasa el tope total (3,5) obtiene lo mismo que antes (cambio aditivo)."""
    assert fill_peor_de_lo_permitido(D("1.00"), D("1.04"), D("3.5")) is True        # el falso aviso de la revisión
    assert fill_peor_de_lo_permitido(D("9.65"), D("10.00"), D("3.5")) is False


# ── nivel_de_senal y pureza del módulo ─────────────────────────────────
def test_nivel_de_senal_de_una_entrada_es_decimal_exacto(esc: Escenario) -> None:
    assert nivel_de_senal(esc.estado, esc.senal.evento) == D("3.8")
    assert nivel_de_senal(esc.estado, _evento(stop=None)) is None


def test_modulo_puro_solo_importa_lo_permitido() -> None:
    """reglas/*: sin I/O, sin reloj, sin logging, sin entorno; solo tipos, precios y dos reglas puras hermanas (§3, §12).

    `reglas.locates` (D1-02/G1A-07: la comprobación 16 usa `asignar_a_lote`)
    y `reglas.salidas` (D1-04: la 14 usa `puede_reentrar`) los permite el
    director: son puros y no importan `entrada` (sin ciclo).
    """
    arbol = ast.parse(Path(ent.__file__).read_text(encoding="utf-8"))
    modulos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom):
            modulos.add(nodo.module)
    permitidos = {"__future__", "copy", "dataclasses", "math", "datetime", "decimal", "functools", "typing",
                  "zoneinfo", "app.bot_das.tipos", "app.bot_das.reglas.precios",
                  "app.bot_das.reglas.locates", "app.bot_das.reglas.salidas"}
    assert modulos <= permitidos, modulos - permitidos
    llamadas = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call):
            funcion = nodo.func
            llamadas.add(funcion.attr if isinstance(funcion, ast.Attribute) else getattr(funcion, "id", ""))
    prohibidas = {"now", "utcnow", "today", "time", "monotonic", "sleep", "open", "print", "getenv", "input"}
    assert not (llamadas & prohibidas), llamadas & prohibidas


def test_D1_02_D1_04_sin_ciclo_de_importacion() -> None:
    """D1-02 / D1-04: `reglas.locates` y `reglas.salidas` no importan `reglas.entrada` (ni `capital`): sin ciclo."""
    from app.bot_das.reglas import locates, salidas
    for modulo in (locates, salidas):
        arbol = ast.parse(Path(modulo.__file__).read_text(encoding="utf-8"))
        importados = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                importados.update(alias.name for alias in nodo.names)
            elif isinstance(nodo, ast.ImportFrom):
                importados.add(nodo.module or "")
                importados.update(f"{nodo.module}.{alias.name}" for alias in nodo.names)
        assert not any(m.endswith("reglas.entrada") or m.endswith("reglas.capital") for m in importados), modulo
