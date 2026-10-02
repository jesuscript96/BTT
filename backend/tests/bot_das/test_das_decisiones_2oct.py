"""Tests de las decisiones de Jaume del 2-oct (57-60) contra el decisor real y el DAS falso del banco de pruebas.

QUÉ PRUEBA. Con el mismo `Banco` que test_das_decisor (decisor real + Emparejador
del simulador, reloj simulado, sin red):
  * 57 «halt en silencio»: mientras el símbolo está parado no sale NINGUNA orden
    nueva ni se toca el stop (solo el intento único de cancelar las salidas en
    vuelo); al reabrir, por eventos, se cierra según la regla del halt (RTH: al
    ask con la persecución del TP y el stop puesto; premercado: la límite de las
    decisiones 46/49, ahora al reabrir), «vuelve a parar» y la cuenta LARGA tras
    reabrir con aviso máximo;
  * 58 entrada a medio llenar en una pausa LULD de RTH con k < k_max: no se
    cancela, se mira el primer minuto tras reabrir y, si no llenó, se cancela y
    se cruza lo que falta con el 3 % de siempre;
  * 59 tras reabrir del segundo halt en RTH las salidas van a MERCADO por OPEN;
    rechazo → ruta normal (una vez) con aviso; el tercer halt con la orden viva;
  * 60 el tope de locates en dólares fijos (también en test_das_config y en
    test_das_decisiones_1oct, decisión 50).

POR QUÉ APARTE. test_das_decisor ya pasa de 4.700 líneas: aquí van solo los
escenarios nuevos, reutilizando sus dobles y ayudantes.
"""
from __future__ import annotations

import types
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.bot_das import diario as mod_diario
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    Avisar,
    Cancelar,
    CancelarTicker,
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
    STOPS,
    TICKER,
    Banco,
    _a_halt,
    _banco_premercado,
    _salida_motor,
    _vivas_compra,
    abrir_posicion,
    acciones_de,
    anotaciones,
    banco,
    evento,
    llenar_entrada,
    salida,
)

D = Decimal


def _avisos(acciones: list, prefijo: str) -> list[Avisar]:
    return [a for a in acciones if isinstance(a, Avisar) and (a.clave or "").startswith(prefijo)]


def _stop(b: Banco):
    (stop,) = [o for o in b.estado.ordenes.values()
               if o.ticker == TICKER and o.proposito in STOPS and o.estado in (EstadoOrden.ACCEPTED, EstadoOrden.SENDING)]
    return stop


def _mutantes(acciones: list) -> list:
    """Lo que de verdad sale hacia DAS sobre órdenes: NEWORDER, REPLACE, CANCEL (y CANCEL ALLSYMB)."""
    return [a for a in acciones if isinstance(a, (EnviarOrden, Reemplazar, Cancelar, CancelarTicker))]


def _banco_k(cfg: Config, tmp_path: Path, k: int) -> Banco:
    """k = halts UP ya hechos hoy (el siguiente halt lo sube en uno)."""
    from app.bot_das.diario import MemoriaDecisor
    b = Banco(cfg, tmp_path, memoria=MemoriaDecisor(k_halts_up={TICKER: k}))
    b.preparar()
    return b


def _tp_vivo(b: Banco) -> None:
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    _salida_motor(b, salida())
    assert [o.qty for o in b.enviadas(Proposito.TP_AGREGAR)] == [50]


def _reabrir(b: Banco, precio: str, bid: str, ask: str, tam_ask=None) -> None:
    b.libro.reabrir(TICKER, D(precio))
    b.cotizar(TICKER, bid, ask, precio, tam_ask=tam_ask)


# ═══════════════ decisión 57: «halt en silencio» ═══════════════
def test_decision_57_durante_el_halt_no_sale_nada_y_el_stop_no_se_toca(banco: Banco) -> None:
    """Decisión 57: halt de noticia en RTH con el TP vivo. Lo ÚNICO que se envía al parar es el intento único de cancelar
    la salida en vuelo (E1); en 70 s de halt (con la decisión «cerrar» tomada) no sale ningún NEWORDER, ni REPLACE ni
    CANCEL del stop residente: sigue cubriendo toda la posición."""
    b = banco
    abrir_posicion(b)
    _tp_vivo(b)
    tp = b.enviadas(Proposito.TP_AGREGAR)[0]
    stop = _stop(b)
    marca = b.marca()
    b.libro.halt(TICKER, "H", "09:31:00")
    b.cotizar(TICKER, "3.40", "3.42", "3.41")
    b.avanzar(70)
    tras = b.desde(marca)
    assert [(type(a).__name__, getattr(a, "token", None)) for a in _mutantes(tras)] == [("Cancelar", tp.token)]
    assert anotaciones(tras, "halt_silencio")[0].datos["decision"] == "cerrar_mercado"
    assert not b.enviadas(Proposito.HALT_OPEN, Proposito.HALT_PM_LIMITE)
    assert b.orden(stop.token).estado is EstadoOrden.ACCEPTED and _vivas_compra(b, *STOPS) == 100


