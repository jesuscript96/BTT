"""Tests de las decisiones de Jaume del 2-oct por la tarde (61-63) contra el decisor real, el vigilante y el DAS falso.

QUÉ PRUEBA.
  * 61 el VIGILANTE conoce el protocolo de halts: con el símbolo parado no envía
    órdenes ni toca stops (salvo el stop de acciones cortas SIN ningún stop), no
    da falsos «descubierta» durante la gracia tras reabrir y vuelve a la
    normalidad después; con `halts.silencio = false`, todo como antes. Por la
    regla pura (`reglas.vigilancia.comprobar`) y por el proceso real contra el
    SimuladorDAS (el halt lo aprende por SU conexión con `GET SymStatus`).
  * 62 los comandos que mandan órdenes sobre un ticker PARADO piden «/confirmar
    ID» con la advertencia; sin confirmar no sale nada, confirmado sí (aunque
    el símbolo siga parado); con el ticker NO parado, nada cambia.
  * 63 el estado de los halts sobrevive a un reinicio (`halt_memoria` en el
    diario → `memoria_decisor` → `sembrar_memoria`): reinicio en pleno halt
    (k no se cuenta dos veces; al reabrir, el cierre de la 57), justo tras
    reabrir (cierre ya enviado: no se duplica), con una salida del motor
    guardada (E3) y con una entrada a medias (58); y lo conservador cuando DAS
    dice que ya reabrió y no se sabe cuándo.

POR QUÉ APARTE. test_das_decisiones_2oct cubre la mañana (57-60); aquí van los
huecos que Jaume pidió cerrar por la tarde, con los mismos dobles.
"""
from __future__ import annotations

import re
import time
import types
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.bot_das import comandos
from app.bot_das import decisor as mod_decisor
from app.bot_das import diario as mod_diario
from app.bot_das.diario import a_json_seguro, memoria_decisor, reconstruir
from app.bot_das.reglas import vigilancia
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    PLAN_B_DESCUBIERTA_S,
    Anotar,
    Avisar,
    Cancelar,
    CancelarTicker,
    ComandoRecibido,
    Config,
    EnviarOrden,
    EstadoOrden,
    EstadoTicker,
    Lado,
    Nivel,
    Proposito,
    Reemplazar,
    Registro,
    TipoOrden,
)
from test_das_decisor import (  # noqa: F401 — `banco` es un fixture: importarlo lo pone a disposición de este módulo
    AUTORIZADOS,
    CHAT,
    HOY,
    STOPS,
    TICKER,
    Banco,
    _a_halt,
    _salida_motor,
    _vivas_compra,
    abrir_posicion,
    anotaciones,
    banco,
    salida,
)
from test_das_decisiones_2oct import _banco_k, _entrada_a_medias, _mutantes, _reabrir, _stop, _tp_vivo

D = Decimal


def _avisos(acciones: list, prefijo: str) -> list[Avisar]:
    return [a for a in acciones if isinstance(a, Avisar) and (a.clave or "").startswith(prefijo)]


def _respuestas(acciones: list) -> list[str]:
    return [a.texto for a in acciones if isinstance(a, Avisar) and a.clave is None]


# ═══════════════════════════════ decisión 61: el vigilante y los halts (regla pura) ═══════════════════════════════
from test_das_reglas_vigilancia import (  # noqa: E402 — los ayudantes de la regla pura del vigilante
    AHORA,
    HORA,
    RUTA_STOP,
    X,
    TokensVigilante,
    foto,
    lote,
    nivel_das,
    ordenes_de,
)


def _comprobar(cfg: Config, f: vigilancia.Foto, ahora: float = AHORA) -> list:
    return vigilancia.comprobar(f, cfg, ahora, TokensVigilante(), HORA, RUTA_STOP, True)


