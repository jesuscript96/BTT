"""Tests de las decisiones de Jaume del 1-oct (50-56) contra el decisor real y el DAS falso del banco de pruebas.

QUÉ PRUEBA. Con el mismo `Banco` que test_das_decisor (decisor real + Emparejador
del simulador, reloj simulado, sin red):
  * 50 tope GLOBAL de locates: el primer tope corta todos los tickers, cancela lo
    pendiente, avisa UNA vez, sobrevive a un reinicio y se rearma al cambiar de día;
  * 51 parciales de locates sin tope de 60 s: el resto se busca hasta que acaba la fase;
  * 52 avisos de ENTRADA PARCIAL / SALIDA PARCIAL;
  * 53 salida rechazada por BP: el stop baja, se espera la confirmación, sale la
    salida y el stop vuelve; reducción rechazada o sin confirmar → no sale;
  * 54 halts: E1 retirar salidas al parar, E2 la salida del halt espera la
    confirmación del stop, E3 salidas del motor guardadas y aplicadas al reabrir;
  * 55 inventario de locates según SLAvailQuery;
  * 56 la entrada agrega 15 s (no 60) antes de cruzar.

POR QUÉ APARTE. test_das_decisor ya pasa de 4.700 líneas: aquí van solo los
escenarios nuevos, reutilizando sus dobles y ayudantes.
"""
from __future__ import annotations

import dataclasses
import types
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.bot_das import diario as mod_diario
from app.bot_das.reglas import locates as reglas_locates
from app.bot_das.simulador_das import Emparejador, LibroSimulado
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    Avisar,
    Cancelar,
    Config,
    DeDAS,
    EnviarOrden,
    EstadoLote,
    EstadoOrden,
    EstadoTicker,
    Locate,
    LocateCancelar,
    MsgSLAvail,
    Nivel,
    Proposito,
    Reemplazar,
    Tic,
    TipoOrden,
)
from test_das_decisor import (  # noqa: F401 — `banco` es un fixture: importarlo lo pone a disposición de este módulo
    OTRO,
    SID,
    STOPS,
    TICKER,
    Banco,
    _a_halt,
    _cfg_ventana_larga,
    _compras,
    _consultas,
    _fila,
    _radar_de,
    _reconstruir_anotado,
    _salida_motor,
    _salta_el_stop,
    _sin_compra_doble,
    _vivas_compra,
    abrir_posicion,
    acciones_de,
    anotaciones,
    banco,
    evento,
    lote_de,
    momento_de,
    salida,
)

D = Decimal
COTIZACIONES_DOS = ((TICKER, "3.44", "3.46", "3.45"), (OTRO, "3.44", "3.46", "3.45"))


def _avisos(acciones: list, prefijo: str) -> list[Avisar]:
    return [a for a in acciones if isinstance(a, Avisar) and (a.clave or "").startswith(prefijo)]


def _das(b: Banco, comando: str, fn) -> None:
    """Cambia cómo contesta el DAS falso del banco a `comando` (el Emparejador guarda sus manejadores al construirse)."""
    b.das._manejadores[comando] = types.MethodType(fn, b.das)


def _stops_vivos(b: Banco, ticker: str = TICKER) -> int:
    return _vivas_compra(b, *STOPS, ticker=ticker)


# ═══════════════ decisión 50: tope GLOBAL de locates ═══════════════
def _pendiente_atascada(monkeypatch, tickers: set[str], servida: bool = False) -> None:
    """La compra de locate de `tickers` se queda Pending en DAS (aún no servida). Con `servida`, el SLCANCELORDER llega
    tarde: DAS ya la había servido y contesta Located (lo que se gastó se contabiliza)."""
    original = Emparejador._localizar

    def localizar(self, loc, cfg_loc):
        if loc["ticker"] in tickers and loc["estado"] == "Pending" and not loc.get("_servir"):
            return
        original(self, loc, cfg_loc)

    monkeypatch.setattr(Emparejador, "_localizar", localizar)
    if servida:
        def cancelar(self, p):
            loc = self._libro._locates.get(int(p[1]))
            loc["_servir"] = True
            original(self, loc, self._libro._cfg_locate(loc["ticker"]))
            return [self._linea_slorder(loc)]
        monkeypatch.setattr(Emparejador, "_sl_cancel", cancelar)


def _banco_tope(cfg: Config, tmp_path: Path) -> Banco:
    """Dos tickers cotizados, ventana larga, cuenta de 1.000 $ (tope 3 % = 30 $) con 25 $ ya pagados hoy."""
    b = Banco(_cfg_ventana_larga(cfg), tmp_path)
    b.preparar(locates=(), cotizaciones=COTIZACIONES_DOS)
    b.estado.cuenta.equity = D("1000")
    b.estado.gasto_locates_dia = D("25")
    b.libro.configurar_locate(OTRO, precio=D("0.01"))                   # 100 · 0,01 = 1 $: cabe (25 + 1 ≤ 30)
    b.libro.configurar_locate(TICKER, precio=D("0.10"))                 # 100 · 0,10 = 10 $: con lo pagado NO cabe
    return b


