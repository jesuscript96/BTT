"""Tests de las decisiones 68-72 de Jaume (2-oct, con lo medido en DAS real ese día).

QUÉ PRUEBA.
  * 68 el límite del stop residente por TRAMO del disparo (`stops.limite_tramos`:
    ≤ 25 $ +9 %, > 25 $ +2 %) en el plan, la protección, el vigilante y /stop;
    sin la hoja, `stops.limite_pct` como siempre; `stops.pref` añade «Pref=».
  * 69 el «bot de emergencia escalonado»: el ejemplo literal de Jaume (stop en
    10 → límite 10,90 → escalones de +19 % en premercado → nunca por encima del
    techo 16,35 = 10,90 × 1,5 → la orden del techo se queda PUESTA), el
    escalón por sesión (RTH/extendido) y por tramo de precio, los tres
    disparadores (precio sobre el límite, stop muerto, 5 s sin ejecutar), la
    cuenta larga → venta del exceso, y el vigilante que no pisa la compra de
    emergencia.
  * 70 el cierre de un halt de PREMERCADO con el mismo escalado hasta × 3,5.
  * 71 cancelación verificada de las salidas en vuelo al parar (reintentos
    acotados, aviso máximo), la redecisión de 60 s sin duplicar la límite de
    PM (silencio = false) y la reapertura tratada por evento.
  * 72 el cuadro de PRODUCCIÓN (`cuadro_produccion.json`) que `exportar` aplica
    por defecto, y MIAX para < 1 $ también desde las 07:00.

POR QUÉ APARTE. Son las decisiones de Jaume del 2-oct sobre lo medido en DAS real;
usan los dobles de test_das_decisor (Banco) y un cuadro con las hojas de producción
encima del fixture (que NO cambia).
"""
from __future__ import annotations

import dataclasses
import json
import types
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.bot_das import config as mod_config, protocolo
from app.bot_das.reglas import precios, stops, vigilancia
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    Anotar,
    Avisar,
    Cancelar,
    Config,
    EnviarOrden,
    EstadoOrden,
    EstadoTicker,
    Lado,
    MsgOrden,
    Nivel,
    Proposito,
    Reemplazar,
    TipoOrden,
)
from test_das_decisor import (  # noqa: F401 — `banco` es un fixture
    CUENTA,
    HOY,
    STOPS,
    TICKER,
    Banco,
    abrir_posicion,
    anotaciones,
    banco,
    cfg_con,
    evento,
    momento_de,
    salida,
)

D = Decimal
PRODUCCION = mod_config.leer_cuadro_produccion()
PM_INICIO = datetime(2026, 9, 25, 8, 0, tzinfo=ET)


def _prod(cfg: Config, **stops_extra) -> Config:
    """El cuadro de ejemplo con las hojas de PRODUCCIÓN encima (decisión 72) y, si se pide, más cambios en `stops`."""
    crudo = mod_config.aplicar_cuadro_produccion({"stops": dict(cfg.stops), "rutas": dict(cfg.rutas)}, PRODUCCION)
    return cfg_con(cfg, stops={**crudo["stops"], **stops_extra}, rutas=crudo["rutas"])


def _respaldos(b: Banco, desde: int = 0):
    return b.enviadas(Proposito.STOP_RESPALDO, desde=desde)


def _avisos(acciones: list, prefijo: str) -> list[Avisar]:
    return [a for a in acciones if isinstance(a, Avisar) and (a.clave or "").startswith(prefijo)]


def _precios_enviados(b: Banco, token: int, desde: int = 0) -> list[Decimal]:
    """Todos los límites que llevó una orden: el del NEWORDER y el de cada REPLACE."""
    salida_: list[Decimal] = []
    for a in b.historial[desde:]:
        if isinstance(a, EnviarOrden) and a.orden.token == token:
            salida_.append(a.orden.precio)
        elif isinstance(a, Reemplazar) and a.token == token and a.precio is not None:
            salida_.append(a.precio)
    return salida_


def _stop(b: Banco):
    (stop,) = [o for o in b.estado.ordenes.values()
               if o.ticker == TICKER and o.proposito in STOPS and o.estado in (EstadoOrden.ACCEPTED, EstadoOrden.SENDING)]
    return stop