def test_decision_61_en_halt_el_vigilante_no_toca_el_stop_aunque_el_ejecutor_este_muerto(cfg: Config) -> None:
    """Ejecutor muerto y stop con otra cantidad (150 para 100 cortas): fuera del halt el vigilante lo REEMPLAZA; con el
    símbolo parado no sale nada, lo retenido se anota y se avisa (2)."""
    f = foto(ordenes=(nivel_das(12, qty=150),), latido=None)
    assert [(r.id_das, r.qty) for r in ordenes_de(_comprobar(cfg, f))] == [(12, 100)]
    acc = _comprobar(cfg, foto(ordenes=(nivel_das(12, qty=150),), latido=None, parados=frozenset({X})))
    assert ordenes_de(acc) == []
    (nota,) = [a for a in acc if isinstance(a, Anotar) and a.tipo == "vigilancia"]
    assert nota.datos["halt_retenidas"] == ["reemplazar 12 a 100"] and "decisión 61" in nota.datos["motivo"]
    (aviso,) = _avisos(acc, f"{vigilancia.CLAVE_AVISO_HALT}:{X}")
    assert aviso.nivel is Nivel.AVISO and "HALT" in aviso.texto


@pytest.mark.parametrize("latido, desde", [pytest.param(None, None, id="ejecutor-muerto"),
                                           pytest.param(1.0, AHORA - 30, id="ejecutor-vivo-descubierta-30s")])
def test_decision_61_en_halt_sin_ningun_stop_el_stop_si_sale(cfg: Config, latido, desde) -> None:
    """La ÚNICA excepción (la misma que el ejecutor): acciones cortas SIN ningún stop vivo → el stop sale en el halt."""
    extra = {"descubierta_desde": {X: desde}} if desde is not None else {}
    acc = _comprobar(cfg, foto(latido=latido, parados=frozenset({X}), **extra))
    nuevas = [a.orden for a in acc if isinstance(a, EnviarOrden)]
    assert [(o.proposito, o.qty, o.lado, o.tipo) for o in nuevas] == [
        (Proposito.STOP, 100, Lado.COMPRA, TipoOrden.STOP_LIMITE_PP)]
    assert not _avisos(acc, vigilancia.CLAVE_AVISO_HALT)


def test_decision_61_en_halt_no_vende_el_exceso_ni_cancela_huerfanas(cfg: Config) -> None:
    """Cuenta LARGA con lotes cortos y el ejecutor muerto: fuera del halt el vigilante vende el exceso; dentro, nada."""
    assert [a for a in ordenes_de(_comprobar(cfg, foto(neta=20, latido=None))) if isinstance(a, EnviarOrden)]
    acc = _comprobar(cfg, foto(neta=20, latido=None, parados=frozenset({X})))
    assert ordenes_de(acc) == [] and _avisos(acc, f"vigilante_larga:{X}")          # el aviso de siempre sigue
    plano = _comprobar(cfg, foto(neta=0, ordenes=(nivel_das(12),), latido=None, parados=frozenset({X})))
    assert ordenes_de(plano) == []


def test_decision_61_otro_ticker_parado_no_cambia_nada(cfg: Config) -> None:
    acc = _comprobar(cfg, foto(ordenes=(nivel_das(12, qty=150),), latido=None, parados=frozenset({"OTRO"})))
    assert [(r.id_das, r.qty) for r in ordenes_de(acc)] == [(12, 100)]


@pytest.mark.sin_silencio
def test_decision_61_con_silencio_false_todo_como_antes(cfg: Config) -> None:
    acc = _comprobar(cfg, foto(ordenes=(nivel_das(12, qty=150),), latido=None, parados=frozenset({X}),
                               reabiertos={X: AHORA - 1}))
    assert [(r.id_das, r.qty) for r in ordenes_de(acc)] == [(12, 100)]