def test_decision_50_el_primer_tope_corta_todos_los_tickers_cancela_lo_pendiente_y_avisa_una_vez(
        cfg: Config, tmp_path: Path, monkeypatch) -> None:
    """Decisión 50 (Jaume 1-oct): la compra de XYZ no cabe en el 3 % con lo ya pagado → corte GENERAL del día: nadie más
    consulta ni compra (tampoco filas nuevas del radar), la compra Pending de ABC se cancela con SLCANCELORDER (sin
    aviso de fallo por pareja) y sale UN solo aviso nivel 2 con lo gastado, el tope y las compras canceladas."""
    _pendiente_atascada(monkeypatch, {OTRO})
    b = _banco_tope(cfg, tmp_path)
    _radar_de(b, [_fila(100.0)], ticker=OTRO)
    b.avanzar(1)
    assert [c.ticker for c in _compras(b)] == [OTRO] and b.estado.locates[(OTRO, SID)].estado == "Pending"
    id_otro = b.estado.locates[(OTRO, SID)].id_das
    marca = b.marca()
    _radar_de(b, [_fila(100.0)])
    b.avanzar(1)
    tras = b.desde(marca)
    assert b.estado.locates_tope_dia is True
    assert not _compras(b, marca)
    (corte,) = anotaciones(tras, reglas_locates.ANOTACION_TOPE_GLOBAL)
    assert (corte.datos["ticker"], corte.datos["gasto_dia"], corte.datos["tope"]) == (TICKER, D("25"), D("30"))
    assert [c.id_das for c in acciones_de(tras, LocateCancelar)] == [id_otro]
    assert [loc["estado"] for loc in b.libro.locates() if loc["ticker"] == OTRO] == ["Canceled"]
    assert b.estado.locates[(OTRO, SID)].estado == "parado" and b.estado.locates[(TICKER, SID)].estado == "parado"
    assert not _avisos(tras, "locate_fallo:")
    (aviso,) = _avisos(b.historial, "locates_tope")
    assert aviso.nivel is Nivel.AVISO
    assert "no se compran más locates hoy en ningún ticker" in aviso.texto and "canceladas 1" in aviso.texto
    assert "25.00 $ de 30.00 $" in aviso.texto
    # (1) nadie vuelve a consultar: ni las parejas que había ni las filas nuevas del radar
    marca = b.marca()
    _radar_de(b, [_fila(100.0)])
    _radar_de(b, [_fila(300.0)], ticker=OTRO)
    b.avanzar(10)
    assert not _consultas(b, marca) and not _compras(b, marca)
    assert len(_avisos(b.historial, "locates_tope")) == 1


def test_decision_50_la_compra_que_das_ya_habia_servido_se_contabiliza(cfg: Config, tmp_path: Path,
                                                                       monkeypatch) -> None:
    """Decisión 50: si DAS ya había servido la compra que el corte cancela, su Located se contabiliza normal (con su
    gasto) y la pareja no sigue buscando el resto."""
    _pendiente_atascada(monkeypatch, {OTRO}, servida=True)
    b = _banco_tope(cfg, tmp_path)
    _radar_de(b, [_fila(100.0)], ticker=OTRO)
    b.avanzar(1)
    _radar_de(b, [_fila(100.0)])
    b.avanzar(1)
    loc = b.estado.locates[(OTRO, SID)]
    assert b.estado.locates_tope_dia is True
    assert (loc.estado, loc.localizadas) == ("Located", 100)
    assert b.estado.gasto_locates_dia == D("26")                         # 25 + el 1 $ de la compra servida
    marca = b.marca()
    b.avanzar(10)
    assert not _consultas(b, marca)


def test_decision_50_lo_pagado_que_alcanza_el_tope_tambien_corta(cfg: Config, tmp_path: Path) -> None:
    """Decisión 50: el Located que hace que lo PAGADO llegue al tope corta el día (aunque esa compra cupiera)."""
    b = Banco(_cfg_ventana_larga(cfg), tmp_path)
    b.preparar(locates=(), cotizaciones=COTIZACIONES_DOS)
    b.estado.cuenta.equity = D("1000")
    b.estado.gasto_locates_dia = D("20")
    b.libro.configurar_locate(TICKER, precio=D("0.10"))                 # 20 + 10 = 30 $: justo en el tope (cabe)
    _radar_de(b, [_fila(100.0)])
    b.avanzar(1)
    assert [c.qty for c in _compras(b)] == [100]
    assert b.estado.gasto_locates_dia == D("30") and b.estado.locates_tope_dia is True
    assert anotaciones(b.historial, reglas_locates.ANOTACION_TOPE_GLOBAL)[0].datos["motivo"] == \
        "lo pagado alcanza el tope del día"
    marca = b.marca()
    _radar_de(b, [_fila(100.0)], ticker=OTRO)
    b.avanzar(5)
    assert not _consultas(b, marca)


def test_decision_50_la_entrada_sin_locates_tras_el_corte_se_pierde_como_con_la_busqueda_parada(
        cfg: Config, tmp_path: Path, monkeypatch) -> None:
    """Decisión 50: tras el corte las entradas siguen con lo YA localizado; una señal sin locates se trata como con la
    búsqueda parada (entrada perdida por locates, con su aviso); con locates libres entra."""
    _pendiente_atascada(monkeypatch, {OTRO})
    b = _banco_tope(cfg, tmp_path)
    b.estado.locates[(OTRO, "prueba-2")] = Locate(ticker=OTRO, strategy_id="prueba-2", pedidas=0)   # ruido inocuo
    _radar_de(b, [_fila(100.0)])
    b.avanzar(1)
    assert b.estado.locates_tope_dia is True
    b.simstatus()
    acciones = b.senal(evento())
    assert anotaciones(acciones, "locate_perdida_entrada")
    assert "tope de locates del día" in anotaciones(acciones, "locate_perdida_entrada")[0].datos["motivo"]
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR)


