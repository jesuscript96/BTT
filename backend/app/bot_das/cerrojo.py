"""Instancia única por fichero, latido por fichero e hilos de borde vigilados.

QUÉ HACE. `CerrojoInstancia` toma un cerrojo del sistema operativo sobre un
fichero (R-J-04 c: una segunda instancia NO arranca); `Latido` escribe el
epoch en un fichero de forma atómica como mucho cada segundo (R-J-04 b: el
supervisor mata y relanza a los 3 s sin latido); `HiloVigilado` ejecuta un
cuerpo en un hilo, captura lo que lance, avisa y lo relanza (injerto A §8.11:
un hilo de borde que muere en silencio deja «vivo» a un ejecutor sordo).

POR QUÉ ESTÁ AQUÍ. Los tres procesos (supervisor, vigilante, ejecutor) los
usan; ninguno depende de nada más que de `tipos`.

LAS TRAMPAS.
  * El cerrojo es `msvcrt.locking(LK_NBLCK)` sobre UN byte y el SO lo libera
    solo cuando muere el proceso: por eso el descriptor se mantiene ABIERTO
    mientras se tiene el cerrojo (cerrarlo lo soltaría). Un `.lock` huérfano
    tras un cuelgue NO bloquea: el cerrojo murió con el proceso.
  * El byte bloqueado está a 1 MiB del principio, lejos del PID que se
    escribe al inicio del fichero: en Windows un byte bloqueado en exclusiva
    tampoco se puede LEER desde otro proceso, y el supervisor tiene que leer
    el PID de un proceso vivo para matarlo si no late (§6.1, riesgo 26).
    Comprobado el 26-sep: bloquear más allá del final del fichero funciona y
    la lectura del PID desde otro proceso también.
  * `Latido.tocar(todo_vivo=False)` NO escribe a propósito: el supervisor
    verá el latido viejo y relanzará el proceso (injerto §8.11). Escribir
    «estoy vivo» con el lector de DAS muerto sería mentir.
  * El latido se escribe en un `.tmp` y se renombra con `os.replace`: quien
    lo lee nunca ve un fichero a medias. Si el disco falla, `tocar` no lanza
    (frontera de fichero): cuenta el fallo y el supervisor hará su trabajo.
  * `HiloVigilado` relanza como mucho `max_relanzos` veces SEGUIDAS; la
    última caída llega a `al_caida` con `relanzado=False` y ahí el ejecutor
    debe dejar de latir (`todo_vivo=False`). Una caída tras ≥ `estable_s`
    (60 s, reloj monotónico) de cuerpo corriendo sin lanzar pone la cuenta
    de seguidas a 0, y `arrancar()` también (L0-02): el freno es contra los
    bucles de caída, no contra seis fallos sueltos en 16 h. `caidas` sigue
    contando el total (métrica). Un cuerpo que TERMINA sin excepción se da por
    acabado (no se relanza): así `parar()` funciona con un cuerpo que mira
    `parando`.
"""
from __future__ import annotations

import msvcrt
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

from app.bot_das.tipos import LATIDO_S

OFFSET_CERROJO = 1 << 20     # byte bloqueado: a 1 MiB, nunca solapa con el PID (ver trampas)
ESTABLE_S = 60.0             # L0-02: un cuerpo que corrió ≥ 60 s antes de caer no cuenta como caída «seguida»