def test_decision_61_tras_reabrir_la_gracia_evita_el_falso_descubierta_y_luego_vuelve_a_la_normalidad(cfg: Config) -> None:
    """Ejecutor VIVO cerrando tras reabrir (decisión 57) y una posición descubierta hace 30 s: durante la gracia el
    vigilante NO actúa por el plazo de descubierta; pasada, actúa como siempre. Con el ejecutor MUERTO no hay gracia."""
    gracia = vigilancia.GRACIA_REAPERTURA_S
    assert gracia >= 2.0 + 3 * 1.0                      # los 2 s de la 57 + las 3 persecuciones de 1 s
    vivo = dict(latido=1.0, descubierta_desde={X: AHORA - 30})
    dentro = _comprobar(cfg, foto(reabiertos={X: AHORA - (gracia - 1)}, **vivo))
    assert ordenes_de(dentro) == []
    assert vigilancia.descubiertas_por_ticker(foto(**vivo), cfg, HOY) == {X: 100}   # la cuenta sigue: no se pierde
    fuera = _comprobar(cfg, foto(reabiertos={X: AHORA - (gracia + 0.5)}, **vivo))
    assert [a.orden.proposito for a in fuera if isinstance(a, EnviarOrden)] == [Proposito.STOP]
    muerto = _comprobar(cfg, foto(latido=None, reabiertos={X: AHORA - 1}))
    assert [a.orden.proposito for a in muerto if isinstance(a, EnviarOrden)] == [Proposito.STOP]
    assert PLAN_B_DESCUBIERTA_S < 30


# ═══════════════════════════════ decisión 61: el proceso vigilante contra el SimuladorDAS ═══════════════════════════════
from test_das_vigilante import (  # noqa: E402,F401 — `montar` y `cfg_canario` son fixtures
    cfg_canario,
    escribir_diario_ejecutor,
    montar,
    neworders,
    stops_vivos,
)


def test_decision_61_proceso_aprende_el_halt_por_su_conexion_y_no_vende_hasta_reabrir(montar, reloj, dir_bot: Path,
                                                                                      libro: Any,
                                                                                      simulador: Any) -> None:
    """E2c-02 con el símbolo PARADO: cuenta LARGA 20, lotes cortos y el ejecutor muerto. El vigilante pregunta `GET
    SymStatus` por su watch, sabe que XYZ está en halt y NO vende (aviso 2); al reabrir, vende el exceso como siempre."""
    libro.sembrar_posicion(TICKER, 20, D("3.45"))
    libro.cotizar(TICKER, D("3.44"), D("3.46"), last=D("3.45"), volumen=500_000)
    libro.halt(TICKER, "H", "09:29:00")
    escribir_diario_ejecutor(dir_bot, reloj)
    m = montar()
    m.listo()
    m.bombear(lambda: TICKER in m.v._parados, "el halt visto por SymStatus")
    m.pasadas(6)
    assert [x for x in m.recibidas() if x.startswith(f"GET SymStatus {TICKER}")]
    assert not neworders(m.recibidas(), TICKER)
    assert m.avisos.con_clave(f"{vigilancia.CLAVE_AVISO_HALT}:{TICKER}")
    assert [r.datos["transicion"] for r in m.regs() if r.tipo == "halt_vigilante"] == ["halt"]
    libro.reabrir(TICKER, D("3.45"))
    m.bombear(lambda: [x for x in neworders(m.recibidas(), TICKER) if x.split()[2] == "S"], "venta tras reabrir")
    assert [r.datos["transicion"] for r in m.regs() if r.tipo == "halt_vigilante"] == ["halt", "reapertura"]


def test_decision_61_proceso_en_halt_pone_el_stop_si_no_hay_ninguno(montar, reloj, dir_bot: Path, libro: Any) -> None:
    """Posición corta SIN stop, ejecutor muerto y el símbolo parado: la excepción de la 57 vale para el vigilante."""
    libro.sembrar_posicion(TICKER, -100, D("3.45"))
    libro.halt(TICKER, "P", "09:29:00")
    escribir_diario_ejecutor(dir_bot, reloj)
    m = montar()
    m.listo()
    m.bombear(lambda: TICKER in m.v._parados and len(stops_vivos(libro)) == 1, "el stop en pleno halt")
    m.pasadas(3)
    assert len(neworders(m.recibidas(), TICKER)) == 1


# ═══════════════════════════════ decisión 62: comandos con el ticker en halt ═══════════════════════════════
def _comando(b: Banco, texto: str) -> list:
    b._comandos += 1
    c = comandos.parsear(texto, CHAT, AUTORIZADOS, id_comando=f"h{b._comandos}")
    assert c is not None, texto
    return b.procesar(ComandoRecibido(c))