def test_decision_50_el_corte_sobrevive_al_reinicio_y_se_rearma_al_cambiar_de_dia(cfg: Config, tmp_path: Path) -> None:
    """Decisión 50: `locates_tope_global` va al diario; `diario.reconstruir` rehace el corte (el bot relanzado no vuelve
    a buscar ni a avisar) y el día siguiente se rearma."""
    b = _banco_tope(cfg, tmp_path)
    _radar_de(b, [_fila(100.0)])
    b.avanzar(1)
    rehecho = _reconstruir_anotado(b)
    assert rehecho.locates_tope_dia is True
    b2 = Banco(_cfg_ventana_larga(cfg), tmp_path / "relanzado", estado=rehecho)
    b2.preparar(locates=(), cotizaciones=COTIZACIONES_DOS)
    b2.estado.cuenta.equity = D("1000")
    _radar_de(b2, [_fila(100.0)], ticker=OTRO)
    b2.avanzar(5)
    assert not _consultas(b2) and not _compras(b2) and not _avisos(b2.historial, "locates_tope")
    assert b2.decisor.foto()["locates_tope_dia"] is True
    b2.reloj.fijar(datetime(2026, 9, 28, 4, 0, tzinfo=ET))
    b2.procesar(Tic())
    assert b2.estado.locates_tope_dia is False


def test_decision_50_diario_reconstruye_el_corte() -> None:
    """Decisión 50 (H-2): el registro `locates_tope_global` pone `locates_tope_dia` al reconstruir; sin él, no."""
    from app.bot_das.tipos import Registro
    base = [Registro(v=1, seq=1, t="t", proceso="ejecutor", tipo="locate_estado",
                     datos={"ticker": TICKER, "strategy_id": SID, "estado": "Located", "localizadas": 100,
                            "coste_nuevo": "1"})]
    hoy = datetime(2026, 9, 25).date()
    assert mod_diario.reconstruir(base, hoy).locates_tope_dia is False
    corte = Registro(v=1, seq=2, t="t", proceso="ejecutor", tipo=reglas_locates.ANOTACION_TOPE_GLOBAL,
                     datos={"ticker": TICKER, "gasto_dia": "30", "tope": "30"})
    assert mod_diario.TIPO_LOCATES_TOPE_GLOBAL == reglas_locates.ANOTACION_TOPE_GLOBAL
    assert mod_diario.reconstruir(base + [corte], hoy).locates_tope_dia is True


# ═══════════════ decisión 51: parciales sin tope de 60 s ═══════════════
def test_decision_51_el_parcial_sigue_buscando_el_resto_mas_de_60_s_y_para_al_salir_del_radar(
        cfg: Config, tmp_path: Path) -> None:
    """Decisión 51 (Jaume 1-oct): DAS da 200 de 300 → se sigue pidiendo SOLO el resto (100) cada 3 s, mucho más allá de
    60 s (el tope del ensayo del 28-sep se quitó), y la búsqueda TERMINA con la fase: aquí al salir del radar."""
    b = Banco(_cfg_ventana_larga(cfg), tmp_path)
    b.preparar(locates=())
    b.libro.configurar_locate(TICKER, precio=D("0.01"), disponibles=200)
    _radar_de(b, [_fila(300.0)])
    b.avanzar(1)
    loc = b.estado.locates[(TICKER, SID)]
    assert [c.qty for c in _compras(b)] == [200] and (loc.estado, loc.localizadas) == ("buscando", 200)
    marca = b.marca()
    b.avanzar(180)
    consultas = _consultas(b, marca)
    assert len(consultas) >= 50 and {c.qty for c in consultas} == {100}  # solo lo que falta, cada 3 s, 3 min seguidos
    assert b.estado.locates[(TICKER, SID)].estado == "buscando"
    b.decisor._radar[TICKER] -= 1801.0                                  # fin de la fase A: 30 min fuera del radar
    b.avanzar(4)
    assert b.estado.locates[(TICKER, SID)].estado == "parado"
    marca = b.marca()
    b.avanzar(20)
    assert not _consultas(b, marca)


