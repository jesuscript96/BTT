"""PREALERTAS: evaluar la vela MIENTRAS SE FORMA, sin esperar a que cierre.

EL PROBLEMA QUE RESUELVE. El backtest entra al `open` de la vela siguiente a la
senyal, o sea en el instante mismo en que la vela de la senyal cierra. Avisar al
cierre deja **margen cero** para poner la orden a mano. La prealerta mira la
vela a falta de diez segundos y avisa antes.

POR QUE FUNCIONA MIRAR LA VELA A MEDIAS, y no adivinando que condicion falta.
Medido sobre tick data (25 ticker-dias, 120 entradas):

    decides en el segundo 50 -> 83,7 % de acierto, captura el 60 %
    decides en el segundo 55 -> 87,5 % de acierto, captura el 70 %

Frente al ~34 % del metodo de «faltan condiciones por cumplirse», que se
descarto. Se usa el **segundo 50** por decision de Jaume: 10 segundos de margen
en vez de 5, y si en el 55 la cosa cambia, el ya esta mirando la pantalla.

EL VOLUMEN DE LA VELA PARCIAL SALE DE `av`, NO DE SUMAR LOS `v`. Sumar los
agregados por segundo deja fuera operaciones (medido: hasta un 4,6 % menos), y
1B decide con dollar volume acumulado. `av` es el volumen acumulado del dia, ya
oficial: restandole el que habia al empezar el minuto sale el del minuto exacto.

LO QUE NO ES UNA PREALERTA. No es una promesa: es una vela a medias, y en los
ultimos diez segundos puede cambiar. Una de cada seis no se confirma. Por eso al
cerrar la vela el aviso se CONFIRMA o se DESCARTA, y el descarte no molesta a
nadie por Telegram — se ve en la pagina y basta.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger("btt.bot_alerts.prealertas")

ET = ZoneInfo("America/New_York")

# A partir de que segundo se mira.
#
# ERA EL 50 HASTA EL 2026-09-04. Se bajo al 44 tras medir dos cosas que no se
# sabian cuando se eligio el 50:
#
# 1. LA SENYAL SE CUMPLE MUCHO ANTES DE LO QUE SE CREIA. Sobre 30 dias y 33
#    entradas de tick data, el segundo en que la vela a medias YA cumple:
#
#        mediana en el segundo 17   ·   9 de 33 ya cumplian en el segundo 5
#
#    O sea que esperabamos al 50 para ver algo que en la mitad de los casos
#    llevaba treinta segundos hecho.
#
# 2. LA LATENCIA SE COME EL MARGEN. El agregado por segundo tarda ~3,7 s en
#    llegar (medido sobre 25.408 mensajes el 2026-09-04: mediana 3,8 s, p99
#    4,1 s, y un pico de 9,8 s). Un aviso del segundo 50 no da 10 s de margen:
#    da 7,8 s hasta que llega la alerta de verdad, y en el pico daba 0,2 s.
#
# QUE SE GANA Y QUE SE PAGA, del mismo estudio (margen = de la prealerta en el
# movil a la alerta confirmada; «en balde» = avisos que no acaban en operacion):
#
#     ventana    margen mediana    de cada N avisos, 1 opera
#     50-59            7,8 s                 2,3
#     44-59           13,8 s                 3,6      <- elegida
#     40-59           17,8 s                 3,8
#     30-59           27,8 s                 4,5
#     20-59           37,8 s                 8,0
#
# La captura NO cambia (32 de 33 en todas): lo unico que se compra es tiempo.
# Jaume, 2026-09-04: «si estoy en la cocina, ir rapido al ordenador y que me de
# el suficiente tiempo de estar preparado; si se cuela alguna que no va a nada
# no pasa nada, pero alguna que otra, no una barbaridad». Por eso el 44 y no el
# 30: el estudio dice que el optimo esta en el 30, pero la cuenta de falsas del
# estudio no cuadro con el primer dia en vivo (predecia ~4, hubo 0), asi que se
# baja un escalon y se mide antes de seguir.
#
# NO SE BAJA MAS sin medirlo en vivo. Y hay tres cosas que ninguna ventana
# arregla: 4 de 33 senyales se cumplen de verdad tarde (segundos 54, 55 y 59) y
# llegaran siempre con menos de 5 s; una de ellas llega despues que su propia
# alerta y la descarta `marcar_cerrada`.
SEGUNDO_DECISION = 44

# Se mira CADA SEGUNDO hasta el 59, no una sola vez.
#
# EL FINAL NO SE TOCA aunque los ultimos segundos den margen negativo. Un aviso
# del segundo 55 llega 2,8 s antes que la alerta, que no sirve para prepararse
# — pero la alternativa no es «un aviso mejor», es NINGUNO: esas senyales no
# existian antes. Y el que llega tarde de verdad ya lo descarta
# `marcar_cerrada`, asi que cerrar antes solo perderia entradas.
#
# Mirar una sola vez pierde las senyales que se cumplen despues del 50, y esas
# llegan al cierre con margen CERO. Medido sobre tick data (12 dias, 14
# entradas reales):
#
#     solo en el 50   -> 12 de 14 (86 %), margen 10 s
#     del 50 al 59    -> 14 de 14 (100 %), margen 9,4 s de media, 6 s el peor
#
# O sea: se capturan TODAS y el margen apenas baja. El maximo sigue siendo 10 s.
#
# Y NO SALE CARO. El riesgo de mirar diez veces era anyadir falsas alarmas: una
# condicion que se cumple en el segundo 52 puede dejar de cumplirse en el 58.
# Medido sobre 14 dias y 2.959 velas de premercado con operaciones:
#
#     solo en el 50   -> 8 prealertas, 5 confirmadas (62 %), 3 falsas
#     del 50 al 59    -> 9 prealertas, 6 confirmadas (67 %), 3 falsas
#
# La prealerta de mas era buena y no aparecio ninguna falsa nueva. Son pocos
# casos para fiarse de los porcentajes sueltos, pero la comparacion vale: son
# los mismos dias y las mismas velas en los dos metodos.
SEGUNDO_LIMITE = 59

# CONDICIONES DE OPERACION QUE NO MUEVEN EL PRECIO DE LA VELA (si el volumen).
# Es la regla con la que Massive monta sus velas oficiales: el odd lot (37,
# menos de 100 acciones) y unas pocas mas (precio medio, cash, next day, fuera
# de secuencia, cierres/aperturas oficiales de centro, contingentes) cuentan
# en el volumen pero no en open/high/low/close. Medido el 21-sep-2026 sobre
# GLND, BTTC y LOBO (700.000 operaciones): sumando todo, el cierre difiere de
# la vela oficial en el 40 % de los minutos; sin odd lots, en el 0-1 %.
CONDICIONES_SIN_PRECIO = {2, 7, 15, 16, 20, 21, 29, 33, 37, 38, 52, 53}

# PRINTS TARDIOS: CADA PRINT VA AL MINUTO EN QUE SE EJECUTO (22-sep-2026,
# decision de Jaume). Cada operacion trae dos relojes: cuando se ejecuto (`pt`)
# y cuando la publico la cinta (`t`). Las de fuera de bolsa (dark pools, sesion
# nocturna) se publican tarde: a las 04:00 NY la cinta suelta lo de la noche
# con horas de retraso (QNME 04:03: 785.000 acciones publicadas, la vela
# oficial lleva 148.000). El print se coloca en la vela del minuto de
# EJECUCION: si ese minuto ya se entrego, se descarta (ni precio ni volumen):
# es lo que hace la vela oficial de Massive (medido: ni la de 04:03 ni ninguna
# anterior llevan esas acciones), y asi los «fogonazos» de hace horas no
# pintan mechas. Los dark pools ejecutados en el minuto EN CURSO y publicados
# unos cientos de ms tarde SI entran, como en la oficial: con la regla anterior
# (descartar todo lo publicado > 20 ms tras ejecutarse, la del lago) la propia
# perdia hasta el 28 % del volumen de la vela en QNME y el cierre en el 7 % de
# las velas.
# El tope de espera al cerrar la vela propia: ver `velas_por_cerrar`.
MARGEN_CIERRE_S = 1.0
# Una vela se cierra en cuanto llega un print del minuto siguiente publicado
# al menos esto despues de acabar el minuto: la cinta va en orden de
# publicacion, asi que lo del minuto anterior ya ha pasado.
MARGEN_SIGUIENTE_MS = 100


@dataclass
class VelaEnCurso:
    """La vela del minuto que se esta formando, montada con los agregados `A`."""
    minuto: int                      # epoch en segundos, al minuto
    open: float
    high: float
    low: float
    close: float
    av_inicio: Optional[float]       # volumen acumulado del dia al empezar
    av_ahora: Optional[float]
    segundos: int = 0
    evaluada: bool = False           # ya se decidio este minuto
    # OPERACIONES SUELTAS (21-sep-2026): lo que han sumado las operaciones
    # del minuto que han llegado por `T.`, y las que han llegado DESPUES del
    # ultimo agregado oficial (`A.`) que actualizo `av_ahora`. Con ellas la
    # vela avanza en milisegundos; el `av` oficial, que llega 3 s tarde, solo
    # sirve de ancla para no quedarnos cortos de volumen.
    v_operaciones: float = 0.0
    v_desde_ultimo_av: float = 0.0
    operaciones: int = 0
    ultimo_ms: int = 0                             # hora SIP de la ultima operacion
    _ops: list = field(default_factory=list)       # (ms, tamanyo) del minuto
    # Si la vela se vio desde el principio del minuto. Un ticker recien
    # admitido empieza a recibir operaciones a mitad de minuto: esa primera
    # vela esta a medias y NO vale para disparar la alerta (espera la oficial).
    completa: bool = True
    cerrada_propia: bool = False                   # ya se entrego como vela propia
    lista: bool = False                            # ya llego un print del minuto siguiente
    con_precio: bool = False                       # alguna operacion movio el precio

    def como_vela_cerrada(self) -> dict:
        """La vela terminada, con el timestamp al INICIO del minuto (como la oficial)."""
        return {
            "timestamp": pd.Timestamp(datetime.fromtimestamp(self.minuto, tz=ET).replace(tzinfo=None)),
            "open": self.open, "high": self.high, "low": self.low, "close": self.close,
            "volume": self.volumen,
        }

    def v_tras(self, ms: int) -> float:
        """Tamanyo sumado de las operaciones con hora >= ms."""
        return float(sum(t for m, t in self._ops if m >= ms))

    def v_hasta(self, ms: int) -> float:
        """Tamanyo sumado de las operaciones con hora < ms."""
        return float(sum(t for m, t in self._ops if m < ms))

    @property
    def volumen(self) -> float:
        """Volumen del minuto.

        Con `av` (acumulado oficial del dia): av_ahora - av_inicio, MAS las
        operaciones llegadas despues de ese `av` (que aun no cuenta). Sin `av`
        (aun no ha llegado ningun agregado del minuto), la suma de operaciones.
        Nunca se devuelve un volumen mas corto que el que ya hemos visto pasar:
        un volumen corto haria que la condicion de dollar volume se cumpliera
        mas tarde de lo que toca.
        """
        # CON OPERACIONES, MANDA SU SUMA (medido en vivo el 21-sep-2026: cuadra
        # con la vela oficial al 0,1 %). Sumarle lo posterior al `av` la inflaba
        # un 1-6 %: el `av` se publica 3 s despues del segundo y YA incluye las
        # operaciones de esos 3 s. El `av` solo manda cuando no hay operaciones
        # (bot sin `T.`), como hasta hoy.
        if self.operaciones > 0:
            return self.v_operaciones
        if self.av_inicio is None or self.av_ahora is None:
            return 0.0
        return max(0.0, self.av_ahora - self.av_inicio)

    def como_vela(self, ts) -> dict:
        return {
            "timestamp": ts, "open": self.open, "high": self.high,
            "low": self.low, "close": self.close, "volume": self.volumen,
        }


class ConstructorParcial:
    """Monta la vela en curso de cada ticker a partir de los agregados `A`.

    Solo para los tickers VIGILADOS: montar la del mercado entero seria tirar
    trabajo, porque la prealerta solo se evalua donde hay estrategia mirando.
    """

    def __init__(self):
        self._curso: dict[str, VelaEnCurso] = {}
        # Ultimo minuto CERRADO de cada ticker, en epoch. Sin esto se emiten
        # prealertas de velas muertas — ver `marcar_cerrada`.
        self._cerradas: dict[str, int] = {}
        # La ultima vela TERMINADA de cada ticker montada con operaciones, para
        # compararla con la oficial (21-sep-2026).
        self._terminadas: dict[str, VelaEnCurso] = {}
        # Operaciones descartadas por tardias (ejecutadas en un minuto que ya
        # se entrego), para el log.
        self.tardias = 0
        self.v_tardias = 0.0

    def olvidar(self, ticker: str) -> None:
        self._curso.pop(ticker, None)
        self._cerradas.pop(ticker, None)
        self._terminadas.pop(ticker, None)

    def reiniciar(self) -> None:
        self._curso.clear()
        self._cerradas.clear()
        self._terminadas.clear()

    def marcar_cerrada(self, ticker: str, ts) -> None:
        """Avisa de que la vela de ese minuto YA CERRO. Llamar al recibir `AM`.

        POR QUE HACE FALTA, y no es una optimizacion. Los agregados por segundo
        tardan ~3 s en llegar, asi que el tick del segundo 59 se procesa DESPUES
        de que su propia vela haya cerrado. Sin esta marca pasaba esto:

            04:52:59  tick del segundo 59      (viaja 3 s)
            04:53:00  llega la vela AM 04:52 -> se confirman o descartan las
                      prealertas del minuto 04:52: no hay ninguna todavia
            04:53:02  se procesa el tick      -> nace una prealerta del minuto
                      04:52, que ya nadie va a confirmar ni descartar

        La prealerta se quedaba en ambar PARA SIEMPRE (visto en vivo con MIMI el
        2026-09-03), y ademas no daba ningun margen: su vela ya habia cerrado.
        """
        try:
            t = pd.Timestamp(ts)
            if t.tzinfo is None:
                t = t.tz_localize(ET)
            minuto = int(t.timestamp()) // 60 * 60
        except (ValueError, TypeError):
            return
        if minuto > self._cerradas.get(ticker, -1):
            self._cerradas[ticker] = minuto

    def aplicar_operacion(self, ev: dict) -> Optional[tuple[str, VelaEnCurso, datetime, int]]:
        """Una operacion suelta (`T.`): {sym, p, s, t}. Misma salida que `aplicar`.

        POR QUE (21-sep-2026). El agregado por segundo llega ~3 s despues de
        cerrarse el segundo; una prealerta «del segundo 44» veia en realidad el
        estado del 41. Las operaciones llegan a decenas de milisegundos: con
        ellas la vela en curso se mueve al instante y la prealerta mira lo que
        hay AHORA. El `av` oficial, cuando llega, sigue siendo el ancla del
        volumen (ver `VelaEnCurso.volumen`).
        """
        tk = ev.get("sym")
        ts, precio, tam = ev.get("t"), ev.get("p"), ev.get("s")
        if not tk or ts is None or precio is None:
            return None
        ms = int(ts)                                   # publicacion (SIP)
        pt = ev.get("pt")
        ms_ejec = int(pt) if pt is not None else ms    # ejecucion
        precio = float(precio)
        tam = float(tam or 0.0)
        mueve_precio = not (set(ev.get("c") or ()) & CONDICIONES_SIN_PRECIO)
        t = datetime.fromtimestamp(ms_ejec / 1000, tz=ET)
        minuto = int(t.timestamp()) // 60 * 60
        if minuto < (ms // 1000) // 60 * 60 - 60:
            # Ejecutado antes del minuto anterior al de publicacion: un dark
            # pool de hace horas. No tiene vela donde caer (ni abre una).
            self.tardias += 1
            self.v_tardias += tam
            return None

        v = self._curso.get(tk)
        if v is not None and v.minuto > minuto:
            # Print de un minuto anterior al en curso. Si es el recien
            # terminado y aun no se entrego, entra en el (llego en la cola);
            # si ya se entrego o es mas viejo (dark pool de hace horas), fuera.
            ant = self._terminadas.get(tk)
            if ant is not None and ant.minuto == minuto and not ant.cerrada_propia:
                self._sumar(ant, ms, ms_ejec, precio, tam, mueve_precio)
            else:
                self.tardias += 1
                self.v_tardias += tam
            return None
        if v is not None and v.minuto == minuto and v.cerrada_propia:
            # Vela ya entregada por tope de espera: el print llega tarde.
            self.tardias += 1
            self.v_tardias += tam
            return None
        if v is None or v.minuto != minuto:
            if v is not None and v.minuto < minuto:
                # La vela anterior queda terminada: se guarda para compararla
                # con la oficial cuando llegue (ver `terminada`).
                self._terminadas[tk] = v
            anterior = v
            # Vista desde el principio del minuto si veniamos siguiendo el
            # ticker (habia vela del minuto anterior) o si esta es la primera
            # operacion del minuto y llega en sus primeros 2 s.
            # (Por hora de PUBLICACION: un dark pool ejecutado en el segundo 1
            # y publicado en el 24 no significa que vieramos el minuto entero.)
            seg_pub = datetime.fromtimestamp(ms / 1000, tz=ET).second
            completa = (anterior is not None and anterior.minuto == minuto - 60) or (seg_pub < 2 and t.second < 2)
            v = VelaEnCurso(
                minuto=minuto, open=precio, high=precio, low=precio, close=precio,
                # El acumulado al empezar el minuto es el que dejo la vela
                # anterior, si la conocemos; si no, no se inventa.
                av_inicio=(anterior.av_ahora if anterior is not None and anterior.minuto == minuto - 60 else None),
                av_ahora=None, segundos=0, completa=completa, con_precio=mueve_precio,
            )
            self._curso[tk] = v
            v.ultimo_ms = ms_ejec
            v.operaciones = 1
            v.v_operaciones = tam
            v._ops.append((ms, tam))
        else:
            self._sumar(v, ms, ms_ejec, precio, tam, mueve_precio)
        # Un print del minuto en curso publicado ya pasado el margen deja la
        # vela anterior lista para entregar (ver `velas_por_cerrar`).
        ant = self._terminadas.get(tk)
        if ant is not None and not ant.lista and not ant.cerrada_propia and ms >= minuto * 1000 + MARGEN_SIGUIENTE_MS:
            ant.lista = True

        if v.evaluada or not (SEGUNDO_DECISION <= t.second <= SEGUNDO_LIMITE):
            return None
        if minuto <= self._cerradas.get(tk, -1):
            return None
        return tk, v, datetime.fromtimestamp(minuto, tz=ET), t.second

    @staticmethod
    def _sumar(v: VelaEnCurso, ms: int, ms_ejec: int, precio: float, tam: float, mueve_precio: bool) -> None:
        """Anyade un print a una vela ya abierta. El cierre es el del ultimo
        print EJECUTADO, no el ultimo publicado."""
        if mueve_precio:
            if not v.con_precio:
                # Hasta ahora solo habia odd lots: el precio arranca aqui.
                v.open = v.high = v.low = v.close = precio
                v.con_precio = True
            else:
                v.high = max(v.high, precio)
                v.low = min(v.low, precio)
                if ms_ejec >= v.ultimo_ms:
                    v.close = precio
        v.ultimo_ms = max(v.ultimo_ms, ms_ejec)
        v.operaciones += 1
        v.v_operaciones += tam
        v._ops.append((ms, tam))
        if v.av_ahora is not None:
            v.v_desde_ultimo_av += tam

    def velas_por_cerrar(self, ahora_epoch: float, margen_s: float = MARGEN_CIERRE_S) -> list:
        """Velas propias listas para entregar, una sola vez: [(ticker, VelaEnCurso)].

        Una vela esta lista cuando (a) ha llegado un print del minuto siguiente
        (la cinta va en orden de publicacion: lo del minuto ya ha pasado) o
        (b) el minuto acabo hace >= margen_s, para los tickers que se callan.
        22-sep-2026: con un margen fijo de 0,8 s y la cinta llegando a +0,9 s,
        se quedaban fuera los prints del ultimo tramo del minuto (TOPS, FBGL:
        cierre distinto de la oficial); Jaume no quiere esperar mas de 1 s.
        """
        out = []
        for tk, v in list(self._curso.items()) + list(self._terminadas.items()):
            if v.cerrada_propia or v.operaciones == 0:
                continue
            if v.lista or ahora_epoch >= v.minuto + 60 + margen_s:
                v.cerrada_propia = True
                out.append((tk, v))
        return out

    def terminada(self, ticker: str, minuto_epoch: int) -> Optional[VelaEnCurso]:
        """La vela que montamos con operaciones para ese minuto, si la hay.
        Sirve para compararla con la oficial (`AM`) al llegar esta."""
        v = self._terminadas.get(ticker)
        if v is not None and v.minuto == minuto_epoch:
            return v
        v = self._curso.get(ticker)
        if v is not None and v.minuto == minuto_epoch:
            return v
        return None

    def aplicar(self, ev: dict) -> Optional[tuple[str, VelaEnCurso, datetime, int]]:
        """Un mensaje `A`. Devuelve el ticker y su vela si TOCA MIRAR.

        Toca mirar en CADA segundo del 50 al 59, no solo en el 50: una senyal
        que se cumple en el 55 llegaria si no al cierre, sin margen. Medido: de
        86 % a 100 % de captura, con el margen bajando solo de 10 a 9,4 s.

        `evaluada` se marca cuando el aviso YA SE HA DADO — lo hace quien llama,
        no esta funcion, porque solo el sabe si de la vela salio senyal. Asi se
        sigue mirando cada segundo hasta que haya algo que avisar, y una vez
        avisado ese minuto se calla.
        """
        tk = ev.get("sym")
        ts = ev.get("s") or ev.get("t")
        o, h, l, c = ev.get("o"), ev.get("h"), ev.get("l"), ev.get("c")
        if not tk or ts is None or None in (o, h, l, c):
            return None

        t = datetime.fromtimestamp(int(ts) / 1000, tz=ET)
        minuto = int(t.timestamp()) // 60 * 60
        av = ev.get("av")
        av = float(av) if av is not None else None

        v = self._curso.get(tk)
        if v is not None and v.minuto < minuto:
            self._terminadas[tk] = v
        if v is not None and v.minuto > minuto:
            # Un agregado de un minuto ya pasado (llega 3 s tarde): las
            # operaciones ya abrieron el minuto siguiente. No se retrocede.
            return None
        if v is None or v.minuto != minuto:
            # Minuto nuevo: la vela empieza aqui. `av_inicio` es el acumulado
            # ANTES de este segundo, para que el volumen del minuto salga bien.
            v = VelaEnCurso(
                minuto=minuto, open=float(o), high=float(h), low=float(l),
                close=float(c),
                av_inicio=(av - float(ev.get("v") or 0.0)) if av is not None else None,
                av_ahora=av, segundos=1,
            )
            self._curso[tk] = v
        else:
            v.high = max(v.high, float(h))
            v.low = min(v.low, float(l))
            # El cierre lo manda quien llegue MAS TARDE en tiempo de mercado: el
            # agregado es de hace 3 s y las operaciones ya han podido moverlo.
            if v.operaciones == 0 or int(ts) >= v.ultimo_ms:
                v.close = float(c)
            v.segundos += 1
            if av is not None:
                if v.av_inicio is None:
                    # El minuto lo abrieron las operaciones (sin `av`). El
                    # acumulado al empezar es este `av` menos lo que el minuto
                    # lleva hasta el fin de este segundo, que ya conocemos.
                    v.av_inicio = av - v.v_hasta(int(ts) + 1000)
                v.av_ahora = av
                # Las operaciones anteriores al fin de este segundo ya estan
                # dentro del `av`; las posteriores, no.
                v.v_desde_ultimo_av = v.v_tras(int(ts) + 1000)

        # `evaluada` la pone el que llama, cuando de verdad ha avisado. Aqui solo
        # se comprueba la ventana: del segundo 50 al 59.
        if v.evaluada or not (SEGUNDO_DECISION <= t.second <= SEGUNDO_LIMITE):
            return None
        # LLEGO TARDE. Su vela ya cerro, asi que esto no es una prealerta: es un
        # aviso sin margen que ademas nadie confirmaria ni descartaria despues.
        # Mejor callarse — la alerta de verdad sale por su lado.
        if minuto <= self._cerradas.get(tk, -1):
            logger.debug("%s: tick del segundo %d descartado, la vela %s ya cerro",
                         tk, t.second, minuto)
            return None
        # El instante que se le pone a la vela es el INICIO del minuto, igual
        # que hace el proveedor con las velas cerradas: asi la prealerta y su
        # confirmacion comparten identidad y la fila se transforma en vez de
        # duplicarse.
        # Se devuelve tambien el segundo: sirve para el log y para saber cuanto
        # margen real ha quedado.
        return tk, v, datetime.fromtimestamp(minuto, tz=ET), t.second