def test_decision_57_ni_el_plan_de_stops_toca_el_stop_durante_el_halt(banco: Banco) -> None:
    """Decisión 57: aunque algo pida rehacer el plan de stops con el símbolo parado (aquí, bandas nuevas que recortarían el
    disparo), el REPLACE se deja para la reapertura."""
    b = banco
    _a_halt(b, ta="P", cot=("3.40", "3.42", "3.41"))
    marca = b.marca()
    b.libro.bandas(TICKER, D("3.00"), D("3.80"))                        # limit up bajo el disparo (4,00)
    b.dar(b.das.recibir(f"GET LDLU {TICKER}"))
    assert b.mercado.simbolo(TICKER).limit_up == D("3.80")
    b.avanzar(5)
    assert not _mutantes(b.desde(marca))
    assert anotaciones(b.desde(marca), "halt_silencio_stop_intacto")
    marca = b.marca()
    _reabrir(b, "3.41", "3.40", "3.42")
    b.avanzar(1)
    assert [o for o in b.enviadas(*STOPS, desde=marca) if o.stop < D("4.00")]   # al reabrir, el plan aplazado sí sale


def test_decision_57_noticia_en_rth_al_reabrir_compra_al_ask_y_el_stop_queda(banco: Banco) -> None:
    """Decisión 57: halt H en RTH (la regla dice CERRAR). Al reabrir, por eventos: compra de 100 AL ASK (límite, techo 3 %)
    por la ruta de cruzar, sin pasar por el punto medio; el stop NO se baja antes (sigue hasta que la compra llena) y,
    al llenar, la cuenta queda plana sin compra doble."""
    b = banco
    _a_halt(b, ta="H", tat="09:30:30", cot=("3.80", "3.82", "3.81"))
    stop = _stop(b)
    b.avanzar(30)
    marca = b.marca()
    _reabrir(b, "3.85", "3.84", "3.86")
    b.avanzar(0.5)
    tras = b.desde(marca)
    (compra,) = b.enviadas(Proposito.TP_CRUCE, desde=marca)
    assert (compra.qty, compra.tipo, compra.precio, compra.lado) == (100, TipoOrden.LIMITE, D("3.86"), Lado.COMPRA)
    assert compra.ruta != "OPEN" and not compra.post_only
    envio = next(i for i, a in enumerate(tras) if isinstance(a, EnviarOrden) and a.orden.token == compra.token)
    assert not [a for a in tras[:envio] if isinstance(a, (Cancelar, Reemplazar)) and a.token == stop.token]
    assert anotaciones(tras, "halt_silencio_cierre")
    b.avanzar(3)
    assert b.pos().neta_fills == 0 and not b.enviadas(Proposito.VENTA_EXCESO)


def test_decision_57_persigue_tres_veces_y_si_queda_resto_avisa_nivel_3(banco: Banco) -> None:
    """Decisión 57: la compra de cierre tras reabrir no llena → se persigue al ask (3 veces, con el techo del 3 %) y,
    agotada, el aviso del resto es de nivel MÁXIMO (debía cerrarse); el stop sigue cubriendo."""
    b = banco
    _a_halt(b, ta="H", tat="09:30:30", cot=("3.80", "3.82", "3.81"))
    b.avanzar(5)
    _reabrir(b, "3.85", "3.84", "3.86", tam_ask=0)                     # sin acciones al ask: no llena
    b.avanzar(0.5)
    (compra,) = b.enviadas(Proposito.TP_CRUCE)
    for ask in ("3.87", "3.88", "3.89"):
        b.cotizar(TICKER, "3.85", ask, "3.86", tam_ask=0)
        b.avanzar(1)
    persecuciones = [a for a in b.historial if isinstance(a, Reemplazar) and a.token == compra.token]
    assert [r.precio for r in persecuciones] == [D("3.87"), D("3.88"), D("3.89")]
    b.avanzar(6)
    (aviso,) = [a for a in _avisos(b.historial, f"limbo:") if str(compra.token) in (a.clave or "")]
    assert aviso.nivel is Nivel.MAXIMO and "debía cerrarse" in aviso.texto
    assert _vivas_compra(b, *STOPS) == 100 and b.pos().neta_fills == -100