def _banco_en(cfg: Config, tmp_path: Path, precio: str, stop: float, inicio: datetime = None) -> Banco:
    """Corto de 100 a `precio` con el stop único en `stop` (la cotización inicial alrededor de `precio`)."""
    p = D(precio)
    kw = {"inicio": inicio} if inicio is not None else {}
    b = Banco(cfg, tmp_path, **kw)
    b.preparar(cotizaciones=((TICKER, str(p - D("0.01")), str(p + D("0.01")), precio),))
    ev = evento(precio=float(p), stop=stop, distancia_stop=round(stop - float(p), 4), riesgo_usd=round((stop - float(p))
                                                                                                    * 100, 2),
                **({"momento": momento_de(inicio)} if inicio is not None else {}))
    b.senal(ev)
    b.cotizar(TICKER, precio, str(p + D("0.02")), precio)
    b.tic_das()
    assert b.pos().neta_fills == -100, b.pos()
    return b


# ═══════════════════════════════ decisión 68: límite por tramo ═══════════════════════════════
def test_68_niveles_por_tramo_y_sin_hoja_como_siempre(cfg: Config) -> None:
    prod = _prod(cfg)
    assert stops.niveles(D("10"), prod.stops).limite == D("10.90")          # ≤ 25 $: +9 %
    assert stops.niveles(D("25"), prod.stops).limite == D("27.25")          # 25 entra en el primer tramo
    assert stops.niveles(D("30"), prod.stops).limite == D("30.60")          # > 25 $: +2 %
    assert stops.niveles(D("10"), cfg.stops).limite == D("15.00")           # fixture: limite_pct 50, sin tramos
    assert stops.pct_limite(cfg.stops, D("30")) == D("50")


def test_68_stop_del_plan_a_9_por_ciento_y_proteccion_a_2_por_encima_de_25(cfg: Config, tmp_path: Path) -> None:
    b = Banco(_prod(cfg), tmp_path)
    b.preparar()
    abrir_posicion(b)                                                     # stop en 4,00
    (stop,) = b.enviadas(*STOPS)
    assert (stop.stop, stop.precio, stop.pref) == (D("4.00"), D("4.36"), None)
    prod = _prod(cfg)
    # protección de una posición desconocida a 28 $ (+25 % → disparo 35,00): su límite, el tramo > 25 $ (+2 %)
    o = stops.stop_proteccion(TICKER, 100, True, D("28"), D("25"), 1, "SMAT", 0, limite_pct=D("50"),
                              cfg_stops=prod.stops)
    assert (o.stop, o.precio) == (D("35.00"), D("35.70"))
    o = stops.stop_proteccion(TICKER, 100, True, D("8"), D("25"), 1, "SMAT", 0, cfg_stops=prod.stops)
    assert (o.stop, o.precio) == (D("10.00"), D("10.90"))