def _confirmar(b: Banco, acciones: list) -> list:
    (texto,) = [t for t in _respuestas(acciones) if "/confirmar" in t]
    ident = re.search(r"/confirmar (\d{4})", texto).group(1)
    return _comando(b, f"/confirmar {ident}")


def _en_halt(b: Banco) -> None:
    _a_halt(b, ta="H", tat="09:30:30", cot=("3.80", "3.82", "3.81"))
    b.avanzar(5)


@pytest.mark.parametrize("texto, enviado", [
    pytest.param(f"/cerrar {TICKER} SI", CancelarTicker, id="cerrar"),
    pytest.param(f"/cerrar {TICKER} 40 SI", Reemplazar, id="cerrar-N"),     # el stop baja antes de la compra (R-G-03)
    pytest.param(f"/cancelar_ordenes {TICKER} SI", CancelarTicker, id="cancelar_ordenes"),
    pytest.param(f"/stop {TICKER} 4.50 SI", EnviarOrden, id="stop"),         # el silencio de la 57 no lo frena
    pytest.param("/cerrar_todo SI", CancelarTicker, id="cerrar_todo"),
])
def test_decision_62_en_halt_pide_confirmacion_y_sin_ella_no_envia(banco: Banco, texto: str, enviado: type) -> None:
    b = banco
    _en_halt(b)
    marca = b.marca()
    acciones = _comando(b, texto)
    assert not _mutantes(b.desde(marca))                                 # sin la confirmación no sale NADA
    (respuesta,) = _respuestas(acciones)
    assert f"{TICKER} está en HALT" in respuesta and "amontonadas" in respuesta and "/confirmar" in respuesta
    assert "no envía nada hasta que reabra" in respuesta
    assert anotaciones(acciones, "comando")[0].datos["halt"] == [TICKER]
    marca = b.marca()
    confirmadas = _confirmar(b, acciones)
    assert anotaciones(confirmadas, "comando_halt_confirmado")
    assert [a for a in b.desde(marca) if isinstance(a, enviado)]          # confirmado: sale aunque siga parado


def test_decision_62_la_confirmacion_caduca_y_no_se_ejecuta(banco: Banco) -> None:
    b = banco
    _en_halt(b)
    acciones = _comando(b, f"/cerrar {TICKER} SI")
    b.reloj.avanzar(comandos.TTL_CONFIRMACION_S + 1)
    marca = b.marca()
    tras = _confirmar(b, acciones)
    assert not _mutantes(b.desde(marca)) and "caducada" in _respuestas(tras)[0]


def test_decision_62_cerrar_y_reiniciar_avisa_en_el_primer_paso(banco: Banco) -> None:
    """Dos pasos: la advertencia del halt va en la PRIMERA respuesta y un solo «/confirmar» basta."""
    b = banco
    _en_halt(b)
    marca = b.marca()
    acciones = _comando(b, "/cerrar_y_reiniciar prueba-1")
    assert not _mutantes(b.desde(marca))
    assert "está en HALT" in _respuestas(acciones)[0]
    _confirmar(b, acciones)
    assert anotaciones(b.desde(marca), "comando_halt_confirmado")


def test_decision_62_sin_halt_nada_cambia(banco: Banco) -> None:
    b = banco
    abrir_posicion(b)
    b.avanzar(2)
    marca = b.marca()
    acciones = _comando(b, f"/cerrar {TICKER} SI")
    assert [a for a in b.desde(marca) if isinstance(a, CancelarTicker)]
    assert not any("HALT" in t for t in _respuestas(acciones))


def test_decision_62_los_comandos_que_no_mandan_ordenes_no_cambian(banco: Banco) -> None:
    b = banco
    _en_halt(b)
    for texto in ("/estado", f"/pausar {TICKER}", f"/sigue {TICKER}"):
        assert not any("HALT" in t for t in _respuestas(_comando(b, texto))), texto


