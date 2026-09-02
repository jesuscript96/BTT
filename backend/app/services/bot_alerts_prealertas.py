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

logger = logging.getLogger("btt.bot_alerts.prealertas")

ET = ZoneInfo("America/New_York")

# A partir de que segundo se mira. NO antes: la fiabilidad cae, y Jaume no
# necesita mas de diez segundos de margen.
SEGUNDO_DECISION = 50

# Se mira CADA SEGUNDO del 50 al 59, no una sola vez.
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

    def olvidar(self, ticker: str) -> None:
        self._curso.pop(ticker, None)

    def reiniciar(self) -> None:
        self._curso.clear()

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
        # El instante que se le pone a la vela es el INICIO del minuto, igual
        # que hace el proveedor con las velas cerradas: asi la prealerta y su
        # confirmacion comparten identidad y la fila se transforma en vez de
        # duplicarse.
        # Se devuelve tambien el segundo: sirve para el log y para saber cuanto
        # margen real ha quedado.
        return tk, v, datetime.fromtimestamp(minuto, tz=ET), t.second
