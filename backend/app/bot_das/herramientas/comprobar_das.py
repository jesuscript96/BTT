"""Comprobación de DAS real el PRIMER DÍA (§3.27, §10 «lo que NO se puede probar sin DAS real», lote H).

QUÉ HACE
  `python -m app.bot_das.herramientas.comprobar_das` recorre los 10 pasos de
  §3.27 contra el DAS de verdad, UNO A UNO y con confirmación por consola:
  1 rutas (`GET RouteStatus`), 2 `GET SymStatus`/`GET LDLU` con y sin
  símbolo, 3 el `%ORDER` crudo de un STOPLMTP (y la ZONA HORARIA de DAS,
  L0-05: si su hora no casa con ET se aborta), 4 si un `REPLACE` de cantidad
  conserva el pre/post, 5 PostOnly en SAGEREB y SMAT, 6 el BP que retienen
  los dos stops, 7 qué llega por una conexión watch y si una segunda
  conexión normal entra, 8 el signo de `%POS` en un corto, 9 `%SLRET` real
  (cuántos llegan por consulta, E2-05) y `SLRouteMinCharge ALLROUTE`, 10 qué
  es el `share` de un `REPLACE` sobre una orden PARCIAL (A-02 / D2a-08:
  cantidad abierta o total). Cada paso va al diario (`comprobacion_das`:
  paso, comando, respuesta_cruda, conclusion) y a un informe de texto en
  `BOT_DAS_DIR/informes/`. `--ayuda` imprime los pasos sin tocar nada.

POR QUÉ ESTÁ AQUÍ
  Hay cosas que el manual no dice y ningún simulador puede inventar (formato
  real del `%ORDER` de un STOPLMTP, riesgo 1; textos de rechazo; rutas de
  Sage; 2FA). Se miden una vez, a mano, con el bot apagado, y sus
  conclusiones pasan a la config (`stops.tipo_esperado_en_order`,
  `tecnicos.get_con_simbolo`), a `fixtures/lineas_das.txt` y al catálogo de
  rechazos: la herramienta PROPONE los valores en el informe y no reescribe
  ningún fichero del repo ni la config firmada.

LAS TRAMPAS
  * NADA se ejecuta solo: cada paso pide «s»; los pasos CANARIO (3, 4, 5, 6
    y el 7c) exigen además `BOT_DAS_PERMITIR_ORDENES=1` en el entorno y
    escribir «SI» (corrección 15); sin eso el cliente es de SOLO LECTURA y
    `ClienteDAS` prohíbe cualquier mutante por código (R-O-03).
  * Las órdenes canario son de 1 acción, de COMPRA y lejos del mercado
    (stops con disparo un 50 % por encima del ask; límites PostOnly un 30 %
    por debajo del bid): no deben llenarse. Todas se cancelan al terminar el
    paso y, por si acaso, otra vez al salir. G2-07: una orden aceptada con
    eco TARDÍO no está en la lista de vivas; por eso, tras cada paso canario
    y al salir, se pide `GET ORDERS` y se cancela TODA orden viva con token
    canario (seq ≥ `SEQ_COMPROBACION_DESDE`) que no se conozca.
  * El paso 10 es el único que PUEDE llenarse: compra 2 acciones (al precio
    que diga la persona; por defecto al bid) y espera un parcial de 1 hasta
    `ESPERA_PARCIAL_S`. Lo comprado se VENDE después (con «SI») por lo
    llenado de ESA orden, nunca por la posición entera. Un parcial no se
    puede forzar en DAS real: si no llega, el paso lo dice y la pregunta
    queda para el soporte de DAS.
  * El bot tiene que estar APAGADO: una orden con token nuestro que el
    ejecutor no tiene en su diario sería para él una orden ajena (caso 4,
    pausa global). Si algún cerrojo de supervisor/ejecutor/vigilante está
    tomado, la herramienta no arranca. Los tokens canario usan secuencias
    desde `SEQ_COMPROBACION_DESDE` (99.000), lejos de las del ejecutor.
  * El paso 8 no abre posiciones: lee `%POS`; si no hay ningún corto, pide
    a la persona que abra uno de 1 acción A MANO y lo vuelve a leer.
  * Todo lo que se escribe (diario, informe, consola) pasa por
    `protocolo.redactar` y el `FiltroSecretos` del entorno (riesgo 20).
  * Importar el módulo no abre red, no lee ficheros y no arranca hilos.
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import time
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from app.bot_das import VERSION
from app.bot_das import avisos as mod_avisos
from app.bot_das import config as mod_config
from app.bot_das import protocolo
from app.bot_das import reloj as mod_reloj
from app.bot_das import tokens as mod_tokens
from app.bot_das.cerrojo import CerrojoInstancia
from app.bot_das.cliente import ENV_PERMITIR_ORDENES, ClienteDAS
from app.bot_das.diario import Diario
from app.bot_das.mercado_das import MercadoDAS
from app.bot_das.reglas import precios
from app.bot_das.reloj import Reloj
from app.bot_das.tipos import (
    STOP_EMERGENCIA_DISPARO_PCT,
    STOP_PRINCIPAL_LIMITE_PCT,
    EstadoOrden,
    Fase,
    Lado,
    MensajeDAS,
    MsgBP,
    MsgConexion,
    MsgIssueStatus,
    MsgLDLU,
    MsgMarcador,
    MsgOrden,
    MsgOrderAct,
    MsgPos,
    MsgRouteStatus,
    MsgSLMinCharge,
    MsgSLRet,
    OrdenNueva,
    Origen,
    Proposito,
    TipoOrden,
)
from app.bot_das.tokens import GeneradorTokens

CODIGO_OK = 0
CODIGO_ERROR = 1
CODIGO_BOT_ENCENDIDO = 3
CODIGO_ENTORNO = 5

RUTAS_TABLA = ("SAGEREB", "SAGEPRO", "EDGA", "MIAX", "STOP", "SMAT", "OPEN")   # §3.27 paso 1 (TABLA-RUTAS)
RUTAS_POST_ONLY = ("SAGEREB", "SMAT")                                          # paso 5
RUTA_INQUIRE = "ALLROUTEWTTYPE1"                                               # R-H-01 (no es mutante)
RUTA_MIN_CHARGE = "ALLROUTE"
QTY_INQUIRE = 100
ESPERA_RESPUESTA_S = 3.0          # cuánto se escucha tras cada comando
ESPERA_WATCH_S = 10.0             # paso 7: escucha de la conexión watch
DISPARO_SOBRE_ASK_PCT = Decimal("50")    # stops canario: lejos del mercado (no deben dispararse)
LIMITE_BAJO_BID_PCT = Decimal("30")      # PostOnly canario: lejos del mercado (no debe llenarse)
SEQ_COMPROBACION_DESDE = 99_000          # tokens canario: lejos de las secuencias del ejecutor en un día
PROCESOS_BOT = ("supervisor", "ejecutor", "vigilante")
CONFIRMACION_CANARIO = "SI"
ESPERA_PARCIAL_S = 60.0                  # paso 10: cuánto se espera a que la compra de 2 quede parcial (1 llena)
QTY_PARCIAL = 2                          # paso 10: la orden que debe quedar parcial
SHARE_REPLACE_PARCIAL = 2                # paso 10: abierta → qty 3 / lvqty 2; total → qty 2 / lvqty 1
MARGEN_VENTA_PCT = Decimal("1")          # paso 10: lo comprado se vende a bid × (1 − 1 %) (vendible)
ESTADOS_VIVOS = frozenset({EstadoOrden.SENDING, EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL, EstadoOrden.HOLD,
                           EstadoOrden.TRIGGERED})


@dataclass(frozen=True)
class PasoComprobacion:
    """Un paso de §3.27 (`canario` = manda órdenes reales de 1 acción)."""
    numero: int
    titulo: str
    canario: bool
    detalle: str


PASOS: tuple[PasoComprobacion, ...] = (
    PasoComprobacion(1, "Rutas habilitadas", False,
                     "GET RouteStatus → lista de rutas y aviso de las de la tabla que falten "
                     "(SAGEREB, SAGEPRO, EDGA, MIAX, STOP/SMAT, OPEN)."),
    PasoComprobacion(2, "GET SymStatus / GET LDLU con y sin símbolo", False,
                     "Qué contesta DAS a cada forma (§5.8) → valor propuesto de tecnicos.get_con_simbolo."),
    PasoComprobacion(3, "%ORDER crudo de un STOPLMTP", True,
                     "NEWORDER B STOPLMTP de 1 acción lejos del mercado → línea %ORDER CRUDA (propuesta para "
                     "fixtures/lineas_das.txt), valor propuesto de stops.tipo_esperado_en_order (riesgo 1), qué es "
                     "su precio (disparo o límite, D2a-10) y la hora de DAS contra ET (L0-05: si no casa, se aborta)."),
    PasoComprobacion(4, "REPLACE de cantidad sobre el STOPLMTP", True,
                     "¿Conserva el pre/post? (2h.8) Compara el tipo del %ORDER antes y después; luego cancela."),
    PasoComprobacion(5, "PostOnly en SAGEREB y SMAT", True,
                     "Compra límite PostOnly de 1 acción lejos del mercado en cada ruta → aceptada o rechazada "
                     "con el texto literal; luego cancela."),
    PasoComprobacion(6, "BP retenido por principal + emergencia", True,
                     "GET BP antes y después de poner dos stops de 1 acción (EP-3); luego los cancela."),
    PasoComprobacion(7, "Conexión watch y segunda conexión normal", False,
                     "Qué llega por watch (%OrderAct? $Quote? marcadores?) y si una segunda conexión normal entra "
                     "(R-C-08); 7c opcional CANARIO: si esa segunda conexión puede enviar una orden."),
    PasoComprobacion(8, "Signo de %POS en un corto", False,
                     "Lee %POS; si no hay cortos, pide abrir uno de 1 acción A MANO → qty_corto_negativa."),
    PasoComprobacion(9, "Locates: %SLRET real y mínimo por ruta", False,
                     f"SLPRICEINQUIRE X {QTY_INQUIRE} {RUTA_INQUIRE} → %SLRET real y CUÁNTOS llegan por consulta "
                     f"(E2-05); SLRouteMinCharge {RUTA_MIN_CHARGE}."),
    PasoComprobacion(10, "REPLACE sobre una orden PARCIAL: ¿share abierto o total?", True,
                     f"Compra límite de {QTY_PARCIAL} acciones que quede parcial (1 llena) → REPLACE id "
                     f"{SHARE_REPLACE_PARCIAL} → lvqty/qty del %ORDER → propuesta stops.replace_share_es_abierta "
                     f"(A-02 / D2a-08); luego cancela y VENDE lo comprado."),
)


def texto_ayuda() -> str:
    """Los 10 pasos, para `--ayuda` (sin red, sin ficheros)."""
    lineas = ["Comprobación de DAS real (primer día, bot APAGADO). Cada paso pide confirmación por consola.",
              f"Los pasos CANARIO mandan órdenes de 1 acción y exigen {ENV_PERMITIR_ORDENES}=1 y escribir "
              f"«{CONFIRMACION_CANARIO}».", ""]
    for p in PASOS:
        marca = " [CANARIO]" if p.canario else ""
        lineas.append(f"  {p.numero}. {p.titulo}{marca}: {p.detalle}")
    lineas += ["", "Uso: python -m app.bot_das.herramientas.comprobar_das [--pasos 1,2,9] [--config ruta] [--ayuda]"]
    return "\n".join(lineas)


class Consola:
    """Entrada/salida de la persona (inyectable). `confirmar` = «s»/«si»; `confirmar_canario` = «SI» exacto."""

    def __init__(self, entrada: Callable[[str], str] = input, salida: Callable[[str], None] = print) -> None:
        self._entrada = entrada
        self._salida = salida

    def decir(self, texto: str) -> None:
        self._salida(_para_consola(texto))

    def preguntar(self, texto: str) -> str:
        try:
            return self._entrada(_para_consola(texto)).strip()
        except EOFError:   # frontera de consola: sin teclado, la respuesta es «no»
            return ""

    def confirmar(self, texto: str) -> bool:
        return self.preguntar(f"{texto} [s/N] ").lower() in ("s", "si", "sí")

    def confirmar_canario(self, texto: str) -> bool:
        return self.preguntar(f"{texto} Escribe {CONFIRMACION_CANARIO} para seguir: ") == CONFIRMACION_CANARIO


class Comprobador:
    """Ejecuta los pasos sobre UNA conexión normal con DAS (`cliente`, que entrega en `cola`)."""

    def __init__(self, cliente: ClienteDAS, cola: "queue.Queue[Any]", reloj: Any, diario: Diario, informe: Path,
                 consola: Consola, canario_permitido: bool, rutas_cfg: dict, limpiar: Callable[[str], str],
                 fabrica_cliente: Callable[..., ClienteDAS]) -> None:
        self._cliente = cliente
        self._cola = cola
        self._reloj = reloj
        self._diario = diario
        self._informe = informe
        self._consola = consola
        self._canario = canario_permitido
        self._rutas_cfg = rutas_cfg
        self._limpiar = limpiar
        self._fabrica = fabrica_cliente
        self._tokens = GeneradorTokens(Origen.EJECUTOR, reloj.hoy(), SEQ_COMPROBACION_DESDE)
        self._mercado = MercadoDAS(reloj)
        self._vivas: dict[int, str] = {}           # id_das → descripción de las órdenes canario sin cancelar
        self._stop_paso3: Optional[tuple[int, int, str, Decimal, Decimal, str]] = None
        self._abortado: Optional[str] = None       # L0-05: DAS no está en ET → no se sigue
        self._envio_canario = False                # G2-07: se mandó algún mutante canario (hay que barrer al salir)

    # ── orquestación ──
    def ejecutar(self, numeros: Sequence[int]) -> int:
        """Cada paso pide confirmación; los canario, además, permiso. Devuelve 0 (los fallos quedan en el informe)."""
        try:
            for paso in PASOS:
                if paso.numero not in numeros:
                    continue
                self._consola.decir(f"\n── Paso {paso.numero}: {paso.titulo}{' [CANARIO]' if paso.canario else ''}")
                self._consola.decir(f"   {paso.detalle}")
                if self._abortado is not None:
                    self._registrar(paso.numero, [], [], f"saltado: comprobación ABORTADA ({self._abortado})")
                    continue
                if paso.canario and not self._canario:
                    self._registrar(paso.numero, [], [], f"saltado: sin permiso canario ({ENV_PERMITIR_ORDENES}=1 + "
                                                          f"{CONFIRMACION_CANARIO})")
                    continue
                if not self._consola.confirmar(f"¿Ejecutar el paso {paso.numero}?"):
                    self._registrar(paso.numero, [], [], "saltado por la persona")
                    continue
                try:
                    getattr(self, f"_paso_{paso.numero}")()
                except Exception as exc:  # noqa: BLE001 — frontera (DAS real): un paso que falla no impide los demás
                    self._registrar(paso.numero, [], [], f"ERROR {type(exc).__name__}: {exc}")
                if paso.canario or paso.numero == 7:
                    self._barrer_canario(paso.numero, conocidas=False)   # G2-07: eco tardío de lo de ESTE paso
        finally:
            self.cancelar_vivas()
        return CODIGO_OK

    def cancelar_vivas(self) -> None:
        """Cancela TODA orden canario que siga viva (también al salir por error) y barre las de eco tardío (G2-07)."""
        for id_das, que in list(self._vivas.items()):
            mensajes = self._enviar(protocolo.cmd_cancel(id_das))
            self._vivas.pop(id_das, None)
            self._registrar(0, [f"CANCEL {id_das}"], mensajes, f"limpieza: cancelada {que}")
        if self._envio_canario:
            self._barrer_canario(0, conocidas=True)

    def _barrer_canario(self, paso: int, conocidas: bool) -> None:
        """G2-07 (riesgo 11): `GET ORDERS` y CANCEL de toda orden VIVA con token canario de hoy (seq ≥ 99 000).

        Una orden aceptada con eco tardío no entró en `_vivas` y quedaría viva
        en la cuenta real. Con `conocidas=False` (tras un paso) se respetan las
        de `_vivas` (el STOPLMTP del paso 3 sigue para el paso 4); al salir se
        cancela todo.
        """
        if not self._envio_canario:
            return
        mensajes = self._enviar(protocolo.cmd_get("ORDERS"))
        ultimas: dict[int, MsgOrden] = {}
        for m in mensajes:
            if isinstance(m, MsgOrden) and _es_token_canario(m.token, self._reloj.hoy()):
                ultimas[m.id] = m
        # una VENTA canario (la que cierra lo comprado en el paso 10) no se cancela nunca: dejaría la cuenta larga
        huerfanas = [m for m in ultimas.values()
                     if m.estado in ESTADOS_VIVOS and not str(m.lado).upper().startswith("S")
                     and (conocidas or m.id not in self._vivas)]
        for m in huerfanas:
            respuesta = self._cancelar(m.id)
            self._registrar(paso, [protocolo.cmd_get("ORDERS"), f"CANCEL {m.id}"], [m] + respuesta,
                            f"limpieza G2-07: orden canario con eco tardío (token {m.token}, {m.ticker}) cancelada")

    # ── los 9 pasos ──
    def _paso_1(self) -> None:
        comando = protocolo.cmd_get("RouteStatus")
        mensajes = self._enviar(comando)
        rutas = {m.ruta.upper(): m.habilitada for m in mensajes if isinstance(m, MsgRouteStatus)}
        esperadas = sorted(set(RUTAS_TABLA) | {str(v).upper() for v in _valores_ruta(self._rutas_cfg)})
        faltan = [r for r in esperadas if r not in rutas]
        apagadas = [r for r in esperadas if rutas.get(r) is False]
        conclusion = (f"rutas vistas: {sorted(rutas)}; faltan: {faltan or 'ninguna'}; deshabilitadas: "
                      f"{apagadas or 'ninguna'}")
        self._registrar(1, [comando], mensajes, conclusion)

    def _paso_2(self) -> None:
        ticker = self._ticker()
        comandos = [protocolo.cmd_get("SymStatus", ticker), protocolo.cmd_get("LDLU", ticker)]
        con = [m for c in comandos for m in self._enviar(c)]
        sb = protocolo.cmd_sb(ticker)
        sin_cmds = [protocolo.cmd_get("SymStatus"), protocolo.cmd_get("LDLU")]
        sin = self._enviar(sb) + [m for c in sin_cmds for m in self._enviar(c)]
        self._enviar(protocolo.cmd_unsb(ticker))
        responde = any(isinstance(m, (MsgIssueStatus, MsgLDLU)) and m.ticker.upper() == ticker for m in con)
        responde_sin = any(isinstance(m, (MsgIssueStatus, MsgLDLU)) and m.ticker.upper() == ticker for m in sin)
        conclusion = (f"con símbolo: {'contesta' if responde else 'NO contesta'}; sin símbolo (con SB): "
                      f"{'contesta' if responde_sin else 'NO contesta'} → propuesta tecnicos.get_con_simbolo = "
                      f"{'true' if responde else 'false'} (§5.8)")
        self._registrar(2, comandos + [sb] + sin_cmds, con + sin, conclusion)

    def _paso_3(self) -> None:
        if not self._consola.confirmar_canario("El paso 3 manda UNA orden STOPLMTP real de 1 acción."):
            self._registrar(3, [], [], "saltado: sin «SI»")
            return
        ticker = self._ticker()
        bid, ask = self._cotizacion(ticker)
        if ask is None:
            self._registrar(3, [], [], f"sin cotización de {ticker}: no se manda nada")
            return
        disparo = precios.con_techo(ask, DISPARO_SOBRE_ASK_PCT, arriba=True)
        limite = precios.con_techo(disparo, STOP_PRINCIPAL_LIMITE_PCT, arriba=True)
        ruta = str(self._rutas_cfg.get("stop") or "STOP")
        orden = OrdenNueva(token=self._tokens.siguiente(), lado=Lado.COMPRA, ticker=ticker, ruta=ruta, qty=1,
                           tipo=TipoOrden.STOP_LIMITE_PP, precio=limite, stop=disparo,
                           proposito=Proposito.STOP_PRINCIPAL)
        comando = protocolo.cmd_neworder(orden)
        mensajes = self._enviar(comando)
        viva = _orden_por_token(mensajes, orden.token)
        if viva is None:
            mensajes += self._enviar(protocolo.cmd_get("ORDERS"))
            viva = _orden_por_token(mensajes, orden.token)
        if viva is None:
            self._registrar(3, [comando], mensajes, f"sin %ORDER del token {orden.token}: {_rechazo(mensajes, orden.token)}")
            return
        self._vivas[viva.id] = f"STOPLMTP {ticker} (paso 3)"
        self._stop_paso3 = (viva.id, orden.token, ticker, disparo, limite, viva.tipo)
        if viva.precio == disparo:
            campo_precio = f"el precio del %ORDER ({viva.precio}) es el DISPARO"
        elif viva.precio == limite:
            campo_precio = (f"el precio del %ORDER ({viva.precio}) es el LÍMITE: con un Type sin números el bot "
                            f"tomaría el límite por disparo (D2a-10): fijar stops.tipo_esperado_en_order")
        else:
            campo_precio = f"el precio del %ORDER ({viva.precio}) no es ni el disparo {disparo} ni el límite {limite}"
        conclusion = (f"%ORDER crudo: {viva.cruda!r}; tipo leído «{viva.tipo}» → propuesta "
                      f"stops.tipo_esperado_en_order = «{viva.tipo}»; {campo_precio}; añadir la línea a "
                      f"fixtures/lineas_das.txt con sus asertos (riesgo 1); {self._comprobar_zona(viva)}")
        self._registrar(3, [comando], mensajes, conclusion)

    def _comprobar_zona(self, viva: MsgOrden) -> str:
        """L0-05 (riesgo 13): la hora del %ORDER recién recibido contra `ahora()` ET; si no casa (> 60 s), se ABORTA."""
        try:
            desfase = mod_reloj.desfase_hora_das_s(viva.hora, self._reloj.ahora())
        except ValueError:
            self._abortado = f"hora ilegible en el %ORDER: {viva.hora!r} (L0-05)"
            return f"ABORTO: {self._abortado}"
        if mod_reloj.hora_das_es_et(viva.hora, self._reloj.ahora()):
            return f"hora de DAS {viva.hora} = ET (desfase {desfase:+.0f} s, L0-05)"
        self._abortado = (f"la hora de DAS ({viva.hora}) no es ET (desfase {desfase:+.0f} s): configura DAS en hora "
                          f"de Nueva York; el bot NO debe operar así (halts y fills desplazados, L0-05)")
        return f"ABORTO: {self._abortado}"

    def _paso_4(self) -> None:
        if self._stop_paso3 is None:
            self._registrar(4, [], [], "saltado: hace falta el STOPLMTP vivo del paso 3")
            return
        if not self._consola.confirmar_canario("El paso 4 hace un REPLACE real de la orden del paso 3 (1 → 2)."):
            self._registrar(4, [], [], "saltado: sin «SI»")
            return
        id_das, _token, ticker, disparo, limite, tipo_antes = self._stop_paso3
        comando = protocolo.cmd_replace(id_das, 2, TipoOrden.STOP_LIMITE_PP, limite, disparo)
        mensajes = self._enviar(comando) + self._enviar(protocolo.cmd_get("ORDERS"))
        despues = [m for m in mensajes if isinstance(m, MsgOrden) and m.id == id_das]
        tipo_despues = despues[-1].tipo if despues else None
        if tipo_despues is None:
            conclusion = f"sin %ORDER tras el REPLACE: {_rechazo(mensajes, None)}"
        elif tipo_despues == tipo_antes:
            conclusion = f"conserva el tipo «{tipo_antes}» → el REPLACE conserva pre/post (2h.8)"
        else:
            conclusion = f"CAMBIA el tipo «{tipo_antes}» → «{tipo_despues}»: el REPLACE pierde pre/post (2h.8)"
        mensajes += self._cancelar(id_das)
        self._stop_paso3 = None
        self._registrar(4, [comando, f"CANCEL {id_das}"], mensajes, f"{ticker}: {conclusion}")

    def _paso_5(self) -> None:
        if not self._consola.confirmar_canario(f"El paso 5 manda {len(RUTAS_POST_ONLY)} compras PostOnly de 1 acción."):
            self._registrar(5, [], [], "saltado: sin «SI»")
            return
        ticker = self._ticker()
        bid, _ask = self._cotizacion(ticker)
        if bid is None:
            self._registrar(5, [], [], f"sin cotización de {ticker}: no se manda nada")
            return
        precio = precios.bajo_bid(bid, LIMITE_BAJO_BID_PCT)
        for ruta in RUTAS_POST_ONLY:
            orden = OrdenNueva(token=self._tokens.siguiente(), lado=Lado.COMPRA, ticker=ticker, ruta=ruta, qty=1,
                               tipo=TipoOrden.LIMITE, precio=precio, post_only=True,
                               proposito=Proposito.TP_AGREGAR)
            comando = protocolo.cmd_neworder(orden)
            mensajes = self._enviar(comando)
            viva = _orden_por_token(mensajes, orden.token)
            if viva is not None:
                self._vivas[viva.id] = f"PostOnly {ticker} {ruta} (paso 5)"
                mensajes += self._cancelar(viva.id)
                conclusion = f"{ruta}: ACEPTADA ({viva.estado.value}); cancelada"
            else:
                conclusion = f"{ruta}: {_rechazo(mensajes, orden.token)}"
            self._registrar(5, [comando], mensajes, conclusion)

    def _paso_6(self) -> None:
        if not self._consola.confirmar_canario("El paso 6 pone DOS stops reales de 1 acción y mira el BP."):
            self._registrar(6, [], [], "saltado: sin «SI»")
            return
        ticker = self._ticker()
        _bid, ask = self._cotizacion(ticker)
        if ask is None:
            self._registrar(6, [], [], f"sin cotización de {ticker}: no se manda nada")
            return
        antes = self._enviar(protocolo.cmd_get("BP"))
        principal = precios.con_techo(ask, DISPARO_SOBRE_ASK_PCT, arriba=True)
        emergencia = precios.con_techo(principal, STOP_EMERGENCIA_DISPARO_PCT, arriba=True)
        ruta = str(self._rutas_cfg.get("stop") or "STOP")
        mensajes = list(antes)
        ids: list[int] = []
        comandos = [protocolo.cmd_get("BP")]
        for disparo, proposito in ((principal, Proposito.STOP_PRINCIPAL), (emergencia, Proposito.STOP_EMERGENCIA)):
            orden = OrdenNueva(token=self._tokens.siguiente(), lado=Lado.COMPRA, ticker=ticker, ruta=ruta, qty=1,
                               tipo=TipoOrden.STOP_LIMITE_PP, stop=disparo,
                               precio=precios.con_techo(disparo, STOP_PRINCIPAL_LIMITE_PCT, arriba=True),
                               proposito=proposito)
            comandos.append(protocolo.cmd_neworder(orden))
            recibidos = self._enviar(comandos[-1])
            mensajes += recibidos
            viva = _orden_por_token(recibidos, orden.token)
            if viva is not None:
                ids.append(viva.id)
                self._vivas[viva.id] = f"STOPLMTP {ticker} (paso 6)"
        despues = self._enviar(protocolo.cmd_get("BP"))
        mensajes += despues
        for id_das in ids:
            mensajes += self._cancelar(id_das)
        bp_antes, bp_despues = _ultimo_bp(antes), _ultimo_bp(despues)
        if bp_antes is None or bp_despues is None:
            conclusion = f"sin #BP antes o después (antes {bp_antes}, después {bp_despues})"
        else:
            conclusion = (f"BP antes {bp_antes}, con {len(ids)} stops {bp_despues}: retenido {bp_antes - bp_despues} "
                          f"(EP-3)")
        self._registrar(6, comandos + [protocolo.cmd_get("BP")], mensajes, conclusion)

    def _paso_7(self) -> None:
        cola_watch: "queue.Queue[Any]" = queue.Queue()
        watch = self._fabrica(watch=True, solo_lectura=True, al_mensaje=cola_watch.put,
                              al_estado=lambda c, m: cola_watch.put(("estado", c, m)))
        recibidos: list[MensajeDAS] = []
        conectado = False
        try:
            conectado = watch.conectar()
            fin = time.monotonic() + ESPERA_WATCH_S
            while conectado and time.monotonic() < fin:
                recibidos += _sacar(cola_watch, 0.2)
        finally:
            watch.cerrar()
        clases = Counter(type(m).__name__ for m in recibidos)
        marcadores = sorted({m.nombre for m in recibidos if isinstance(m, MsgMarcador)})
        self._registrar(7, ["LOGIN … 1 (watch)"], recibidos,
                        f"watch {'conectada' if conectado else 'NO conectó'}: {dict(clases)}; marcadores {marcadores}")
        cola_2: "queue.Queue[Any]" = queue.Queue()
        segunda = self._fabrica(watch=False, solo_lectura=True, al_mensaje=cola_2.put,
                                al_estado=lambda c, m: cola_2.put(("estado", c, m)))
        mensajes: list[MensajeDAS] = []
        entra, logon, puede = False, {}, None
        try:
            entra = segunda.conectar()
            mensajes = _sacar(cola_2, ESPERA_RESPUESTA_S)
            logon = dict(segunda.logon)
            if entra and self._canario and self._consola.confirmar_canario(
                    "7c: ¿mandar por la SEGUNDA conexión un STOPLMTP de 1 acción (y cancelarlo)?"):
                segunda.cerrar()
                segunda = self._fabrica(watch=False, solo_lectura=False, al_mensaje=cola_2.put,
                                        al_estado=lambda c, m: cola_2.put(("estado", c, m)))
                puede = self._probar_envio(segunda, cola_2, mensajes)
        finally:
            segunda.cerrar()
        conclusion = (f"segunda conexión normal: {'conecta' if entra else 'NO conecta'}; logon {logon}; "
                      f"envío por ella: {'no probado' if puede is None else ('SÍ' if puede else 'NO')} (R-C-08)")
        self._registrar(7, ["LOGIN … 0 (segunda)"], mensajes, conclusion)

    def _probar_envio(self, cliente: ClienteDAS, cola: "queue.Queue[Any]", mensajes: list) -> bool:
        if not cliente.conectar():
            return False
        ticker = self._ticker()
        _bid, ask = self._cotizacion(ticker)
        if ask is None:
            return False
        disparo = precios.con_techo(ask, DISPARO_SOBRE_ASK_PCT, arriba=True)
        orden = OrdenNueva(token=self._tokens.siguiente(), lado=Lado.COMPRA, ticker=ticker,
                           ruta=str(self._rutas_cfg.get("stop") or "STOP"), qty=1, tipo=TipoOrden.STOP_LIMITE_PP,
                           stop=disparo, precio=precios.con_techo(disparo, STOP_PRINCIPAL_LIMITE_PCT, arriba=True),
                           proposito=Proposito.STOP_PRINCIPAL)
        self._envio_canario = True                    # G2-07: si el eco llega tarde, el barrido la encuentra
        cliente.enviar(protocolo.cmd_neworder(orden))
        recibidos = _sacar(cola, ESPERA_RESPUESTA_S)
        mensajes += recibidos
        viva = _orden_por_token(recibidos, orden.token)
        if viva is None:
            return False
        self._vivas[viva.id] = f"STOPLMTP {ticker} (paso 7c)"
        cliente.enviar(protocolo.cmd_cancel(viva.id))
        mensajes += _sacar(cola, ESPERA_RESPUESTA_S)
        self._vivas.pop(viva.id, None)
        return True

    def _paso_8(self) -> None:
        comando = protocolo.cmd_get("POSITIONS")
        mensajes = self._enviar(comando)
        cortos = [m for m in mensajes if isinstance(m, MsgPos) and m.tipo == 3]
        if not cortos and self._consola.confirmar("No hay cortos. ¿Abres uno de 1 acción A MANO en DAS y lo leo?"):
            self._consola.preguntar("Abre el corto en DAS y pulsa Intro cuando esté hecho… ")
            mensajes += self._enviar(comando)
            cortos = [m for m in mensajes if isinstance(m, MsgPos) and m.tipo == 3]
        if not cortos:
            conclusion = "sin cortos que leer: qty_corto_negativa sigue sin saberse"
        else:
            negativos = {m.qty_cruda < 0 for m in cortos}
            valor = "true" if negativos == {True} else "false" if negativos == {False} else "MIXTO (revisar)"
            conclusion = (f"%POS de cortos: {[(m.ticker, m.qty_cruda) for m in cortos]} → propuesta "
                          f"qty_corto_negativa = {valor}")
        self._registrar(8, [comando], mensajes, conclusion)

    def _paso_9(self) -> None:
        ticker = self._ticker()
        inquire = protocolo.cmd_sl_inquire(ticker, QTY_INQUIRE, RUTA_INQUIRE)
        minimo = protocolo.cmd_sl_min_charge(RUTA_MIN_CHARGE)
        slret = self._enviar(inquire)
        cargos = self._enviar(minimo)
        rets = [(m.tipo, m.ruta, str(m.precio), m.tamano, m.notas) for m in slret if isinstance(m, MsgSLRet)]
        minimos = [(m.ruta, str(m.minimo)) for m in cargos if isinstance(m, MsgSLMinCharge)]
        rutas = sorted({str(r[1]) for r in rets})
        if len(rets) <= 1:
            cuantos = f"{len(rets)} %SLRET por consulta: la atribución por consulta del decisor vale tal cual (E2-05)"
        else:
            cuantos = (f"{len(rets)} %SLRET por UNA consulta (rutas {rutas}): DAS contesta una vez por ruta; el "
                       f"decisor los recoge en su ventana y elige el más barato (E2-05)")
        self._registrar(9, [inquire, minimo], slret + cargos,
                        f"%SLRET: {rets or 'ninguno'}; {cuantos}; mínimos: {minimos or 'ninguno'}")

    def _paso_10(self) -> None:
        """A-02 / D2a-08: ¿el `share` de un REPLACE sobre una orden PARCIAL es la cantidad ABIERTA o la TOTAL?

        Compra límite de 2 acciones que quede parcial (1 llena) → REPLACE id 2
        precio → abierta: qty 3 / lvqty 2; total: qty 2 / lvqty 1. Después se
        cancela lo vivo y se VENDE lo que llenó ESA orden (nunca la posición
        entera del ticker).
        """
        if not self._consola.confirmar_canario(f"El paso 10 COMPRA hasta {QTY_PARCIAL} acciones REALES (y las vende "
                                               f"después)."):
            self._registrar(10, [], [], "saltado: sin «SI»")
            return
        ticker = self._ticker()
        bid, ask = self._cotizacion(ticker)
        if bid is None or ask is None:
            self._registrar(10, [], [], f"sin cotización de {ticker}: no se manda nada")
            return
        precio = self._precio_paso_10(bid)
        ruta = str(_primera_ruta(self._rutas_cfg, "agregar") or "SAGEREB")
        orden = OrdenNueva(token=self._tokens.siguiente(), lado=Lado.COMPRA, ticker=ticker, ruta=ruta, qty=QTY_PARCIAL,
                           tipo=TipoOrden.LIMITE, precio=precio, proposito=Proposito.TP_AGREGAR)
        comandos = [protocolo.cmd_neworder(orden)]
        mensajes = self._enviar(comandos[0])
        viva = _orden_por_token(mensajes, orden.token)
        if viva is not None and viva.estado in ESTADOS_VIVOS:
            self._vivas[viva.id] = f"LMT {QTY_PARCIAL} {ticker} (paso 10)"
        esperas = max(int(ESPERA_PARCIAL_S // max(_espera_respuesta(), 0.001)), 1)
        for _ in range(esperas):
            if viva is None or _llenas(viva) >= 1 or viva.estado not in ESTADOS_VIVOS:
                break
            comandos.append(protocolo.cmd_get("ORDERS"))
            mensajes += self._enviar(comandos[-1])
            viva = _orden_por_token(mensajes, orden.token) or viva
        if viva is None:
            self._registrar(10, comandos, mensajes, f"sin %ORDER del token {orden.token}: {_rechazo(mensajes, orden.token)}")
            return
        conclusion = "sin parcial de 1: no se pudo medir el share (preguntar al soporte de DAS, D2a-08)"
        if viva.estado in ESTADOS_VIVOS and _llenas(viva) == 1 and viva.lvqty == QTY_PARCIAL - 1:
            reemplazo = protocolo.cmd_replace(viva.id, SHARE_REPLACE_PARCIAL, TipoOrden.LIMITE, precio, None)
            comandos.append(reemplazo)
            respuesta = self._enviar(reemplazo)
            mensajes += respuesta
            despues = [m for m in respuesta if isinstance(m, MsgOrden) and m.id == viva.id]
            if not despues:
                comandos.append(protocolo.cmd_get("ORDERS"))
                mensajes += self._enviar(comandos[-1])
                despues = [m for m in mensajes if isinstance(m, MsgOrden) and m.id == viva.id]
            conclusion = _conclusion_share(despues[-1] if despues else None, mensajes)
        final = self._cerrar_paso_10(viva, ticker, mensajes, comandos)
        self._registrar(10, comandos, mensajes, f"{ticker}: {conclusion}; {final}")

    def _precio_paso_10(self, bid: Decimal) -> Decimal:
        texto = self._consola.preguntar(f"Precio límite de la compra de {QTY_PARCIAL} (Intro = bid {bid}; para que "
                                        f"quede PARCIAL elige uno que solo encuentre 1 acción): ")
        if not texto:
            return bid
        try:
            precio = Decimal(texto.replace(",", "."))
        except ArithmeticError:
            self._consola.decir(f"   precio no válido: se usa el bid {bid}")
            return bid
        return precio if precio.is_finite() and precio > 0 else bid

    def _cerrar_paso_10(self, viva: MsgOrden, ticker: str, mensajes: list, comandos: list) -> str:
        """Cancela lo vivo de la orden del paso 10 y VENDE lo que llenó (solo eso), con «SI»."""
        if viva.id in self._vivas:
            comandos.append(f"CANCEL {viva.id}")
            mensajes += self._cancelar(viva.id)
            finales = [m for m in mensajes if isinstance(m, MsgOrden) and m.id == viva.id]
            viva = finales[-1] if finales else viva
        llenas = _llenas(viva)
        if llenas <= 0:
            return "nada comprado"
        bid, _ask = self._cotizacion(ticker)
        if bid is None or not self._consola.confirmar_canario(f"Se compraron {llenas} {ticker}: ¿las vendo ya?"):
            return f"COMPRADAS {llenas} {ticker}: VENDER A MANO"
        venta = OrdenNueva(token=self._tokens.siguiente(), lado=Lado.VENTA, ticker=ticker,
                           ruta=str(_primera_ruta(self._rutas_cfg, "cruzar") or "SAGEPRO"), qty=llenas,
                           tipo=TipoOrden.LIMITE, precio=precios.bajo_bid(bid, MARGEN_VENTA_PCT),
                           proposito=Proposito.VENTA_EXCESO)
        comandos.append(protocolo.cmd_neworder(venta))
        respuesta = self._enviar(comandos[-1])
        mensajes += respuesta
        vendida = _orden_por_token(respuesta, venta.token)
        if vendida is not None and vendida.estado is EstadoOrden.EXECUTED:
            return f"vendidas las {llenas} compradas"
        # una venta aún viva NO va a `_vivas`: cancelarla al salir dejaría la cuenta larga
        return f"venta de {llenas} {ticker} enviada ({vendida.estado.value if vendida else 'sin %ORDER'}): COMPRUEBA en DAS"

    # ── ayudas de red ──
    def _enviar(self, linea: str, espera_s: Optional[float] = None) -> list[MensajeDAS]:
        """Manda `linea` y devuelve lo que llegue en `espera_s` (defecto `ESPERA_RESPUESTA_S`; también alimenta el libro)."""
        _sacar(self._cola, 0.0)
        if protocolo.es_mutante(linea):
            self._envio_canario = True               # G2-07: al salir se barre GET ORDERS
        self._cliente.enviar(linea)
        recibidos = _sacar(self._cola, _espera_respuesta() if espera_s is None else espera_s)
        for m in recibidos:
            self._mercado.aplicar(m)
        return recibidos

    def _cancelar(self, id_das: int) -> list[MensajeDAS]:
        mensajes = self._enviar(protocolo.cmd_cancel(id_das))
        self._vivas.pop(id_das, None)
        return mensajes

    def _ticker(self) -> str:
        while True:
            ticker = self._consola.preguntar("Ticker para la prueba (una acción líquida, p. ej. la que uses a diario): ")
            ticker = ticker.upper()
            if ticker and ticker.isascii() and " " not in ticker:
                return ticker
            self._consola.decir("Ticker no válido.")

    def _cotizacion(self, ticker: str) -> tuple[Optional[Decimal], Optional[Decimal]]:
        self._enviar(protocolo.cmd_sb(ticker))
        cot = self._mercado.cotizacion(ticker)
        self._enviar(protocolo.cmd_unsb(ticker), espera_s=0.5)
        bid = cot.bid if cot is not None else None
        ask = cot.ask if cot is not None else None
        self._consola.decir(f"   {ticker}: bid {bid}, ask {ask}")
        return bid, ask

    # ── registro ──
    def _registrar(self, paso: int, comandos: list[str], mensajes: list, conclusion: str) -> None:
        crudas = [self._limpiar(protocolo.redactar(m.cruda)) for m in mensajes if isinstance(m, MensajeDAS)]
        comandos_limpios = [self._limpiar(protocolo.redactar(c)) for c in comandos]
        conclusion = self._limpiar(conclusion)
        self._diario.anotar("comprobacion_das", paso=paso, comando=comandos_limpios, respuesta_cruda=crudas,
                            conclusion=conclusion)
        texto = [f"[paso {paso}] {conclusion}"] + [f"    > {c}" for c in comandos_limpios] + \
                [f"    < {c}" for c in crudas]
        try:
            self._informe.parent.mkdir(parents=True, exist_ok=True)
            with open(self._informe, "a", encoding="utf-8", newline="\n") as fichero:
                fichero.write("\n".join(texto) + "\n")
        except OSError as exc:   # frontera de fichero: queda en el diario y en la consola
            self._consola.decir(f"   (no se pudo escribir el informe: {type(exc).__name__})")
        self._consola.decir(f"   → {conclusion}")


# ── funciones sueltas ──────────────────────────────────────────────────
def _para_consola(texto: str) -> str:
    """El texto con lo que la consola no sabe escribir sustituido («?»): la de Windows es cp1252 y no tiene «→»."""
    codificacion = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return texto.encode(codificacion, errors="replace").decode(codificacion, errors="replace")
    except LookupError:   # codificación desconocida: ASCII seguro
        return texto.encode("ascii", errors="replace").decode("ascii")


def _sacar(cola: "queue.Queue[Any]", espera_s: float) -> list[MensajeDAS]:
    """Los mensajes de DAS que lleguen a `cola` durante `espera_s` (los estados de conexión se descartan)."""
    fin = time.monotonic() + max(espera_s, 0.0)
    salida: list[MensajeDAS] = []
    while True:
        restante = fin - time.monotonic()
        try:
            item = cola.get(timeout=restante) if restante > 0 else cola.get_nowait()
        except queue.Empty:
            return salida
        if isinstance(item, MensajeDAS):
            salida.append(item)


def _espera_respuesta() -> float:
    """`ESPERA_RESPUESTA_S` leído en la llamada (los tests lo acortan)."""
    return float(ESPERA_RESPUESTA_S)


def _es_token_canario(token: Optional[int], hoy: Any) -> bool:
    """G2-07: token del esquema del bot (Origen.EJECUTOR), de HOY y con seq ≥ `SEQ_COMPROBACION_DESDE`."""
    if token is None:
        return False
    partes = mod_tokens.descomponer(token)
    if partes is None:
        return False
    origen, dia, seq = partes
    return origen is Origen.EJECUTOR and dia == hoy.timetuple().tm_yday and seq >= SEQ_COMPROBACION_DESDE


def _llenas(m: MsgOrden) -> int:
    """Acciones llenas de una orden según su %ORDER: qty − abiertas − canceladas (nunca negativo)."""
    return max(int(m.qty) - int(m.lvqty) - int(m.cxlqty), 0)


def _primera_ruta(rutas: Any, clave: str) -> Optional[str]:
    """La primera ruta que nombra `rutas[clave]` (texto o bloque anidado), o None."""
    valores = _valores_ruta(rutas.get(clave)) if isinstance(rutas, dict) else []
    return valores[0] if valores else None


def _conclusion_share(despues: Optional[MsgOrden], mensajes: list) -> str:
    """A-02 / D2a-08: lectura del %ORDER tras `REPLACE id 2` sobre una orden de 2 con 1 llena."""
    if despues is None:
        return f"sin %ORDER tras el REPLACE: {_rechazo(mensajes, None)} (share sin medir)"
    llenas = _llenas(despues)
    if despues.lvqty == SHARE_REPLACE_PARCIAL and despues.qty == llenas + SHARE_REPLACE_PARCIAL:
        return (f"tras REPLACE {SHARE_REPLACE_PARCIAL}: qty {despues.qty}, lvqty {despues.lvqty} → el share es la "
                f"cantidad ABIERTA → propuesta stops.replace_share_es_abierta = true (A-02)")
    if despues.qty == SHARE_REPLACE_PARCIAL and despues.lvqty == SHARE_REPLACE_PARCIAL - llenas:
        return (f"tras REPLACE {SHARE_REPLACE_PARCIAL}: qty {despues.qty}, lvqty {despues.lvqty} → el share es la "
                f"cantidad TOTAL → propuesta stops.replace_share_es_abierta = false (A-02)")
    return (f"tras REPLACE {SHARE_REPLACE_PARCIAL}: qty {despues.qty}, lvqty {despues.lvqty}, cxlqty "
            f"{despues.cxlqty}: lectura AMBIGUA, revisar a mano (A-02)")


def _orden_por_token(mensajes: list, token: int) -> Optional[MsgOrden]:
    for m in reversed(mensajes):
        if isinstance(m, MsgOrden) and m.token == token:
            return m
    return None


def _rechazo(mensajes: list, token: Optional[int]) -> str:
    """El texto literal de un rechazo (`%OrderAct Send_Rej` o `%ORDER Rejected`), o lo que se sepa."""
    for m in mensajes:
        if isinstance(m, MsgOrderAct) and m.accion in ("Send_Rej", "CancelRej", "ReplaceRej") \
                and (token is None or m.token in (None, token)):
            return f"RECHAZADA ({m.accion}): «{m.notas}»"
        if isinstance(m, MsgConexion):
            return f"conexión: {m.servidor} {m.evento}"
    return "sin respuesta de DAS"


def _ultimo_bp(mensajes: list) -> Optional[Decimal]:
    bps = [m.bp for m in mensajes if isinstance(m, MsgBP)]
    return bps[-1] if bps else None


def _valores_ruta(rutas: Any) -> list[str]:
    """Todas las rutas que nombra el bloque `rutas` de la config (anidado)."""
    if isinstance(rutas, str):
        return [rutas]
    if isinstance(rutas, dict):
        return [r for v in rutas.values() for r in _valores_ruta(v)]
    return []


def _pasos_de(texto: Optional[str]) -> list[int]:
    if not texto:
        return [p.numero for p in PASOS]
    numeros = []
    for trozo in texto.split(","):
        trozo = trozo.strip()
        if not trozo.isdigit() or int(trozo) not in {p.numero for p in PASOS}:
            raise ValueError(f"paso desconocido: {trozo!r} (1-{len(PASOS)})")
        numeros.append(int(trozo))
    return numeros


def _bot_encendido(dir_bot: Path) -> list[str]:
    """Procesos del bot cuyo cerrojo está tomado (el bot tiene que estar APAGADO)."""
    encendidos = []
    for proceso in PROCESOS_BOT:
        ruta = dir_bot / "estado" / f"cerrojo_{proceso}.lock"
        if not ruta.exists():
            continue
        cerrojo = CerrojoInstancia(ruta)
        if cerrojo.adquirir():
            cerrojo.soltar()
        else:
            encendidos.append(proceso)
    return encendidos


def main(argv: Optional[Sequence[str]] = None, consola: Optional[Consola] = None) -> int:
    """`python -m app.bot_das.herramientas.comprobar_das [--ayuda] [--pasos 1,2] [--config ruta]` (§3.27).

    `--ayuda` imprime los pasos y sale (0) sin leer el entorno ni abrir red.
    Códigos: 0 hecho, 1 DAS no conecta, 3 bot encendido, 5 entorno
    incompleto o pasos mal escritos.
    """
    consola = consola or Consola()
    parser = argparse.ArgumentParser(prog="python -m app.bot_das.herramientas.comprobar_das", add_help=False,
                                     description="Comprobación de DAS real (primer día)")
    parser.add_argument("--ayuda", "-h", "--help", action="store_true", help="muestra los pasos y sale")
    parser.add_argument("--pasos", default=None, help="lista de pasos separados por comas (defecto: todos)")
    parser.add_argument("--config", type=Path, default=None, help="fichero del cuadro (rutas)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.ayuda:
        consola.decir(texto_ayuda())
        return CODIGO_OK
    try:
        numeros = _pasos_de(args.pasos)
    except ValueError as exc:
        consola.decir(f"comprobar_das: {exc}")
        return CODIGO_ENTORNO
    backend = Path(__file__).resolve().parents[3]
    ruta_env = backend / ".env"
    if ruta_env.is_file():
        try:
            from dotenv import load_dotenv   # perezoso
            load_dotenv(ruta_env, override=False)
        except ImportError:
            pass
    dir_bot = Path(os.environ.get("BOT_DAS_DIR", "").strip() or mod_config.DIR_BOT_POR_DEFECTO)
    encendidos = _bot_encendido(dir_bot)
    if encendidos:
        consola.decir(f"comprobar_das: el bot está encendido ({', '.join(encendidos)}): apágalo antes.")
        return CODIGO_BOT_ENCENDIDO
    reloj = Reloj()
    secretos = mod_avisos.secretos_desde_env()
    filtro = mod_avisos.FiltroSecretos(secretos)
    mod_avisos.instalar_logging("comprobar_das", dir_bot / "logs", secretos, consola=False, reloj=reloj)
    try:
        rutas_cfg: dict = {}
        cuenta = os.environ.get("DAS_CUENTA", "").strip()
        ruta_cfg = args.config or dir_bot / "config" / mod_config.NOMBRE_FICHERO_CONFIG
        if cuenta:
            try:
                rutas_cfg = dict(mod_config.cargar(ruta_cfg, cuenta).rutas)
            except mod_config.ConfigInvalida:
                consola.decir("   (config no válida: se usa la tabla de rutas de §3.27)")
        hay_canario = any(p.canario for p in PASOS if p.numero in numeros) or 7 in numeros
        canario = False
        if hay_canario and os.environ.get(ENV_PERMITIR_ORDENES, "").strip() == "1":
            canario = consola.confirmar_canario("Hay pasos CANARIO (órdenes REALES de 1 acción).")
        cola: "queue.Queue[Any]" = queue.Queue()

        def fabrica(**kw: Any) -> ClienteDAS:
            return ClienteDAS.desde_env(reloj=reloj, **kw)

        try:
            cliente = fabrica(watch=False, solo_lectura=not canario, al_mensaje=cola.put,
                              al_estado=lambda c, m: cola.put(("estado", c, m)))
        except RuntimeError as exc:
            consola.decir(f"comprobar_das: {exc}")
            return CODIGO_ENTORNO
        diario = Diario(dir_bot / "diario", reloj, "supervisor", VERSION, Fase.CANARIO if canario else Fase.SOMBRA,
                        limpiar=filtro.limpiar)
        informe = dir_bot / "informes" / f"comprobar_das_{reloj.ahora().strftime('%Y-%m-%d_%H%M%S')}.txt"
        try:
            if not cliente.conectar():
                consola.decir("comprobar_das: DAS no acepta la conexión (¿abierto y con LOGIN hecho?)")
                return CODIGO_ERROR
            _sacar(cola, ESPERA_RESPUESTA_S)             # el volcado del LOGIN
            comprobador = Comprobador(cliente, cola, reloj, diario, informe, consola, canario, rutas_cfg,
                                      filtro.limpiar, fabrica)
            codigo = comprobador.ejecutar(numeros)
            consola.decir(f"\nInforme: {informe}")
            return codigo
        finally:
            cliente.cerrar()
            diario.cerrar()
    finally:
        mod_avisos.desinstalar_logging()


if __name__ == "__main__":
    sys.exit(main())