def test_decision_62_cerrar_todo_con_mezcla_pide_confirmacion_para_todo(cfg: Config, tmp_path: Path) -> None:
    """/cerrar_todo con un ticker parado y otro no: se pide la confirmación para TODO (lista los parados) y, sin ella,
    no se cierra ninguno."""
    from test_das_decisor import OTRO, _banco_dos_tickers, evento
    b = _banco_dos_tickers(cfg, tmp_path)
    abrir_posicion(b)
    b.senal(evento(ticker=OTRO))
    b.cotizar(OTRO, "3.45", "3.47", "3.45")
    b.tic_das()
    assert b.pos(OTRO).neta_fills == -100
    b.libro.halt(TICKER, "H", "09:30:30")
    b.avanzar(2)
    marca = b.marca()
    acciones = _comando(b, "/cerrar_todo SI")
    assert not _mutantes(b.desde(marca))
    (respuesta,) = _respuestas(acciones)
    assert f"{TICKER} está en HALT" in respuesta and OTRO not in respuesta.split("está en HALT")[0]
    _confirmar(b, acciones)
    assert {a.ticker for a in b.desde(marca) if isinstance(a, CancelarTicker)} == {TICKER, OTRO}


# ═══════════════════════════════ decisión 63: el halt sobrevive a un reinicio ═══════════════════════════════
def _registros(b: Banco) -> list[Registro]:
    """El diario del ejecutor que `b` habría escrito: sus `Anotar` y la `orden_intencion` de cada NEWORDER (M6)."""
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


def _relanzar(b1: Banco, cfg: Config, tmp_path: Path, cotizacion: tuple = ("3.80", "3.82", "3.81")) -> Banco:
    """El ejecutor se cae y se relanza: estado y memoria rehechos del diario; el MISMO DAS (libro, órdenes, posición) y
    el mismo reloj. El bot viejo no vuelve a hablar."""
    regs = _registros(b1)
    b2 = Banco(cfg, tmp_path / "relanzado", estado=reconstruir(regs, HOY), memoria=memoria_decisor(regs, HOY))
    b2.reloj = b1.reloj
    b2.mercado._reloj = b1.reloj
    b2.referencia._reloj = b1.reloj
    b2.libro = b1.libro
    b2.das = b1.das
    b2.preparar(locates=(), cotizaciones=((TICKER, *cotizacion),))
    return b2


def test_decision_63_la_foto_del_halt_va_al_diario_y_memoria_decisor_se_queda_con_la_ultima(banco: Banco) -> None:
    b = banco
    _a_halt(b, ta="H", tat="09:30:30", cot=("3.80", "3.82", "3.81"))
    b.avanzar(30)
    fotos = [a for a in b.historial if isinstance(a, Anotar) and a.tipo == mod_diario.TIPO_HALT_MEMORIA]
    assert fotos and fotos[-1].datos["en_halt"] is True and fotos[-1].datos["decision"] == "cerrar_mercado"
    assert mod_decisor.TIPO_HALT_MEMORIA == mod_diario.TIPO_HALT_MEMORIA
    memoria = memoria_decisor(_registros(b), HOY)
    assert memoria.halt_memoria[TICKER]["en_halt"] is True
    _reabrir(b, "3.85", "3.84", "3.86")
    b.avanzar(4)
    assert b.pos().neta_fills == 0
    assert TICKER not in memoria_decisor(_registros(b), HOY).halt_memoria      # la última es `activo: false`