@pytest.mark.parametrize("k_previo, cot, cierra", [
    pytest.param(2, ("3.40", "3.42", "3.41"), True, id="tercer-LULD-cierra"),
    pytest.param(0, ("4.04", "4.06", "4.05"), True, id="LULD-k1-sobre-el-stop-cierra"),
    pytest.param(0, ("3.40", "3.42", "3.41"), False, id="LULD-k1-bajo-el-stop-mantiene"),
])
def test_decision_57_luld_en_rth_cierra_o_mantiene_segun_k_y_el_stop(cfg: Config, tmp_path: Path, k_previo: int,
                                                                     cot: tuple, cierra: bool) -> None:
    """Decisión 57: pausa LULD en RTH. Tercer LULD o parado por encima del stop → CERRAR al reabrir (al ask); 1.º/2.º
    parado por debajo → «mantener» (nada sale; el stop sigue). En ningún caso sale nada DURANTE el halt."""
    b = _banco_k(cfg, tmp_path, k_previo)
    marca = b.marca()
    _a_halt(b, ta="P", tat="09:27:00", cot=cot)
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 30, tzinfo=ET))
    durante = [a for a in b.desde(marca) if isinstance(a, EnviarOrden) and a.orden.proposito not in
               (Proposito.ENTRADA_AGREGAR, Proposito.STOP)]
    assert not durante
    marca = b.marca()
    _reabrir(b, "3.90", "3.89", "3.91", tam_ask=0)                      # bajo el stop: el stop no salta
    b.avanzar(3)
    compras = b.enviadas(Proposito.TP_CRUCE, desde=marca)
    assert ([o.qty for o in compras] == [100]) is cierra
    if not cierra:
        assert not compras and _vivas_compra(b, *STOPS) == 100


def test_decision_57_si_el_stop_ya_salto_al_reabrir_no_se_compra_nada(cfg: Config, tmp_path: Path) -> None:
    """Decisión 57: LULD parado por encima del stop (la regla dice cerrar) que reabre aún por encima: el stop salta y
    llena en la reapertura; la compra de cierre descuenta lo que los stops compran a ese precio → nada más sale y la
    cuenta queda plana, sin venta del exceso."""
    b = _banco_k(cfg, tmp_path, 0)
    _a_halt(b, ta="P", tat="09:27:00", cot=("4.04", "4.06", "4.05"))
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 30, tzinfo=ET))
    marca = b.marca()
    _reabrir(b, "4.10", "4.09", "4.11")
    b.avanzar(3)
    assert not b.enviadas(Proposito.TP_CRUCE, Proposito.HALT_OPEN, desde=marca)
    assert b.pos().neta_fills == 0 and not b.enviadas(Proposito.VENTA_EXCESO)


def test_decision_57_vuelve_a_parar_mientras_cierra_y_se_retoma_en_la_siguiente_reapertura(banco: Banco) -> None:
    """Decisión 57: la compra de cierre no ha llenado y el símbolo vuelve a parar: silencio otra vez (UN intento de
    cancelarla y nada más) y en la siguiente reapertura se vuelve a cerrar al ask."""
    b = banco
    _a_halt(b, ta="H", tat="09:30:30", cot=("3.80", "3.82", "3.81"))
    b.avanzar(5)
    _reabrir(b, "3.85", "3.84", "3.86", tam_ask=0)
    b.avanzar(0.5)
    (primera,) = b.enviadas(Proposito.TP_CRUCE)
    marca = b.marca()
    b.libro.halt(TICKER, "P", "09:31:10")
    b.cotizar(TICKER, "3.84", "3.86", "3.85", tam_ask=0)
    b.avanzar(40)
    tras = b.desde(marca)
    assert [(type(a).__name__, a.token) for a in _mutantes(tras)] == [("Cancelar", primera.token)]
    marca = b.marca()
    _reabrir(b, "3.86", "3.85", "3.87")
    b.avanzar(1)
    otra = b.enviadas(Proposito.TP_CRUCE, desde=marca)
    assert [o.qty for o in otra] == [100] and otra[0].token != primera.token
    b.avanzar(3)
    assert b.pos().neta_fills == 0


def test_decision_57_premercado_la_limite_sale_al_reabrir_no_durante(cfg: Config, tmp_path: Path) -> None:
    """Decisión 57 en PREMERCADO: halt H con el precio sobre el stop (la regla dice cerrar con la límite de PM). Durante
    el halt no sale nada; al reabrir (aún en premercado, bajo el stop: el stop no lo cierra) sale la límite que cruza el
    ask (decisiones 46/49 sin cambios de lógica: el stop baja antes, como siempre en esa salida)."""
    b = _banco_premercado(cfg, tmp_path)
    marca = b.marca()
    b.libro.halt(TICKER, "H", "08:00:30")
    b.cotizar(TICKER, "4.08", "4.10", "4.09")
    b.avanzar(30)
    assert not _mutantes(b.desde(marca))
    assert anotaciones(b.desde(marca), "halt_silencio")[0].datos["decision"] == "cerrar_limite_pm"
    marca = b.marca()
    _reabrir(b, "3.95", "3.94", "3.96")
    b.avanzar(3)
    (pm,) = b.enviadas(Proposito.HALT_PM_LIMITE, desde=marca)
    assert pm.tipo is TipoOrden.LIMITE and pm.precio >= D("3.96") and pm.ruta != "OPEN" and pm.qty == 100
    assert b.pos().neta_fills == 0 and not b.enviadas(Proposito.VENTA_EXCESO)


