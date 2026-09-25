"""Fontaneria comun de los procesos hijos del bot (23-sep-2026).

POR QUE EXISTE ESTE MODULO. En Python un proceso usa UN nucleo, por mucho hilo
que le pongas: mientras un hilo calcula, el que lee el socket esta parado. La
maquina de Jaume tiene 20 nucleos y el bot solo podia usar uno. Medido el
23-sep: con el mercado abierto el bot llego al 97 % de su nucleo mientras la
maquina entera marcaba 3 %, y la alerta pasaba de 1,2 s a 15 s de mediana. Con
el p90 en 30,78 s Massive dejo de recibir respuesta a su ping y nos corto la
conexion (1011) — y cada corte nuestro puede echar a un socio de la cuenta al
reconectar.

La salida es repartir el trabajo en varios procesos, uno por nucleo. Esto es lo
que comparten todos: la tuberia con el padre y las reglas para que ninguno de
los dos se quede esperando al otro.

LAS TRAMPAS, medidas el 22-sep antes de escribir el primer hijo (el radar):

  1. Mandar 5.700 mensajes UNO A UNO cuesta 84 ms al padre; en UN solo envio,
     3,4 ms. Se manda SIEMPRE en lote.
  2. Un lote grande pesa mas que el buffer de la tuberia, asi que `send` se
     BLOQUEA hasta que el otro lado lea. Si el hijo estuviera calculando, el
     padre se quedaria esperando: justo lo que veniamos a evitar. De ahi el
     hilo lector en el hijo (que solo vacia la tuberia) y el hilo de envio en
     el padre con una cola acotada que TIRA LO VIEJO antes que esperar.
  3. Un hijo se puede morir sin avisar. El padre lo vigila, lo levanta y le
     devuelve lo que sabia (`al_resucitar`).

NO HAY SEGUNDA CONEXION A MASSIVE. Ningun hijo abre un websocket: el padre
mantiene la unica conexion y les pasa por tuberia local lo que ya recibe. El
limite de conexiones de la cuenta es lo que provoca los 1008, y ese limite lo
comparte Jaume con su socio.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Cuantos lotes pueden estar esperando a salir hacia un hijo. Si se llena
# (hijo colgado o muy ocupado) se tiran los mas viejos y se cuenta: mas vale un
# hijo con retraso que un bot que se para a esperarlo.
COLA_MAX = 16

# Mensajes que entiende cualquier hijo. Cada hijo anyade los suyos.
FIN = "fin"              # padre -> hijo: cierra
AVISO = "aviso"          # hijo -> padre: una linea para el log
LATIDO = "latido"        # hijo -> padre: sigo vivo, y como voy


def bucle_hijo(tuberia, manejador: Callable[[dict], None],
               periodica: Optional[Callable[[], None]] = None,
               cada_seg: float = 1.0,
               nombre: str = "hijo") -> None:
    """El cuerpo de un proceso hijo: un hilo lee la tuberia y el principal
    hace la tarea periodica (si la hay).

    `manejador` recibe cada mensaje del padre. Que sea BARATO: mientras dure,
    la tuberia no se vacia y el padre puede quedarse sin sitio donde encolar.
    Si el trabajo es caro, que el manejador solo apunte y lo haga `periodica`.
    """
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
            if msg.get("t") == FIN:
                parar.set()
                return
            try:
                manejador(msg)
            except Exception as exc:            # noqa: BLE001
                # Un fallo con UN mensaje no puede matar al hijo entero: el
                # padre se quedaria sin prealertas (o sin alertas) en silencio.
                try:
                    tuberia.send({"t": AVISO, "texto": f"[{nombre}] fallo con {msg.get('t')}: {exc}"})
                except Exception:               # noqa: BLE001
                    parar.set()
                    return

    hilo = threading.Thread(target=leer, name=f"{nombre}-lector", daemon=True)
    hilo.start()

    if periodica is None:
        parar.wait()
        return

    while not parar.is_set():
        t0 = time.perf_counter()
        try:
            periodica()
        except Exception as exc:                # noqa: BLE001
            try:
                tuberia.send({"t": AVISO, "texto": f"[{nombre}] fallo periodico: {exc}"})
            except Exception:                   # noqa: BLE001
                return
        parar.wait(max(0.05, cada_seg - (time.perf_counter() - t0)))


class ProcesoHijo:
    """Un hijo visto desde el bot. Nada de lo que hace aqui bloquea.

    `enviar` deja el mensaje en una cola y un hilo lo saca; lo que el hijo
    devuelve llega por `al_recibir`, que corre en el hilo lector del padre — y
    por eso tambien tiene que ser barato.
    """

    def __init__(self, destino: Callable, nombre: str,
                 al_recibir: Optional[Callable[[dict], None]] = None,
                 argumentos: tuple = ()):
        self.destino = destino          # la funcion que corre en el hijo
        self.nombre = nombre
        self.argumentos = argumentos
        self.al_recibir = al_recibir
        self._proc: Optional[mp.Process] = None
        self._tuberia = None
        self._cola: "queue.Queue[dict]" = queue.Queue(maxsize=COLA_MAX)
        self._parar = threading.Event()
        # Contadores, para saber como va sin preguntarle.
        self.lotes_tirados = 0
        self.reinicios = 0
        self.ultimo_mensaje = 0.0       # cuando contesto por ultima vez
        self.al_resucitar: Optional[Callable[["ProcesoHijo"], None]] = None
        # Ademas del log, quien quiera los avisos del hijo los recibe aqui. Lo
        # usan las pruebas: fiarse del log no vale, porque otra prueba puede
        # haber cambiado la configuracion del registro (25-sep: en la suite
        # completa el texto capturado llegaba vacio).
        self.al_aviso: Optional[Callable[[str], None]] = None

    # ── arrancar y parar ──────────────────────────────────────────────────
    def arrancar(self) -> None:
        if self.vivo():
            return
        self._parar.clear()
        padre, cria = mp.Pipe()
        self._tuberia = padre
        self._proc = mp.Process(target=self.destino, args=(cria,) + self.argumentos,
                                name=self.nombre, daemon=True)
        self._proc.start()
        cria.close()
        threading.Thread(target=self._enviar_bucle, name=f"{self.nombre}-envio",
                         daemon=True).start()
        threading.Thread(target=self._leer_bucle, name=f"{self.nombre}-recibo",
                         daemon=True).start()

    def parar(self) -> None:
        self._parar.set()
        try:
            if self._tuberia is not None:
                self._tuberia.send({"t": FIN})
        except Exception:                       # noqa: BLE001
            pass
        if self._proc is not None:
            self._proc.join(3)
            if self._proc.is_alive():
                self._proc.terminate()

    def vivo(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def vigilar(self) -> bool:
        """Si se murio, lo levanta y llama a `al_resucitar` para que le
        devuelvan lo que sabia. Devuelve True si hubo que levantarlo."""
        if self.vivo():
            return False
        self.reinicios += 1
        logger.warning("[%s] el proceso no esta vivo; lo levanto de nuevo (van %d)",
                       self.nombre, self.reinicios)
        try:
            self.parar()
        except Exception:                       # noqa: BLE001
            pass
        self._proc = None
        # La cola vieja lleva mensajes de antes del corte: no valen.
        while True:
            try:
                self._cola.get_nowait()
            except queue.Empty:
                break
        self.arrancar()
        if self.al_resucitar is not None:
            try:
                self.al_resucitar(self)
            except Exception as exc:            # noqa: BLE001
                logger.warning("[%s] no pude devolverle su estado: %s", self.nombre, exc)
        return True

    # ── hablar con el ─────────────────────────────────────────────────────
    def enviar(self, msg: dict) -> None:
        try:
            self._cola.put_nowait(msg)
        except queue.Full:
            # Se tira lo MAS VIEJO, que es lo que ya ha quedado superado por lo
            # que viene detras. Nunca se bloquea al bot.
            try:
                self._cola.get_nowait()
                self.lotes_tirados += 1
            except queue.Empty:
                pass
            try:
                self._cola.put_nowait(msg)
            except queue.Full:
                self.lotes_tirados += 1

    # ── tripas ────────────────────────────────────────────────────────────
    def _enviar_bucle(self) -> None:
        while not self._parar.is_set():
            try:
                msg = self._cola.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._tuberia.send(msg)
            except Exception as exc:            # noqa: BLE001
                logger.warning("[%s] no pude enviar: %s", self.nombre, exc)
                return

    def _leer_bucle(self) -> None:
        while not self._parar.is_set():
            try:
                if not self._tuberia.poll(0.5):
                    continue
                msg = self._tuberia.recv()
            except (EOFError, OSError):
                return
            except Exception:                   # noqa: BLE001
                return
            self.ultimo_mensaje = time.time()
            if msg.get("t") == AVISO:
                logger.info("[%s] %s", self.nombre, msg.get("texto"))
                if self.al_aviso is not None:
                    try:
                        self.al_aviso(msg.get("texto") or "")
                    except Exception:           # noqa: BLE001
                        pass
                continue
            if self.al_recibir is not None:
                try:
                    self.al_recibir(msg)
                except Exception as exc:        # noqa: BLE001
                    logger.warning("[%s] fallo al procesar %s: %s",
                                   self.nombre, msg.get("t"), exc)


class Vigilante:
    """Mira cada pocos segundos que los hijos sigan vivos y levanta al que se
    haya caido. Corre en un hilo del padre: no calcula nada, solo pregunta.

    Va en el padre y no en un quinto proceso a proposito: si el padre se muere
    no hay bot, y un vigilante externo no arreglaria eso. Lo que si arregla es
    que un hijo se cuelgue sin que nadie se entere, que en ejecucion automatica
    dejaria de ser un detalle.
    """

    def __init__(self, hijos: list, cada_seg: float = 5.0):
        self.hijos = hijos
        self.cada_seg = cada_seg
        self._parar = threading.Event()
        self._hilo: Optional[threading.Thread] = None

    def arrancar(self) -> None:
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="vigilante", daemon=True)
        self._hilo.start()

    def parar(self) -> None:
        self._parar.set()

    def _bucle(self) -> None:
        while not self._parar.is_set():
            for hijo in self.hijos:
                try:
                    hijo.vigilar()
                except Exception as exc:        # noqa: BLE001
                    logger.warning("[vigilante] fallo vigilando %s: %s",
                                   getattr(hijo, "nombre", "?"), exc)
            self._parar.wait(self.cada_seg)

    def resumen(self) -> str:
        partes = []
        for h in self.hijos:
            partes.append("%s %s%s" % (
                h.nombre, "vivo" if h.vivo() else "MUERTO",
                f" (relanzado {h.reinicios}x)" if h.reinicios else ""))
        return " · ".join(partes)