def test_decision_63_reinicio_en_pleno_halt_k_no_se_cuenta_dos_veces_y_sigue_en_silencio(cfg: Config,
                                                                                          tmp_path: Path) -> None:
    """LULD k = 1 parado bajo el stop (mantener). Reinicio en pleno halt: el bot relanzado sabe que está parado (k = 1,
    no 2), no envía nada y el stop sigue; al reabrir, «mantener»: nada sale."""
    b1 = _banco_k(cfg, tmp_path, 0)
    _a_halt(b1, ta="P", tat="09:30:30", cot=("3.40", "3.42", "3.41"))
    b1.avanzar(10)
    assert b1.mercado.simbolo(TICKER).k_halts_up == 1
    b2 = _relanzar(b1, cfg, tmp_path, ("3.40", "3.42", "3.41"))
    marca = b2.marca()
    b2.avanzar(5)
    assert b2.mercado.simbolo(TICKER).k_halts_up == 1
    assert anotaciones(b2.historial, "halt_reinicio_retomado")
    (aviso,) = _avisos(b2.historial, f"halt_reinicio:{TICKER}")
    assert "k=1" in aviso.texto and "sigue parado" in aviso.texto
    assert not _mutantes(b2.desde(marca)) and _vivas_compra(b2, *STOPS) == 100
    assert b2.pos().estado is EstadoTicker.HALT
    marca = b2.marca()
    _reabrir(b2, "3.45", "3.44", "3.46", tam_ask=0)
    b2.avanzar(3)
    assert not b2.enviadas(Proposito.TP_CRUCE, Proposito.HALT_OPEN, desde=marca)
    assert b2.pos().estado is EstadoTicker.NORMAL and _vivas_compra(b2, *STOPS) == 100


def test_decision_63_reinicio_en_pleno_halt_al_reabrir_cierra_al_ask_sin_duplicar(cfg: Config, tmp_path: Path) -> None:
    """Halt de noticia en RTH (la regla dice CERRAR). Reinicio en pleno halt; al reabrir, el relanzado cierra al ask
    las 100 (una sola compra), el stop no se baja antes y la cuenta queda plana."""
    b1 = Banco(cfg, tmp_path)
    b1.preparar()
    _a_halt(b1, ta="H", tat="09:30:30", cot=("3.80", "3.82", "3.81"))
    b1.avanzar(30)
    b2 = _relanzar(b1, cfg, tmp_path)
    b2.avanzar(5)
    marca = b2.marca()
    assert not _mutantes(b2.historial)
    _reabrir(b2, "3.85", "3.84", "3.86")
    b2.avanzar(3)
    assert [o.qty for o in b2.enviadas(Proposito.TP_CRUCE, desde=marca)] == [100]
    assert b2.pos().neta_fills == 0 and not b2.enviadas(Proposito.VENTA_EXCESO)


def test_decision_63_reinicio_justo_tras_reabrir_con_el_cierre_en_marcha_no_lo_duplica(cfg: Config,
                                                                                         tmp_path: Path) -> None:
    """La compra de cierre tras reabrir ya salió (y no ha llenado) cuando el ejecutor se cae. El relanzado ve por DAS que
    está viva: la cuenta como compra, NO manda otra; cuando llena, plana."""
    b1 = Banco(cfg, tmp_path)
    b1.preparar()
    _a_halt(b1, ta="H", tat="09:30:30", cot=("3.80", "3.82", "3.81"))
    b1.avanzar(5)
    _reabrir(b1, "3.85", "3.84", "3.86", tam_ask=0)
    b1.avanzar(0.5)
    (compra,) = b1.enviadas(Proposito.TP_CRUCE)
    assert TICKER in b1.decisor._cierre_halt_pendiente
    b2 = _relanzar(b1, cfg, tmp_path, ("3.86", "3.88", "3.87"))          # ask por encima de su límite: sigue viva
    b2.avanzar(4)
    assert anotaciones(b2.historial, "halt_reinicio_reanuda")
    assert not b2.enviadas(Proposito.TP_CRUCE, Proposito.HALT_OPEN)       # la de antes cuenta: no se duplica
    assert b2.orden(compra.token).estado in (EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL)
    b2.cotizar(TICKER, "3.85", "3.86", "3.86")
    b2.avanzar(2)
    assert b2.pos().neta_fills == 0 and not b2.enviadas(Proposito.VENTA_EXCESO)