def test_decision_57_halt_de_premercado_que_sigue_a_las_0930_cierra_al_reabrir_en_rth(cfg: Config,
                                                                                    tmp_path: Path) -> None:
    """Decisión 57 + 48: halt H de premercado con «mantener» que sigue parado a las 09:30: ya no sale la MKT por OPEN
    durante el halt; al reabrir en RTH se cierra al ask (la regla dice cerrar)."""
    b = _banco_premercado(cfg, tmp_path)
    b.libro.halt(TICKER, "H", "08:00:30")
    b.cotizar(TICKER, "3.60", "3.62", "3.61")
    marca = b.marca()
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 0, tzinfo=ET))
    assert not _mutantes(b.desde(marca))
    assert "cerrar_mercado" in {a.datos["decision"] for a in anotaciones(b.desde(marca), "halt_silencio")}
    marca = b.marca()
    _reabrir(b, "3.70", "3.69", "3.71")
    b.avanzar(3)
    assert [o.qty for o in b.enviadas(Proposito.TP_CRUCE, desde=marca)] == [100]
    assert b.pos().neta_fills == 0


def test_decision_57_reabre_y_se_espera_a_conocer_lo_vivo_como_mucho_2_s(banco: Banco) -> None:
    """Decisión 57: con una salida cuyo CANCEL quedó sin respuesta (estado desconocido) la compra de cierre NO sale al
    reabrir; a los 2 s sale con lo que se sepa (la salida sin confirmar cuenta como compra viva)."""
    b = banco
    abrir_posicion(b)
    _tp_vivo(b)
    tp = b.enviadas(Proposito.TP_AGREGAR)[0]
    original = b.das._manejadores["CANCEL"]

    def cancel_mudo(self, p):
        if len(p) == 2 and p[1] == str(b.orden(tp.token).id_das):
            return []                                                   # DAS no contesta al CANCEL de la TP
        return original(p)

    b.das._manejadores["CANCEL"] = types.MethodType(cancel_mudo, b.das)
    b.libro.halt(TICKER, "H", "09:31:00")
    b.cotizar(TICKER, "3.40", "3.42", "3.41", tam_ask=0)
    b.avanzar(10)
    assert b.orden(tp.token).estado is EstadoOrden.ACCEPTED and tp.token in b.decisor._cancel_pedido
    marca = b.marca()
    b.libro.reabrir(TICKER, D("3.60"))                                  # la TP (límite 3,45) no llena en el cruce
    b.avanzar(1.2)                                                      # el SymStatus de 1 s ve la reapertura
    assert anotaciones(b.desde(marca), "halt_silencio_reapertura")
    assert not b.enviadas(Proposito.TP_CRUCE, desde=marca)              # lo vivo aún no se conoce: no sale nada
    b.avanzar(2)
    compras = b.enviadas(Proposito.TP_CRUCE, desde=marca)
    assert [o.qty for o in compras] == [50]                              # la TP sin confirmar cuenta como compra viva
    assert _vivas_compra(b, Proposito.TP_CRUCE, Proposito.TP_AGREGAR) <= 100


def test_decision_57_larga_tras_reabrir_vende_el_exceso_con_aviso_maximo(cfg: Config, tmp_path: Path) -> None:
    """Decisión 57 + 59: una salida a mercado por OPEN que quedó viva entra en el tercer halt; al reabrir por encima del
    stop se ejecutan LAS DOS (la OPEN y el stop): la cuenta queda LARGA → venta del exceso de siempre y aviso MÁXIMO."""
    b = _banco_k(cfg, tmp_path, 2)
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    _salida_motor(b, salida())                                          # TP de 50 → MKT por OPEN (k = 2)
    (tp,) = b.enviadas(Proposito.TP_AGREGAR)
    assert (tp.tipo, tp.ruta) == (TipoOrden.MERCADO, "OPEN")
    b.libro.halt(TICKER, "P", "09:31:00")                               # tercer halt con la OPEN viva
    b.cotizar(TICKER, "3.98", "4.00", "3.99", tam_ask=0)
    b.avanzar(5)
    assert b.orden(tp.token).estado is EstadoOrden.ACCEPTED
    marca = b.marca()
    _reabrir(b, "4.10", "4.09", "4.11")
    b.avanzar(3)
    assert b.enviadas(Proposito.VENTA_EXCESO, desde=marca)
    avisos_exceso = _avisos(b.desde(marca), f"exceso:{TICKER}")
    assert avisos_exceso and all(a.nivel is Nivel.MAXIMO for a in avisos_exceso)


