"""El motor de ALERTAS en su propio proceso (23-sep-2026).

QUE HACE. Lleva su copia del motor (`RunnerAlertas`) y solo recibe VELAS DE
MINUTO ya cerradas de los tickers vigilados. Nada de prints: la vela oficial de
Massive llega a 1,2-2 s del cierre del minuto y es lo unico que necesita para
decidir una entrada, una piramide o una salida. Los prints van al proceso de
prealertas, que es el que mira la vela a medias.

POR QUE ESTA AQUI Y NO EN EL BOT. Dos cosas que costaban tiempo en el hilo que
lee el socket y ahora salen de el:

  - `nueva_vela`: el motor recalcula el dia entero del ticker en cada vela,
    porque los niveles de estructura son acumulados. Medido: 0,01-0,08 s por
    vela, con picos; por si solo no ahogaba, pero suma.
  - `hidratar`: repasar el dia entero de un ticker que acaba de entrar. La
    PRIMERA del dia cuesta 1 s (compila el motor) y se comia la lectura del
    socket justo al arrancar. Es el «mordisco» que veiamos cada manyana.

LO QUE NO SE VA CON EL. El aviso por Telegram y el guardado se quedan en el
bot: este proceso devuelve los eventos y no habla con nadie mas. Asi hay UN
solo sitio que publica y no pueden salir dos mensajes del mismo aviso.

EL CIERRE DE VELA RESUELVE LAS PREALERTAS. Cuando una vela cierra, las
prealertas vivas de ese minuto quedan confirmadas o descartadas. Como viven en
OTRO proceso, este devuelve al bot los eventos junto con el ticker y el minuto,
y el bot se lo reenvia al de prealertas. Un salto mas, pero no corre prisa:
resolver una prealerta no es una orden que meter, es pintar una fila.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from app.services.bot_alerts_proceso_base import AVISO, ProcesoHijo, bucle_hijo

logger = logging.getLogger(__name__)

# ── Mensajes (el protocolo, a proposito tonto: un dict con "t") ────────────
ESTRATEGIAS = "estrategias"     # bot -> hijo: la lista vigilada
HIDRATAR = "hidratar"           # bot -> hijo: el pasado del dia de un ticker
VELA = "vela"                   # bot -> hijo: una vela de minuto cerrada
SUSTITUIR = "sustituir"         # bot -> hijo: cambia una vela ya aplicada
RECUPERAR = "recuperar"         # bot -> hijo: velas del hueco tras un corte
SOLTAR = "soltar"               # bot -> hijo: deja de seguir un ticker
DIA_NUEVO = "dia_nuevo"         # bot -> hijo: reinicia
LOCATES = "locates"             # bot -> hijo: pregunta puntual (Telegram)

EVENTOS = "eventos"             # hijo -> bot: avisos de una vela
HIDRATADO = "hidratado"         # hijo -> bot: resultado de hidratar
RESPUESTA_LOCATES = "resp_locates"


def _hijo(tuberia) -> None:
    """El proceso. Todo el trabajo es por mensaje: no hay tarea periodica."""
    sys.path.insert(0, r"D:\Backtester\backend")
    import pandas as pd
    from app.services.bot_alerts_runner import RunnerAlertas

    runner = RunnerAlertas([])

    def _eventos(evs) -> list:
        # Los `Evento` son dataclasses de campos simples: viajan por la
        # tuberia tal cual. `momento` es un Timestamp y tambien se pickla.
        return list(evs or [])

    def manejador(msg: dict) -> None:
        t = msg.get("t")

        if t == ESTRATEGIAS:
            cambios = runner.actualizar(msg["datos"])
            hay = {k: v for k, v in (cambios or {}).items() if v}
            if hay:
                tuberia.send({"t": AVISO, "texto": f"estrategias al dia: {hay}"})

        elif t == HIDRATAR:
            # `df` llega como lista de filas para no depender de la version de
            # pandas a los dos lados de la tuberia.
            df = pd.DataFrame(msg["velas"])
            evs = _eventos(runner.hidratar(msg["ticker"], df, msg.get("stats")))
            tuberia.send({"t": HIDRATADO, "ticker": msg["ticker"],
                          "velas": len(df), "eventos": evs,
                          "prev_close": (msg.get("stats") or {}).get("prev_close")})

        elif t == VELA:
            tk, vela = msg["ticker"], msg["vela"]
            evs = _eventos(runner.nueva_vela(tk, vela))
            # El minuto viaja SIEMPRE, haya eventos o no: el proceso de
            # prealertas lo necesita para cerrar las suyas de ese minuto.
            tuberia.send({"t": EVENTOS, "ticker": tk,
                          "minuto": str(vela.get("timestamp"))[:16],
                          "timestamp": vela.get("timestamp"), "eventos": evs})

        elif t == SUSTITUIR:
            runner.sustituir_vela(msg["ticker"], msg["vela"])

        elif t == RECUPERAR:
            # Tras un corte: el bot manda el dia entero por REST y aqui se
            # procesan SOLO los minutos que falten, en orden y por el camino
            # normal, para que una senal del hueco salga aunque sea tarde.
            tk = msg["ticker"]
            ultima = runner.ultima_vela_ts(tk)
            puestas = 0
            for fila in msg["velas"]:
                ts = pd.Timestamp(fila.get("timestamp"))
                if ultima is not None and ts <= pd.Timestamp(ultima):
                    continue
                evs = _eventos(runner.nueva_vela(tk, fila))
                puestas += 1
                tuberia.send({"t": EVENTOS, "ticker": tk,
                              "minuto": str(fila.get("timestamp"))[:16],
                              "timestamp": fila.get("timestamp"),
                              "eventos": evs, "recuperada": True})
            if puestas:
                tuberia.send({"t": AVISO, "texto": f"{tk}: {puestas} vela(s) recuperadas del hueco"})

        elif t == SOLTAR:
            runner.soltar(msg["ticker"])

        elif t == DIA_NUEVO:
            runner.reiniciar()
            tuberia.send({"t": AVISO, "texto": "dia nuevo: motor a cero"})

        elif t == LOCATES:
            try:
                datos = runner.estimacion_locates(msg["ticker"], msg["precio"])
            except Exception:                   # noqa: BLE001
                datos = []
            tuberia.send({"t": RESPUESTA_LOCATES, "id": msg.get("id"), "datos": datos})

    bucle_hijo(tuberia, manejador, nombre="alerta")


class AlertaEnProceso(ProcesoHijo):
    """El motor de alertas, visto desde el bot.

    `al_eventos(ticker, minuto, timestamp, eventos, recuperada)` se llama con
    cada vela procesada, tenga avisos o no. Corre en el hilo lector del padre,
    asi que tiene que ser barato: encolar y volver.
    """

    def __init__(self, al_eventos=None, al_hidratado=None):
        super().__init__(_hijo, "alerta", al_recibir=self._recibir)
        self.al_eventos = al_eventos
        self.al_hidratado = al_hidratado
        self._locates: dict = {}
        # Lo que hay que devolverle si se muere: las estrategias y el pasado de
        # cada ticker vigilado. Se guarda aqui porque el bot ya no lleva motor.
        self._estrategias: list = []
        self._pasado: dict = {}
        self.al_resucitar = self._devolver_estado

    # ── lo que el bot le manda ────────────────────────────────────────────
    def configurar(self, estrategias: list) -> None:
        self._estrategias = list(estrategias)
        self.enviar({"t": ESTRATEGIAS, "datos": self._estrategias})

    def hidratar(self, ticker: str, velas: list, stats: Optional[dict] = None) -> None:
        # Se recuerda para poder resucitarlo: sin esto, un hijo que muere a
        # media manyana perderia el dia entero de cada ticker y dejaria de
        # avisar sin decir nada.
        self._pasado[ticker] = (velas, stats)
        self.enviar({"t": HIDRATAR, "ticker": ticker, "velas": velas, "stats": stats})

    def vela(self, ticker: str, vela: dict) -> None:
        self.enviar({"t": VELA, "ticker": ticker, "vela": vela})

    def sustituir(self, ticker: str, vela: dict) -> None:
        self.enviar({"t": SUSTITUIR, "ticker": ticker, "vela": vela})

    def recuperar(self, ticker: str, velas: list) -> None:
        self.enviar({"t": RECUPERAR, "ticker": ticker, "velas": velas})

    def soltar(self, ticker: str) -> None:
        self._pasado.pop(ticker, None)
        self.enviar({"t": SOLTAR, "ticker": ticker})

    def limpiar_dia(self) -> None:
        self._pasado.clear()
        self.enviar({"t": DIA_NUEVO})

    def pedir_locates(self, ident: str, ticker: str, precio: float) -> None:
        self.enviar({"t": LOCATES, "id": ident, "ticker": ticker, "precio": precio})

    def locates(self, ident: str) -> Optional[list]:
        """Lo ultimo que contesto para esa pregunta, o None si aun no ha
        llegado. El que pregunta (Telegram) puede esperar unas decimas."""
        return self._locates.pop(ident, None)

    # ── tripas ────────────────────────────────────────────────────────────
    def _recibir(self, msg: dict) -> None:
        t = msg.get("t")
        if t == EVENTOS and self.al_eventos is not None:
            self.al_eventos(msg["ticker"], msg["minuto"], msg.get("timestamp"),
                            msg.get("eventos") or [], bool(msg.get("recuperada")))
        elif t == HIDRATADO and self.al_hidratado is not None:
            self.al_hidratado(msg["ticker"], msg.get("velas", 0),
                              msg.get("eventos") or [], msg.get("prev_close"))
        elif t == RESPUESTA_LOCATES:
            self._locates[msg.get("id")] = msg.get("datos") or []

    def _devolver_estado(self, _hijo) -> None:
        """Tras resucitarlo: estrategias primero y luego el pasado de cada
        ticker, en el mismo orden en que entraron. Los avisos que devuelva la
        rehidratacion NO se publican otra vez — el bot los marca como
        repetidos por el minuto, igual que hace con los del arranque."""
        if self._estrategias:
            self.enviar({"t": ESTRATEGIAS, "datos": self._estrategias})
        for ticker, (velas, stats) in list(self._pasado.items()):
            self.enviar({"t": HIDRATAR, "ticker": ticker, "velas": velas, "stats": stats})