def test_decision_63_reinicio_justo_tras_reabrir_con_el_cierre_sin_enviar_lo_envia(cfg: Config,
                                                                                    tmp_path: Path) -> None:
    """Al reabrir, el cierre esperaba a conocer lo vivo (un CANCEL del TP sin respuesta) y el ejecutor se cae antes de
    enviarlo. El relanzado, reconciliado con DAS (el TP sigue vivo por 50), cierra SOLO lo que no cubre: 50."""
    b1 = Banco(cfg, tmp_path)
    b1.preparar()
    abrir_posicion(b1)
    _tp_vivo(b1)
    tp = b1.enviadas(Proposito.TP_AGREGAR)[0]
    original = b1.das._manejadores["CANCEL"]

    def cancel_mudo(self, p):
        if len(p) == 2 and p[1] == str(b1.orden(tp.token).id_das):
            return []
        return original(p)

    b1.das._manejadores["CANCEL"] = types.MethodType(cancel_mudo, b1.das)
    b1.libro.halt(TICKER, "H", "09:31:00")
    b1.cotizar(TICKER, "3.40", "3.42", "3.41", tam_ask=0)
    b1.avanzar(10)
    b1.libro.reabrir(TICKER, D("3.60"))
    b1.avanzar(1.2)
    assert anotaciones(b1.historial, "halt_silencio_reapertura") and not b1.enviadas(Proposito.TP_CRUCE)
    assert TICKER in b1.decisor._reapertura_silencio
    b2 = _relanzar(b1, cfg, tmp_path, ("3.59", "3.61", "3.60"))
    b2.avanzar(3)
    assert anotaciones(b2.historial, "halt_reinicio_reanuda")
    assert [o.qty for o in b2.enviadas(Proposito.TP_CRUCE)] == [50]
    assert _vivas_compra(b2, Proposito.TP_CRUCE, Proposito.TP_AGREGAR) <= 100


def test_decision_63_salida_guardada_en_el_halt_se_aplica_al_reabrir_tras_el_reinicio(cfg: Config,
                                                                                       tmp_path: Path) -> None:
    """LULD k = 1 bajo el stop (mantener) y el motor manda un TP durante el halt: se guarda (E3). Reinicio en pleno halt:
    la salida guardada vuelve del diario y, al reabrir, se aplica (TP de 50)."""
    b1 = _banco_k(cfg, tmp_path, 0)
    _a_halt(b1, ta="P", tat="09:30:30", cot=("3.40", "3.42", "3.41"))
    _salida_motor(b1, salida())
    assert anotaciones(b1.historial, "salida_guardada_halt") and not b1.enviadas(Proposito.TP_AGREGAR)
    b2 = _relanzar(b1, cfg, tmp_path, ("3.40", "3.42", "3.41"))
    assert b2.decisor._salidas_halt.get(TICKER)
    b2.avanzar(3)
    marca = b2.marca()
    _reabrir(b2, "3.45", "3.44", "3.46", tam_ask=0)
    b2.avanzar(2)
    assert anotaciones(b2.desde(marca), "salidas_guardadas_halt_aplicadas")
    assert sum(o.qty for o in b2.enviadas(Proposito.TP_AGREGAR, Proposito.TP_CRUCE, desde=marca)) == 50


def test_decision_63_entrada_a_medias_en_el_halt_tras_el_reinicio_se_queda_lo_llenado(cfg: Config,
                                                                                       tmp_path: Path) -> None:
    """Decisión 58 + reinicio: la entrada a medias (20 de 100) esperaba la reapertura. El intento no sobrevive al
    reinicio: se queda lo llenado (20, con su stop), NO se completa y el aviso lo dice; ninguna venta en corto nueva."""
    b1 = Banco(cfg, tmp_path)
    b1.preparar()
    _entrada_a_medias(b1)
    b1.libro.halt(TICKER, "P", "09:30:30")
    b1.cotizar(TICKER, "3.44", "3.46", "3.45")
    b1.avanzar(5)
    assert anotaciones(b1.historial, "entrada_espera_reapertura")
    b2 = _relanzar(b1, cfg, tmp_path, ("3.44", "3.46", "3.45"))
    b2.avanzar(3)
    (aviso,) = _avisos(b2.historial, f"halt_reinicio:{TICKER}")
    assert "entrada a medias" in aviso.texto
    _reabrir(b2, "3.45", "3.44", "3.46")
    b2.avanzar(70)
    assert not [o for o in b2.enviadas() if o.lado in (Lado.CORTO, Lado.VENTA)]
    assert b2.pos().neta_fills == -20 and _vivas_compra(b2, *STOPS) == 20