@pytest.mark.sin_silencio
def test_decision_57_con_silencio_false_la_mkt_por_open_sale_durante_el_halt(banco: Banco) -> None:
    """Con `halts.silencio = false` el comportamiento es el de antes del 2-oct: la MKT por OPEN sale durante el halt
    (tras la confirmación del stop, decisión 54 E2)."""
    b = banco
    _a_halt(b, ta="H", tat="09:30:30")
    b.avanzar(2)
    assert [o.qty for o in b.enviadas(Proposito.HALT_OPEN)] == [100]


# ═══════════════ decisión 58: entrada a medio llenar en una pausa LULD (k < k_max) ═══════════════
def _entrada_a_medias(b: Banco):
    """Señal de 100: el agregar llena 20 y queda vivo por 80 (el resto no llena)."""
    b.libro.llenar_parcial(D("0.2"), TICKER)
    b.senal(evento())
    llenar_entrada(b)
    assert b.pos().neta_fills == -20
    b.libro.llenar_parcial(D("1"), TICKER)
    intento = b.pos().intento
    entrada = b.orden(intento.token_agregar)
    assert entrada.estado is EstadoOrden.PARTIAL
    return entrada


def _sin_tope(b: Banco, token: int) -> None:
    """La orden de DAS ya puede llenar lo que le falta (el simulador le había puesto un tope de llenado)."""
    o = b.orden(token)
    b.libro._ordenes[o.id_das].tope_llenado = None


def test_decision_58_la_entrada_no_se_cancela_y_llena_en_el_primer_minuto(banco: Banco) -> None:
    b = banco
    entrada = _entrada_a_medias(b)
    marca = b.marca()
    b.libro.halt(TICKER, "P", "09:30:30")
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.avanzar(5)
    tras = b.desde(marca)
    assert entrada.token not in [c.token for c in acciones_de(tras, Cancelar)]
    assert anotaciones(tras, "entrada_espera_reapertura")
    _reabrir(b, "3.45", "3.44", "3.46")
    b.avanzar(10)
    _sin_tope(b, entrada.token)
    b.cotizar(TICKER, "3.45", "3.47", "3.45")                           # el bid toca su precio: llena las 80
    b.avanzar(5)
    assert b.pos().neta_fills == -100 and b.pos().intento is None
    assert _vivas_compra(b, *STOPS) == 100
    b.avanzar(60)
    assert not b.enviadas(Proposito.ENTRADA_CRUCE)


def test_decision_58_sin_llenar_en_el_minuto_se_cancela_y_cruza_lo_que_falta(banco: Banco) -> None:
    b = banco
    entrada = _entrada_a_medias(b)
    b.libro.halt(TICKER, "P", "09:30:30")
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.avanzar(5)
    _reabrir(b, "3.45", "3.44", "3.46")
    marca = b.marca()
    b.avanzar(30)
    assert not acciones_de(b.desde(marca), Cancelar)                    # dentro del minuto no se toca
    b.avanzar(31)
    tras = b.desde(marca)
    assert entrada.token in [c.token for c in acciones_de(tras, Cancelar)]
    (cruce,) = b.enviadas(Proposito.ENTRADA_CRUCE, desde=marca)
    assert cruce.qty == 80 and cruce.lado is Lado.CORTO
    assert anotaciones(tras, "entrada_reapertura_cruce")
    # aclaración de Jaume: se cancela solo lo PENDIENTE y la venta espera a la confirmación (nunca dos entradas vivas)
    cancelada = next(i for i, a in enumerate(tras) if getattr(a, "tipo", None) == "orden_act"
                     and a.datos.get("token") == entrada.token and a.datos.get("accion") == "Canceled")
    envio = next(i for i, a in enumerate(tras) if isinstance(a, EnviarOrden) and a.orden.token == cruce.token)
    assert cancelada < envio and b.orden(entrada.token).llenas == 20


def test_decision_58_sin_llenar_y_con_el_bid_caido_mas_del_3_se_queda_lo_llenado(banco: Banco) -> None:
    b = banco
    _entrada_a_medias(b)
    b.libro.halt(TICKER, "P", "09:30:30")
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.avanzar(5)
    _reabrir(b, "3.30", "3.29", "3.31")                                 # bid −4,4 % desde el de la señal
    marca = b.marca()
    b.avanzar(62)
    assert not b.enviadas(Proposito.ENTRADA_CRUCE, desde=marca)
    assert b.pos().intento is None and b.pos().neta_fills == -20