def test_68_vigilante_pone_la_proteccion_con_el_limite_del_tramo(cfg: Config) -> None:
    from test_das_reglas_vigilancia import AHORA, HORA, RUTA_STOP, X, TokensVigilante, cot, foto
    prod = _prod(cfg)
    f = foto(lotes=[], latido=None, cotizacion=cot(last="28.00", ask="28.01", bid="27.99"))
    acciones = vigilancia.comprobar(f, prod, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    (env,) = [a for a in acciones if isinstance(a, EnviarOrden)]
    assert env.orden.ticker == X and (env.orden.stop, env.orden.precio) == (D("35.00"), D("35.70"))


def test_68_stop_manual_con_el_limite_del_tramo(cfg: Config, tmp_path: Path) -> None:
    """/stop en una posición SIN lotes (protección propia): límite del tramo del precio pedido."""
    b = Banco(_prod(cfg), tmp_path)
    b.preparar()
    acciones, motivo = b.decisor._stop_manual_sin_lotes(dataclasses.replace(b.decisor._pos(TICKER), neta_fills=-100,
                                                                           neta_das=-100), D("30"))
    (env,) = [a for a in acciones if isinstance(a, EnviarOrden)]
    assert motivo is None and (env.orden.stop, env.orden.precio) == (D("30"), D("30.60"))


def test_68_pref_en_el_neworder_del_stop(cfg: Config, tmp_path: Path) -> None:
    b = Banco(_prod(cfg, pref="SAGEPRO"), tmp_path)
    b.preparar()
    abrir_posicion(b)
    (stop,) = b.enviadas(*STOPS)
    assert stop.pref == "SAGEPRO"
    assert " Pref=SAGEPRO" in protocolo.cmd_neworder(stop)
    assert [x for x in b.canal.enviadas() if x.startswith("NEWORDER") and "STOPLMTP" in x and "Pref=SAGEPRO" in x]
    # producción: `pref` null → el stop no lleva Pref (queda preparado para probarlo el lunes)
    assert PRODUCCION["stops"]["pref"] is None and _prod(cfg).stops.get("pref") is None


def test_68_y_69_hojas_del_cuadro_validan() -> None:
    from test_das_decisiones_2oct_noche import _cuadro
    assert mod_config.validar(_cuadro(stops__limite_tramos=[[25, 9], [None, 2]],
                                      stops__banda_tramos=[[25, 19, 9], [50, 9, 4], [None, 5, 2]],
                                      stops__escalon_s=0.5, stops__pref="SAGEPRO")) == []
    for malo in ([[25, 9]], [[None, 9], [25, 2]], [[25, 9], [20, 4], [None, 2]], [[25, 0], [None, 2]], [], "9",
                 [[25, 9, 1], [None, 2]]):
        assert mod_config.validar(_cuadro(stops__limite_tramos=malo)), malo
    assert mod_config.validar(_cuadro(stops__banda_tramos=[[25, 19], [None, 5]]))
    assert mod_config.validar(_cuadro(stops__escalon_s=0))


# ═══════════════════════════════ decisión 69: emergencia escalonada ═══════════════════════════════
def test_69_pct_escalon_por_sesion_y_tramo(cfg: Config) -> None:
    prod = _prod(cfg).stops
    assert [stops.pct_escalon(prod, D(p), rth) for p, rth in
            (("10", False), ("10", True), ("30", False), ("30", True), ("80", False), ("80", True))] == \
        [D("19"), D("9"), D("9"), D("4"), D("5"), D("2")]
    assert stops.pct_escalon(cfg.stops, D("10"), True) is None              # fixture: sin banda_tramos


def test_69_ejemplo_literal_de_jaume_stop_10_escalones_y_techo_16_35(cfg: Config, tmp_path: Path) -> None:
    """Texto de Jaume: stop en 10 → límite 10,90 (+9 %). El precio pasa de 10,90 sin cerrar → compra AL ASK un escalón
    por encima del precio del momento (premercado, +19 %: ~13,05), otro escalón (~15,60)… hasta el TECHO 10,90 × 1,5 =
    16,35; ninguna orden pasa de ahí; por encima del techo la del techo se queda PUESTA y, si el precio vuelve, compra."""
    b = _banco_en(_prod(cfg), tmp_path, "9.20", 10.0, inicio=PM_INICIO)
    stop = _stop(b)
    assert (stop.stop, stop.precio) == (D("10.00"), D("10.90"))
    marca = b.marca()
    b.avanzar(1)
    b.cotizar(TICKER, "10.95", "11.00", "10.97", tam_ask=0)           # por encima del límite 10,90: al instante
    (r,) = _respaldos(b, desde=marca)
    assert (r.qty, r.precio, r.lado, r.tipo) == (100, D("13.06"), Lado.COMPRA, TipoOrden.LIMITE)   # 10,97 × 1,19
    assert _avisos(b.desde(marca), f"stop_sin_ejecutar:{TICKER}")[0].nivel is Nivel.MAXIMO
    b.avanzar(1)
    b.cotizar(TICKER, "13.05", "13.15", "13.10", tam_ask=0)
    assert b.orden(r.token).precio == D("15.59")                       # 13,10 × 1,19 = 15,589
    b.avanzar(1)
    b.cotizar(TICKER, "13.95", "14.05", "14.00", tam_ask=0)
    assert b.orden(r.token).precio == D("16.35")                       # 14 × 1,19 = 16,66 → techo
    b.avanzar(1)
    marca2 = b.marca()
    b.cotizar(TICKER, "16.95", "17.05", "17.00", tam_ask=0)            # sobre el techo: cisne negro
    b.avanzar(3)
    assert b.orden(r.token).estado is EstadoOrden.ACCEPTED and b.orden(r.token).precio == D("16.35")
    assert not [a for a in b.desde(marca2) if isinstance(a, (Reemplazar, Cancelar)) and a.token == r.token]
    assert _avisos(b.desde(marca2), f"stop_respaldo_techo:{TICKER}")[0].nivel is Nivel.MAXIMO
    assert max(_precios_enviados(b, r.token, marca)) == D("16.35")
    assert not [o for o in b.enviadas(desde=marca) if o.lado is Lado.COMPRA and o.precio and o.precio > D("16.35")]
    assert b.orden(stop.token).estado is EstadoOrden.CANCELED              # el stop se fue al ACEPTAR la compra
    b.cotizar(TICKER, "16.00", "16.10", "16.05", tam_ask=1000)         # el precio vuelve: compra en el techo
    b.tic_das()
    b.avanzar(2)
    assert b.pos().neta_fills == 0 and not b.enviadas(Proposito.VENTA_EXCESO)


def test_69_el_escalon_en_rth_es_el_de_rth(cfg: Config, tmp_path: Path) -> None:
    """RTH (09:30): el escalón ≤ 25 $ es +9 % (premercado +19 %)."""
    b = _banco_en(_prod(cfg), tmp_path, "9.20", 10.0)
    marca = b.marca()
    b.avanzar(1)
    b.cotizar(TICKER, "10.95", "11.00", "10.97", tam_ask=0)
    (r,) = _respaldos(b, desde=marca)
    assert r.precio == D("11.96")                                     # 10,97 × 1,09 = 11,957


def test_69_tramo_25_50_en_rth(cfg: Config, tmp_path: Path) -> None:
    """Valor de 30 $: stop en 30 → límite +2 % (30,60), techo 45,90; escalón RTH del tramo 25-50 (+4 %)."""
    b = _banco_en(_prod(cfg), tmp_path, "29.00", 30.0)
    assert (_stop(b).stop, _stop(b).precio) == (D("30.00"), D("30.60"))
    marca = b.marca()
    b.avanzar(1)
    b.cotizar(TICKER, "30.65", "30.75", "30.70", tam_ask=0)
    (r,) = _respaldos(b, desde=marca)
    assert r.precio == D("31.93")                                     # 30,70 × 1,04 = 31,928


def test_69_disparador_3_cinco_segundos_sin_ejecutar(cfg: Config, tmp_path: Path) -> None:
    """(3) el último ≥ disparo 5 s seguidos sin ningún fill (dentro del límite): respaldo a los 5 s, no antes."""
    b = _banco_en(_prod(cfg), tmp_path, "9.20", 10.0)
    marca = b.marca()
    b.cotizar(TICKER, "10.40", "10.60", "10.50", tam_ask=0)            # sobre el disparo, bajo el límite 10,90
    b.tic_das()
    b.avanzar(4)
    assert not _respaldos(b, desde=marca)
    b.avanzar(1.5)
    (r,) = _respaldos(b, desde=marca)
    assert r.precio == D("11.45")                                     # 10,50 × 1,09 = 11,445


def test_69_disparador_2_stop_muerto(cfg: Config, tmp_path: Path) -> None:
    """(2) la hija del stop (límite 10,90) la rechaza el bróker (tope del simulador: último × 1,03 = 10,815): stop
    MUERTO → la compra de emergencia sale AL INSTANTE (sin los 5 s) a 10,50 × 1,09 = 11,45; también la rechaza → UNA
    vez con la mitad del escalón (10,50 × 1,045 = 10,98), rechazada → aviso MÁXIMO «sin stop: PONER A MANO»."""
    b = _banco_en(_prod(cfg), tmp_path, "9.20", 10.0)
    b.das.tope_broker_pct = D("3")
    marca = b.marca()
    antes = b.ahora()
    b.cotizar(TICKER, "10.40", "10.60", "10.50", tam_ask=0)
    b.tic_das()
    assert b.ahora() == antes and anotaciones(b.desde(marca), "stop_muerto")
    assert [r.precio for r in _respaldos(b, desde=marca)] == [D("11.45"), D("10.98")]
    assert [a for a in b.desde(marca) if isinstance(a, Avisar) and a.nivel is Nivel.MAXIMO
            and "PONER A MANO" in a.texto]


def test_69_cuenta_larga_venta_del_exceso(cfg: Config, tmp_path: Path) -> None:
    """Llenan la compra de emergencia y el stop (el CANCEL del stop no llega a tiempo): cuenta LARGA → la venta del
    exceso de siempre la deja plana, con aviso."""
    b = _banco_en(_prod(cfg), tmp_path, "9.20", 10.0)
    stop = _stop(b)
    original = b.das._manejadores["CANCEL"]

    def cancel_mudo(self, p):
        o = b.estado.ordenes.get(stop.token)
        if len(p) == 2 and o is not None and p[1] in (str(o.id_das), str(o.id_madre)):
            return []
        return original(p)

    b.das._manejadores["CANCEL"] = types.MethodType(cancel_mudo, b.das)
    b.cotizar(TICKER, "10.40", "10.60", "10.50", tam_ask=0)
    b.tic_das()
    b.avanzar(6)
    assert len(_respaldos(b)) == 1
    marca = b.marca()
    b.cotizar(TICKER, "10.40", "10.45", "10.42", tam_ask=1000)        # llenan los dos (stop 10,90 y respaldo 11,45)
    b.tic_das()
    b.avanzar(3)
    assert b.enviadas(Proposito.VENTA_EXCESO, desde=marca)
    assert [a for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith(f"exceso:{TICKER}")]
    assert b.pos().neta_fills == 0


def test_69_vigilante_no_pisa_la_compra_de_emergencia(cfg: Config) -> None:
    """69 (8): ejecutor MUERTO, posición sin stop (se canceló al aceptar la compra) y la compra de emergencia viva y
    confirmada: el vigilante NO la da por descubierta ni pone su protección; sin conocerla, sí lo haría."""
    from test_das_reglas_vigilancia import AHORA, HORA, RUTA_STOP, X, TokensVigilante, foto, tok
    compra = MsgOrden(cruda="%IORDER …", id=21, token=tok(21), ticker=X, lado="B", tipo="L", qty=100, lvqty=100,
                      cxlqty=0, precio=D("16.35"), ruta="SAGEPRO", estado=EstadoOrden.ACCEPTED, hora="09:45:00",
                      origoid=0, cuenta=CUENTA, trader="T", order_src="CMDAPI", tif="DAY", pref="N/A", watch=True)
    desde = {X: AHORA - 100}
    con = foto(ordenes=(compra,), latido=None, descubierta_desde=desde, respaldo_tokens=frozenset({tok(21)}))
    assert vigilancia.descubiertas_por_ticker(con, cfg, HOY) == {}
    acciones = vigilancia.comprobar(con, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert not [a for a in acciones if isinstance(a, (EnviarOrden, Cancelar, Reemplazar))]
    sin = foto(ordenes=(compra,), latido=None, descubierta_desde=desde)
    acciones = vigilancia.comprobar(sin, cfg, AHORA, TokensVigilante(), HORA, RUTA_STOP, True)
    assert [a for a in acciones if isinstance(a, EnviarOrden) and a.orden.tipo is TipoOrden.STOP_LIMITE_PP]


def test_69_el_vigilante_lee_los_tokens_de_emergencia_del_diario(cfg: Config) -> None:
    """La foto del proceso vigilante lleva los tokens STOP_RESPALDO del diario del ejecutor."""
    import inspect
    from app.bot_das import vigilante as mod_vigilante
    fuente = inspect.getsource(mod_vigilante.VigilanteDAS._foto)
    assert "respaldo_tokens" in fuente and "STOP_RESPALDO" in fuente


# ═══════════════════════════════ decisión 70: cierre de halt de PM escalonado ═══════════════════════════════
def test_70_halt_de_premercado_cierra_escalonado_hasta_el_techo_3_5(cfg: Config, tmp_path: Path) -> None:
    """Halt H de premercado (parada 3,61, techo × 3,5 = 12,63) que reabre a 5,00, por encima del límite del stop (4,36):
    en lugar de UNA límite en 12,63 (el bróker la rechazaría: > último × 1,20) sale una compra a min(5,00 × 1,19, techo)
    y sube con el precio; a los 2 s NO se retira; nunca pasa del techo; sobre el techo, la orden se queda EN el techo,
    stops fuera y control humano (decisión 49)."""
    b = Banco(_prod(cfg), tmp_path, inicio=PM_INICIO)
    b.preparar()
    abrir_posicion(b, evento(momento=momento_de(PM_INICIO)))
    b.libro.halt(TICKER, "H", "08:00:30")
    b.cotizar(TICKER, "3.60", "3.62", "3.61")
    b.avanzar(2)
    techo = D("12.63")
    marca = b.marca()
    b.libro.reabrir(TICKER, D("5.00"))
    b.avanzar(1.2)
    b.cotizar(TICKER, "4.95", "5.05", "5.00", tam_ask=0)
    (c,) = b.enviadas(Proposito.HALT_PM_LIMITE, desde=marca)
    assert (c.precio, c.qty, c.tipo) == (D("5.95"), 100, TipoOrden.LIMITE) and c.ruta != "OPEN"
    b.avanzar(3)                                                        # pasa la verificación de los 2 s
    assert b.orden(c.token).estado is EstadoOrden.ACCEPTED and b.pos().estado is not EstadoTicker.CONTROL_HUMANO
    assert anotaciones(b.desde(marca), "halt_pm_escalando")
    b.cotizar(TICKER, "6.95", "7.05", "7.00", tam_ask=0)
    assert b.orden(c.token).precio == D("8.33")                       # 7 × 1,19
    b.avanzar(1)
    b.cotizar(TICKER, "10.95", "11.05", "11.00", tam_ask=0)
    assert b.orden(c.token).precio == techo                           # 13,09 → techo 12,63
    b.avanzar(1)
    marca2 = b.marca()
    b.cotizar(TICKER, "12.95", "13.05", "13.00", tam_ask=0)
    b.avanzar(3)
    assert b.orden(c.token).estado is EstadoOrden.ACCEPTED and b.orden(c.token).precio == techo
    assert not [a for a in b.desde(marca2) if isinstance(a, Cancelar) and a.token == c.token]
    assert b.pos().estado is EstadoTicker.CONTROL_HUMANO
    assert any(isinstance(a, Avisar) and a.nivel is Nivel.MAXIMO and a.clave == f"halt_pm_techo_vivo:{TICKER}"
               for a in b.desde(marca2))
    assert not [o for o in b.estado.ordenes.values() if o.ticker == TICKER and o.proposito in STOPS
                and o.estado in (EstadoOrden.ACCEPTED, EstadoOrden.SENDING)]
    assert max(_precios_enviados(b, c.token, marca)) == techo
    b.cotizar(TICKER, "12.00", "12.10", "12.05", tam_ask=1000)        # vuelve bajo el techo: llena
    b.tic_das()
    b.avanzar(2)
    assert b.pos().neta_fills == 0 and not b.enviadas(Proposito.VENTA_EXCESO)


def test_70_sin_banda_tramos_el_cierre_de_pm_es_el_de_siempre(cfg: Config, tmp_path: Path) -> None:
    """Fixture (sin `banda_tramos`): la compra al techo del T1 de siempre (decisión 46)."""
    from test_das_decisor import _halt_pm_mantener, _techo
    b = _halt_pm_mantener(cfg, tmp_path)
    marca = b.marca()
    b.libro.reabrir(TICKER, D("7.00"))
    b.avanzar(1.2)
    b.cotizar(TICKER, "6.95", "7.05", "7.00", tam_ask=1000)
    (c,) = b.enviadas(Proposito.HALT_PM_LIMITE, desde=marca)
    assert c.precio == _techo(b, cfg) and not anotaciones(b.desde(marca), "halt_pm_escalon_inicio")


# ═══════════════════════════════ decisión 71: halts ═══════════════════════════════
def _tp_vivo(b: Banco) -> None:
    from test_das_decisiones_2oct import _tp_vivo as tp
    tp(b)


def _cancel_mudo(b: Banco, veces: int) -> list:
    """DAS no contesta a los primeros `veces` CANCEL (de cualquier orden); luego sí."""
    original = b.das._manejadores["CANCEL"]
    vistos: list = []

    def mudo(self, p):
        vistos.append(p)
        if len(vistos) <= veces:
            return []
        return original(p)

    b.das._manejadores["CANCEL"] = types.MethodType(mudo, b.das)
    return vistos


def test_71_a_cancel_de_la_salida_sin_confirmar_reintenta_dos_veces_y_avisa(banco: Banco) -> None:
    b = banco
    abrir_posicion(b)
    _tp_vivo(b)
    tp = b.enviadas(Proposito.TP_AGREGAR)[0]
    _cancel_mudo(b, 99)
    marca = b.marca()
    b.libro.halt(TICKER, "H", "09:31:00")
    b.cotizar(TICKER, "3.40", "3.42", "3.41")
    b.avanzar(20)
    tras = b.desde(marca)
    cancels = [a for a in tras if isinstance(a, Cancelar) and a.token == tp.token]
    assert len(cancels) == 3                                            # el intento + 2 reintentos, nunca un bucle
    assert len(anotaciones(tras, "halt_cancel_reintento")) == 2
    (aviso,) = _avisos(tras, f"halt_cancel_sin_confirmar:{TICKER}")
    assert aviso.nivel is Nivel.MAXIMO
    assert b.decisor._comprando(TICKER) == 50                          # sigue contando como compra viva
    b.avanzar(30)
    assert len([a for a in b.desde(marca) if isinstance(a, Cancelar) and a.token == tp.token]) == 3


def test_71_a_cancel_confirmado_al_segundo_intento_sin_aviso(banco: Banco) -> None:
    b = banco
    abrir_posicion(b)
    _tp_vivo(b)
    tp = b.enviadas(Proposito.TP_AGREGAR)[0]
    _cancel_mudo(b, 1)
    marca = b.marca()
    b.libro.halt(TICKER, "H", "09:31:00")
    b.cotizar(TICKER, "3.40", "3.42", "3.41")
    b.avanzar(10)
    tras = b.desde(marca)
    assert len([a for a in tras if isinstance(a, Cancelar) and a.token == tp.token]) == 2
    assert b.orden(tp.token).estado is EstadoOrden.CANCELED
    assert anotaciones(tras, "halt_cancel_confirmado") and not _avisos(tras, "halt_cancel_sin_confirmar")


@pytest.mark.sin_silencio
@pytest.mark.parametrize("escalonado", [False, True], ids=["fixture", "produccion"])
def test_71_b_redecision_de_60_s_en_premercado_no_duplica_la_limite(cfg: Config, tmp_path: Path,
                                                                      escalonado: bool) -> None:
    """`halts.silencio = false` en PREMERCADO: la límite de salida sale durante el halt y la redecisión cada 60 s NO
    manda otra mientras esa vive (ni con la confirmación del stop en vuelo)."""
    c = _prod(cfg) if escalonado else cfg
    b = Banco(c, tmp_path, inicio=PM_INICIO)
    b.preparar()
    abrir_posicion(b, evento(momento=momento_de(PM_INICIO)))
    marca = b.marca()
    b.libro.halt(TICKER, "H", "08:00:30")
    b.cotizar(TICKER, "4.08", "4.10", "4.09", tam_ask=0)              # sobre el stop: cerrar con la límite de PM
    b.avanzar(250)                                                      # cuatro redecisiones
    assert len(anotaciones(b.desde(marca), "halt_decision")) >= 4
    assert len(b.enviadas(Proposito.HALT_PM_LIMITE, desde=marca)) == 1
    (pm,) = b.enviadas(Proposito.HALT_PM_LIMITE, desde=marca)
    assert b.orden(pm.token).estado is EstadoOrden.ACCEPTED


@pytest.mark.parametrize("silencio", [True, False])
def test_71_c_la_reapertura_se_trata_por_evento_al_instante(cfg: Config, tmp_path: Path, silencio: bool) -> None:
    """La reapertura (el TA nuevo de DAS) se trata en cuanto llega: la salida decidida sale en ese mismo mensaje, sin
    esperar al ciclo de 60 s de `halt_decidir`."""
    c = cfg_con(cfg, halts={**cfg.halts, "silencio": silencio})
    b = Banco(c, tmp_path)
    b.preparar()
    abrir_posicion(b)
    b.libro.halt(TICKER, "H", "09:31:00")
    b.cotizar(TICKER, "3.40", "3.42", "3.41")
    b.avanzar(5)
    b.libro.reabrir(TICKER, D("3.41"))
    marca = b.marca()
    antes = b.ahora()
    b.cotizar(TICKER, "3.40", "3.42", "3.41")
    b.dar(b.das.recibir(f"GET SymStatus {TICKER}"))                    # el mensaje de DAS con el TA de reapertura
    tras = b.desde(marca)
    assert anotaciones(tras, "halt_reapertura") and b.ahora() == antes
    cierres = [o for o in b.enviadas(desde=marca) if o.lado is Lado.COMPRA and o.proposito not in STOPS]
    if silencio:
        assert cierres                                                  # decisión 57: al ask, ya
    assert not [a for a in tras if (getattr(a, "clave", "") or "").startswith("halt_decidir") and getattr(a, "en_s", 0) >= 60]


# ═══════════════════════════════ decisión 72: cuadro de producción ═══════════════════════════════
def test_72_cuadro_de_produccion_solo_trae_lo_que_difiere_y_carga() -> None:
    crudo = json.loads(Path(mod_config.RUTA_CUADRO_PRODUCCION).read_text(encoding="utf-8"))
    hojas = {k for k in crudo if not k.startswith("_")}
    assert hojas == {"stops", "rutas"}
    st = crudo["stops"]
    assert st["limite_tramos"] == [[25, 9], [None, 2]]
    assert st["banda_tramos"] == [[25, 19, 9], [50, 9, 4], [None, 5, 2]]
    assert (st["techo_pct"], st["respaldo"], st["escalon_s"], st["pref"]) == (50, True, 0.5, None)
    assert crudo["rutas"] == {"cruzar": {"lt_1_desde_0700": "MIAX"}}
    from test_das_config import RUTA_EJEMPLO
    base = json.loads(Path(RUTA_EJEMPLO).read_text(encoding="utf-8"))
    junto = mod_config.aplicar_cuadro_produccion(base, crudo)
    assert junto["rutas"]["cruzar"]["ge_1"] == base["rutas"]["cruzar"]["ge_1"]       # mezcla hoja a hoja
    junto["sha256"] = mod_config.hash_canonico({k: v for k, v in junto.items() if k != "sha256"})
    assert mod_config.validar(junto) == []


def test_72_exportar_aplica_produccion_por_defecto_y_carga(backend, dir_bot) -> None:
    from test_das_config import RUTA_EJEMPLO, _fila_backend
    backend.responder({"total": 1, "estrategias": [_fila_backend("s-1")]})
    assert mod_config.main(["exportar", "--url", backend.url, "--defaults", str(RUTA_EJEMPLO)]) == 0
    destino = dir_bot / "config" / mod_config.NOMBRE_FICHERO_CONFIG
    crudo = json.loads(destino.read_text(encoding="utf-8"))
    assert mod_config.validar(crudo) == []
    assert crudo["stops"]["limite_tramos"] == [[25, 9], [None, 2]] and crudo["stops"]["respaldo"] is True
    assert crudo["stops"]["techo_pct"] == 50 and crudo["stops"]["escalon_s"] == 0.5 and crudo["stops"]["pref"] is None
    assert crudo["stops"]["banda_tramos"] == [[25, 19, 9], [50, 9, 4], [None, 5, 2]]
    assert crudo["rutas"]["cruzar"]["lt_1_desde_0700"] == "MIAX"
    cfg = mod_config.cargar(destino, CUENTA)
    assert stops.niveles(D("10"), cfg.stops).limite == D("10.90")
    assert precios.ruta(cfg.rutas, "cruzar", D("0.50"), datetime(2026, 10, 5, 8, 0, tzinfo=ET)) == "MIAX"
    # con --sin-produccion, los defaults tal cual
    assert mod_config.main(["exportar", "--url", backend.url, "--defaults", str(RUTA_EJEMPLO), "--sin-produccion"]) == 0
    crudo = json.loads(destino.read_text(encoding="utf-8"))
    assert "limite_tramos" not in crudo["stops"] and crudo["rutas"]["cruzar"]["lt_1_desde_0700"] == "EDGA"


from test_das_config import backend  # noqa: E402,F401 — fixture del puente `exportar` (dir_bot, de conftest)