def test_decision_63_reinicio_en_halt_y_das_dice_que_ya_reabrio_lo_conservador(cfg: Config, tmp_path: Path) -> None:
    """El ejecutor se cae en pleno halt (la regla dice CERRAR) y vuelve cuando DAS ya negocia: no se sabe cuándo reabrió
    → no se envía nada, el stop se queda, CONTROL HUMANO y aviso 3 con la situación; /sigue X lo devuelve a la gestión
    normal (sin el cierre del halt)."""
    b1 = Banco(cfg, tmp_path)
    b1.preparar()
    _a_halt(b1, ta="H", tat="09:30:30", cot=("3.80", "3.82", "3.81"))
    b1.avanzar(30)
    b1.libro.reabrir(TICKER, D("3.85"))
    b2 = _relanzar(b1, cfg, tmp_path, ("3.84", "3.86", "3.85"))
    b2.avanzar(5)
    assert not b2.enviadas(Proposito.TP_CRUCE, Proposito.HALT_OPEN, Proposito.HALT_PM_LIMITE)
    (aviso,) = _avisos(b2.historial, f"halt_reinicio_humano:{TICKER}")
    assert aviso.nivel is Nivel.MAXIMO and "reinicio en pleno halt" in aviso.texto and "/sigue" in aviso.texto
    assert "posición -100" in aviso.texto.lower() or "Posición -100" in aviso.texto
    assert b2.pos().estado is EstadoTicker.CONTROL_HUMANO and _vivas_compra(b2, *STOPS) == 100
    b2.comando(f"/sigue {TICKER}")
    assert b2.pos().estado is EstadoTicker.NORMAL


def test_decision_63_reinicio_tras_reabrir_hace_mucho_lo_conservador(cfg: Config, tmp_path: Path) -> None:
    """El cierre de la reapertura estaba pendiente pero el bot vuelve más de 2 min después: no se cierra a ciegas."""
    b1 = Banco(cfg, tmp_path)
    b1.preparar()
    abrir_posicion(b1)
    _tp_vivo(b1)
    tp = b1.enviadas(Proposito.TP_AGREGAR)[0]
    original = b1.das._manejadores["CANCEL"]

    def cancel_mudo(self, p):
        if len(p) == 2 and p[1] == str(b1.orden(tp.token).id_das):
            return []
        return original(p)

    b1.das._manejadores["CANCEL"] = types.MethodType(cancel_mudo, b1.das)
    b1.libro.halt(TICKER, "H", "09:31:00")
    b1.cotizar(TICKER, "3.40", "3.42", "3.41", tam_ask=0)
    b1.avanzar(10)
    b1.libro.reabrir(TICKER, D("3.60"))
    b1.avanzar(1.2)
    b1.reloj.avanzar(mod_decisor.REINICIO_REAPERTURA_MAX_S + 30)
    b2 = _relanzar(b1, cfg, tmp_path, ("3.59", "3.61", "3.60"))
    b2.avanzar(3)
    assert not b2.enviadas(Proposito.TP_CRUCE)
    assert _avisos(b2.historial, f"halt_reinicio_humano:{TICKER}")[0].nivel is Nivel.MAXIMO


def test_decision_63_diario_halt_memoria_activo_false_borra() -> None:
    def reg(seq: int, **datos) -> Registro:
        return Registro(v=1, seq=seq, t="t", proceso="ejecutor", tipo=mod_diario.TIPO_HALT_MEMORIA, datos=datos)
    activo = reg(1, ticker=TICKER, activo=True, en_halt=True, k=2)
    assert memoria_decisor([activo], HOY).halt_memoria == {TICKER: dict(activo.datos)}
    assert memoria_decisor([activo, reg(2, ticker=TICKER, activo=False)], HOY).halt_memoria == {}
    assert memoria_decisor([], HOY).halt_memoria == {}