class CerrojoInstancia:
    """Cerrojo de instancia única sobre `ruta` (R-J-04 c)."""

    def __init__(self, ruta: Path) -> None:
        self._ruta = Path(ruta)
        self._fichero = None

    @property
    def ruta(self) -> Path:
        return self._ruta

    @property
    def tomado(self) -> bool:
        return self._fichero is not None

    def adquirir(self) -> bool:
        """True si el cerrojo es nuestro (y el fichero contiene nuestro PID); False si otro proceso lo tiene.

        `msvcrt.locking(LK_NBLCK)` sobre 1 byte; el SO lo libera si el proceso
        muere. Idempotente: adquirir dos veces desde la misma instancia es True.
        """
        if self._fichero is not None:
            return True
        self._ruta.parent.mkdir(parents=True, exist_ok=True)
        fichero = open(self._ruta, "a+", encoding="ascii")   # crea sin truncar; a+ nunca pisa el PID de otro
        try:
            fichero.seek(OFFSET_CERROJO)
            msvcrt.locking(fichero.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:              # frontera de fichero: errno 13 = lo tiene otro proceso (R-J-04 c: la nueva instancia no arranca)
            fichero.close()
            return False
        fichero.truncate(0)          # solo lo escribe quien tiene el cerrojo
        fichero.write(str(os.getpid()))
        fichero.flush()
        self._fichero = fichero
        return True

    def soltar(self) -> None:
        """Libera el byte y cierra el descriptor (el SO haría lo mismo al morir)."""
        fichero, self._fichero = self._fichero, None
        if fichero is None:
            return
        try:
            fichero.seek(OFFSET_CERROJO)
            msvcrt.locking(fichero.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:              # frontera de fichero: ya no estaba bloqueado; cerrar basta
            pass
        finally:
            fichero.close()

    @staticmethod
    def pid_guardado(ruta: Path) -> Optional[int]:
        """PID escrito por el último que tomó el cerrojo, o None si no hay fichero o no es un número."""
        try:
            texto = Path(ruta).read_text(encoding="ascii").strip()
        except OSError:              # frontera de fichero: sin fichero = nadie lo ha tomado nunca
            return None
        if not texto.isdigit():
            return None
        return int(texto)


class Latido:
    """Latido por fichero (R-J-04 b): epoch en `ruta`, atómico, como mucho cada `cada_s`."""

    def __init__(self, ruta: Path, reloj, cada_s: float = LATIDO_S) -> None:
        self._ruta = Path(ruta)
        self._tmp = self._ruta.with_name(self._ruta.name + ".tmp")
        self._reloj = reloj
        self._cada_s = float(cada_s)
        self._ultimo_mono: Optional[float] = None
        self.fallos = 0
        self.ultimo_error: Optional[str] = None
        self.escrituras = 0

    @property
    def ruta(self) -> Path:
        return self._ruta

    def tocar(self, todo_vivo: bool = True) -> None:
        """Escribe `reloj.epoch()` en tmp + `os.replace`, como mucho cada `cada_s`.

        Con `todo_vivo=False` NO escribe (el supervisor lo verá viejo y
        relanzará, injerto §8.11). Nunca lanza: un fallo de disco se cuenta
        en `fallos` y el latido simplemente envejece.
        """
        if not todo_vivo:
            return
        ahora = self._reloj.mono()
        if self._ultimo_mono is not None and (ahora - self._ultimo_mono) < self._cada_s:
            return
        try:
            self._ruta.parent.mkdir(parents=True, exist_ok=True)
            self._tmp.write_text(repr(float(self._reloj.epoch())), encoding="ascii")
            os.replace(self._tmp, self._ruta)
        except OSError as exc:       # frontera de fichero: disco lleno o bloqueado → el latido envejece y el supervisor actúa (R-J-04 b)
            self.fallos += 1
            self.ultimo_error = f"{type(exc).__name__}: {exc}"
            return
        self._ultimo_mono = ahora
        self.escrituras += 1

    @staticmethod
    def edad(ruta: Path, ahora_epoch: float) -> Optional[float]:
        """Segundos desde el último latido, o None si no existe o no se puede leer."""
        try:
            texto = Path(ruta).read_text(encoding="ascii").strip()
            return float(ahora_epoch) - float(texto)
        except (OSError, ValueError):   # frontera de fichero: sin fichero o contenido raro = «no late»
            return None


class HiloVigilado:
    """Ejecuta `cuerpo` en un hilo daemon; si lanza, avisa por `al_caida(nombre, error, relanzado)` y relanza.

    Equivalente al `tarea_vigilada` del diseño A (injerto §8.11): registra,
    avisa nivel 2 (lo hace quien recibe `al_caida`) y relanza tras `espera_s`
    hasta `max_relanzos` veces; la caída número `max_relanzos + 1` llega con
    `relanzado=False` y el hilo termina. `parando` es el `threading.Event`
    que el cuerpo debe consultar para terminar de forma cooperativa.
    """

    def __init__(self, nombre: str, cuerpo: Callable[[], None], al_caida: Callable[[str, str, bool], None],
                 max_relanzos: int = 5, espera_s: float = 1.0, estable_s: float = ESTABLE_S,
                 mono: Callable[[], float] = time.monotonic) -> None:
        if max_relanzos < 0:
            raise ValueError(f"max_relanzos debe ser ≥ 0: {max_relanzos}")
        if espera_s < 0:
            raise ValueError(f"espera_s debe ser ≥ 0: {espera_s}")
        if estable_s < 0:
            raise ValueError(f"estable_s debe ser ≥ 0: {estable_s}")
        self.nombre = nombre
        self._cuerpo = cuerpo
        self._al_caida = al_caida
        self._max_relanzos = max_relanzos
        self._espera_s = float(espera_s)
        self._estable_s = float(estable_s)
        self._mono = mono
        self.parando = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self._caidas = 0
        self._caidas_seguidas = 0
        self.ultima_traza: Optional[str] = None

    def arrancar(self) -> None:
        """Arranca el hilo (una sola vez; si ya está vivo no hace nada). Pone a 0 las caídas SEGUIDAS (L0-02)."""
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._caidas_seguidas = 0
        self.parando.clear()
        self._hilo = threading.Thread(target=self._correr, name=self.nombre, daemon=True)
        self._hilo.start()

    def parar(self, espera_s: float = 5.0) -> None:
        """Pide parar (`parando`) y espera hasta `espera_s` a que el hilo termine."""
        self.parando.set()
        hilo = self._hilo
        if hilo is not None and hilo is not threading.current_thread():
            hilo.join(espera_s)

    @property
    def vivo(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    @property
    def caidas(self) -> int:
        """Caídas de TODA la vida del objeto (métrica; no decide el relanzamiento)."""
        return self._caidas

    @property
    def caidas_seguidas(self) -> int:
        """Caídas sin una racha estable (≥ `estable_s`) entre ellas: son las que agotan `max_relanzos` (L0-02)."""
        return self._caidas_seguidas

    def _correr(self) -> None:
        while not self.parando.is_set():
            inicio = self._mono()
            try:
                self._cuerpo()
                return                              # terminó por las buenas: no se relanza
            except Exception as exc:  # noqa: BLE001 — frontera de callback: un hilo de borde que muere se registra y se relanza (injerto §8.11)
                if self._mono() - inicio >= self._estable_s:
                    self._caidas_seguidas = 0       # L0-02: corrió estable antes de caer → un fallo aislado, no un bucle
                self._caidas += 1
                self._caidas_seguidas += 1
                self.ultima_traza = traceback.format_exc()
                error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                relanzado = (not self.parando.is_set()) and self._caidas_seguidas <= self._max_relanzos
                try:
                    self._al_caida(self.nombre, error, relanzado)
                except Exception:  # noqa: BLE001 — frontera de callback: un aviso que falla no puede impedir el relanzamiento
                    pass
                if not relanzado:
                    return
                if self.parando.wait(self._espera_s):
                    return