@pytest.mark.parametrize("ta, k_previo", [pytest.param("P", 2, id="tercer-LULD"), pytest.param("H", 0, id="halt-H")])
def test_decision_58_no_aplica_en_k3_ni_en_halt_de_noticia(cfg: Config, tmp_path: Path, ta: str, k_previo: int) -> None:
    """Decisión 58: en el tercer LULD y en un halt de noticia la entrada viva se cancela al parar, como siempre."""
    b = _banco_k(cfg, tmp_path, k_previo)
    entrada = _entrada_a_medias(b)
    marca = b.marca()
    b.libro.halt(TICKER, ta, "09:30:30")
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.avanzar(3)
    assert entrada.token in [c.token for c in acciones_de(b.desde(marca), Cancelar)]
    assert not anotaciones(b.desde(marca), "entrada_espera_reapertura")


def test_decision_58_no_aplica_en_premercado(cfg: Config, tmp_path: Path) -> None:
    inicio = datetime(2026, 9, 25, 8, 0, tzinfo=ET)
    b = Banco(cfg, tmp_path, inicio=inicio)
    b.preparar()
    b.libro.llenar_parcial(D("0.2"), TICKER)
    from test_das_decisor import momento_de
    b.senal(evento(momento=momento_de(inicio)))
    llenar_entrada(b)
    assert b.pos().neta_fills == -20
    entrada = b.orden(b.pos().intento.token_agregar)
    marca = b.marca()
    b.libro.halt(TICKER, "P", "08:00:30")
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.avanzar(3)
    assert entrada.token in [c.token for c in acciones_de(b.desde(marca), Cancelar)]
    assert not anotaciones(b.desde(marca), "entrada_espera_reapertura")


# ═══════════════ decisión 59: tras reabrir del segundo halt en RTH, salidas a MERCADO por OPEN ═══════════════
def test_decision_59_tras_k2_el_tp_sale_a_mercado_por_open_sin_punto_medio(cfg: Config, tmp_path: Path) -> None:
    b = _banco_k(cfg, tmp_path, 2)
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    _salida_motor(b, salida())
    (tp,) = b.enviadas(Proposito.TP_AGREGAR)
    assert (tp.tipo, tp.ruta, tp.precio, tp.post_only, tp.qty) == (TipoOrden.MERCADO, "OPEN", None, False, 50)
    b.avanzar(2)
    assert b.pos().neta_fills == -50 and _vivas_compra(b, *STOPS) == 50


@pytest.mark.sin_open_k2
def test_decision_59_con_open_tras_k2_false_el_tp_va_por_su_ruta(cfg: Config, tmp_path: Path) -> None:
    b = _banco_k(cfg, tmp_path, 2)
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    _salida_motor(b, salida())
    (tp,) = b.enviadas(Proposito.TP_AGREGAR)
    assert tp.tipo is TipoOrden.LIMITE and tp.ruta != "OPEN" and tp.post_only


def test_decision_59_con_k1_no_aplica(cfg: Config, tmp_path: Path) -> None:
    b = _banco_k(cfg, tmp_path, 1)
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    _salida_motor(b, salida())
    (tp,) = b.enviadas(Proposito.TP_AGREGAR)
    assert tp.tipo is TipoOrden.LIMITE and tp.ruta != "OPEN"


def test_decision_59_rechazo_de_la_open_reenvia_por_la_ruta_normal_una_vez_y_avisa(cfg: Config, tmp_path: Path) -> None:
    """Decisión 59 (salvaguarda): DAS rechaza la salida por OPEN con el símbolo NO parado → se reenvía YA por la ruta y
    el protocolo normales (el TP agrega en el punto medio), aviso nivel 2, y ese ticker no vuelve a probar OPEN hoy."""
    b = _banco_k(cfg, tmp_path, 2)
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    b.libro.rechazar_siguiente("Route OPEN not available in continuous trading")
    marca = b.marca()
    _salida_motor(b, salida())
    open_, normal = b.enviadas(Proposito.TP_AGREGAR, desde=marca)
    assert (open_.tipo, open_.ruta) == (TipoOrden.MERCADO, "OPEN")
    assert b.orden(open_.token).estado is EstadoOrden.REJECTED
    assert normal.tipo is TipoOrden.LIMITE and normal.ruta != "OPEN" and normal.post_only and normal.qty == 50
    (aviso,) = _avisos(b.desde(marca), f"open_rechazada:{TICKER}")
    assert aviso.nivel is Nivel.AVISO and "DAS no acepta OPEN con el mercado abierto" in aviso.texto
    assert anotaciones(b.desde(marca), "halt_open_rechazada")
    assert f"tp_cruce:{normal.lote_id}:{normal.token}" in b.temporizadores       # hereda su seguimiento
    marca = b.marca()
    _salida_motor(b, salida(acciones=25.0, momento=pd.Timestamp("2026-09-25 09:32:00")))
    assert all(o.ruta != "OPEN" for o in b.enviadas(desde=marca) if o.lado is Lado.COMPRA)