def test_decision_51_con_la_entrada_dada_y_sin_piramides_el_resto_ya_no_se_busca(cfg: Config, tmp_path: Path) -> None:
    """Decisión 51: el parcial de la fase A (200 de 300) entra con 200 (B2) y, DENTRO y sin pirámides pendientes, la
    pareja ya no necesita más: N pasa a lo que usa el lote y la búsqueda del resto termina."""
    b = Banco(_cfg_ventana_larga(cfg), tmp_path)
    b.preparar(locates=())
    b.libro.configurar_locate(TICKER, precio=D("0.01"), disponibles=200)
    _radar_de(b, [_fila(300.0)])
    b.avanzar(1)
    b.simstatus()
    b.senal(evento(acciones=300.0))
    assert [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [200]
    loc = b.estado.locates[(TICKER, SID)]
    assert (loc.fase, loc.pedidas) == ("C", 200)
    marca = b.marca()
    b.avanzar(30)
    assert not _consultas(b, marca)


# ═══════════════ decisión 52: avisos de parcial ═══════════════
def test_decision_52_salida_parcial_dice_cuantas_salieron_cuantas_faltan_y_que_el_stop_cubre(banco: Banco) -> None:
    """Decisión 52 (Jaume 1-oct): el TP que agrega llena 20 de 50 y se cancela para cruzar el resto → el aviso de ESA
    orden dice «SALIDA PARCIAL»: 20 de 50, faltan 30 y el stop sigue cubriendo las 80 cortas."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.libro.llenar_parcial(D("0.4"), TICKER)
    _salida_motor(b, salida())
    tp = b.enviadas(Proposito.TP_AGREGAR)[0]
    b.cotizar(TICKER, "3.43", "3.45", "3.44")                           # el ask baja al TP: llena el 40 %
    b.tic_das()
    assert b.orden(tp.token).llenas == 20
    b.libro.llenar_parcial(D("1"), TICKER)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    b.avanzar(61)
    (aviso,) = [a for a in b.historial if isinstance(a, Avisar) and a.clave == f"salida:{tp.token}"]
    assert aviso.nivel is Nivel.INFO
    assert "SALIDA PARCIAL" in aviso.texto and "20 de 50" in aviso.texto and "faltan 30" in aviso.texto
    assert "el stop sigue cubriendo" in aviso.texto


def test_decision_52_salida_entera_sigue_siendo_salida(banco: Banco) -> None:
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    _salida_motor(b, salida())
    tp = b.enviadas(Proposito.TP_AGREGAR)[0]
    b.cotizar(TICKER, "3.43", "3.45", "3.44")
    b.tic_das()
    (aviso,) = [a for a in b.historial if isinstance(a, Avisar) and a.clave == f"salida:{tp.token}"]
    assert aviso.texto.startswith("[SOMBRA] SALIDA ") and "PARCIAL" not in aviso.texto


# ═══════════════ decisión 53: salida rechazada por BP → liberar BP bajando el stop ═══════════════
BP = "Not Enough Buying Power"


def test_decision_53_ciclo_completo_baja_el_stop_espera_reenvia_y_restaura(banco: Banco) -> None:
    """Decisión 53 (Jaume 1-oct): el TP de 50 se rechaza por BP con el stop de 100 vivo → REPLACE del stop a 50, se ESPERA
    su confirmación, el TP sale otra vez (token nuevo), aviso 2; cuando el TP termina (aquí se cancela para cruzar) el
    stop vuelve a la posición. Nunca stop + salidas por encima de lo corto."""
    b = banco
    abrir_posicion(b)
    (stop,) = b.enviadas(*STOPS)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    b.libro.rechazar_siguiente(BP)
    marca = b.marca()
    _salida_motor(b, salida())
    tras = b.desde(marca)
    tps = b.enviadas(Proposito.TP_AGREGAR, desde=marca)
    assert len(tps) == 2 and tps[0].token != tps[1].token and tps[1].qty == 50
    assert b.orden(tps[0].token).estado is EstadoOrden.REJECTED
    replace = next(i for i, a in enumerate(tras) if isinstance(a, Reemplazar) and a.token == stop.token)
    reenvio = next(i for i, a in enumerate(tras) if isinstance(a, EnviarOrden) and a.orden.token == tps[1].token)
    confirmado = next(i for i, a in enumerate(tras) if getattr(a, "tipo", None) == "reduccion_stop_confirmada")
    assert replace < confirmado < reenvio                               # (2) la salida espera la confirmación de DAS
    assert tras[replace].qty == 50 and _stops_vivos(b) == 50
    (aviso,) = _avisos(tras, "bp_libera:")
    assert aviso.nivel is Nivel.AVISO
    assert "salida rechazada por buying power; stop reducido de 100 a 50 para poder salir" in aviso.texto
    assert anotaciones(tras, "rechazo")[0].datos["decision"] == "liberar_bp"
    assert _stops_vivos(b) + _vivas_compra(b, Proposito.TP_AGREGAR, Proposito.TP_CRUCE) <= 100
    marca = b.marca()
    b.avanzar(61)                                                       # el TP no llena: se cancela para cruzar
    assert b.orden(tps[1].token).estado is EstadoOrden.CANCELED
    assert anotaciones(b.desde(marca), "bp_stop_repuesto")
    assert any(isinstance(a, Reemplazar) and a.token == stop.token and a.qty == 100 for a in b.desde(marca))
    assert b.pos().estado is EstadoTicker.NORMAL


def test_decision_53_reduccion_rechazada_no_reenvia_y_el_stop_queda_entero(banco: Banco) -> None:
    """Decisión 53: si DAS rechaza la bajada del stop (ReplaceRej), la salida NO sale, el stop se queda entero y aviso 3."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    b.libro.rechazar_siguiente(BP)
    b.libro.rechazar_siguiente("Replace not allowed", accion="ReplaceRej")
    marca = b.marca()
    _salida_motor(b, salida())
    tras = b.desde(marca)
    assert len(b.enviadas(Proposito.TP_AGREGAR, desde=marca)) == 1          # solo la rechazada: no se reenvía
    (aviso,) = _avisos(tras, "bp_sin_reduccion:")
    assert aviso.nivel is Nivel.MAXIMO and "NO se reenvía la salida" in aviso.texto
    assert anotaciones(tras, "reduccion_stop_fallida")
    assert _stops_vivos(b) == 100 and TICKER not in b.decisor._reduccion_stop


def test_decision_53_sin_confirmacion_en_el_plazo_no_reenvia(banco: Banco, monkeypatch) -> None:
    """Decisión 53: DAS no contesta al REPLACE del stop → a los `REDUCCION_STOP_ESPERA_S` la salida no sale, aviso 3."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    b.libro.rechazar_siguiente(BP)
    _das(b, "REPLACE", lambda self, p: [])
    marca = b.marca()
    _salida_motor(b, salida())
    assert len(b.enviadas(Proposito.TP_AGREGAR, desde=marca)) == 1
    b.avanzar(5)
    assert len(b.enviadas(Proposito.TP_AGREGAR, desde=marca)) == 1
    (aviso,) = _avisos(b.desde(marca), "bp_sin_reduccion:")
    assert aviso.nivel is Nivel.MAXIMO and "no confirmó" in aviso.texto


def test_decision_53_un_solo_ciclo_la_segunda_vez_lo_de_siempre_con_el_stop_repuesto(banco: Banco) -> None:
    """Decisión 53: la salida reenviada vuelve a rechazarse por BP → ya no hay otro ciclo: lo de siempre al agotar los
    reintentos (pausa o control humano con aviso) y el stop vuelve a cubrir la posición."""
    b = banco
    abrir_posicion(b)
    (stop,) = b.enviadas(*STOPS)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    b.libro.rechazar_siguiente(BP)
    b.libro.rechazar_siguiente(BP)
    marca = b.marca()
    _salida_motor(b, salida())
    b.avanzar(2)
    tras = b.desde(marca)
    assert len(b.enviadas(Proposito.TP_AGREGAR, desde=marca)) == 2      # la original y UN reenvío
    decisiones = [a.datos["decision"] for a in anotaciones(tras, "rechazo")]
    assert decisiones[0] == "liberar_bp" and decisiones[-1] in ("pausa", "control_humano")
    assert b.pos().estado in (EstadoTicker.PAUSADO, EstadoTicker.CONTROL_HUMANO)
    assert any(isinstance(a, Reemplazar) and a.token == stop.token and a.qty == 100 for a in tras)
    assert _stops_vivos(b) == 100


def test_decision_53_sin_stop_vivo_es_lo_de_siempre(banco: Banco) -> None:
    """Decisión 53: sin stop residente vivo no hay nada que liberar: GET BP y reintento (R-B-07) como hasta ahora."""
    b = banco
    abrir_posicion(b)
    (stop,) = b.enviadas(*STOPS)
    b.decisor._stop_bloqueo[(TICKER, Proposito.STOP, D("4.0").normalize())] = float("inf")   # que no se reponga
    b.dar(b.das.recibir(f"CANCEL {b.orden(stop.token).id_das}"))
    assert _stops_vivos(b) == 0
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    b.libro.rechazar_siguiente(BP)
    marca = b.marca()
    _salida_motor(b, salida())
    assert anotaciones(b.desde(marca), "rechazo")[0].datos["decision"] != "liberar_bp"


# ═══════════════ decisión 54: halts ═══════════════
def _tp_vivo(b: Banco) -> None:
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    _salida_motor(b, salida())
    assert [o.qty for o in b.enviadas(Proposito.TP_AGREGAR)] == [50]


def test_decision_54_e1_al_parar_se_cancela_la_salida_en_vuelo_una_sola_vez(banco: Banco) -> None:
    """E1: al entrar en halt se intenta cancelar el TP vivo (no el stop); confirmado, fuera, y la salida del halt cubre
    la posición entera. Con CancelRej no se insiste durante el halt."""
    b = banco
    abrir_posicion(b)
    _tp_vivo(b)
    tp = b.enviadas(Proposito.TP_AGREGAR)[0]
    (stop,) = b.enviadas(*STOPS)
    marca = b.marca()
    b.libro.halt(TICKER, "H", "09:31:00")
    b.avanzar(1.5)
    tras = b.desde(marca)
    assert [c.token for c in acciones_de(tras, Cancelar)][:1] == [tp.token]             # lo primero: la salida en vuelo
    (intento,) = anotaciones(tras, "halt_salida_retirada_intento")                      # el stop NO se toca en E1
    assert intento.datos["token"] == tp.token and intento.datos["token"] != stop.token
    assert b.orden(tp.token).estado is EstadoOrden.CANCELED
    assert anotaciones(tras, "halt_salida_guardada")[0].datos["resto"] == 50
    assert [o.qty for o in b.enviadas(Proposito.HALT_OPEN, desde=marca)] == [100]
    assert _sin_compra_doble(b, 100)


def test_decision_54_e1_cancel_rechazado_sigue_contando_y_no_se_reintenta(banco: Banco) -> None:
    b = banco
    abrir_posicion(b)
    _tp_vivo(b)
    tp = b.enviadas(Proposito.TP_AGREGAR)[0]
    b.libro.rechazar_siguiente("Cannot cancel during halt", accion="CancelRej")
    marca = b.marca()
    b.libro.halt(TICKER, "H", "09:31:00")
    b.avanzar(30)
    tras = b.desde(marca)
    assert [c.token for c in acciones_de(tras, Cancelar)].count(tp.token) == 1
    assert b.orden(tp.token).estado in (EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL)
    assert [o.qty for o in b.enviadas(Proposito.HALT_OPEN, desde=marca)] == [50]   # el TP vivo cuenta
    assert _stops_vivos(b) + _vivas_compra(b, Proposito.HALT_OPEN, Proposito.TP_AGREGAR) <= 100 + 50
    assert _vivas_compra(b, Proposito.HALT_OPEN, Proposito.TP_AGREGAR) <= 100


def test_decision_54_e2_la_salida_del_halt_espera_la_confirmacion_del_stop(banco: Banco) -> None:
    """E2: la MKT por OPEN no sale en la misma tanda que la retirada del stop: sale cuando DAS confirma el Canceled."""
    b = banco
    _a_halt(b)
    (stop,) = b.enviadas(*STOPS)
    marca = b.marca()
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 1, tzinfo=ET))
    tras = b.desde(marca)
    cancel = next(i for i, a in enumerate(tras) if isinstance(a, Cancelar) and a.token == stop.token)
    canceled = next(i for i, a in enumerate(tras) if getattr(a, "tipo", None) == "orden_act"
                    and a.datos.get("token") == stop.token and a.datos.get("accion") == "Canceled")
    envio = next(i for i, a in enumerate(tras) if isinstance(a, EnviarOrden) and a.orden.proposito is Proposito.HALT_OPEN)
    assert cancel < canceled < envio
    assert anotaciones(tras, "reduccion_stop_confirmada")[0].datos["motivo"] == "halt"
    assert _sin_compra_doble(b, 100)


def test_decision_54_e2_cancel_del_stop_rechazado_no_envia_la_salida_y_avisa_3(banco: Banco) -> None:
    """E2: si DAS no deja retirar el stop (CancelRej), NO sale la salida del halt; el stop queda como única protección,
    aviso 3 y no se insiste durante el halt."""
    b = banco
    _a_halt(b)
    b.libro.rechazar_siguiente("Halted: cannot cancel", accion="CancelRej")
    marca = b.marca()
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 1, tzinfo=ET))
    b.avanzar(70)                                                       # otra decisión no vuelve a intentarlo
    tras = b.desde(marca)
    assert not b.enviadas(Proposito.HALT_OPEN, Proposito.HALT_PM_LIMITE, desde=marca)
    (aviso,) = _avisos(tras, f"halt_sin_reduccion:{TICKER}")
    assert aviso.nivel is Nivel.MAXIMO and "no se envía la salida, queda el stop" in aviso.texto
    assert _stops_vivos(b) == 100
    assert len([a for a in acciones_de(tras, Cancelar)]) == 1


def test_decision_54_e2_replace_rechazado_pasa_a_cancel_y_si_tambien_se_rechaza_no_sale(banco: Banco) -> None:
    """E2 + decisión 48: TP de 50 vivo (CancelRej al parar) → la MKT sería de 50 y el stop baja a 50 con REPLACE;
    ReplaceRej → CANCEL; CancelRej → no sale nada, aviso 3 y el stop entero sigue."""
    b = banco
    abrir_posicion(b)
    _tp_vivo(b)
    b.libro.rechazar_siguiente("Cannot cancel during halt", accion="CancelRej")      # el TP al parar (E1)
    b.libro.rechazar_siguiente("Replace blocked", accion="ReplaceRej")              # bajar el stop
    b.libro.rechazar_siguiente("Cancel blocked", accion="CancelRej")                # retirar el stop
    marca = b.marca()
    b.libro.halt(TICKER, "H", "09:31:00")
    b.avanzar(1.5)
    tras = b.desde(marca)
    assert anotaciones(tras, "halt_stop_cancelado_replace_rej")
    assert not b.enviadas(Proposito.HALT_OPEN, desde=marca)
    assert _avisos(tras, f"halt_sin_reduccion:{TICKER}")[0].nivel is Nivel.MAXIMO
    assert _stops_vivos(b) == 100


def test_decision_54_e2_sin_confirmacion_en_el_plazo_no_sale(banco: Banco, monkeypatch) -> None:
    b = banco
    _a_halt(b)
    original = b.das._manejadores["CANCEL"]

    def cancel_mudo(self, p):
        o = self._libro._ordenes.get(int(p[1])) if len(p) == 2 and p[1].isdigit() else None
        if o is not None and o.tipo == TipoOrden.STOP_LIMITE_PP.value:
            return []                                                   # DAS no contesta (símbolo parado)
        return original(p)

    _das(b, "CANCEL", cancel_mudo)
    marca = b.marca()
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 1, tzinfo=ET))
    assert not b.enviadas(Proposito.HALT_OPEN, desde=marca)
    b.avanzar(5)
    assert not b.enviadas(Proposito.HALT_OPEN, desde=marca)
    assert _avisos(b.desde(marca), f"halt_sin_reduccion:{TICKER}")


def _halt_mantener(b: Banco) -> None:
    """Halt LULD con el precio BAJO el stop: «mantener» (no sale nada; el stop sigue)."""
    _a_halt(b, ta="P", cot=("3.40", "3.42", "3.41"))


def test_decision_54_e3_tp_que_llega_en_el_halt_se_guarda_y_sale_al_reabrir(banco: Banco) -> None:
    """E3: un TP del motor con el símbolo parado no se pierde: se guarda y se aplica AL REABRIR (sin plazo fijo: en
    cuanto el estado de lo vivo se conoce)."""
    b = banco
    _halt_mantener(b)
    marca = b.marca()
    acciones = _salida_motor(b, salida(momento=pd.Timestamp("2026-09-25 09:31:00")))
    assert anotaciones(acciones, "salida_guardada_halt") and not b.enviadas(Proposito.TP_AGREGAR, desde=marca)
    b.avanzar(5)
    assert not b.enviadas(Proposito.TP_AGREGAR, Proposito.TP_CRUCE, desde=marca)
    b.libro.reabrir(TICKER, D("3.41"))
    b.cotizar(TICKER, "3.40", "3.42", "3.41", tam_ask=0)
    b.avanzar(1.0)
    reabre = next(i for i, a in enumerate(b.historial) if getattr(a, "tipo", None) == "halt_reapertura")
    assert reabre >= marca
    tps = b.enviadas(Proposito.TP_AGREGAR, desde=reabre)
    assert [o.qty for o in tps] == [50]
    assert anotaciones(b.desde(marca), "salidas_guardadas_halt_aplicadas")


def test_decision_54_e3_tp_previo_vivo_y_tp_guardado_no_sobrecubren(banco: Banco) -> None:
    """E3: TP de 50 vivo antes del halt que DAS no deja cancelar + un TP de 100 del motor durante el halt → al reabrir
    el guardado sale por lo que queda (50): las compras de salida nunca pasan de la posición corta."""
    b = banco
    abrir_posicion(b)
    _tp_vivo(b)
    b.libro.rechazar_siguiente("Cannot cancel during halt", accion="CancelRej")
    b.libro.halt(TICKER, "P", "09:27:00")
    b.cotizar(TICKER, "3.40", "3.42", "3.41", tam_ask=0)
    b.avanzar(1.5)
    assert b.pos().estado is EstadoTicker.HALT
    marca = b.marca()
    _salida_motor(b, salida(acciones=100.0, momento=pd.Timestamp("2026-09-25 09:32:00")))
    b.libro.reabrir(TICKER, D("3.41"))
    b.cotizar(TICKER, "3.40", "3.42", "3.41", tam_ask=0)
    b.avanzar(1.0)
    nuevos = b.enviadas(Proposito.TP_AGREGAR, Proposito.TP_CRUCE, desde=marca)
    assert [o.qty for o in nuevos] == [50]
    assert _vivas_compra(b, Proposito.TP_AGREGAR, Proposito.TP_CRUCE, Proposito.HALT_OPEN,
                         Proposito.HALT_PM_LIMITE) <= 100


def test_decision_54_e3_si_el_halt_ya_cerro_la_posicion_lo_guardado_se_descarta(banco: Banco) -> None:
    """E3: halt de noticia en RTH → MKT por OPEN de toda la posición; un TP del motor durante el halt se guarda y, al
    reabrir y llenar la OPEN, se descarta con anotación (no sale ninguna compra de más)."""
    b = banco
    _a_halt(b, ta="H", tat="09:30:30")
    b.avanzar(2)
    marca = b.marca()
    _salida_motor(b, salida(momento=pd.Timestamp("2026-09-25 09:31:00")))
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 36, 0, tzinfo=ET))
    assert b.enviadas(Proposito.HALT_OPEN)
    b.libro.reabrir(TICKER, D("3.95"))
    b.avanzar(3)
    assert b.pos().neta_fills == 0
    assert not b.enviadas(Proposito.TP_AGREGAR, Proposito.TP_CRUCE, desde=marca)
    assert anotaciones(b.desde(marca), "salida_guardada_halt_descartada")
    assert not b.enviadas(Proposito.VENTA_EXCESO)


# ═══════════════ decisión 55: el inventario de locates lo manda DAS ═══════════════
def _reuso_no(monkeypatch) -> None:
    monkeypatch.setattr(Emparejador, "_sl_reuse", lambda self, p: [f"$SLReuseQueryRet {p[1]} No"])


def test_decision_55_reentrada_con_das_diciendo_que_hay_disponibles_no_compra(cfg: Config, tmp_path: Path,
                                                                              monkeypatch) -> None:
    """Decisión 55: al cerrarse el lote se pregunta SLAvailQuery; aunque SLReuseQuery diga «No» (pista), DAS dice que
    las 100 siguen disponibles → se liberan y la reentrada NO compra locates."""
    _reuso_no(monkeypatch)
    b = Banco(cfg, tmp_path)
    b.preparar(locates=((TICKER, SID, 100),))
    abrir_posicion(b)
    _salta_el_stop(b)
    consultas = [a.comando for a in b.historial if type(a).__name__ == "Consultar"
                 and a.comando.startswith("SLAvailQuery")]
    assert consultas and consultas[-1] == f"SLAvailQuery CUENTA_PRUEBA {TICKER}"
    nota = anotaciones(b.historial, "locates_inventario_das")[-1].datos
    assert (nota["disponibles_das"], nota["libres_antes"], nota["libres_despues"]) == (100, 0, 100)
    b.avanzar(61)                                                       # otra vela (otro id de señal)
    marca = b.marca()
    b.cotizar(TICKER, "4.00", "4.02", "4.01")
    b.simstatus()
    b.senal(evento(precio=4.01, stop=4.6, momento=momento_de(b.reloj.ahora())))
    b.avanzar(1)
    assert [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca)] == [100]
    assert not _compras(b, marca)


def test_decision_55_das_dice_menos_y_se_compra_solo_la_diferencia(cfg: Config, tmp_path: Path, monkeypatch) -> None:
    """Decisión 55: el bot cree tener 200 localizadas de 300 pero DAS dice que solo hay 100 disponibles → antes de comprar
    se espera la respuesta, se dan 100 por gastadas y se compra SOLO lo que falta según DAS (300 − 100 = 200)."""
    original = LibroSimulado.disponibles_locate
    # DAS ya da por consumidas 100 de las 200 que el bot cree libres (p. ej. un locate de un solo uso que el bot no supo)
    monkeypatch.setattr(LibroSimulado, "disponibles_locate", lambda self, t: max(original(self, t) - 100, 0))
    b = Banco(_cfg_ventana_larga(cfg), tmp_path)
    b.preparar(locates=())
    b.libro.sembrar_locate(TICKER, 200)
    b.estado.locates[(TICKER, SID)] = Locate(ticker=TICKER, strategy_id=SID, pedidas=300, localizadas=200,
                                             estado="buscando", compras=1, precio_accion=D("0.01"))
    _radar_de(b, [_fila(300.0)])
    b.avanzar(1)
    assert anotaciones(b.historial, "locate_espera_inventario")
    nota = anotaciones(b.historial, "locates_inventario_das")[0].datos
    assert (nota["libres_antes"], nota["libres_despues"]) == (200, 100)
    b.avanzar(10)
    assert sum(c.qty for c in _compras(b)) == 200                       # 300 necesarias − 100 que DAS tiene
    loc = b.estado.locates[(TICKER, SID)]
    assert loc.localizadas - loc.usadas == 300 and loc.estado == "Located"
    marca = b.marca()
    b.avanzar(10)
    assert not _compras(b, marca)


def test_decision_55_sin_respuesta_se_usa_el_inventario_propio_y_avisa_una_vez(cfg: Config, tmp_path: Path,
                                                                               monkeypatch) -> None:
    monkeypatch.setattr(Emparejador, "_sl_avail", lambda self, p: [])
    b = Banco(_cfg_ventana_larga(cfg), tmp_path)
    b.preparar(locates=())
    b.estado.locates[(TICKER, SID)] = Locate(ticker=TICKER, strategy_id=SID, pedidas=300, localizadas=200,
                                             estado="buscando", compras=1, precio_accion=D("0.01"))
    _radar_de(b, [_fila(300.0)])
    b.avanzar(1)
    assert not _compras(b)                                              # espera la respuesta (≤ 2 s)
    b.avanzar(2)
    assert [c.qty for c in _compras(b)] == [100]                        # inventario propio: 300 − 200
    (aviso,) = _avisos(b.historial, f"avail_sin_respuesta:{TICKER}")
    assert aviso.nivel is Nivel.AVISO and "se usa el inventario propio" in aviso.texto
    b.avanzar(10)
    assert len(_avisos(b.historial, f"avail_sin_respuesta:{TICKER}")) == 1


def _respuesta_avail(b: Banco, n: int, ticker: str = TICKER) -> list:
    return b.procesar(DeDAS(MsgSLAvail(cruda=f"$SLAvailQueryRet CUENTA_PRUEBA {ticker} {n}", cuenta="CUENTA_PRUEBA",
                                       ticker=ticker, disponibles=n)))


@pytest.mark.parametrize("n, usadas_a, usadas_b", [
    pytest.param(300, 0, 200, id="liberar-primero-la-que-las-va-a-usar"),
    pytest.param(250, 50, 200, id="liberar-solo-lo-que-falta"),
    pytest.param(50, 200, 250, id="gastar-primero-la-que-no-las-necesita"),
])
def test_decision_55_cuadre_del_inventario_en_los_dos_sentidos(banco: Banco, n: int, usadas_a: int,
                                                               usadas_b: int) -> None:
    """Decisión 55 (2): libres del bot 100 (A: 200 localizadas, 200 usadas; B: 300 localizadas, 200 usadas). A busca (la
    que las va a usar) y B no. Liberar: primero A; gastar: primero B. Nunca se libera lo que usa un lote vivo."""
    b = banco
    sid_b = "prueba-2"
    b.estado.locates[(TICKER, SID)] = Locate(ticker=TICKER, strategy_id=SID, pedidas=200, localizadas=200, usadas=200,
                                             estado="buscando")
    b.estado.locates[(TICKER, sid_b)] = Locate(ticker=TICKER, strategy_id=sid_b, pedidas=300, localizadas=300,
                                               usadas=200, estado="Located")
    acciones = _respuesta_avail(b, n)
    assert (b.estado.locates[(TICKER, SID)].usadas, b.estado.locates[(TICKER, sid_b)].usadas) == (usadas_a, usadas_b)
    nota = anotaciones(acciones, "locates_inventario_das")[0].datos
    assert nota["libres_antes"] == 100 and nota["libres_despues"] == min(n, 300)
    assert all(a.datos.get("usadas") is not None for a in anotaciones(acciones, "locate_estado"))


def test_decision_55_no_se_libera_lo_que_usa_un_lote_vivo(banco: Banco) -> None:
    b = banco
    abrir_posicion(b)                                                   # 100 cortas con el locate de 1.000
    assert b.estado.locates[(TICKER, SID)].usadas == 100
    _respuesta_avail(b, 1000)                                           # DAS: todo disponible (p. ej. atrasado)
    assert b.estado.locates[(TICKER, SID)].usadas == 100                 # el lote vivo sigue usándolas


# ═══════════════ decisión 56: la entrada agrega 15 s ═══════════════
def test_decision_56_la_entrada_agrega_15_s_y_cruza(banco: Banco) -> None:
    """Decisión 56 (Jaume 1-oct): la límite de entrada espera en el punto medio hasta el cierre de la vela + 15 s (no
    60) y entonces cruza; el TP sigue con sus 60 s."""
    b = banco
    assert b.decisor.cfg.entrada["agregar_s"] == 15 and b.decisor.cfg.salidas["tp_parcial"]["agregar_s"] == 60
    b.simstatus()
    b.senal(evento())
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_bid=0)
    assert f"cruce:{TICKER}" in b.temporizadores
    vence = b.temporizadores[f"cruce:{TICKER}"][0]
    assert round(vence - b.ahora(), 1) == 15.0
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 14, tzinfo=ET))
    assert not b.enviadas(Proposito.ENTRADA_CRUCE)
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 16, tzinfo=ET))
    assert b.enviadas(Proposito.ENTRADA_CRUCE)
