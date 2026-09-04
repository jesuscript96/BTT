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

    @property
    def volumen(self) -> float:
        """Volumen del minuto, del acumulado del dia.

        Si por lo que sea no viene `av`, se devuelve 0 en vez de una suma
        aproximada: un volumen corto haria que la condicion de dollar volume se
        cumpliera mas tarde de lo que toca, y eso es peor que no prealertar.
        """
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

    def olvidar(self, ticker: str) -> None:
        self._curso.pop(ticker, None)
        self._cerradas.pop(ticker, None)

    def reiniciar(self) -> None:
        self._curso.clear()
        self._cerradas.clear()

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
            v.close = float(c)
            v.segundos += 1
            if av is not None:
                v.av_ahora = av

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