def test_decision_59_el_rechazo_se_recuerda_tras_un_reinicio() -> None:
    hoy = datetime(2026, 9, 25).date()
    reg = Registro(v=1, seq=1, t="t", proceso="ejecutor", tipo=mod_diario.TIPO_HALT_OPEN_RECHAZADA,
                   datos={"ticker": TICKER, "token": 1})
    assert mod_diario.memoria_decisor([reg], hoy).open_rechazada == {TICKER}
    assert mod_diario.memoria_decisor([], hoy).open_rechazada == set()


def test_decision_59_tercer_halt_con_la_open_viva_no_se_toca_y_al_reabrir_se_cierra_el_resto(cfg: Config,
                                                                                             tmp_path: Path) -> None:
    """Decisión 59 + 57: la TP por OPEN sin llenar entra en el tercer halt: queda VIVA (ni se cancela ni se toca el stop);
    al reabrir (bajo el stop) la OPEN llena en el cruce y lo que no cubre (50) se compra al ask: plana, sin doble."""
    b = _banco_k(cfg, tmp_path, 2)
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    _salida_motor(b, salida())
    (tp,) = b.enviadas(Proposito.TP_AGREGAR)
    marca = b.marca()
    b.libro.halt(TICKER, "P", "09:31:00")
    b.cotizar(TICKER, "3.60", "3.62", "3.61", tam_ask=0)
    b.avanzar(10)
    assert not _mutantes(b.desde(marca))
    assert anotaciones(b.desde(marca), "halt_salida_open_se_queda")
    marca = b.marca()
    _reabrir(b, "3.70", "3.69", "3.71")
    b.avanzar(3)
    assert b.orden(tp.token).llenas == 50
    assert [o.qty for o in b.enviadas(Proposito.TP_CRUCE, desde=marca)] == [50]
    assert b.pos().neta_fills == 0 and not b.enviadas(Proposito.VENTA_EXCESO)


def test_decision_59_la_banda_va_por_open_y_el_stop_no_baja(cfg: Config, tmp_path: Path) -> None:
    """Decisión 59: la salida «cerca de la banda» (k = 2) va a MERCADO por OPEN y, como puede quedar esperando al cruce,
    el stop NO se baja por ella; si no llena, no se retira a los 2 s."""
    from test_das_decisor import _dar_bandas
    b = _banco_k(cfg, tmp_path, 2)
    abrir_posicion(b)
    _dar_bandas(b)
    b.cotizar(TICKER, "3.88", "3.92", "3.91", tam_ask=0)
    b.avanzar(1)
    (banda,) = b.enviadas(Proposito.HALT_BANDA)
    assert (banda.tipo, banda.ruta, banda.qty) == (TipoOrden.MERCADO, "OPEN", 100)
    assert _vivas_compra(b, *STOPS) == 100
    b.avanzar(3)
    assert b.orden(banda.token).estado is EstadoOrden.ACCEPTED and _vivas_compra(b, *STOPS) == 100
    assert EstadoTicker.NORMAL is b.pos().estado


# ═══════════════ aclaración de Jaume (2-oct) a 57/58: en un CIERRE la entrada a medias no se completa ═══════════════
def _entrada_20_de_120(b: Banco):
    b.libro.llenar_parcial(D("0.17"), TICKER)                          # floor(120 · 0,17) = 20
    b.senal(evento(acciones=120.0, riesgo_usd=66.0))
    llenar_entrada(b)
    b.libro.llenar_parcial(D("1"), TICKER)
    intento = b.pos().intento
    assert (intento.qty_total, b.pos().neta_fills) == (120, -20)
    return b.orden(intento.token_agregar)


def test_aclaracion_tercer_halt_con_entrada_a_medias_cierra_las_20_sin_completar(cfg: Config, tmp_path: Path) -> None:
    """Entrada 20 de 120 y tercer LULD: la entrada se cancela al parar (como siempre); al reabrir se compran las 20 que
    hay (protocolo de la 57), ninguna venta en corto nueva, y al quedar plano el stop se retira. Después del halt k_max
    no hay más entradas en el ticker ese día."""
    b = _banco_k(_cfg_rth(cfg), tmp_path, 2)
    entrada = _entrada_20_de_120(b)
    marca = b.marca()
    b.libro.halt(TICKER, "P", "09:30:30")
    b.cotizar(TICKER, "3.40", "3.42", "3.41")
    b.avanzar(5)
    assert entrada.token in [c.token for c in acciones_de(b.desde(marca), Cancelar)]
    _reabrir(b, "3.50", "3.49", "3.51")
    b.avanzar(3)
    assert [o.qty for o in b.enviadas(Proposito.TP_CRUCE, desde=marca)] == [20]
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE, desde=marca)
    assert b.pos().neta_fills == 0 and _vivas_compra(b, *STOPS) == 0
    marca = b.marca()
    acciones = b.senal(evento(momento=pd.Timestamp("2026-09-25 09:33:00")))
    assert anotaciones(acciones, "senal_descartada")                    # R-F-03 / k_max: no más entradas hoy
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE, desde=marca)


