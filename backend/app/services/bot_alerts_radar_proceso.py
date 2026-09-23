"""El radar en un PROCESO APARTE (22-sep-2026, decision de Jaume).

POR QUE. El radar recorre los 5.700 tickers del mercado y calcula las metricas
de cada uno. Eso son segundos de CPU: medido el 22-sep, barridos de 3,5 a 5,8 s.
Corria en un HILO del bot, y en Python los hilos de un proceso se turnan un
unico interprete: mientras el radar calculaba, el hilo que lee el socket estaba
parado. Medido ese mismo dia: un barrido de 5,81 s dejo el bucle 11,09 s sin
leer, y las velas de minuto de esos minutos llegaron a 9-11 s en vez de 2. El
8 % de las velas del dia pasaron de 5 s por esto.

Un PROCESO aparte tiene su propio interprete y corre en otro nucleo (la maquina
tiene 20), asi que no se estorban. Ademas, si el radar revienta o se atasca, el
bot sigue avisando con los tickers que ya vigila: en ejecucion automatica eso
deja de ser un detalle.

NO HAY SEGUNDA CONEXION A MASSIVE. El bot mantiene la unica conexion y le pasa
al hijo, por una tuberia local, las velas del mercado que YA recibe. Massive
sigue viendo un solo cliente (el limite de conexiones de la cuenta es lo que
provoca los cortes 1008).

LAS DOS TRAMPAS, medidas antes de escribir esto (banco de pruebas del 22-sep):

  1. Mandar las 5.700 velas UNA A UNA cuesta 84 ms al bot; mandarlas en UN solo
     envio, 3,4 ms. Se manda en lote, siempre.
  2. El lote pesa mas que el buffer de la tuberia, asi que `send` se BLOQUEA
     hasta que el otro lado lea. Si el hijo estuviera barriendo, el bot se
     quedaria esperando: exactamente el problema que veniamos a resolver. Por
     eso el hijo tiene un hilo lector que solo vacia la tuberia y aplica las
     velas (9 ms por rafaga), y el padre envia desde otro hilo con una cola
     acotada. Ninguno de los dos bloquea su camino critico.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Cada cuanto barre el hijo. Ya no hay motivo para espaciarlo: barrer no le
# quita tiempo a nadie.
CADA_SEG = 5.0

# Cuantos lotes de velas pueden estar esperando a salir hacia el hijo. Si se
# llena (hijo colgado), se tiran los mas viejos y se avisa: mas vale un radar
# con un minuto de retraso que un bot que se para a esperarlo.
COLA_MAX = 8


# ── Mensajes (el protocolo, a proposito tonto: un dict con "t") ────────────
VELAS = "velas"
PREV_CLOSE = "prev_close"
MAXIMOS = "maximos"
ESTRATEGIAS = "estrategias"
DIA_NUEVO = "dia_nuevo"
ESTADO = "estado"           # volcado completo, para resucitar al hijo
FIN = "fin"
CANDIDATOS = "candidatos"
AVISO = "aviso"


def _hijo(tuberia, cada_seg: float) -> None:
    """El proceso del radar. Dos hilos: uno lee la tuberia (barato) y otro
    barre (caro). Asi el padre nunca se queda esperando a que leamos."""
    import sys
    sys.path.insert(0, r"D:\Backtester\backend")
    from app.services.bot_alerts_mercado import MercadoEnVivo
    from app.services.bot_alerts_radar import RadarPorEstrategia

    mercado = MercadoEnVivo()
    mercado.reiniciar_si_cambia_el_dia()
    radar = RadarPorEstrategia(mercado)
    cerrojo = threading.Lock()
    parar = threading.Event()

    def leer():
        while not parar.is_set():
            try:
                if not tuberia.poll(0.5):
                    continue
                msg = tuberia.recv()
            except (EOFError, OSError):
                parar.set()
                return
            t = msg.get("t")
            try:
                if t == VELAS:
                    for ev in msg["lote"]:
                        mercado.aplicar(ev)
                elif t == PREV_CLOSE:
                    n = mercado.sembrar_prev_close(msg["datos"])
                    tuberia.send({"t": AVISO, "texto": f"{n:,} cierres de ayer cargados"})
                elif t == MAXIMOS:
                    mercado.sembrar_maximos(msg["ticker"], msg["velas"])
                elif t == ESTADO:
                    mercado.cargar(msg["datos"])
                    tuberia.send({"t": AVISO, "texto": f"estado del mercado restaurado ({len(msg['datos']):,} tickers)"})
                elif t == ESTRATEGIAS:
                    with cerrojo:
                        avisos = radar.configurar(msg["datos"])
                    for a in avisos:
                        tuberia.send({"t": AVISO, "texto": a})
                elif t == DIA_NUEVO:
                    with cerrojo:
                        mercado.reiniciar_si_cambia_el_dia()
                        radar.limpiar_dia()
                elif t == FIN:
                    parar.set()
                    return
            except Exception as exc:        # noqa: BLE001
                try:
                    tuberia.send({"t": AVISO, "texto": f"fallo con {t}: {exc}"})
                except Exception:           # noqa: BLE001
                    parar.set()
                    return

    hilo = threading.Thread(target=leer, name="radar-lector", daemon=True)
    hilo.start()

    while not parar.is_set():
        t0 = time.perf_counter()
        try:
            with cerrojo:
                cand = radar.escanear()
            coste = time.perf_counter() - t0
            tuberia.send({"t": CANDIDATOS, "datos": cand, "coste": coste,
                          "tickers": mercado.tickers_con_datos})
        except (EOFError, OSError):
            return
        except Exception as exc:            # noqa: BLE001
            try:
                tuberia.send({"t": AVISO, "texto": f"fallo al barrer: {exc}"})
            except Exception:               # noqa: BLE001
                return
        parar.wait(max(0.2, cada_seg - (time.perf_counter() - t0)))


class RadarEnProceso:
    """El radar, visto desde el bot. Misma idea que `RadarPorEstrategia`, pero
    lo que pide se manda al hijo y lo que devuelve es el ULTIMO barrido.

    Nada de lo que hace bloquea: `enviar_velas` deja el lote en una cola y un
    hilo lo saca; `candidatos()` devuelve lo ultimo que llego.
    """

    def __init__(self, cada_seg: float = CADA_SEG):
        self.cada_seg = cada_seg
        self._proc: Optional[mp.Process] = None
        self._tuberia = None
        self._cola: "queue.Queue[dict]" = queue.Queue(maxsize=COLA_MAX)
        self._enviador: Optional[threading.Thread] = None
        self._lector: Optional[threading.Thread] = None
        self._parar = threading.Event()
        self._candidatos: list = []
        self._lock = threading.Lock()
        # Para saber si esta vivo y como va, sin preguntarle.
        self.ultimo_barrido = 0.0        # cuando llego el ultimo resultado
        self.coste_barrido = 0.0         # lo que le costo al hijo
        self.tickers_vistos = 0
        self.lotes_tirados = 0
        self.reinicios = 0
        self._estrategias: list = []

    # ── arrancar y parar ──────────────────────────────────────────────────
    def arrancar(self) -> None:
        if self._proc is not None and self._proc.is_alive():
            return
        self._parar.clear()
        padre, cria = mp.Pipe()
        self._tuberia = padre
        self._proc = mp.Process(target=_hijo, args=(cria, self.cada_seg),
                                name="radar", daemon=True)
        self._proc.start()
        cria.close()
        self._enviador = threading.Thread(target=self._enviar_bucle, name="radar-envio", daemon=True)
        self._enviador.start()
        self._lector = threading.Thread(target=self._leer_bucle, name="radar-recibo", daemon=True)
        self._lector.start()

    def parar(self) -> None:
        self._parar.set()
        try:
            if self._tuberia is not None:
                self._tuberia.send({"t": FIN})
        except Exception:           # noqa: BLE001
            pass
        if self._proc is not None:
            self._proc.join(3)
            if self._proc.is_alive():
                self._proc.terminate()

    def vivo(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def vigilar(self, estado_mercado: Optional[dict] = None) -> bool:
        """Si el hijo se ha muerto, lo levanta y le devuelve lo que sabia: el
        estado del mercado del bot (que lleva el suyo propio, y le cuesta 9 ms
        por rafaga) y las estrategias. Devuelve True si hubo que resucitarlo."""
        if self.vivo():
            return False
        self.reinicios += 1
        logger.warning("[RADAR] el proceso del radar no esta vivo; lo levanto de nuevo")
        try:
            self.parar()
        except Exception:           # noqa: BLE001
            pass
        self._proc = None
        # La cola vieja puede tener lotes de antes del corte: no valen.
        while True:
            try:
                self._cola.get_nowait()
            except queue.Empty:
                break
        self.arrancar()
        if estado_mercado:
            self._encolar({"t": ESTADO, "datos": estado_mercado})
        if self._estrategias:
            self._encolar({"t": ESTRATEGIAS, "datos": self._estrategias})
        return True

    # ── lo que el bot le manda ────────────────────────────────────────────
    def enviar_velas(self, lote: list) -> None:
        if lote:
            self._encolar({"t": VELAS, "lote": lote})

    def sembrar_prev_close(self, datos: dict) -> None:
        self._encolar({"t": PREV_CLOSE, "datos": dict(datos)})

    def sembrar_maximos(self, ticker: str, velas: list) -> None:
        self._encolar({"t": MAXIMOS, "ticker": ticker, "velas": velas})

    def configurar(self, estrategias: list) -> None:
        self._estrategias = list(estrategias)
        self._encolar({"t": ESTRATEGIAS, "datos": self._estrategias})

    def limpiar_dia(self) -> None:
        self._encolar({"t": DIA_NUEVO})

    # ── lo que el bot le pide ─────────────────────────────────────────────
    def candidatos(self) -> list:
        with self._lock:
            return list(self._candidatos)

    # ── tripas ────────────────────────────────────────────────────────────
    def _encolar(self, msg: dict) -> None:
        try:
            self._cola.put_nowait(msg)
        except queue.Full:
            # El hijo no lee: se tira lo MAS VIEJO, que son velas ya superadas
            # por las siguientes. Nunca se bloquea al bot.
            try:
                self._cola.get_nowait()
                self.lotes_tirados += 1
            except queue.Empty:
                pass
            try:
                self._cola.put_nowait(msg)
            except queue.Full:
                self.lotes_tirados += 1

    def _enviar_bucle(self) -> None:
        while not self._parar.is_set():
            try:
                msg = self._cola.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._tuberia.send(msg)
            except Exception as exc:        # noqa: BLE001
                logger.warning("[RADAR] no pude enviar al radar: %s", exc)
                return

    def _leer_bucle(self) -> None:
        while not self._parar.is_set():
            try:
                if not self._tuberia.poll(0.5):
                    continue
                msg = self._tuberia.recv()
            except (EOFError, OSError):
                return
            except Exception:               # noqa: BLE001
                return
            if msg.get("t") == CANDIDATOS:
                with self._lock:
                    self._candidatos = msg["datos"]
                self.ultimo_barrido = time.time()
                self.coste_barrido = float(msg.get("coste") or 0.0)
                self.tickers_vistos = int(msg.get("tickers") or 0)
            elif msg.get("t") == AVISO:
                logger.info("[RADAR] %s", msg.get("texto"))
