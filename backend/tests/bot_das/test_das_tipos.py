"""tipos.py: lo que DAS no debe ver jamás, el tick, las constantes VIGENTES y el fichero de ejemplo.

Cada fila de las tablas cita la regla del libro (riesgos 21 y 32): si alguien
cambia un valor en `tipos.py` o en `config_ejemplo.json` sin cambiar el libro,
aquí se ve. El hash canónico de la config queda FIJADO en este fichero (lote 0).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

import pytest

from app.bot_das import VERSION, tipos
from app.bot_das.tipos import (
    Accion, Anotar, Avisar, Cancelar, CancelarTicker, ClaseSalida, Comando, Config, ConfigNueva, Consultar,
    Cotizacion, Cuenta, DeDAS, Desprogramar, EnviarOrden, EstadoBot, EstadoBS, EstadoLote, EstadoOrden,
    EstadoSimbolo, EstadoTicker, EstrategiaConfig, Fase, FaseIntento, Ficha, Fill, Grupo, HiloCaido,
    IntentoEntrada, InvalidarSerie, Lado, Locate, LocateComprar, LocateInquire, LocateOferta, Lote, Mensaje,
    MensajeDAS, MsgOrden, MsgOrderAct, MsgTrade, Nivel, NivelesStop, Orden, OrdenNueva, Origen,
    PedirAlSupervisor, PosicionTicker, Programar, Proposito, PublicarFoto, Reemplazar, Registro, Salir, Senal,
    SenalRecibida, StopDeseado, Suscribir, Temporizador, Tic, TipoOrden, al_tick, en_tick, tick_de,
)

RUTA_CONFIG = Path(__file__).parent / "fixtures" / "config_ejemplo.json"
D = Decimal


def hash_canonico(obj) -> str:
    """FIJADO por el lote 0 (el lote B lo implementa igual en config.hash_canonico)."""
    canon = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canon).hexdigest()


def _orden(**cambios) -> OrdenNueva:
    base = dict(token=100_269_001, lado=Lado.CORTO, ticker="XYZ", ruta="SAGEREB", qty=1200,
                tipo=TipoOrden.LIMITE, precio=D("3.45"))
    base.update(cambios)
    return OrdenNueva(**base)


# ── OrdenNueva.__post_init__ (injerto A §8.2) ─────────────────────────────
def test_version_del_paquete():
    """R-O-01 + R2-FUE-1: subida a 2026.09.27 para que el «hola» rechace a un enlace anterior a F-01 (EventoLigero)."""
    assert VERSION == "2026.09.27"   # R-O-01: va al diario en cada arranque
    assert tuple(int(x) for x in VERSION.split(".")) > (2026, 9, 26)   # R2-FUE-1: posterior al enlace de c3a07c9b


def test_orden_limite_valida_y_defaults():
    o = _orden(post_only=True)
    assert (o.tif, o.post_only, o.pref, o.version) == ("DAY+", True, None, 0)
    assert o.proposito is Proposito.DESCONOCIDA and o.lote_id is None and o.nivel is None and o.stop is None


def test_orden_mercado_valida():
    o = _orden(tipo=TipoOrden.MERCADO, precio=None)
    assert o.precio is None and o.stop is None


def test_orden_stoplmtp_valida_compra():
    o = _orden(lado=Lado.COMPRA, tipo=TipoOrden.STOP_LIMITE_PP, stop=D("10.00"), precio=D("15.00"),
               proposito=Proposito.STOP, nivel=D("10.00"))
    assert o.stop == D("10.00") and o.precio == D("15.00")


def test_orden_stoplmtp_limite_igual_al_disparo_se_admite():
    o = _orden(lado=Lado.COMPRA, tipo=TipoOrden.STOP_LIMITE_PP, stop=D("10.00"), precio=D("10.00"))
    assert o.precio == o.stop


@pytest.mark.parametrize("cambios", [
    pytest.param(dict(qty=100.0), id="qty-float"),
    pytest.param(dict(qty=1199.0), id="qty-float-entero-del-Evento-l.1208"),
    pytest.param(dict(qty=0), id="qty-cero"),
    pytest.param(dict(qty=True), id="qty-bool"),
    pytest.param(dict(qty=-100), id="qty-negativa"),
    pytest.param(dict(qty="100"), id="qty-texto"),
    pytest.param(dict(qty=D("100")), id="qty-Decimal"),
    pytest.param(dict(precio=D("3.455")), id="limite-fuera-de-tick-ge-1$-regla-612"),
    pytest.param(dict(precio=D("0.12345")), id="limite-fuera-de-tick-lt-1$-0.0001"),
    pytest.param(dict(precio=None), id="limite-sin-precio"),
    pytest.param(dict(precio=D("0")), id="limite-precio-cero"),
    pytest.param(dict(precio=D("-3.45")), id="limite-precio-negativo"),
    pytest.param(dict(precio=D("NaN")), id="limite-precio-NaN"),
    pytest.param(dict(lado=Lado.COMPRA, tipo=TipoOrden.STOP_LIMITE_PP, stop=D("10.30"), precio=D("10.20")),
                 id="STOPLMTP-compra-limite-bajo-disparo"),
    pytest.param(dict(lado=Lado.COMPRA, tipo=TipoOrden.STOP_LIMITE_PP, stop=None, precio=D("10.30")),
                 id="STOPLMTP-sin-disparo"),
    pytest.param(dict(lado=Lado.COMPRA, tipo=TipoOrden.STOP_LIMITE_PP, stop=D("10.00"), precio=None),
                 id="STOPLMTP-sin-limite"),
    pytest.param(dict(lado=Lado.COMPRA, tipo=TipoOrden.STOP_LIMITE_PP, stop=D("10.005"), precio=D("10.30")),
                 id="STOPLMTP-disparo-fuera-de-tick"),
    pytest.param(dict(lado=Lado.COMPRA, tipo=TipoOrden.STOP_LIMITE_PP, stop=D("10.00"), precio=D("10.301")),
                 id="STOPLMTP-limite-fuera-de-tick"),
    pytest.param(dict(lado=Lado.VENTA, tipo=TipoOrden.STOP_LIMITE_PP, stop=D("10.00"), precio=D("10.10")),
                 id="L0-03-STOPLMTP-venta-limite-sobre-disparo"),
    pytest.param(dict(lado=Lado.CORTO, tipo=TipoOrden.STOP_LIMITE_PP, stop=D("10.00"), precio=D("10.01")),
                 id="L0-03-STOPLMTP-corto-limite-sobre-disparo"),
    pytest.param(dict(stop=D("3.40")), id="L0-03-LMT-con-disparo"),
    pytest.param(dict(tipo=TipoOrden.MERCADO), id="MKT-con-precio"),
    pytest.param(dict(tipo=TipoOrden.MERCADO, precio=None, stop=D("10.00")), id="MKT-con-stop"),
    pytest.param(dict(tipo=TipoOrden.MERCADO, precio=None, post_only=True), id="PostOnly-sin-limite-MKT"),
    pytest.param(dict(lado=Lado.COMPRA, tipo=TipoOrden.STOP_LIMITE_PP, stop=D("10.00"), precio=D("10.30"),
                      post_only=True), id="PostOnly-sin-limite-STOPLMTP"),
    pytest.param(dict(token=2**31), id="token-fuera-de-int32-alto-manual-L595"),
    pytest.param(dict(token=-(2**31) - 1), id="token-fuera-de-int32-bajo"),
    pytest.param(dict(token=True), id="token-bool"),
    pytest.param(dict(token=100269001.0), id="token-float"),
])
def test_orden_nueva_rechaza(cambios):
    with pytest.raises(ValueError):
        _orden(**cambios)


@pytest.mark.parametrize("lado", [Lado.VENTA, Lado.CORTO])
@pytest.mark.parametrize("limite", [D("9.90"), D("10.00")], ids=["bajo-disparo", "igual-disparo"])
def test_L0_03_stoplmtp_venta_con_limite_no_superior_al_disparo_se_admite(lado, limite):
    """L0-03: la regla simétrica solo rechaza límite > disparo; ≤ sigue valiendo."""
    o = _orden(lado=lado, tipo=TipoOrden.STOP_LIMITE_PP, stop=D("10.00"), precio=limite)
    assert o.precio <= o.stop


def test_orden_nueva_es_inmutable():
    o = _orden()
    with pytest.raises(FrozenInstanceError):
        o.qty = 5   # type: ignore[misc]


# ── tick (regla 612) ────────────────────────────────────────────────────
@pytest.mark.parametrize("precio,arriba,esperado", [
    pytest.param(D("0.0001"), True, D("0.0001"), id="0.0001-arriba"),
    pytest.param(D("0.0001"), False, D("0.0001"), id="0.0001-abajo"),
    pytest.param(D("0.9999"), True, D("0.9999"), id="0.9999-arriba"),
    pytest.param(D("0.9999"), False, D("0.9999"), id="0.9999-abajo"),
    pytest.param(D("1.0"), True, D("1.00"), id="1.0-arriba"),
    pytest.param(D("1.0"), False, D("1.00"), id="1.0-abajo"),
    pytest.param(D("1.005"), True, D("1.01"), id="1.005-arriba-regla-612"),
    pytest.param(D("1.005"), False, D("1.00"), id="1.005-abajo-regla-612"),
    pytest.param(D("0.99995"), True, D("1.0000"), id="0.99995-arriba-cruza-el-dolar"),
    pytest.param(D("0.99995"), False, D("0.9999"), id="0.99995-abajo"),
    pytest.param(D("0.12345"), True, D("0.1235"), id="penny-arriba"),
    pytest.param(D("0.12345"), False, D("0.1234"), id="penny-abajo"),
    pytest.param(D("10.001"), True, D("10.01"), id="10.001-arriba"),
    pytest.param(D("10.3103"), True, D("10.32"), id="10.3103-arriba"),
])
def test_al_tick(precio, arriba, esperado):
    resultado = al_tick(precio, arriba)
    assert resultado == esperado
    assert isinstance(resultado, Decimal) and en_tick(resultado)


@pytest.mark.parametrize("precio,tick", [
    pytest.param(D("1"), D("0.01"), id="1$-centimos"),
    pytest.param(D("100"), D("0.01"), id="100$-centimos"),
    pytest.param(D("0.9999"), D("0.0001"), id="bajo-1$-diezmilesimas"),
    pytest.param(D("0.5"), D("0.0001"), id="0.5$-diezmilesimas"),
])
def test_tick_de(precio, tick):
    assert tick_de(precio) == tick


@pytest.mark.parametrize("precio,esperado", [
    pytest.param(D("10.30"), True, id="10.30"),
    pytest.param(D("10.3"), True, id="10.3"),
    pytest.param(D("10.305"), False, id="10.305"),
    pytest.param(D("0.1234"), True, id="0.1234"),
    pytest.param(D("0.12345"), False, id="0.12345"),
    pytest.param(D("1.0000"), True, id="1.0000"),
    pytest.param(D("0"), False, id="cero"),
    pytest.param(D("-1"), False, id="negativo"),
    pytest.param(D("NaN"), False, id="NaN"),
    pytest.param(D("Infinity"), False, id="inf"),
])
def test_en_tick(precio, esperado):
    assert en_tick(precio) is esperado


@pytest.mark.parametrize("precio", [D("NaN"), D("Infinity"), D("-Infinity")], ids=["NaN", "inf", "-inf"])
def test_tick_de_y_al_tick_rechazan_no_finitos(precio):
    with pytest.raises(ValueError):
        tick_de(precio)
    with pytest.raises(ValueError):
        al_tick(precio, True)


# ── constantes por defecto = tabla de reglas VIGENTES (riesgos 21 y 32) ──
@pytest.mark.parametrize("nombre,esperado", [
    pytest.param("STOP_LIMITE_PCT", D("50"), id="R-C-01-v4-stop-unico-limite-L+50%"),
    pytest.param("STOP_PROTECCION_PCT", D("25"), id="R-C-10-(4)-proteccion-20-30%"),
    pytest.param("STOP_MARGEN_BAJO_LIMIT_UP_PCT", D("1.5"), id="R-F-02-bajo-la-banda-1-2%"),
    pytest.param("ENTRADA_AGREGAR_S", 60, id="R-B-01-v3-agregar-60s"),
    pytest.param("ENTRADA_TOPE_CAIDA_BID_PCT", D("3"), id="R-B-01-v3-tope-caida-bid-3%"),
    pytest.param("ENTRADA_CRUCE_BAJO_BID_PCT", D("0.5"), id="R-B-01-v3-cruce-bid-0.5%"),
    pytest.param("ENTRADA_CADUCIDAD_S", 60, id="R-B-04-caducidad-60s"),
    pytest.param("ENTRADA_RETRASO_MAX_PCT", D("1"), id="R-A-01-retraso-1%-provisional"),
    pytest.param("ENTRADA_DISTANCIA_ULTIMO_BID_PCT", None, id="B20-bis-apagada-decision-11"),
    pytest.param("ENTRADA_REINTENTOS_RECHAZO", 2, id="R-B-07-2-reintentos"),
    pytest.param("SALIDA_ANTICIPO_S", 60, id="R-D-08-anticipo-60s"),
    pytest.param("EOD_COMPROBAR_DESPUES_S", 30, id="R-D-02-comprobar-+30s"),
    pytest.param("TP_TECHO_ASK_PCT", D("3"), id="R-D-03-v2-techo-3%"),
    pytest.param("CERRAR_TODO_TECHO_PCT", D("5"), id="R-D-06-techo-5%"),
    pytest.param("CERRAR_TODO_REINTENTOS", 2, id="R-D-06-2-reintentos"),
    pytest.param("PERSEGUIR_ASK_MAX", 3, id="F5-correccion-11-max-3-REPLACE"),
    pytest.param("HALT_K_MAX", 3, id="R-F-01-k-max-3"),
    pytest.param("HALT_DISTANCIA_BANDA_K2_PCT", D("4"), id="R-F-01-banda-k2-3-5%"),
    pytest.param("HALT_PRIMERA_VELA_MAX_PCT", D("6"), id="R-F-01/03/04-primera-vela-6%"),
    pytest.param("HALT_T1_SUBIDA_MAX_PCT", D("250"), id="R-F-05-T1-250%"),
    pytest.param("HALT_ENVIAR_ANTES_FIN_S", 60, id="R-F-01-OPEN-60s-antes"),
    pytest.param("LOCATES_TOPE_GASTO_PCT", D("3"), id="R-H-03-tope-3%"),
    pytest.param("LOCATES_UMBRAL_ULTIMO_PAQUETE_PCT", D("30"), id="H6-ultimo-paquete-30%"),
    pytest.param("LOCATES_INQUIRE_S", 3.0, id="manual-L2000-inquire-3s"),
    pytest.param("MODO_SEGURIDAD_PRECIO_MIN", D("5"), id="R-I-04-precio-5$"),
    pytest.param("MODO_SEGURIDAD_DOLLAR_VOLUME_MIN", D("2000000"), id="R-I-04-2M$"),
    pytest.param("FEED_PREALERTA_S", 30, id="R-J-01-prealerta-30s"),
    pytest.param("FEED_EMERGENCIA_S", 60, id="R-J-01-emergencia-60s"),
    pytest.param("DAS_RECONEXION_S", (2.0, 4.0, 8.0, 16.0), id="R-J-02-2/4/8/16"),
    pytest.param("DAS_RECONEXION_TOPE_S", 30.0, id="R-J-02-luego-30s"),
    pytest.param("DAS_AVISO_CADA_S", 300, id="R-J-02-(3)-aviso-5min"),
    pytest.param("RELANZAR_S", (1.0, 2.0, 5.0, 10.0), id="R-J-04-v2-relanzar-1/2/5/10"),
    pytest.param("LATIDO_S", 1.0, id="R-J-04-v2-latido-1s"),
    pytest.param("COLGADO_S", 3.0, id="R-J-04-v2-colgado-3s"),
    pytest.param("PING_EXTERNO_S", 60, id="R-J-05-ping-60s"),
    pytest.param("PING_FALLOS_ALARMA", 3, id="R-J-05-3-fallos"),
    pytest.param("RELOJ_NEGARSE_S", 2.0, id="R-J-07-negarse-2s"),
    pytest.param("RELOJ_AVISO_S", 0.5, id="R-J-07-aviso-0.5s"),
    pytest.param("DISCO_MIN_GB", 5, id="R-J-07-disco-5GB"),
    pytest.param("BARRIDO_TRAS_FILL_S", 1.0, id="R-K-01-barrido-tras-fill-1s"),
    pytest.param("BARRIDO_CON_POSICIONES_S", 2.0, id="R-K-01-con-posiciones-2s"),
    pytest.param("BARRIDO_SIN_NADA_S", 10.0, id="R-K-01-sin-nada-10s"),
    pytest.param("BARRIDO_VENTANA_TRAS_FILL_S", 60.0, id="R-K-01-ventana-60s"),
    pytest.param("RECONCILIACION_CADUCA_S", 30.0, id="R-K-03-caduca-30s"),
    pytest.param("BS_PRIMEROS_INFORMES", 5, id="R-G-01-v2-5-primeros"),
    pytest.param("BS_CADENCIA_INICIAL_S", 60, id="R-G-01-v2-cada-1min"),
    pytest.param("BS_CADENCIA_DESPUES_S", 300, id="R-G-01-v2-luego-5min"),
    pytest.param("FILTRO_PRINTS_MS", 20, id="R-A-06-prints-20ms"),
    pytest.param("IPO_DIAS", 30, id="R-A-03-v2-IPO-30d"),
    pytest.param("SPAC_SIC", ("6770",), id="R-A-03-v2-SPAC-6770"),
    pytest.param("OPA_BANDA_MIN", 30, id="R-A-03-v2-OPA-30min"),
    pytest.param("OPA_RANGO_MAX_PCT", D("1.5"), id="R-A-03-v2-OPA-1.5%"),
    pytest.param("OPA_DOLARES_MIN", D("100000"), id="R-A-03-v2-OPA-100k$"),
    pytest.param("STOP_REINTENTOS", 5, id="R-C-03-(1)-5-intentos"),
    pytest.param("STOP_VENTANA_MIN", 5, id="R-C-03-(3)-ventana-5min-solo-registro"),
    pytest.param("STOP_COMPROBACION_S", 1.0, id="R-C-04-1s"),
    pytest.param("STOP_DEBOUNCE_S", 0.3, id="F1.6-debounce-0.3s"),
    pytest.param("PLAN_B_LATIDO_S", 3.0, id="R-C-08-plan-B-latido-3s"),
    pytest.param("PLAN_B_DESCUBIERTA_S", 5.0, id="R-C-08-plan-B-descubierta-5s"),
    pytest.param("MAX_LV1", 100, id="manual-L1996-Lv1-100"),
    pytest.param("COLA_AVISOS_TOPE", 10_000, id="§6.1-cola-avisos-10000"),
    pytest.param("COLA_SALIDA_TOPE", 1_000, id="§6.1-cola-salida-1000"),
    pytest.param("TICK_GE_1", D("0.01"), id="regla-612-tick-centimos"),
    pytest.param("TICK_LT_1", D("0.0001"), id="regla-612-tick-diezmilesimas"),
])
def test_constante_vigente(nombre, esperado):
    valor = getattr(tipos, nombre)
    assert valor == esperado
    assert type(valor) is type(esperado)   # Decimal donde toca, nunca float en porcentajes de precio


def test_stop_unico_sin_constantes_del_par():
    """R-C-01 v4 (Jaume 29-sep, stop único): un solo margen (límite L + 50 %, > 0, lo mismo exige config.validar);
    las constantes del principal y la emergencia de v3 ya no existen (nadie puede usarlas por error)."""
    assert tipos.STOP_LIMITE_PCT > 0
    for vieja in ("STOP_PRINCIPAL_LIMITE_PCT", "STOP_EMERGENCIA_DISPARO_PCT", "STOP_EMERGENCIA_LIMITE_PCT"):
        assert not hasattr(tipos, vieja), vieja


# ── enumeraciones ───────────────────────────────────────────────────────
def test_fases_sin_demo():
    assert [f.value for f in Fase] == ["sombra", "canario", "real"]   # R-O-03: demo DESCARTADA 24-sep


def test_lados_y_tipos_del_manual():
    assert {l.value for l in Lado} == {"B", "S", "SS"}                       # manual L671-694
    assert {t.value for t in TipoOrden} == {"LMT", "MKT", "STOPLMTP"}        # manual L618-624


def test_estados_de_orden_conjunto_cerrado():
    assert {e.value for e in EstadoOrden} == {"Closed", "Hold", "Sending", "Accepted", "Canceled", "Rejected",
                                              "Executed", "Partial", "Triggered", "?"}   # manual L379-405


def test_origenes_niveles_grupos():
    assert [o.value for o in Origen] == [1, 2, 3] and Origen.EJECUTOR == 1 and Origen.VIGILANTE == 2
    assert [n.value for n in Nivel] == [1, 2, 3]                              # R-M-01
    assert {g.value for g in Grupo} == {"A", "B"}                             # R-M-05


def test_propositos_y_clases_de_salida():
    assert len(Proposito) == 17 and Proposito.DESCONOCIDA.value == "desconocida"
    assert {p.value for p in Proposito} == {                                  # R-C-01 v4: «stop» sustituye al par
        "entrada_agregar", "entrada_cruce", "stop", "stop_proteccion", "tp_agregar",
        "tp_cruce", "hora_agregar", "hora_ask", "salida_motor_agregar", "salida_motor_cruce", "halt_open",
        "halt_pm_limite", "halt_banda", "venta_exceso", "cierre_humano", "cierre_reinicio", "desconocida"}
    assert {c.value for c in ClaseSalida} == {"tp", "hora", "eod", "stop", "stop_lote", "reduce", "motor", "halt",
                                              "bs", "daily_limit"}
    assert {e.value for e in EstadoTicker} == {"normal", "pausado", "cisne_negro", "sin_simbolo", "halt",
                                               "control_humano"}
    assert {e.value for e in EstadoLote} == {"abriendo", "abierto", "cerrando", "cerrado", "cancelado"}
    assert {f.value for f in FaseIntento} == {"agregando", "cancelando", "cruzando", "terminado"}


def test_enums_de_texto_comparan_con_su_valor():
    assert Fase.SOMBRA == "sombra" and Lado.CORTO == "SS" and Proposito.STOP == "stop"
    assert not hasattr(Proposito, "STOP_PRINCIPAL") and not hasattr(Proposito, "STOP_EMERGENCIA")   # Jaume 29-sep


# ── acciones, mensajes y dataclasses ────────────────────────────────────
ACCIONES = (EnviarOrden, Cancelar, CancelarTicker, Reemplazar, InvalidarSerie, Consultar, Suscribir,
            LocateInquire, LocateComprar, LocateOferta, Avisar, Anotar, Programar, Desprogramar, PublicarFoto,
            PedirAlSupervisor, Salir)
MENSAJES = (SenalRecibida, DeDAS, Tic, Temporizador, ConfigNueva, tipos.ConexionDAS, HiloCaido,
            tipos.ComandoRecibido, tipos.OrdenDescartada)   # D2a-06: +OrdenDescartada


def test_las_17_acciones_del_documento():
    assert set(Accion.__subclasses__()) == set(ACCIONES) and len(ACCIONES) == 17
    for clase in ACCIONES:
        assert dataclasses.is_dataclass(clase) and clase.__dataclass_params__.frozen


def test_los_9_mensajes_del_documento():
    """Los 8 de §2 más `OrdenDescartada` (D2a-06)."""
    assert set(Mensaje.__subclasses__()) == set(MENSAJES) and len(MENSAJES) == 9
    for clase in MENSAJES:
        assert clase.__dataclass_params__.frozen


def test_mensajes_das_conservan_cruda_y_son_inmutables():
    for clase in MensajeDAS.__subclasses__():
        assert clase.__dataclass_params__.frozen
        assert dataclasses.fields(clase)[0].name == "cruda"
    assert len(MensajeDAS.__subclasses__()) == 24
    act = MsgOrderAct(cruda="%OrderAct 56 Accept SS XYZ 1200 3.45 SAGEREB 09:31:02  100269001", id=56, accion="Accept",
                      lado="SS", ticker="XYZ", qty=1200, precio=D("3.45"), ruta="SAGEREB", hora="09:31:02", notas="",
                      token=100_269_001)
    with pytest.raises(FrozenInstanceError):
        act.qty = 1   # type: ignore[misc]


def test_posicion_neta_es_la_de_los_fills():
    pos = PosicionTicker(ticker="XYZ", neta_fills=-1200, neta_das=-1000)
    assert pos.neta == -1200                       # corrección 2 del juez: fills = verdad inmediata
    assert pos.estado is EstadoTicker.NORMAL and pos.lotes == {} and pos.version_stops == 0


def test_estado_bot_defaults_independientes(estado_vacio):
    otro = EstadoBot(fase=Fase.SOMBRA, dia=estado_vacio.dia)
    estado_vacio.senales_vistas.add("XYZ|prueba-1|2026-09-25 09:30:00|entrada")
    estado_vacio.posiciones["XYZ"] = PosicionTicker(ticker="XYZ")
    assert otro.senales_vistas == set() and otro.posiciones == {}
    assert isinstance(estado_vacio.cuenta, Cuenta) and estado_vacio.cuenta is not otro.cuenta
    assert estado_vacio.modo_degradado == set() and estado_vacio.gasto_locates_dia == D("0")
    assert estado_vacio.ultimo_seq_token == 0 and estado_vacio.qty_corto_negativa is None


def test_lote_e_intento_defaults():
    lote = Lote(id="XYZ|prueba-1|2026-09-25 09:30:00|entrada", strategy_id="prueba-1", estrategia="PM (A) prueba",
                ticker="XYZ", direccion="Short", pedidas=1200)
    assert lote.estado is EstadoLote.ABRIENDO and lote.llenas == 0 and lote.precio_medio == D("0")
    assert not hasattr(lote, "principal_consumido") and lote.version_estrategia == ""   # Jaume 29-sep: stop único
    intento = IntentoEntrada(ticker="XYZ", lotes=[lote.id], qty_total=1200, bid_senal=D("3.44"), ask_senal=D("3.46"),
                             precio_senal=D("3.45"), t_cierre_vela=1000.0, t_limite=1060.0)
    assert intento.fase is FaseIntento.AGREGANDO and intento.cfg_congelada is None


@pytest.mark.parametrize("clase,campos", [
    pytest.param(OrdenNueva, ["token", "lado", "ticker", "ruta", "qty", "tipo", "precio", "stop", "tif", "post_only",
                              "pref", "proposito", "lote_id", "nivel", "version"], id="OrdenNueva"),
    pytest.param(Orden, ["token", "ticker", "lado", "tipo", "qty", "precio", "stop", "ruta", "proposito", "lote_id",
                         "nivel", "origen", "id_das", "estado", "lvqty", "llenas", "cxlqty", "tipo_das_crudo",
                         "enviada_en", "ultima_act", "notas", "version", "intentos", "primer_intento_en"], id="Orden"),
    pytest.param(Fill, ["id_trade", "token", "id_orden", "ticker", "lado", "qty", "precio", "ruta", "hora", "liq",
                        "ecn_fee", "simulado"], id="Fill"),
    pytest.param(Lote, ["id", "strategy_id", "estrategia", "ticker", "direccion", "pedidas", "llenas", "precio_medio",
                        "nivel_stop", "riesgo_usd", "estado", "reentrada_n", "entrada_idx", "nivel_piramide",
                        "hora_salida", "eod", "tp_pendiente", "version_estrategia"], id="Lote"),
    pytest.param(Senal, ["clase", "ticker", "id", "evento", "momento", "recibida_en", "recuperada", "estimacion",
                         "precio_radar", "feed", "origen"], id="Senal"),
    pytest.param(Cotizacion, ["ticker", "bid", "ask", "bsz", "asz", "last", "volumen", "vwap", "hi", "lo",
                              "hora_servidor", "actualizada_en"], id="Cotizacion"),
    pytest.param(EstadoSimbolo, ["ticker", "ssr", "ta", "tat", "limit_down", "limit_up", "consultado_en", "halt_desde",
                                 "k_halts_up", "precio_parada", "orden_open_enviada", "shortable", "tasa_corta",
                                 "reg_sho"], id="EstadoSimbolo"),
    pytest.param(EstadoBS, ["activado_en", "primer_stop", "limite_stop", "max_visto", "informes",
                            "ultimo_informe", "silenciado", "perdido_realizado"], id="EstadoBS"),
    pytest.param(PosicionTicker, ["ticker", "lotes", "neta_fills", "neta_das", "avg_das", "tipo_das", "neta_das_en",
                                  "estado", "motivo_estado", "desde", "bs", "intento", "senal_guardada_halt",
                                  "sin_reentrada_hasta_sigue", "intervencion_humana", "version_stops",
                                  "descubierta_desde", "persecuciones_ask", "ultimo_fill_en", "pausado_por_humano"],
                 id="PosicionTicker-R3-SAL-1"),
    pytest.param(Locate, ["ticker", "strategy_id", "pedidas", "localizadas", "precio_accion", "coste", "id_das", "token",
                          "estado", "usadas", "reutilizable", "comprado_en", "ultimo_inquire_en", "compras",
                          "fase", "precio_senal"], id="Locate"),
    pytest.param(EstadoBot, ["fase", "dia", "vigilando", "pausa_global", "control_humano", "senales_vistas", "posiciones",
                             "ordenes", "id_a_token", "fills", "ordenes_ajenas", "locates", "gasto_locates_dia",
                             "locates_deshabilitados", "cuenta", "das_conectado", "das_logon", "reconciliacion_ok_en",
                             "ultima_respuesta_barrido_en", "feed_ultima_vela_en", "modo_degradado", "ultimo_fill_en",
                             "config_version", "ultimo_seq_token", "rutas_habilitadas", "qty_corto_negativa",
                             "senales_principales"],
                 id="EstadoBot"),
    pytest.param(EstrategiaConfig, ["strategy_id", "name", "origen", "ejecutar", "avisar_grupo_a", "riesgo_usd",
                                    "riesgos_piramide", "riesgo_piramide_usd", "ev_pct", "ev_rangos", "excluir_ipo",
                                    "al_desactivar", "hora_fin_sesion", "ventana_entradas", "hora_salida",
                                    "accept_reentries", "max_reentries", "niveles_piramide", "es_rth",
                                    "definition_hash", "definition"], id="EstrategiaConfig"),
    pytest.param(Config, ["schema_version", "config_version", "sha256", "motor_hash", "estrategias_hash", "generado_at",
                          "fase", "vigilando", "horario", "modo_seguridad", "lista_negra", "pausar_entradas", "locates",
                          "entrada", "salidas", "stops", "halts", "exclusiones", "rutas", "tecnicos", "alertas_grupo_a",
                          "estrategias", "cuenta_das"], id="Config"),
    pytest.param(MsgOrden, ["cruda", "id", "token", "ticker", "lado", "tipo", "qty", "lvqty", "cxlqty", "precio", "ruta",
                            "estado", "hora", "origoid", "cuenta", "trader", "order_src", "tif", "pref", "watch"],
                 id="MsgOrden"),
    pytest.param(MsgTrade, ["cruda", "id", "ticker", "lado", "qty", "precio", "ruta", "hora", "id_orden", "liq", "ecn_fee",
                            "pl", "cuenta", "trader", "watch"], id="MsgTrade"),
    pytest.param(Comando, ["nombre", "args", "chat_id", "requiere", "id", "texto"], id="Comando"),
    pytest.param(Registro, ["v", "seq", "t", "proceso", "tipo", "datos"], id="Registro"),
    pytest.param(Ficha, ["ticker", "list_date", "sic_code", "tipo", "market_cap", "nombre"], id="Ficha-ajuste-a"),
    pytest.param(NivelesStop, ["disparo", "limite", "bajo_banda"], id="NivelesStop-v4-stop-unico"),
    pytest.param(StopDeseado, ["proposito", "nivel", "qty", "disparo", "limite"], id="StopDeseado-ajuste-a"),
    pytest.param(tipos.OrdenDescartada, ["token", "serie", "version", "motivo", "ticker"], id="OrdenDescartada-D2a-06"),
])
def test_orden_de_campos_segun_seccion_2(clase, campos):
    assert [f.name for f in dataclasses.fields(clase)] == campos


def test_campos_con_default_van_despues_de_los_obligatorios():
    """Comprobación explícita sobre TODAS las dataclasses del módulo (el import ya lo exige; aquí queda escrito)."""
    for nombre in dir(tipos):
        clase = getattr(tipos, nombre)
        if not (isinstance(clase, type) and dataclasses.is_dataclass(clase)):
            continue
        visto_default = False
        for campo in dataclasses.fields(clase):
            tiene_default = campo.default is not dataclasses.MISSING or campo.default_factory is not dataclasses.MISSING
            assert not (visto_default and not tiene_default), f"{nombre}.{campo.name} obligatorio tras un default"
            visto_default = visto_default or tiene_default


def test_ficha_niveles_y_stop_deseado_inmutables():
    ficha = Ficha(ticker="XYZ", list_date=None, sic_code="6770", tipo="CS", market_cap=D("12000000"), nombre="XYZ Corp")
    niveles = NivelesStop(disparo=D("10.00"), limite=D("15.00"), bajo_banda=False)
    deseado = StopDeseado(proposito=Proposito.STOP, nivel=D("10.00"), qty=1200, disparo=D("10.00"), limite=D("15.00"))
    for objeto, campo in ((ficha, "ticker"), (niveles, "bajo_banda"), (deseado, "qty")):
        with pytest.raises(FrozenInstanceError):
            setattr(objeto, campo, None)
    assert niveles.disparo < niveles.limite


# ── fixtures/config_ejemplo.json: hash canónico FIJADO aquí (lote 0) ─────
CLAVES_CONFIG = {"schema_version", "config_version", "generado_at", "generado_por", "motor_hash", "estrategias_hash",
                 "sha256", "fase", "vigilando", "pausar_entradas", "horario", "modo_seguridad", "lista_negra", "locates",
                 "entrada", "salidas", "stops", "halts", "exclusiones", "rutas", "tecnicos", "alertas_grupo_a",
                 "estrategias"}
CLAVES_ESTRATEGIA = {"strategy_id", "name", "origen", "ejecutar", "avisar_grupo_a", "riesgo_usd", "riesgo_piramide_usd",
                     "riesgos_piramide", "capital_usd", "ev_pct", "ev_rangos", "cuentas", "excluir_ipo", "al_desactivar",
                     "definition_hash", "definition"}


@pytest.fixture(scope="module")
def config_cruda() -> dict:
    return json.loads(RUTA_CONFIG.read_text(encoding="utf-8"))


def test_config_ejemplo_reproduce_sus_tres_hashes(config_cruda):
    sin_sha = {k: v for k, v in config_cruda.items() if k != "sha256"}
    assert config_cruda["sha256"] == hash_canonico(sin_sha)
    assert len(config_cruda["sha256"]) == 64 and not config_cruda["sha256"].startswith("sha256:")
    assert config_cruda["estrategias_hash"] == "sha256:" + hash_canonico(config_cruda["estrategias"])
    estrategia = config_cruda["estrategias"][0]
    assert estrategia["definition_hash"] == "sha256:" + hash_canonico(estrategia["definition"])
    assert config_cruda["motor_hash"] == "sha256:" + "0" * 64          # placeholder: lo calcula config.motor_hash


def test_hash_canonico_es_estable_ante_orden_y_espacios():
    assert hash_canonico({"b": 1, "a": [1, 2]}) == hash_canonico({"a": [1, 2], "b": 1})
    assert hash_canonico({"a": "ñ"}) == hashlib.sha256('{"a":"ñ"}'.encode("utf-8")).hexdigest()


def test_config_ejemplo_tiene_todos_los_bloques_de_seccion_7(config_cruda):
    assert set(config_cruda) == CLAVES_CONFIG
    assert set(config_cruda["estrategias"][0]) == CLAVES_ESTRATEGIA
    assert config_cruda["schema_version"] == 1 and config_cruda["fase"] == "sombra"
    assert set(config_cruda["rutas"]) == {"agregar", "cruzar", "stop", "halt"}
    assert set(config_cruda["rutas"]["cruzar"]) == {"ge_1", "lt_1_desde_0700", "lt_1_antes_0700"}
    assert set(config_cruda["tecnicos"]) == {"barrido_s", "reconciliacion_fallida_s", "feed", "das_reconexion_s",
                                             "das_aviso_cada_min", "vigilante", "reloj", "disco_min_gb",
                                             "cisne_negro_informes", "filtro_prints_ms", "get_con_simbolo", "max_lv1",
                                             "cuotas", "cola_aviso_umbral", "foto_cada_s"}


@pytest.mark.parametrize("ruta,constante", [
    pytest.param("stops.limite_pct", "STOP_LIMITE_PCT", id="R-C-01-v4-stop-unico-limite"),
    pytest.param("stops.proteccion_desconocidas_pct", "STOP_PROTECCION_PCT", id="R-C-10-proteccion"),
    pytest.param("stops.margen_bajo_limit_up_pct", "STOP_MARGEN_BAJO_LIMIT_UP_PCT", id="R-F-02"),
    pytest.param("stops.reintentos", "STOP_REINTENTOS", id="R-C-03-reintentos"),
    pytest.param("stops.ventana_min", "STOP_VENTANA_MIN", id="R-C-03-ventana"),
    pytest.param("stops.comprobacion_s", "STOP_COMPROBACION_S", id="R-C-04"),
    pytest.param("stops.debounce_s", "STOP_DEBOUNCE_S", id="F1.6-debounce"),
    pytest.param("entrada.agregar_s", "ENTRADA_AGREGAR_S", id="R-B-01-v3-agregar"),
    pytest.param("entrada.tope_caida_bid_pct", "ENTRADA_TOPE_CAIDA_BID_PCT", id="R-B-01-v3-tope"),
    pytest.param("entrada.cruce_bajo_bid_pct", "ENTRADA_CRUCE_BAJO_BID_PCT", id="R-B-01-v3-cruce"),
    pytest.param("entrada.caducidad_senal_s", "ENTRADA_CADUCIDAD_S", id="R-B-04"),
    pytest.param("entrada.retraso_max_senal_pct", "ENTRADA_RETRASO_MAX_PCT", id="R-A-01"),
    pytest.param("entrada.reintentos_rechazo_conocido", "ENTRADA_REINTENTOS_RECHAZO", id="R-B-07"),
    pytest.param("salidas.por_hora.anticipo_s", "SALIDA_ANTICIPO_S", id="R-D-08-anticipo"),
    pytest.param("salidas.por_hora.perseguir_ask_max", "PERSEGUIR_ASK_MAX", id="F5-perseguir"),
    pytest.param("salidas.eod.lanzar_antes_s", "SALIDA_ANTICIPO_S", id="R-D-02-lanzar-antes"),
    pytest.param("salidas.eod.comprobar_despues_s", "EOD_COMPROBAR_DESPUES_S", id="R-D-02-comprobar"),
    pytest.param("salidas.tp_parcial.techo_ask_pct", "TP_TECHO_ASK_PCT", id="R-D-03-v2-techo"),
    pytest.param("salidas.tp_parcial.agregar_s", "ENTRADA_AGREGAR_S", id="R-D-03-v2-agregar-60s"),
    pytest.param("salidas.cerrar_todo.techo_pct", "CERRAR_TODO_TECHO_PCT", id="R-D-06-techo"),
    pytest.param("salidas.cerrar_todo.reintentos", "CERRAR_TODO_REINTENTOS", id="R-D-06-reintentos"),
    pytest.param("halts.k_max", "HALT_K_MAX", id="R-F-01-k"),
    pytest.param("halts.distancia_banda_k2_pct", "HALT_DISTANCIA_BANDA_K2_PCT", id="R-F-01-banda"),
    pytest.param("halts.primera_vela_max_reentrada_pct", "HALT_PRIMERA_VELA_MAX_PCT", id="R-F-01-vela"),
    pytest.param("halts.t1_subida_max_cierre_pct", "HALT_T1_SUBIDA_MAX_PCT", id="R-F-05"),
    pytest.param("halts.enviar_antes_fin_halt_s", "HALT_ENVIAR_ANTES_FIN_S", id="EP-2-OPEN-60s"),
    pytest.param("locates.tope_gasto_pct_cuenta", "LOCATES_TOPE_GASTO_PCT", id="R-H-03"),
    pytest.param("locates.umbral_ultimo_paquete_pct", "LOCATES_UMBRAL_ULTIMO_PAQUETE_PCT", id="H6"),
    pytest.param("locates.inquiry_intervalo_s", "LOCATES_INQUIRE_S", id="manual-L2000"),
    pytest.param("modo_seguridad.precio_min", "MODO_SEGURIDAD_PRECIO_MIN", id="R-I-04-precio"),
    pytest.param("modo_seguridad.acum_dollar_volume_min", "MODO_SEGURIDAD_DOLLAR_VOLUME_MIN", id="R-I-04-volumen"),
    pytest.param("exclusiones.ipo_dias", "IPO_DIAS", id="R-A-03-v2-IPO"),
    pytest.param("exclusiones.opa_banda.minutos", "OPA_BANDA_MIN", id="R-A-03-v2-OPA-min"),
    pytest.param("exclusiones.opa_banda.rango_max_pct", "OPA_RANGO_MAX_PCT", id="R-A-03-v2-OPA-rango"),
    pytest.param("exclusiones.opa_banda.dolares_min", "OPA_DOLARES_MIN", id="R-A-03-v2-OPA-$"),
    pytest.param("tecnicos.feed.prealerta_s", "FEED_PREALERTA_S", id="R-J-01-prealerta"),
    pytest.param("tecnicos.feed.emergencia_s", "FEED_EMERGENCIA_S", id="R-J-01-emergencia"),
    pytest.param("tecnicos.vigilante.colgado_s", "COLGADO_S", id="R-J-04-v2-colgado"),
    pytest.param("tecnicos.vigilante.latido_s", "LATIDO_S", id="R-J-04-v2-latido"),
    pytest.param("tecnicos.vigilante.ping_externo_s", "PING_EXTERNO_S", id="R-J-05-ping"),
    pytest.param("tecnicos.vigilante.ping_fallos_alarma", "PING_FALLOS_ALARMA", id="R-J-05-fallos"),
    pytest.param("tecnicos.vigilante.plan_b_latido_s", "PLAN_B_LATIDO_S", id="R-C-08-plan-B-latido"),
    pytest.param("tecnicos.vigilante.plan_b_descubierta_s", "PLAN_B_DESCUBIERTA_S", id="R-C-08-plan-B-descubierta"),
    pytest.param("tecnicos.reloj.negarse_s", "RELOJ_NEGARSE_S", id="R-J-07-negarse"),
    pytest.param("tecnicos.reloj.aviso_s", "RELOJ_AVISO_S", id="R-J-07-aviso"),
    pytest.param("tecnicos.disco_min_gb", "DISCO_MIN_GB", id="R-J-07-disco"),
    pytest.param("tecnicos.barrido_s.tras_fill", "BARRIDO_TRAS_FILL_S", id="R-K-01-tras-fill"),
    pytest.param("tecnicos.barrido_s.ventana_tras_fill_s", "BARRIDO_VENTANA_TRAS_FILL_S", id="R-K-01-ventana"),
    pytest.param("tecnicos.barrido_s.con_posiciones", "BARRIDO_CON_POSICIONES_S", id="R-K-01-con-posiciones"),
    pytest.param("tecnicos.barrido_s.sin_nada", "BARRIDO_SIN_NADA_S", id="R-K-01-sin-nada"),
    pytest.param("tecnicos.reconciliacion_fallida_s", "RECONCILIACION_CADUCA_S", id="R-K-03"),
    pytest.param("tecnicos.cisne_negro_informes.primeros", "BS_PRIMEROS_INFORMES", id="R-G-01-v2-primeros"),
    pytest.param("tecnicos.cisne_negro_informes.cadencia_inicial_s", "BS_CADENCIA_INICIAL_S", id="R-G-01-v2-inicial"),
    pytest.param("tecnicos.cisne_negro_informes.cadencia_despues_s", "BS_CADENCIA_DESPUES_S", id="R-G-01-v2-despues"),
    pytest.param("tecnicos.filtro_prints_ms", "FILTRO_PRINTS_MS", id="R-A-06"),
    pytest.param("tecnicos.max_lv1", "MAX_LV1", id="manual-L1996"),
    pytest.param("tecnicos.cola_aviso_umbral", "COLA_AVISOS_TOPE", id="§6.1-cola"),
])
def test_config_ejemplo_coincide_con_las_constantes(config_cruda, ruta, constante):
    valor = config_cruda
    for parte in ruta.split("."):
        valor = valor[parte]
    assert Decimal(str(valor)) == Decimal(str(getattr(tipos, constante)))


def test_config_ejemplo_b20bis_apagada_como_la_constante(config_cruda):
    """Decisión 11 (Jaume 30-sep): la fixture trae `null` (apagada), igual que el defecto del libro."""
    assert config_cruda["entrada"]["distancia_max_ultimo_bid_pct"] is None
    assert tipos.ENTRADA_DISTANCIA_ULTIMO_BID_PCT is None


def test_config_ejemplo_listas_tecnicas(config_cruda):
    tecnicos = config_cruda["tecnicos"]
    assert tecnicos["das_reconexion_s"] == [*map(int, tipos.DAS_RECONEXION_S), int(tipos.DAS_RECONEXION_TOPE_S)]
    assert tecnicos["vigilante"]["relanzar_s"] == [int(s) for s in tipos.RELANZAR_S]
    assert tecnicos["das_aviso_cada_min"] * 60 == tipos.DAS_AVISO_CADA_S
    assert config_cruda["exclusiones"]["spac_sic"] == list(tipos.SPAC_SIC)


def test_config_ejemplo_estrategia_de_ejemplo(config_cruda):
    e = config_cruda["estrategias"][0]
    assert (e["strategy_id"], e["name"], e["origen"]) == ("prueba-1", "PM (A) prueba", "portfolio")
    assert e["ejecutar"] is True and e["avisar_grupo_a"] is False and e["riesgo_usd"] == 300
    assert e["riesgo_piramide_usd"] is None and e["riesgos_piramide"] == [] and e["capital_usd"] is None
    assert e["ev_pct"] == 4.0 and e["ev_rangos"] == [] and e["cuentas"] is None
    assert e["excluir_ipo"] is False and e["al_desactivar"] == "esperar_fin_dia"
    d = e["definition"]
    assert d["bias"] == "short"                                              # el motor deriva direction de bias
    assert d["entry_logic"]["root_condition"]["operator"] == "AND" and d["entry_logic"]["root_condition"]["conditions"]
    assert d["entry_logic"]["timeframe"] == "1m"
    assert d["entry_logic"]["entry_time_windows"] == [{"from_time": "04:00", "to_time": "09:29"}]
    assert d["market_sessions"] == ["custom"] and d["custom_end_time"] == "11:30" and d["custom_start_time"] == "04:00"
    assert d["risk_management"]["accept_reentries"] is True and d["risk_management"]["max_reentries"] == -1
    assert "pyramiding" in d and d["pyramiding"]["levels"] == []
    assert "exit_logic" in d


def test_config_ejemplo_sin_credenciales(config_cruda):
    """R-Q-01: chat ids, tokens y cuenta van en el .env, NUNCA en el fichero del cuadro."""
    texto = json.dumps(config_cruda).lower()
    for prohibido in ("telegram", "chat_id", "authkey", "password", "das_clave", "cuenta_das", "api_key"):
        assert prohibido not in texto


# ── añadidos de la ronda de correcciones (27-sep) ─────────────────────────
def test_D2a_06_orden_descartada_defaults_e_inmutable():
    """D2a-06: el emisor avisa al decisor de un NEWORDER purgado por versión; solo `token` es obligatorio."""
    m = tipos.OrdenDescartada(token=100_269_001)
    assert (m.serie, m.version, m.motivo, m.ticker) == (None, 0, "descartada por versión", None)
    assert isinstance(m, Mensaje)
    completo = tipos.OrdenDescartada(token=100_269_002, serie="stops:XYZ", version=3, motivo="versión 3 < 4",
                                     ticker="XYZ")
    assert completo.serie == "stops:XYZ" and completo.version == 3
    with pytest.raises(FrozenInstanceError):
        m.token = 1   # type: ignore[misc]


@pytest.mark.parametrize("abierta,llenas,es_abierta,esperado", [
    pytest.param(300, 200, True, 300, id="A-02-abierta"),
    pytest.param(300, 200, False, 500, id="A-02-total"),
    pytest.param(300, 0, False, 300, id="A-02-total-sin-fills"),
    pytest.param(1, 1, True, 1, id="A-02-canario-abierta"),
    pytest.param(1, 1, False, 2, id="A-02-canario-total"),
])
def test_A_02_share_de_replace(abierta, llenas, es_abierta, esperado):
    assert tipos.share_de_replace(abierta, llenas, share_es_abierta=es_abierta) == esperado


def test_A_02_share_de_replace_defecto_es_abierta():
    assert tipos.REPLACE_SHARE_ES_ABIERTA is True
    assert tipos.share_de_replace(300, 200) == 300


@pytest.mark.parametrize("abierta,llenas", [
    pytest.param(0, 0, id="abierta-cero-es-un-Cancelar"),
    pytest.param(-5, 0, id="abierta-negativa"),
    pytest.param(300.0, 0, id="abierta-float"),
    pytest.param(True, 0, id="abierta-bool"),
    pytest.param(300, -1, id="llenas-negativa"),
    pytest.param(300, 2.0, id="llenas-float"),
])
def test_A_02_share_de_replace_rechaza(abierta, llenas):
    with pytest.raises(ValueError):
        tipos.share_de_replace(abierta, llenas)


def test_D1_12_cotizacion_fresca_max_s_en_tipos():
    """D1-12: la edad máxima de la cotización vive en tipos (mercado_das y entrada la importan de aquí)."""
    assert tipos.COTIZACION_FRESCA_MAX_S == 5.0