def test_aclaracion_tras_el_halt_k_max_no_hay_mas_entradas_ese_dia(cfg: Config, tmp_path: Path) -> None:
    """Jaume 2-oct: tras el tercer halt (k = k_max) no hay más entradas en ese ticker ese día, aunque no hubiera posición
    (sin stop no aplicaba el veto de R-F-03)."""
    b = _banco_k(_cfg_rth(cfg), tmp_path, 2)
    b.libro.halt(TICKER, "P", "09:30:10")
    b.cotizar(TICKER, "3.40", "3.42", "3.41")
    b.simstatus()                                                       # sin posición: el estado lo trae la consulta
    assert b.mercado.simbolo(TICKER).k_halts_up == 3
    b.avanzar(3)
    _reabrir(b, "3.45", "3.44", "3.46")
    b.simstatus()
    b.avanzar(70)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.simstatus()
    marca = b.marca()
    acciones = b.senal(evento(momento=pd.Timestamp("2026-09-25 09:31:00")))
    (descarte,) = anotaciones(acciones, "senal_descartada")
    assert "k_max" in descarte.datos["motivo"]
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE, desde=marca)


def test_aclaracion_entrada_que_no_se_pudo_cancelar_y_das_lleno_al_reabrir_se_cierra_entera(cfg: Config,
                                                                                           tmp_path: Path) -> None:
    """Entrada 20 de 120, tercer LULD, y DAS no contesta al CANCEL de la entrada: al reabrir la orden llena las 100 que
    faltaban → la posición REAL es 120 y se cierra entera (120 al ask), sin ninguna venta en corto nueva del bot."""
    b = _banco_k(_cfg_rth(cfg), tmp_path, 2)
    entrada = _entrada_20_de_120(b)
    original = b.das._manejadores["CANCEL"]

    def cancel_mudo(self, p):
        if len(p) == 2 and p[1] == str(b.orden(entrada.token).id_das):
            return []
        return original(p)

    b.das._manejadores["CANCEL"] = types.MethodType(cancel_mudo, b.das)
    marca = b.marca()
    b.libro.halt(TICKER, "P", "09:30:30")
    b.cotizar(TICKER, "3.40", "3.42", "3.41")
    b.avanzar(5)
    _sin_tope(b, entrada.token)
    _reabrir(b, "3.50", "3.49", "3.51")                                 # la venta (3,45) llena las 100 en la reapertura
    b.avanzar(3)
    assert b.orden(entrada.token).llenas == 120
    assert sum(o.qty for o in b.enviadas(Proposito.TP_CRUCE, desde=marca)) == 120
    assert not [o for o in b.enviadas(desde=marca) if o.lado in (Lado.CORTO, Lado.VENTA)]
    assert b.pos().neta_fills == 0 and _vivas_compra(b, *STOPS) == 0


def _cfg_rth(cfg: Config) -> Config:
    from test_das_decisor import _cfg_ventana_larga
    return _cfg_ventana_larga(cfg)


def test_aclaracion_luld_k1_que_dice_cerrar_no_completa_la_entrada_a_medias(cfg: Config, tmp_path: Path) -> None:
    """Pausa LULD k = 1 parada POR ENCIMA del stop (la regla dice cerrar) con la entrada a medias que la 58 dejó viva: al
    reabrir NO se completa; se retira la entrada y se cierra la posición real al ask; ninguna venta en corto nueva."""
    b = Banco(_cfg_rth(cfg), tmp_path)
    b.preparar()
    entrada = _entrada_a_medias(b)
    marca = b.marca()
    b.libro.halt(TICKER, "P", "09:30:30")
    b.cotizar(TICKER, "4.04", "4.06", "4.05")
    b.avanzar(5)
    assert anotaciones(b.desde(marca), "entrada_espera_reapertura")
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 35, 0, tzinfo=ET))       # la decisión del halt: cerrar (sobre el stop)
    _reabrir(b, "3.90", "3.89", "3.91")
    b.avanzar(5)
    tras = b.desde(marca)
    assert entrada.token in [c.token for c in acciones_de(tras, Cancelar)]
    assert not b.enviadas(Proposito.ENTRADA_CRUCE, Proposito.ENTRADA_AGREGAR, desde=marca)
    assert b.enviadas(Proposito.TP_CRUCE, desde=marca)
    assert b.pos().neta_fills == 0 and _vivas_compra(b, *STOPS) == 0
    b.avanzar(70)
    assert not b.enviadas(Proposito.ENTRADA_CRUCE, desde=marca)
