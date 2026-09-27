"""Proceso supervisor del bot de DAS: ventana del día, DAS abierto, vigilante y ejecutor vivos, latidos y apagado.

QUÉ HACE
  `Supervisor` es el proceso raíz (§6.1, §6.2). Cada 0,5 s: calcula la
  ventana del día (R-L-01: `horario.encender`, 03:55 por defecto, hasta el
  último EOD de las estrategias + el margen de R-D-02, u `horario.apagar`;
  festivos por `bot_alerts_calendario.hay_sesion`, medias sesiones por
  `media_sesion`). Dentro de la ventana asegura DAS (EP-7: si `DAS_EXE` está y
  DAS no sale en `tasklist`, lo abre y avisa 3 «LOGIN/2FA a mano»; espera a
  que el puerto del API acepte conexiones, con aviso cada 5 min), lanza el
  VIGILANTE, espera su latido (≤ 10 s) y lanza el EJECUTOR (R-J-06). Mide los
  latidos por fichero: un hijo muerto se relanza con `PlanRelanzamiento`
  (1, 2, 5, 10 y luego 10 s; se reinicia tras 300 s estable) y uno colgado
  (latido de más de `colgado_s`, 3 s) se mata y se relanza (R-J-04 v2). Lee
  las peticiones de los hijos en `estado/orden_supervisor.jsonl` («relanzar
  ejecutor» del vigilante, corrección 16). Fuera de la ventana escribe
  `{"parar": true}` para cada hijo, espera ≤ 10 s y los termina; si a esa
  hora `estado/foto.json` dice que hay posición, avisa 3 y NO apaga (L4).
  Avisa 2 con el disco por debajo de `disco_min_gb` (R-J-07). Al arrancar
  mata por el PID guardado en su cerrojo al hijo huérfano que no late y
  adopta al que sí late (riesgo 26).

POR QUÉ ESTÁ AQUÍ
  Nadie más puede relanzar un proceso muerto ni matar uno colgado: el
  ejecutor y el vigilante no se vigilan a sí mismos. El supervisor no decide
  nada de trading (no importa el decisor, el ejecutor ni el vigilante: un
  módulo roto de un hijo no puede tumbarlo) y no es imprescindible: si muere,
  los hijos siguen protegiendo la posición y el ping externo del vigilante
  alarma; al volver, adopta o mata según el latido.

LAS TRAMPAS
  * `python.exe` del venv en Windows es un LANZADOR: `Popen.pid` no es el PID
    del intérprete (el que escribe `estado/cerrojo_*.lock`). `terminate()`
    sobre el lanzador mata también al intérprete (objeto de trabajo con
    KILL_ON_JOB_CLOSE, comprobado el 27-sep), pero además, por si acaso, se
    mata el PID guardado en el cerrojo mientras el cerrojo siga tomado.
  * Matar por PID solo si el cerrojo del hijo está TOMADO: un PID de un
    fichero viejo puede pertenecer ya a otro programa (reutilización de PID).
    El cerrojo tomado garantiza que el PID escrito es el de su dueño vivo.
  * En Windows `os.kill(pid, 0)` NO pregunta: llama a TerminateProcess con
    código 0 y MATA el proceso. Para saber si un PID vive se usa
    `OpenProcess` + `GetExitCodeProcess` (ctypes).
  * Un hijo recién lanzado aún no tiene latido y el fichero puede ser de la
    instancia anterior (viejo): solo cuenta el latido escrito DESPUÉS del
    lanzamiento; sin él, se le dan `arranque_max_s` (30 s) antes de darlo por
    colgado.
  * La orden «parar» y las peticiones viajan por el MISMO fichero; el
    supervisor lee desde el tamaño que tenía al arrancar (una petición de
    ayer no relanza nada hoy) y se salta sus propias líneas.
  * Un hijo que sale con código 0 sin que el supervisor lo pidiera lo ha
    parado alguien a mano (Ctrl+C en su consola, fin de una grabación): NO se
    relanza hasta el día siguiente (control humano) y se avisa.
  * Parar el supervisor NO para a los hijos (riesgo 26: siguen protegiendo
    la posición); los para él mismo solo al salir de la ventana.
  * El calendario real (`bot_alerts_calendario`) puede pedir la lista oficial
    a Massive en un hilo propio (httpx a WARNING por `instalar_logging`); se
    importa de forma perezosa y es inyectable (los tests no tocan la red).
  * Relojes: las decisiones van con el reloj inyectado (`mono()` para plazos,
    `epoch()` para comparar con los latidos, `ahora()` para la ventana); solo
    la espera del bucle es tiempo real.
  * Importar este módulo no abre red, no lee ficheros y no arranca hilos; las
    variables de entorno se leen en la llamada.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from app.bot_das import VERSION
from app.bot_das import avisos as mod_avisos
from app.bot_das import config as mod_config
from app.bot_das.cerrojo import CerrojoInstancia, Latido
from app.bot_das.cliente import ENV_HOST, ENV_PUERTO, HOST_POR_DEFECTO
from app.bot_das.diario import Diario
from app.bot_das.reglas import salidas
from app.bot_das.reloj import ET, Reloj, a_hora_et
from app.bot_das.tipos import (
    COLGADO_S,
    DAS_AVISO_CADA_S,
    DISCO_MIN_GB,
    EOD_COMPROBAR_DESPUES_S,
    RELANZAR_S,
    Aviso,
    Config,
    EstadoOrden,
    Fase,
    Grupo,
    Nivel,
)

logger = logging.getLogger("btt.bot_das.supervisor")

# ── códigos de salida del proceso ──────────────────────────────────────
CODIGO_OK = 0                   # parada ordenada
CODIGO_ERROR = 1                # excepción no prevista en main
CODIGO_DOBLE_INSTANCIA = 3      # R-J-04 c: otro supervisor tiene el cerrojo
CODIGO_CONFIG = 5               # entorno imposible (main)

# significado de los códigos de los hijos (ejecutor.py / vigilante.py): solo para el texto del aviso
SIGNIFICADO_CODIGO = {0: "parada ordenada", 1: "error no previsto", 2: "reloj desviado (R-J-07)",
                      3: "doble instancia (R-J-04 c)", 4: "motor distinto de la config (H-6)",
                      5: "config o entorno imposibles"}

# ── tiempos (R-J-04 v2, R-L-01, §6.2) ──────────────────────────────────
PERIODO_S = 0.5                 # §3.27: bucle cada 0,5 s dentro de la ventana
ESPERA_FUERA_S = 30.0           # §6.2.1: fuera de la ventana comprueba cada 30 s
ESTABLE_S = 300.0               # R-J-04 v2: tras 300 s vivo, el plan de relanzamiento vuelve a 1 s
ESPERA_LATIDO_VIGILANTE_S = 10.0    # §6.2.3: el ejecutor sale tras el latido del vigilante o, como mucho, 10 s después
ARRANQUE_MAX_S = 30.0           # un hijo lanzado que no late en este plazo se da por colgado (objetivo < 10 s, R-J-04)
ESPERA_PARADA_S = 10.0          # §6.2.5: tras «parar», espera ≤ 10 s antes de terminate
ESPERA_TERMINAR_S = 5.0         # tras terminate/TerminateProcess, espera a que el SO lo dé por muerto
GRACIA_PETICION_S = 15.0        # corrección 16: un «relanzar ejecutor» no mata a un ejecutor lanzado hace menos
SONDA_DAS_CADA_S = 5.0          # §6.2.2: sonda del puerto del API como mucho cada 5 s
SONDA_DAS_TIMEOUT_S = 2.0
DISCO_CADA_S = 60.0             # R-J-07: el disco se mira cada minuto
DISCO_AVISO_CADA_S = 3600.0     # y con poco disco se avisa como mucho cada hora
TASKLIST_TIMEOUT_S = 10.0
ESPERA_AVISOS_S = 30.0          # §6.2.5: avisos.parar(30)
TOLERANCIA_LATIDO_S = 0.5       # un latido escrito «a la vez» que el lanzamiento cuenta como posterior
DAS_VIGILAR_CADA_S = 30.0       # G2-03: durante toda la ventana, el proceso DAS se mira cada 30 s
CODIGOS_SIN_RELANZAR = frozenset({4, 5})   # G2-08: motor distinto (H-6) y config/entorno: relanzar no lo arregla
RELOJ_RELANZOS_MAX = 3          # G2-08: tras 3 salidas seguidas por reloj (código 2) se deja a control humano
ORDEN_HUERFANA_S = 60.0         # R2-PRO-2: una SENDING sin id de DAS vista más de 60 s no impide el apagado nocturno
HORA_ENCENDER_DEFECTO = "03:55"     # R-L-01 / §7 horario.encender
HORA_APAGAR_SIN_CONFIG = "20:00"    # sin config legible: ventana larga (apagar antes nunca es lo conservador)
EOD_SIN_ESTRATEGIAS = salidas.EOD_POR_DEFECTO   # 16:00 (L4)
CIERRE_MEDIA_SESION = "13:00"   # bot_alerts_calendario.MEDIA_SESION_FIN (13:00 ET)

# ── ficheros y entorno ─────────────────────────────────────────────────
HIJOS = ("vigilante", "ejecutor")   # orden de arranque (§6.2.3); se paran al revés
NOMBRE_CERROJO = "cerrojo_supervisor.lock"
NOMBRE_ORDEN_SUPERVISOR = "orden_supervisor.jsonl"
NOMBRE_FOTO = "foto.json"
SUBCARPETAS_BOT = ("config", "diario", "estado", "cache", "logs")
ENV_DIR = "BOT_DAS_DIR"
ENV_CUENTA = "DAS_CUENTA"
ENV_DAS_EXE = "DAS_EXE"
CUENTA_SOLO_LECTURA = "supervisor"      # la cuenta no influye en la ventana; sin DAS_CUENTA la config se lee igual
RUTA_DOTENV: Optional[Path] = None      # None = backend/.env (lo carga SOLO main; un test lo apunta a otro sitio)

_STILL_ACTIVE = 259
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_EN_WINDOWS = sys.platform == "win32"


def nombre_latido(hijo: str) -> str:
    """`latido_{hijo}` (ejecutor.NOMBRE_LATIDO / vigilante.NOMBRE_LATIDO)."""
    return f"latido_{hijo}"


def nombre_cerrojo(hijo: str) -> str:
    """`cerrojo_{hijo}.lock` (ejecutor.NOMBRE_CERROJO / vigilante.NOMBRE_CERROJO)."""
    return f"cerrojo_{hijo}.lock"


# ══════════════════════════════════════════════════════════════════════
# Plan de relanzamiento (R-J-04 v2)
# ══════════════════════════════════════════════════════════════════════
class PlanRelanzamiento:
    """Esperas antes de relanzar un hijo caído: 1, 2, 5, 10 s y luego 10 s sin límite (R-J-04 v2).

    `siguiente(ahora, lanzado_en)` devuelve la espera para el intento
    siguiente; si el hijo llevaba vivo `estable_s` (300 s) o más desde su
    último lanzamiento, el plan vuelve al principio (una caída aislada tras
    horas de marcha no espera 10 s). Trampa evitada: sin el reinicio, dos
    caídas separadas por horas acabarían esperando siempre 10 s.
    """

    def __init__(self, esperas: Sequence[float] = RELANZAR_S, estable_s: float = ESTABLE_S) -> None:
        lista = tuple(esperas)
        if not lista:
            raise ValueError("esperas no puede estar vacía")
        for espera in lista:
            if isinstance(espera, bool) or not isinstance(espera, (int, float)) or not math.isfinite(espera) \
                    or espera < 0:
                raise ValueError(f"cada espera debe ser un número finito ≥ 0: {espera!r}")
        if isinstance(estable_s, bool) or not isinstance(estable_s, (int, float)) or not math.isfinite(estable_s) \
                or estable_s <= 0:
            raise ValueError(f"estable_s debe ser un número finito > 0: {estable_s!r}")
        self._esperas = tuple(float(e) for e in lista)
        self._estable_s = float(estable_s)
        self._indice = 0

    @property
    def esperas(self) -> tuple[float, ...]:
        return self._esperas

    @property
    def estable_s(self) -> float:
        return self._estable_s

    @property
    def intentos(self) -> int:
        """Caídas encadenadas desde el último reinicio del plan."""
        return self._indice

    def siguiente(self, ahora: float, lanzado_en: Optional[float] = None) -> float:
        """R-J-04 v2: la espera antes del próximo lanzamiento (1, 2, 5, 10, 10, …; vuelve a 1 tras `estable_s` vivo)."""
        if lanzado_en is not None and (ahora - lanzado_en) >= self._estable_s:
            self._indice = 0
        espera = self._esperas[min(self._indice, len(self._esperas) - 1)]
        self._indice += 1
        return espera

    def reiniciar(self) -> None:
        """Vuelve al principio (día nuevo, apagado ordenado)."""
        self._indice = 0


# ══════════════════════════════════════════════════════════════════════
# Procesos del SO (Windows primero; POSIX como respaldo para no romper fuera)
# ══════════════════════════════════════════════════════════════════════
def pid_vivo(pid: int) -> bool:
    """True si el proceso `pid` existe y no ha terminado. NUNCA lo mata (trampa de `os.kill(pid, 0)` en Windows)."""
    if type(pid) is not int or pid <= 0:
        return False
    if _EN_WINDOWS:
        import ctypes   # perezoso: importar el módulo no carga ctypes
        kernel32 = ctypes.windll.kernel32
        manejador = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not manejador:
            return kernel32.GetLastError() == _ERROR_ACCESS_DENIED   # existe, pero es de otro usuario
        try:
            codigo = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(manejador, ctypes.byref(codigo)):
                return False
            return codigo.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(manejador)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def matar_pid(pid: int) -> bool:
    """Termina el proceso `pid` (TerminateProcess en Windows). True si se pudo pedir. Nunca se mata a sí mismo."""
    if type(pid) is not int or pid <= 0 or pid == os.getpid():
        return False
    if _EN_WINDOWS:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        manejador = kernel32.OpenProcess(_PROCESS_TERMINATE, False, pid)
        if not manejador:
            return False
        try:
            return bool(kernel32.TerminateProcess(manejador, 1))
        finally:
            kernel32.CloseHandle(manejador)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


def cerrojo_tomado_por_otro(ruta: Path) -> bool:
    """True si OTRO proceso (o handle) tiene el cerrojo de `ruta` (R-J-04 c). Si estaba libre, lo suelta al instante.

    Trampa: si lo consigue, `CerrojoInstancia.adquirir` escribe el PID del
    supervisor en el fichero; es inocuo (el siguiente dueño lo sobrescribe)
    y el cerrojo se suelta en la misma llamada.
    """
    if not Path(ruta).exists():
        return False
    cerrojo = CerrojoInstancia(Path(ruta))
    try:
        libre = cerrojo.adquirir()
    except OSError:   # frontera de fichero: sin poder abrirlo no se puede afirmar que haya dueño
        return False
    if libre:
        cerrojo.soltar()
        return False
    return True


def das_en_tasklist(imagen: str) -> Optional[bool]:
    """EP-7: ¿sale `imagen` (p. ej. «DASTrader.exe») en `tasklist`? None si no se pudo preguntar."""
    if not _EN_WINDOWS:
        return None
    try:
        resultado = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {imagen}", "/NH", "/FO", "CSV"],
                                   capture_output=True, text=True, timeout=TASKLIST_TIMEOUT_S,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):   # frontera del SO: sin tasklist no se sabe
        return None
    if resultado.returncode != 0:
        return None
    return f'"{imagen.lower()}"' in resultado.stdout.lower()


def sonda_puerto_das() -> Optional[bool]:
    """§6.2.2: ¿acepta conexión el puerto del API de DAS (DAS_API_HOST/DAS_API_PORT)? None sin puerto en el entorno.

    Abre y cierra un socket TCP sin mandar nada (ni LOGIN ni comandos): solo
    se quiere saber si DAS escucha. Nunca lanza.
    """
    puerto_txt = os.environ.get(ENV_PUERTO, "").strip()
    if not puerto_txt.isdigit() or not (1 <= int(puerto_txt) <= 65535):
        return None
    host = os.environ.get(ENV_HOST, "").strip() or HOST_POR_DEFECTO
    try:
        with socket.create_connection((host, int(puerto_txt)), timeout=SONDA_DAS_TIMEOUT_S):
            return True
    except OSError:   # frontera de red: DAS cerrado o sin API todavía
        return False


def disco_libre_gb(ruta: Path) -> Optional[float]:
    """GiB libres en la unidad de `ruta` (R-J-07); None si no se puede medir. GiB (< GB): avisa antes, no después."""
    try:
        return shutil.disk_usage(Path(ruta)).free / float(1 << 30)
    except OSError:   # frontera del SO
        return None


# ══════════════════════════════════════════════════════════════════════
# Estado de un hijo
# ══════════════════════════════════════════════════════════════════════
@dataclass
class EstadoHijo:
    """Lo que el supervisor sabe de UN hijo (§6.1). Lectura para tests y para la foto; lo muta solo el supervisor.

    `proceso` es el Popen (None si es adoptado o no corre); `pid` el del
    intérprete si se conoce (cerrojo) o el del Popen; `relanzar_en` el
    `mono()` a partir del cual se puede lanzar (None = ya, si toca);
    `parado_a_mano` bloquea el relanzamiento hasta el día siguiente.
    """
    nombre: str
    plan: PlanRelanzamiento
    proceso: Any = None
    pid: Optional[int] = None
    adoptado: bool = False
    lanzado_mono: Optional[float] = None
    lanzado_epoch: Optional[float] = None
    relanzar_en: Optional[float] = None
    lanzamientos: int = 0
    parada_pedida: bool = False
    parado_a_mano: bool = False
    ultimo_codigo: Optional[int] = None
    ultima_espera: Optional[float] = None
    salidas_reloj: int = 0                   # G2-08: salidas seguidas con código 2 (reloj desviado)
    parado_por_codigo: Optional[int] = None  # G2-08: 4/5 (o 2 agotado): no se relanza hasta cambiar la config o el día

    @property
    def corriendo(self) -> bool:
        return self.proceso is not None or self.adoptado


# ══════════════════════════════════════════════════════════════════════
# Supervisor
# ══════════════════════════════════════════════════════════════════════
class Supervisor:
    """Proceso raíz (§3.27, §6.1, §6.2; R-J-04 v2, R-J-06, R-J-07, R-L-01, EP-7, riesgo 26).

    Firma de §3.27 más parámetros SOLO por nombre para los tests y el
    replay: calendario, sondas del SO, fábrica de procesos y tiempos. `None`
    en un tiempo toma el valor de la config (`tecnicos.vigilante.relanzar_s`,
    `colgado_s`, `tecnicos.disco_min_gb`) o, sin config, la constante de
    `tipos`.
    """

    def __init__(self, cfg_ruta: Path, reloj: Any, avisos: Any, python: str, cwd: Path, das_exe: Optional[Path],
                 ruta_estado: Path, diario: Diario, *,
                 cuenta_das: Optional[str] = None,
                 argv_hijo: Optional[Callable[[str], list]] = None,
                 popen: Callable[..., Any] = subprocess.Popen,
                 hay_sesion: Optional[Callable[[date], bool]] = None,
                 media_sesion: Optional[Callable[[date], Optional[str]]] = None,
                 das_vivo: Optional[Callable[[], Optional[bool]]] = None,
                 sonda_das: Optional[Callable[[], Optional[bool]]] = None,
                 libre_gb: Optional[Callable[[], Optional[float]]] = None,
                 pid_vivo_fn: Optional[Callable[[int], bool]] = None,
                 matar_pid_fn: Optional[Callable[[int], bool]] = None,
                 periodo_s: float = PERIODO_S,
                 espera_fuera_s: float = ESPERA_FUERA_S,
                 esperas_relanzar: Optional[Sequence[float]] = None,
                 estable_s: float = ESTABLE_S,
                 colgado_s: Optional[float] = None,
                 arranque_max_s: float = ARRANQUE_MAX_S,
                 espera_latido_vigilante_s: float = ESPERA_LATIDO_VIGILANTE_S,
                 espera_parada_s: float = ESPERA_PARADA_S,
                 gracia_peticion_s: float = GRACIA_PETICION_S,
                 das_aviso_cada_s: float = float(DAS_AVISO_CADA_S),
                 espera_avisos_s: float = ESPERA_AVISOS_S) -> None:
        for nombre in ("mono", "ahora", "epoch"):
            if not callable(getattr(reloj, nombre, None)):
                raise TypeError(f"reloj debe tener {nombre}()")
        for nombre in ("poner", "arrancar", "parar"):
            if not callable(getattr(avisos, nombre, None)):
                raise TypeError(f"avisos debe tener {nombre}()")
        if not isinstance(diario, Diario):
            raise TypeError("diario debe ser un diario.Diario")
        if not isinstance(python, str) or not python.strip():
            raise ValueError("python debe ser la ruta del intérprete")
        if not callable(popen):
            raise TypeError("popen debe ser llamable (subprocess.Popen)")
        for nombre, fn in (("argv_hijo", argv_hijo), ("hay_sesion", hay_sesion), ("media_sesion", media_sesion),
                           ("das_vivo", das_vivo), ("sonda_das", sonda_das), ("libre_gb", libre_gb),
                           ("pid_vivo_fn", pid_vivo_fn), ("matar_pid_fn", matar_pid_fn)):
            if fn is not None and not callable(fn):
                raise TypeError(f"{nombre} debe ser llamable")
        for nombre, valor, minimo_cero in (("periodo_s", periodo_s, False), ("espera_fuera_s", espera_fuera_s, False),
                                           ("arranque_max_s", arranque_max_s, False),
                                           ("espera_latido_vigilante_s", espera_latido_vigilante_s, True),
                                           ("espera_parada_s", espera_parada_s, True),
                                           ("gracia_peticion_s", gracia_peticion_s, True),
                                           ("das_aviso_cada_s", das_aviso_cada_s, False),
                                           ("espera_avisos_s", espera_avisos_s, True)):
            if not _numero_valido(valor, admite_cero=minimo_cero):
                raise ValueError(f"{nombre} debe ser un número finito {'≥' if minimo_cero else '>'} 0: {valor!r}")
        if colgado_s is not None and not _numero_valido(colgado_s, admite_cero=False):
            raise ValueError(f"colgado_s debe ser un número finito > 0: {colgado_s!r}")
        self._cfg_ruta = Path(cfg_ruta)
        self._reloj = reloj
        self._avisos = avisos
        self._python = python
        self._cwd = Path(cwd)
        self._das_exe = Path(das_exe) if das_exe is not None else None
        self._ruta_estado = Path(ruta_estado)
        self._diario = diario
        self._cuenta_das = cuenta_das
        self._argv_hijo = argv_hijo
        self._popen = popen
        self._hay_sesion = hay_sesion
        self._media_sesion = media_sesion
        self._das_vivo = das_vivo
        self._sonda_das = sonda_das if sonda_das is not None else sonda_puerto_das
        self._libre_gb = libre_gb if libre_gb is not None else (lambda: disco_libre_gb(self._ruta_estado))
        self._pid_vivo = pid_vivo_fn if pid_vivo_fn is not None else pid_vivo
        self._matar_pid = matar_pid_fn if matar_pid_fn is not None else matar_pid
        self._periodo_s = float(periodo_s)
        self._espera_fuera_s = float(espera_fuera_s)
        self._esperas_forzadas = tuple(esperas_relanzar) if esperas_relanzar is not None else None
        self._estable_s = float(estable_s)
        self._colgado_forzado = float(colgado_s) if colgado_s is not None else None
        self._arranque_max_s = float(arranque_max_s)
        self._espera_latido_vigilante_s = float(espera_latido_vigilante_s)
        self._espera_parada_s = float(espera_parada_s)
        self._gracia_peticion_s = float(gracia_peticion_s)
        self._das_aviso_cada_s = float(das_aviso_cada_s)
        self._espera_avisos_s = float(espera_avisos_s)
        PlanRelanzamiento(self._esperas_forzadas if self._esperas_forzadas is not None else RELANZAR_S,
                          self._estable_s)                                    # valida ya (ValueError)

        self._cerrojo = CerrojoInstancia(self._ruta_estado / NOMBRE_CERROJO)
        self._cfg: Optional[Config] = None
        self._firma_cfg: Optional[tuple] = None
        self._ventanas: dict[date, tuple[Optional[datetime], Optional[datetime]]] = {}
        self._hijos: dict[str, EstadoHijo] = {}
        self._arrancado = False
        self._parado = False
        self._codigo: Optional[int] = None
        self._motivo_parada = ""
        self._despertar = threading.Event()
        self._cerrojo_estado = threading.Lock()
        self._dia: Optional[date] = None
        self._orden_offset = 0
        self._das_listo_hoy = False
        self._das_lanzado_en: Optional[float] = None
        self._das_aviso_en: Optional[float] = None
        self._sonda_en: Optional[float] = None
        self._sonda_sin_puerto_anotada = False
        self._disco_mirado_en: Optional[float] = None
        self._disco_aviso_en: Optional[float] = None
        self._apagado_hecho = False
        self._posicion_avisada = False
        self._prorroga = False                          # G2-01: fuera de la ventana con posición, los hijos siguen
        self._estuvo_dentro = False                     # R2-PRO-1: hubo ventana y aún no se hizo el apagado de su fin
        self._sending_visto: dict[str, float] = {}      # R2-PRO-2: orden SENDING sin id de DAS → mono de la 1.ª vez
        self._huerfanas_avisadas: set[str] = set()      # R2-PRO-2: huérfanas ya anotadas y avisadas
        self._firma_al_parar: dict[str, Optional[tuple]] = {}   # G2-08: firma del fichero del cuadro al dejar un hijo
        self._das_vigilado_en: Optional[float] = None   # G2-03: última mirada al proceso DAS
        self._das_caido_desde: Optional[float] = None
        self._das_login_pendiente = False
        self._dentro_anterior: Optional[bool] = None
        self._vigilante_lanzado_mono: Optional[float] = None
        self._pasadas = 0

    # ── propiedades (lectura) ─────────────────────────────────────────
    @property
    def cfg(self) -> Optional[Config]:
        return self._cfg

    @property
    def codigo(self) -> Optional[int]:
        return self._codigo

    @property
    def pasadas(self) -> int:
        return self._pasadas

    @property
    def ruta_orden_supervisor(self) -> Path:
        return self._ruta_estado / NOMBRE_ORDEN_SUPERVISOR

    @property
    def ruta_foto(self) -> Path:
        return self._ruta_estado / NOMBRE_FOTO

    @property
    def das_listo_hoy(self) -> bool:
        return self._das_listo_hoy

    @property
    def hijos(self) -> dict[str, EstadoHijo]:
        """El estado de cada hijo (el objeto vivo: los tests leen `proceso`, `relanzar_en`, …; no mutarlo)."""
        return dict(self._hijos)

    def hijo(self, nombre: str) -> EstadoHijo:
        """El estado del hijo `nombre` ∈ HIJOS (KeyError si no existe)."""
        return self._hijos[nombre]

    @property
    def colgado_s(self) -> float:
        """R-J-04 v2: latido más viejo que esto ⇒ colgado (config `tecnicos.vigilante.colgado_s`, 3 s)."""
        if self._colgado_forzado is not None:
            return self._colgado_forzado
        return _numero_positivo(self._vigilante_cfg().get("colgado_s"), COLGADO_S)

    @property
    def disco_min_gb(self) -> float:
        """R-J-07: aviso por debajo de esto (config `tecnicos.disco_min_gb`, 5)."""
        tecnicos = self._cfg.tecnicos if self._cfg is not None else {}
        return _numero_positivo(tecnicos.get("disco_min_gb") if isinstance(tecnicos, dict) else None,
                                float(DISCO_MIN_GB))

    # ── configuración y ventana (R-L-01) ───────────────────────────────
    def _vigilante_cfg(self) -> dict:
        if self._cfg is None or not isinstance(self._cfg.tecnicos, dict):
            return {}
        bloque = self._cfg.tecnicos.get("vigilante")
        return bloque if isinstance(bloque, dict) else {}

    def _esperas_relanzar(self) -> tuple[float, ...]:
        if self._esperas_forzadas is not None:
            return tuple(float(e) for e in self._esperas_forzadas)
        crudas = self._vigilante_cfg().get("relanzar_s")
        if isinstance(crudas, list) and crudas and all(_numero_valido(e, admite_cero=True) for e in crudas):
            return tuple(float(e) for e in crudas)
        return RELANZAR_S

    def recargar_config(self) -> Optional[Config]:
        """Lee la config del cuadro si cambió (H-4): `cfg_ruta` o, si no valida, su `ultimo_bueno.json`; sin escribir nada.

        El supervisor no guarda el último bueno (eso es del ejecutor): dos
        procesos escribiendo el mismo fichero no aportan nada. Sin config
        legible devuelve None y la ventana usa los defectos (03:55 → 20:00).
        """
        firma = (_firma_fichero(self._cfg_ruta), _firma_fichero(self._ultimo_bueno()))
        if self._firma_cfg is not None and firma == self._firma_cfg:
            return self._cfg
        self._firma_cfg = firma
        self._ventanas.clear()
        cuenta = (self._cuenta_das if self._cuenta_das is not None
                  else os.environ.get(ENV_CUENTA, "").strip()) or CUENTA_SOLO_LECTURA
        try:
            self._cfg = mod_config.cargar(self._cfg_ruta, cuenta)
            self._diario.anotar("config", config_version=self._cfg.config_version, sha256=self._cfg.sha256,
                                ruta=str(self._cfg_ruta))
            return self._cfg
        except mod_config.ConfigInvalida as exc1:
            errores_fichero = list(exc1.errores)
        errores = "; ".join(errores_fichero[:3])
        try:
            self._cfg = mod_config.cargar(self._ultimo_bueno(), cuenta)
        except mod_config.ConfigInvalida as exc2:
            self._cfg = None
            self._diario.anotar("config_invalida", errores=errores_fichero[:10] + list(exc2.errores[:10]),
                                regla="H-4")
            self._avisar(Nivel.MAXIMO, f"Supervisor: no hay config válida ({errores}); ventana por defecto "
                                       f"{HORA_ENCENDER_DEFECTO}-{HORA_APAGAR_SIN_CONFIG} y los hijos no arrancarán "
                                       f"(H-4)", "supervisor_config")
            return None
        self._diario.anotar("config", config_version=self._cfg.config_version, sha256=self._cfg.sha256,
                            ruta=str(self._ultimo_bueno()), respaldo=True)
        self._avisar(Nivel.AVISO, f"Supervisor: config del cuadro inválida ({errores}); se usa el último bueno "
                                  f"(config_version {self._cfg.config_version}) (H-4)", "supervisor_config")
        return self._cfg

    def _ultimo_bueno(self) -> Path:
        return self._cfg_ruta.parent / mod_config.NOMBRE_ULTIMO_BUENO

    def ventana(self, hoy: date) -> tuple[Optional[datetime], Optional[datetime]]:
        """R-L-01 (F10/F12): (encender, apagar) de `hoy`, aware en ET; (None, None) si hoy no hay mercado.

        encender = `horario.encender` (03:55). apagar = `horario.apagar` si
        está; si no, el último EOD de las estrategias de la config (todas: el
        apagado nunca se ADELANTA por una estrategia desactivada con lote
        vivo; la posición a esa hora la cubre la foto) recortado a las 13:00
        en media sesión (`media_sesion`), más el margen de R-D-02
        (`salidas.eod.comprobar_despues_s`, 30 s). Sin estrategias, 16:00 +
        margen; sin config, 20:00. Sin sesión (`hay_sesion`: fin de semana o
        festivo) → (None, None). Si la hora de apagar no es posterior a la de
        encender (config imposible), se apaga a las 20:00: una ventana vacía
        dejaría una posición sin gestionar.
        """
        if hoy in self._ventanas:
            return self._ventanas[hoy]
        if not self._sesion(hoy):
            self._ventanas[hoy] = (None, None)
            return None, None
        cfg = self._cfg
        horario = cfg.horario if cfg is not None and isinstance(cfg.horario, dict) else {}
        inicio = _hora_o(horario.get("encender"), hoy, HORA_ENCENDER_DEFECTO)
        if cfg is None:
            fin = a_hora_et(HORA_APAGAR_SIN_CONFIG, hoy)
        elif isinstance(horario.get("apagar"), str) and horario.get("apagar"):
            fin = _hora_o(horario.get("apagar"), hoy, HORA_APAGAR_SIN_CONFIG)
        else:
            eod = salidas.ultimo_eod(cfg.estrategias.values(), hoy) or a_hora_et(EOD_SIN_ESTRATEGIAS, hoy)
            if self._media(hoy):
                eod = min(eod, a_hora_et(CIERRE_MEDIA_SESION, hoy))
            fin = eod + timedelta(seconds=self._margen_eod_s(cfg))
        if fin <= inicio:
            self._diario.anotar("ventana_imposible", encender=inicio, apagar=fin, regla="R-L-01")
            fin = max(a_hora_et(HORA_APAGAR_SIN_CONFIG, hoy), inicio + timedelta(minutes=1))
        self._ventanas[hoy] = (inicio, fin)
        return inicio, fin

    @staticmethod
    def _margen_eod_s(cfg: Config) -> float:
        eod = (cfg.salidas or {}).get("eod") if isinstance(cfg.salidas, dict) else None
        valor = eod.get("comprobar_despues_s") if isinstance(eod, dict) else None
        return _numero_positivo(valor, float(EOD_COMPROBAR_DESPUES_S))

    def _sesion(self, dia: date) -> bool:
        """`hay_sesion` del calendario (inyectado o `bot_alerts_calendario`, perezoso). Si falla, se supone sesión."""
        fn = self._hay_sesion
        try:
            if fn is None:
                from app.services import bot_alerts_calendario   # perezoso: solo al calcular una ventana
                fn = bot_alerts_calendario.hay_sesion
            return bool(fn(dia))
        except Exception as exc:  # noqa: BLE001 — frontera (calendario de otro paquete): encendido es lo conservador
            self._diario.anotar("calendario_fallo", dia=dia, error=f"{type(exc).__name__}: {exc}", regla="R-L-01")
            return dia.weekday() < 5

    def _media(self, dia: date) -> bool:
        fn = self._media_sesion
        try:
            if fn is None:
                from app.services import bot_alerts_calendario
                fn = bot_alerts_calendario.media_sesion
            return fn(dia) is not None
        except Exception as exc:  # noqa: BLE001 — frontera (calendario): sin saberlo, día entero (apagar más tarde)
            self._diario.anotar("calendario_fallo", dia=dia, error=f"{type(exc).__name__}: {exc}", regla="F10/F12")
            return False

    # ── ciclo de vida ─────────────────────────────────────────────────
    def arrancar(self) -> int:
        """§6.2.1: avisos → cerrojo (R-J-04 c) → diario → config → huérfanos (riesgo 26). Devuelve 0 o 3.

        Con el cerrojo tomado por otro supervisor: aviso 3 y 3, sin tocar el
        diario ni a los hijos (son de la instancia viva). Una segunda llamada
        lanza RuntimeError.
        """
        if self._arrancado:
            raise RuntimeError("arrancar() solo se llama una vez")
        self._arrancado = True
        self._avisos.arrancar()
        if not self._cerrojo.adquirir():
            logger.error("[SUPERVISOR] otro supervisor tiene el cerrojo %s: no arranco (R-J-04 c)",
                         self._cerrojo.ruta)
            self._poner_aviso(Nivel.MAXIMO, "Supervisor: ya hay otro supervisor en marcha; este NO arranca "
                                            "(R-J-04 c)", "arranque:doble_instancia")
            self._codigo = CODIGO_DOBLE_INSTANCIA
            return CODIGO_DOBLE_INSTANCIA
        self._ruta_estado.mkdir(parents=True, exist_ok=True)
        hoy = self._reloj.ahora().astimezone(ET).date()
        self._dia = hoy
        self._diario.abrir_dia(hoy)
        self.recargar_config()
        self._hijos = {n: EstadoHijo(n, PlanRelanzamiento(self._esperas_relanzar(), self._estable_s)) for n in HIJOS}
        self._orden_offset = _tamano_fichero(self.ruta_orden_supervisor)
        self._revisar_huerfanos()
        self._diario.anotar("supervisor_listo", pid=os.getpid(), python=self._python, cwd=str(self._cwd),
                            das_exe=str(self._das_exe) if self._das_exe is not None else None)
        return CODIGO_OK

    def correr(self) -> int:
        """Bucle: `paso()` cada `periodo_s` (dentro de la ventana) o hasta `espera_fuera_s` (fuera), hasta tener código."""
        if not self._arrancado:
            codigo = self.arrancar()
            if codigo != CODIGO_OK:
                return codigo
        while self._codigo is None:
            espera = self.paso()
            if self._codigo is None and espera is not None:
                self._despertar.wait(espera)
                self._despertar.clear()
        return self._codigo

    def pedir_parada(self, motivo: str = "parada pedida", codigo: int = CODIGO_OK) -> None:
        """Pide salir del bucle (segura desde cualquier hilo o un manejador de señal)."""
        with self._cerrojo_estado:
            if self._codigo is None:
                self._codigo = int(codigo)
                self._motivo_parada = str(motivo)
        self._despertar.set()

    def parar(self) -> None:
        """Cierre ordenado del SUPERVISOR: los hijos siguen (riesgo 26). Idempotente; nunca lanza."""
        if self._parado:
            return
        self._parado = True
        try:
            vivos = [h.nombre for h in self._hijos.values() if h.corriendo]
            if self._cerrojo.tomado:
                self._diario.anotar("supervisor_parado", motivo=self._motivo_parada or "parar()",
                                    hijos_que_siguen=vivos, regla="riesgo 26")
        except Exception:  # noqa: BLE001 — frontera: parar nunca lanza
            logger.exception("[SUPERVISOR] fallo al anotar la parada")
        for paso_cierre in (lambda: self._avisos.parar(self._espera_avisos_s), self._diario.cerrar,
                            self._cerrojo.soltar):
            try:
                paso_cierre()
            except Exception:  # noqa: BLE001 — frontera: un paso del cierre que falla no impide los demás
                logger.exception("[SUPERVISOR] fallo en el cierre")

    # ── una vuelta del bucle ──────────────────────────────────────────
    def paso(self) -> Optional[float]:
        """Una vuelta (§3.27). Devuelve cuánto esperar hasta la siguiente (None si hay código). Nunca lanza.

        Orden: día nuevo → config → peticiones de los hijos → disco → dentro
        de la ventana: hijos muertos/colgados, DAS, vigilante, ejecutor;
        fuera: apagado ordenado.
        """
        if not self._arrancado:
            raise RuntimeError("paso() antes de arrancar()")
        if self._codigo is not None:
            return None
        self._pasadas += 1
        try:
            return self._paso()
        except Exception as exc:  # noqa: BLE001 — frontera del proceso: el supervisor no puede morir por un fallo suyo
            logger.exception("[SUPERVISOR] excepción en la vuelta")
            self._diario.anotar("excepcion", donde="supervisor.paso", error=f"{type(exc).__name__}: {exc}")
            self._avisar(Nivel.AVISO, f"Supervisor: excepción en el bucle ({type(exc).__name__}: {exc})",
                         "excepcion_supervisor")
            return self._periodo_s

    def _paso(self) -> float:
        ahora_et = self._reloj.ahora().astimezone(ET)
        hoy = ahora_et.date()
        if hoy != self._dia:
            self._dia_nuevo(hoy)
        self.recargar_config()
        self._reintentar_si_config_cambia()
        self._revisar_peticiones()
        self._revisar_disco()
        inicio, fin = self.ventana(hoy)
        dentro = inicio is not None and fin is not None and inicio <= ahora_et < fin
        if dentro != self._dentro_anterior:
            self._dentro_anterior = dentro
            self._diario.anotar("ventana", dentro=dentro, encender=inicio, apagar=fin, regla="R-L-01")
        if dentro:
            self._prorroga = False
            self._estuvo_dentro = True
            self._vigilar_hijos(apagando=False)
            self._apagado_hecho = False
            self._posicion_avisada = False
            self._gestionar_dentro()
            return self._periodo_s
        # G2-01 (L4 / R-D-02): fuera de la ventana con posición u órdenes vivas los hijos SIGUEN al mando: se vigilan
        # colgados y se relanzan como dentro (sin esperar a DAS); solo se apaga cuando la foto dice que no queda nada.
        prorroga = self._en_prorroga()
        self._vigilar_hijos(apagando=not prorroga)
        if prorroga:
            self._gestionar_prorroga()
            return self._periodo_s
        self._apagar_fuera()
        if any(h.corriendo for h in self._hijos.values()):
            return self._periodo_s
        if inicio is not None and ahora_et < inicio:
            return max(min(self._espera_fuera_s, (inicio - ahora_et).total_seconds()), self._periodo_s)
        return self._espera_fuera_s

    def _en_prorroga(self) -> bool:
        """G2-01: fuera de la ventana, ¿siguen los hijos al mando? Sí mientras la foto diga posición/órdenes vivas (o no se
        pueda leer) y el bot estuviera en marcha (algún hijo corriendo o ya en prórroga). Avisa 3 UNA vez por episodio.

        R2-PRO-1: también en el FIN de una ventana que este supervisor vivió
        aunque en ese momento no corra ningún hijo (los dos murieron o esperan
        su relanzamiento): con posición o foto ilegible NO se marca el apagado,
        se avisa 3 una vez y `_gestionar_prorroga` relanza vigilante y
        ejecutor para que la gestionen. Un supervisor que arranca de noche sin
        haber visto la ventana no lanza nada por una foto vieja.
        """
        if not any(h.corriendo for h in self._hijos.values()) and not self._prorroga \
                and not (self._estuvo_dentro and not self._apagado_hecho):
            return False
        posicion = self.hay_posicion()
        if posicion is False:
            if self._prorroga:
                self._prorroga = False
                self._diario.anotar("prorroga_fin", regla="L4 / G2-01")
            return False
        if not self._posicion_avisada:
            self._posicion_avisada = True
            que = "hay posición abierta u órdenes vivas" if posicion else "no puedo leer la foto del ejecutor"
            self._diario.anotar("apagado_con_posicion", posicion=posicion, regla="L4 / R-D-02")
            self._avisar(Nivel.MAXIMO, f"Supervisor: fin de la ventana y {que}: NO apago el bot (sin posiciones "
                                       f"overnight, L4): sigo vigilando y relanzando vigilante y ejecutor hasta que no "
                                       f"quede nada; CONTROL HUMANO", "apagado_con_posicion")
        self._prorroga = True
        return True

    def _gestionar_prorroga(self) -> None:
        """G2-01: como dentro de la ventana pero SIN esperar a DAS: relanza por plan al hijo muerto (vigilante primero)."""
        self._vigilar_das()
        if self._cfg is None:
            return
        ahora = self._reloj.mono()
        vigilante, ejecutor = self._hijos["vigilante"], self._hijos["ejecutor"]
        if self._puede_lanzar(vigilante, ahora):
            if self._lanzar_hijo(vigilante):
                self._vigilante_lanzado_mono = ahora
        if self._puede_lanzar(ejecutor, ahora) and self._vigilante_permite_ejecutor(ahora):
            self._lanzar_hijo(ejecutor)

    def _vigilar_das(self) -> None:
        """G2-03 (R-J-02 (2), EP-7): cada `DAS_VIGILAR_CADA_S` se mira que la aplicación DAS viva (tasklist).

        Si falta, se abre (`_lanzar_das`, aviso 3 «LOGIN/2FA a mano»; como mucho
        cada `das_aviso_cada_s`, 5 min) y, hasta que su API vuelva a aceptar
        (sonda del puerto), se repite el aviso 3 cada 5 min. Sin `DAS_EXE` no se
        puede relanzar: no se hace nada (los hijos llevan su reconexión).
        """
        if self._das_exe is None:
            return
        ahora = self._reloj.mono()
        if self._das_vigilado_en is not None and ahora - self._das_vigilado_en < DAS_VIGILAR_CADA_S:
            return
        self._das_vigilado_en = ahora
        vivo = self._das_vivo() if self._das_vivo is not None else das_en_tasklist(self._das_exe.name)
        if vivo is False:
            if self._das_caido_desde is None:
                self._das_caido_desde = ahora
                self._diario.anotar("das_caido", exe=str(self._das_exe), regla="R-J-02 / G2-03")
            if self._das_lanzado_en is None or ahora - self._das_lanzado_en >= self._das_aviso_cada_s:
                self._lanzar_das(ahora)
                self._das_login_pendiente = True
            return
        if self._das_caido_desde is not None:
            self._das_caido_desde = None
            self._diario.anotar("das_proceso_vuelve", regla="R-J-02 / G2-03")
        if not self._das_login_pendiente:
            return
        try:
            acepta = self._sonda_das()
        except Exception as exc:  # noqa: BLE001 — frontera (sonda inyectada o de red): no se sabe → se reintenta
            self._diario.anotar("sonda_das_fallo", error=f"{type(exc).__name__}: {exc}")
            return
        if acepta is not False:
            self._das_login_pendiente = False
            self._diario.anotar("das_listo", tras="relanzamiento", regla="G2-03")
            self._avisar(Nivel.INFO, "Supervisor: DAS vuelve a aceptar conexiones del API (G2-03)", "das_listo")
            return
        if self._das_aviso_en is None or ahora - self._das_aviso_en >= self._das_aviso_cada_s:
            self._das_aviso_en = ahora
            self._diario.anotar("das_sin_api", tras="relanzamiento", regla="EP-7 / G2-03")
            self._avisar(Nivel.MAXIMO, "Supervisor: DAS se cerró a media sesión y lo he abierto, pero su API no "
                                       "responde: haz el LOGIN/2FA A MANO (EP-7)", "das_sin_api")

    def _reintentar_si_config_cambia(self) -> None:
        """G2-08: un hijo dejado por código 4/5 se vuelve a lanzar UNA vez cuando cambia el fichero del cuadro.

        Se mira solo el fichero PRINCIPAL (el ejecutor reescribe el último bueno
        en cada arranque: mirarlo daría un bucle de relanzamientos).
        """
        for h in self._hijos.values():
            if h.parado_por_codigo not in CODIGOS_SIN_RELANZAR:
                continue
            firma = _firma_fichero(self._cfg_ruta)
            if firma == self._firma_al_parar.get(h.nombre):
                continue
            codigo = h.parado_por_codigo
            h.parado_a_mano = False
            h.parado_por_codigo = None
            h.relanzar_en = None
            self._firma_al_parar.pop(h.nombre, None)
            self._diario.anotar("hijo_reintento_config", hijo=h.nombre, codigo_anterior=codigo, regla="G2-08")
            self._avisar(Nivel.INFO, f"Supervisor: la config del cuadro cambió: vuelvo a lanzar el {h.nombre} (había "
                                     f"salido con código {codigo})", f"hijo_reintento_config:{h.nombre}")

    def _dia_nuevo(self, hoy: date) -> None:
        """Día nuevo: diario del día, planes a cero, DAS por comprobar y los «parados a mano» vuelven a poder arrancar."""
        self._dia = hoy
        self._diario.abrir_dia(hoy)
        self._diario.anotar("dia_nuevo", dia=hoy)
        self._das_listo_hoy = False
        self._das_aviso_en = None
        self._dentro_anterior = None
        self._ventanas = {d: v for d, v in self._ventanas.items() if d >= hoy}
        for h in self._hijos.values():
            h.plan.reiniciar()
            h.parado_a_mano = False
            h.parado_por_codigo = None
            h.salidas_reloj = 0
        self._firma_al_parar.clear()
        self._huerfanas_avisadas.clear()                 # R2-PRO-2: los tokens llevan el día; se avisa de nuevo

    # ── dentro de la ventana ──────────────────────────────────────────
    def _gestionar_dentro(self) -> None:
        """§6.2.2-3: DAS listo → vigilante → (latido del vigilante o 10 s) → ejecutor. G2-03: DAS vigilado toda la ventana."""
        if not self._das_listo_hoy and not self._asegurar_das():
            return
        self._vigilar_das()
        if self._cfg is None:
            return                                   # H-4: sin config los hijos saldrían con código 5 en bucle
        ahora = self._reloj.mono()
        vigilante, ejecutor = self._hijos["vigilante"], self._hijos["ejecutor"]
        if self._puede_lanzar(vigilante, ahora):
            if self._lanzar_hijo(vigilante):
                self._vigilante_lanzado_mono = ahora
        if self._puede_lanzar(ejecutor, ahora) and self._vigilante_permite_ejecutor(ahora):
            self._lanzar_hijo(ejecutor)

    @staticmethod
    def _puede_lanzar(h: EstadoHijo, ahora: float) -> bool:
        return not h.corriendo and not h.parado_a_mano and (h.relanzar_en is None or ahora >= h.relanzar_en)

    def _vigilante_permite_ejecutor(self, ahora: float) -> bool:
        """§6.2.3: el ejecutor sale cuando el vigilante ya late o, como mucho, `espera_latido_vigilante_s` después."""
        vigilante = self._hijos["vigilante"]
        if vigilante.parado_a_mano:
            return True
        if vigilante.corriendo and self._latio_desde_lanzamiento(vigilante):
            return True
        return self._vigilante_lanzado_mono is not None and \
            (ahora - self._vigilante_lanzado_mono) >= self._espera_latido_vigilante_s

    def _asegurar_das(self) -> bool:
        """EP-7 / §6.2.2: DAS abierto (tasklist; si falta y hay DAS_EXE, se abre) y su puerto del API aceptando."""
        ahora = self._reloj.mono()
        if self._das_exe is not None:
            vivo = self._das_vivo() if self._das_vivo is not None else das_en_tasklist(self._das_exe.name)
            self._das_vigilado_en = ahora                   # G2-03: la vigilancia periódica cuenta desde aquí
            if vivo is False and (self._das_lanzado_en is None
                                  or ahora - self._das_lanzado_en >= self._das_aviso_cada_s):
                self._lanzar_das(ahora)
        if self._sonda_en is not None and ahora - self._sonda_en < SONDA_DAS_CADA_S:
            return False
        self._sonda_en = ahora
        try:
            acepta = self._sonda_das()
        except Exception as exc:  # noqa: BLE001 — frontera (sonda inyectada o de red): no se sabe → se trata como «sin sonda»
            self._diario.anotar("sonda_das_fallo", error=f"{type(exc).__name__}: {exc}")
            acepta = None
        if acepta is None:
            if not self._sonda_sin_puerto_anotada:
                self._sonda_sin_puerto_anotada = True
                self._diario.anotar("das_sin_sonda", motivo=f"sin {ENV_PUERTO} en el entorno: no se espera al puerto",
                                    regla="§6.2.2")
            self._das_listo_hoy = True
            return True
        if acepta:
            self._das_listo_hoy = True
            self._diario.anotar("das_listo", regla="§6.2.2")
            if self._das_aviso_en is not None:
                self._avisar(Nivel.INFO, "Supervisor: DAS ya acepta conexiones del API; arrancan vigilante y ejecutor",
                             "das_listo")
            self._das_aviso_en = None
            return True
        if self._das_aviso_en is None or ahora - self._das_aviso_en >= self._das_aviso_cada_s:
            self._das_aviso_en = ahora
            self._diario.anotar("das_sin_api", regla="EP-7")
            self._avisar(Nivel.MAXIMO, "Supervisor: DAS no acepta conexiones del API: ¿falta el LOGIN/2FA a mano? "
                                       "No arranco vigilante ni ejecutor hasta que responda (EP-7)", "das_sin_api")
        return False

    def _lanzar_das(self, ahora: float) -> None:
        exe = self._das_exe
        if exe is None:
            return
        self._das_lanzado_en = ahora
        try:
            self._popen([str(exe)], cwd=str(exe.parent), stdin=subprocess.DEVNULL,
                        creationflags=_flags_grupo_nuevo())
        except (OSError, ValueError) as exc:   # frontera del SO: DAS no se pudo abrir; lo hará una persona
            self._diario.anotar("das_lanzar_fallo", exe=str(exe), error=f"{type(exc).__name__}: {exc}", regla="EP-7")
            self._avisar(Nivel.MAXIMO, f"Supervisor: DAS no está abierto y no se pudo abrir ({type(exc).__name__}): "
                                       f"ábrelo y haz el LOGIN/2FA a mano (EP-7)", "das_lanzar")
            return
        self._diario.anotar("das_lanzado", exe=str(exe), regla="EP-7")
        self._avisar(Nivel.MAXIMO, "Supervisor: DAS no estaba abierto y lo he abierto: haz el LOGIN/2FA A MANO (EP-7)",
                     "das_lanzado")

    # ── lanzar un hijo ────────────────────────────────────────────────
    def lanzar(self, modulo: str) -> Any:
        """§3.27: `Popen([python, "-m", "app.bot_das.<modulo>"], cwd=backend, CREATE_NEW_PROCESS_GROUP)`, entorno heredado.

        El `.env` lo carga cada hijo (`main`). `argv_hijo` (tests) sustituye
        la línea de órdenes. Lanza OSError/ValueError si el SO no puede.
        """
        if modulo not in HIJOS:
            raise ValueError(f"módulo desconocido: {modulo!r} (esperado uno de {HIJOS})")
        argv = list(self._argv_hijo(modulo)) if self._argv_hijo is not None else \
            [self._python, "-m", f"app.bot_das.{modulo}"]
        return self._popen(argv, cwd=str(self._cwd), stdin=subprocess.DEVNULL, creationflags=_flags_grupo_nuevo())

    def _lanzar_hijo(self, h: EstadoHijo) -> bool:
        try:
            proceso = self.lanzar(h.nombre)
        except (OSError, ValueError) as exc:   # frontera del SO: se reintenta con el plan
            espera = h.plan.siguiente(self._reloj.mono(), None)
            h.relanzar_en = self._reloj.mono() + espera
            h.ultima_espera = espera
            self._diario.anotar("lanzar_fallido", hijo=h.nombre, error=f"{type(exc).__name__}: {exc}",
                                espera_s=espera)
            self._avisar(Nivel.MAXIMO, f"Supervisor: no se pudo lanzar el {h.nombre} ({type(exc).__name__}: {exc}); "
                                       f"reintento en {espera:g} s", f"lanzar_fallido:{h.nombre}")
            return False
        h.proceso = proceso
        h.pid = getattr(proceso, "pid", None)
        h.adoptado = False
        h.lanzado_mono = self._reloj.mono()
        h.lanzado_epoch = float(self._reloj.epoch())
        h.relanzar_en = None
        h.parada_pedida = False
        h.lanzamientos += 1
        self._diario.anotar("hijo_lanzado", hijo=h.nombre, pid=h.pid, lanzamiento=h.lanzamientos,
                            intento_plan=h.plan.intentos, regla="R-J-06")
        logger.info("[SUPERVISOR] %s lanzado (pid %s, lanzamiento %d)", h.nombre, h.pid, h.lanzamientos)
        return True

    # ── vigilar a los hijos (R-J-04 v2) ───────────────────────────────
    def _vigilar_hijos(self, apagando: bool) -> None:
        for h in self._hijos.values():
            if not h.corriendo:
                continue
            codigo = self._codigo_de_salida(h)
            if codigo is not _SIGUE_VIVO:
                self._al_morir(h, codigo)
                continue
            if apagando:
                continue
            motivo = self._motivo_colgado(h)
            if motivo is not None:
                self._matar(h)
                espera = self._programar_relanzamiento(h)
                self._diario.anotar("hijo_colgado", hijo=h.nombre, pid=h.pid, motivo=motivo, espera_s=espera,
                                    regla="R-J-04 b")
                self._avisar(Nivel.MAXIMO, f"Supervisor: el {h.nombre} está colgado ({motivo}): lo mato y lo "
                                           f"relanzo en {espera:g} s (R-J-04 b)", f"hijo_colgado:{h.nombre}")

    def _codigo_de_salida(self, h: EstadoHijo) -> Any:
        """Código de salida si el hijo terminó (None = desconocido, p. ej. un adoptado); `_SIGUE_VIVO` si vive."""
        if h.proceso is not None:
            codigo = h.proceso.poll()
            return _SIGUE_VIVO if codigo is None else codigo
        if h.adoptado and h.pid is not None and self._pid_vivo(h.pid):
            return _SIGUE_VIVO
        return None

    def _al_morir(self, h: EstadoHijo, codigo: Optional[int]) -> None:
        """R-J-04 a: muerto → relanzar por plan y avisar; pedida → nada; código 0 sin pedirla → parado a mano."""
        h.proceso, h.adoptado = None, False
        h.ultimo_codigo = codigo
        texto_codigo = SIGNIFICADO_CODIGO.get(codigo, "desconocido") if codigo is not None else "desconocido"
        if h.parada_pedida:
            h.parada_pedida = False
            self._diario.anotar("hijo_parado", hijo=h.nombre, pid=h.pid, codigo=codigo, regla="R-L-01")
            return
        if codigo == CODIGO_OK:
            h.parado_a_mano = True
            self._diario.anotar("hijo_parado_a_mano", hijo=h.nombre, pid=h.pid, codigo=codigo, regla="R-J-04")
            self._avisar(Nivel.MAXIMO if h.nombre == "ejecutor" else Nivel.AVISO,
                         f"Supervisor: el {h.nombre} se ha parado de forma ordenada sin que yo lo pidiera: NO lo "
                         f"relanzo hoy (control humano)", f"hijo_parado_a_mano:{h.nombre}")
            return
        h.salidas_reloj = h.salidas_reloj + 1 if codigo == 2 else 0
        if codigo in CODIGOS_SIN_RELANZAR or (codigo == 2 and h.salidas_reloj >= RELOJ_RELANZOS_MAX):
            # G2-08: «relanzar no lo arregla» (motor distinto, config/entorno imposibles, reloj que no se corrige):
            # relanzarlo cada 10 s solo daría un aviso 3 cada 10 s todo el día → control humano
            h.parado_a_mano = True
            h.parado_por_codigo = codigo
            self._firma_al_parar[h.nombre] = _firma_fichero(self._cfg_ruta)
            cuando ="si cambias la config lo reintento; si no, mañana" if codigo in CODIGOS_SIN_RELANZAR else \
                "sincroniza la hora; mañana lo relanzo (o relanza el supervisor)"
            self._diario.anotar("hijo_no_relanzable", hijo=h.nombre, pid=h.pid, codigo=codigo, significado=texto_codigo,
                                salidas_reloj=h.salidas_reloj, regla="R-J-04 a / G2-08")
            self._avisar(Nivel.MAXIMO, f"Supervisor: el {h.nombre} ha salido con código {codigo} ({texto_codigo}): "
                                       f"relanzarlo no lo arregla y NO lo relanzo: CONTROL HUMANO ({cuando})",
                         f"hijo_no_relanzable:{h.nombre}")
            return
        espera = self._programar_relanzamiento(h)
        self._diario.anotar("hijo_muerto", hijo=h.nombre, pid=h.pid, codigo=codigo, significado=texto_codigo,
                            espera_s=espera, intento_plan=h.plan.intentos, regla="R-J-04 a")
        self._avisar(Nivel.MAXIMO if h.nombre == "ejecutor" else Nivel.AVISO,
                     f"Supervisor: el {h.nombre} ha muerto (código {codigo}: {texto_codigo}); lo relanzo en "
                     f"{espera:g} s (R-J-04 a)", f"hijo_muerto:{h.nombre}")

    def _programar_relanzamiento(self, h: EstadoHijo) -> float:
        ahora = self._reloj.mono()
        espera = h.plan.siguiente(ahora, h.lanzado_mono)
        h.relanzar_en = ahora + espera
        h.ultima_espera = espera
        return espera

    def _latio_desde_lanzamiento(self, h: EstadoHijo) -> bool:
        edad = Latido.edad(self._ruta_estado / nombre_latido(h.nombre), self._reloj.epoch())
        if edad is None or h.lanzado_epoch is None:
            return False
        latido_en = float(self._reloj.epoch()) - edad
        return latido_en >= h.lanzado_epoch - TOLERANCIA_LATIDO_S and edad <= self.colgado_s

    def _motivo_colgado(self, h: EstadoHijo) -> Optional[str]:
        """R-J-04 b: texto si el hijo está colgado; None si late (o aún está dentro del plazo de arranque)."""
        ahora_epoch = float(self._reloj.epoch())
        edad = Latido.edad(self._ruta_estado / nombre_latido(h.nombre), ahora_epoch)
        latio = edad is not None and h.lanzado_epoch is not None and \
            (ahora_epoch - edad) >= h.lanzado_epoch - TOLERANCIA_LATIDO_S
        if latio:
            return f"sin latido desde hace {edad:.1f} s" if edad > self.colgado_s else None
        if h.lanzado_mono is not None and self._reloj.mono() - h.lanzado_mono > self._arranque_max_s:
            return f"no ha latido en {self._arranque_max_s:g} s desde que se lanzó"
        return None

    def _matar(self, h: EstadoHijo) -> None:
        """Termina al hijo: `terminate()` del Popen (el lanzador del venv arrastra al intérprete) y, si su cerrojo
        sigue tomado, TerminateProcess al PID guardado en él (riesgo 26). Espera a que el SO lo dé por muerto."""
        ruta_cerrojo = self._ruta_estado / nombre_cerrojo(h.nombre)
        proceso = h.proceso
        if proceso is not None:
            try:
                proceso.terminate()
            except OSError:   # frontera del SO: ya había terminado
                pass
            try:
                proceso.wait(ESPERA_TERMINAR_S)
            except subprocess.TimeoutExpired:
                try:
                    proceso.kill()
                except OSError:
                    pass
        self._matar_por_cerrojo(ruta_cerrojo)
        h.proceso, h.adoptado = None, False

    def _matar_por_cerrojo(self, ruta_cerrojo: Path) -> Optional[int]:
        """Mata al dueño del cerrojo si está TOMADO (el PID del fichero es entonces el suyo). Devuelve el PID o None."""
        if not cerrojo_tomado_por_otro(ruta_cerrojo):
            return None
        pid = CerrojoInstancia.pid_guardado(ruta_cerrojo)
        if pid is None or pid == os.getpid():
            return None
        self._matar_pid(pid)
        limite = time.monotonic() + ESPERA_TERMINAR_S
        while self._pid_vivo(pid) and time.monotonic() < limite:
            time.sleep(0.05)
        return pid

    # ── huérfanos al arrancar (riesgo 26) ─────────────────────────────
    def _revisar_huerfanos(self) -> None:
        """Hijo con cerrojo tomado: si no late (o late viejo) se mata por su PID; si late, se adopta."""
        for h in self._hijos.values():
            ruta_cerrojo = self._ruta_estado / nombre_cerrojo(h.nombre)
            if not cerrojo_tomado_por_otro(ruta_cerrojo):
                continue
            pid = CerrojoInstancia.pid_guardado(ruta_cerrojo)
            edad = Latido.edad(self._ruta_estado / nombre_latido(h.nombre), self._reloj.epoch())
            if edad is not None and edad <= self.colgado_s and pid is not None and pid != os.getpid():
                h.adoptado, h.pid = True, pid
                h.lanzado_mono = self._reloj.mono()
                h.lanzado_epoch = float(self._reloj.epoch()) - edad
                self._diario.anotar("hijo_adoptado", hijo=h.nombre, pid=pid, edad_latido_s=edad, regla="riesgo 26")
                logger.info("[SUPERVISOR] %s ya estaba en marcha (pid %s) y late: lo adopto", h.nombre, pid)
                continue
            matado = self._matar_por_cerrojo(ruta_cerrojo)
            if matado is None:
                self._diario.anotar("huerfano_sin_pid", hijo=h.nombre, pid=pid, edad_latido_s=edad, regla="riesgo 26")
                self._avisar(Nivel.MAXIMO, f"Supervisor: hay un {h.nombre} huérfano sin latido y no puedo saber su "
                                           f"PID para pararlo: ciérralo a mano (riesgo 26)", f"huerfano:{h.nombre}")
                continue
            self._diario.anotar("huerfano_matado", hijo=h.nombre, pid=matado, edad_latido_s=edad, regla="riesgo 26")
            self._avisar(Nivel.AVISO, f"Supervisor: había un {h.nombre} huérfano sin latido (pid {matado}); lo he "
                                      f"matado y lo relanzo (riesgo 26)", f"huerfano:{h.nombre}")

    # ── peticiones de los hijos (corrección 16) ───────────────────────
    def _revisar_peticiones(self) -> None:
        """Lee lo nuevo de `estado/orden_supervisor.jsonl` (hasta el último salto) y atiende «relanzar X»."""
        ruta = self.ruta_orden_supervisor
        tamano = _tamano_fichero(ruta)
        if tamano < self._orden_offset:
            self._orden_offset = 0                      # lo truncaron: se relee desde el principio
        if tamano == self._orden_offset:
            return
        try:
            with open(ruta, "rb") as fichero:
                fichero.seek(self._orden_offset)
                bloque = fichero.read(tamano - self._orden_offset)
        except OSError:   # frontera de fichero: se vuelve a mirar en la vuelta siguiente
            return
        corte = bloque.rfind(b"\n")
        if corte < 0:
            return
        self._orden_offset += corte + 1
        for cruda in bloque[:corte].splitlines():
            try:
                peticion = json.loads(cruda.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            if not isinstance(peticion, dict) or peticion.get("parar") is True \
                    or peticion.get("proceso") == "supervisor":
                continue
            destino = peticion.get("relanzar")
            if destino is None:
                continue
            self._atender_relanzar(str(destino), peticion)

    def _atender_relanzar(self, destino: str, peticion: dict) -> None:
        de_quien = str(peticion.get("proceso", "?"))
        if destino not in self._hijos:
            self._diario.anotar("peticion_ignorada", peticion=peticion, motivo="destino desconocido")
            return
        h = self._hijos[destino]
        ahora = self._reloj.mono()
        if h.parado_a_mano:
            self._diario.anotar("peticion_ignorada", peticion=peticion, motivo="parado a mano", regla="corrección 16")
            self._avisar(Nivel.MAXIMO, f"Supervisor: el {de_quien} pide relanzar el {destino}, pero lo paró una "
                                       f"persona: NO lo relanzo (control humano)", f"peticion_ignorada:{destino}")
            return
        if not h.corriendo:
            if h.relanzar_en is not None and h.relanzar_en > ahora:
                h.relanzar_en = ahora
            self._diario.anotar("peticion_supervisor", peticion=peticion, accion="adelantar lanzamiento",
                                regla="corrección 16")
            return
        if h.lanzado_mono is not None and ahora - h.lanzado_mono < self._gracia_peticion_s:
            self._diario.anotar("peticion_ignorada", peticion=peticion, motivo="recién lanzado",
                                edad_s=ahora - h.lanzado_mono, regla="corrección 16")
            return
        self._matar(h)
        espera = self._programar_relanzamiento(h)
        self._diario.anotar("peticion_supervisor", peticion=peticion, accion="relanzar", espera_s=espera,
                            regla="corrección 16")
        self._avisar(Nivel.MAXIMO, f"Supervisor: el {de_quien} pide relanzar el {destino} (corrección 16): lo mato y "
                                   f"lo relanzo en {espera:g} s", f"peticion_relanzar:{destino}")

    # ── fuera de la ventana: apagado (R-L-01, §6.2.5, L4) ─────────────
    def _apagar_fuera(self) -> None:
        corriendo = [h for h in self._hijos.values() if h.corriendo]
        if not corriendo:
            # R2-PRO-1: aquí solo se llega sin hijos si `_en_prorroga` ya consultó `hay_posicion()` y dijo False (o si
            # este supervisor no vivió la ventana); con posición no se marca el apagado.
            self._estuvo_dentro = False
            if not self._apagado_hecho:
                self._apagado_hecho = True
                for h in self._hijos.values():
                    h.relanzar_en = None
                    h.plan.reiniciar()
            return
        posicion = self.hay_posicion()
        if posicion is not False:
            if not self._posicion_avisada:
                self._posicion_avisada = True
                que = "hay posición abierta" if posicion else "no puedo leer la foto del ejecutor"
                self._diario.anotar("apagado_con_posicion", posicion=posicion, regla="L4 / R-D-02")
                self._avisar(Nivel.MAXIMO, f"Supervisor: fin de la ventana y {que}: NO apago el bot (sin posiciones "
                                           f"overnight, L4): CONTROL HUMANO", "apagado_con_posicion")
            return
        for nombre in reversed(HIJOS):                   # primero el ejecutor; el vigilante protege hasta el final
            h = self._hijos[nombre]
            if h.corriendo:
                self._parar_hijo(h)
        self._estuvo_dentro = False                      # R2-PRO-1: apagado hecho con la foto plana
        self._diario.anotar("apagado", regla="R-L-01")
        self._avisar(Nivel.INFO, "Supervisor: fin de la ventana: bot apagado (R-L-01)", "apagado")

    def _parar_hijo(self, h: EstadoHijo) -> None:
        """§6.2.5: `{"parar": true, "para": X}` → espera ≤ `espera_parada_s` → terminate si sigue."""
        h.parada_pedida = True
        self._escribir_parar(h.nombre)
        limite = time.monotonic() + self._espera_parada_s
        while time.monotonic() < limite:
            if self._codigo_de_salida(h) is not _SIGUE_VIVO:
                break
            time.sleep(0.05)
        codigo = self._codigo_de_salida(h)
        if codigo is _SIGUE_VIVO:
            self._diario.anotar("hijo_terminado", hijo=h.nombre, pid=h.pid, motivo="no paró en plazo",
                                espera_s=self._espera_parada_s)
            self._matar(h)
            codigo = None
        self._al_morir(h, codigo)

    def _escribir_parar(self, destino: str) -> None:
        cuerpo = {"t": self._reloj.ahora().isoformat(), "proceso": "supervisor", "pid": os.getpid(), "parar": True,
                  "para": destino}
        try:
            self._ruta_estado.mkdir(parents=True, exist_ok=True)
            with open(self.ruta_orden_supervisor, "a", encoding="utf-8", newline="\n") as fichero:
                fichero.write(json.dumps(cuerpo, ensure_ascii=False) + "\n")
                fichero.flush()
        except OSError as exc:   # frontera de fichero: sin la orden, el hijo se termina igual al vencer el plazo
            self._diario.anotar("orden_parar_fallo", para=destino, error=f"{type(exc).__name__}: {exc}")
            return
        self._diario.anotar("orden_parar", para=destino, regla="§6.2.5")

    def hay_posicion(self) -> Optional[bool]:
        """L4: ¿dice `estado/foto.json` que hay posición, intento u ORDEN viva? False sin foto; None si no se puede leer.

        G2-04: una orden viva sin posición (una entrada límite que no se
        canceló, un stop que quedó en el libro) también cuenta: si se llenara
        con el bot apagado quedaría un corto sin stop ni gestión overnight.
        `ordenes` que no es una lista → None (no se sabe: no se apaga).

        R2-PRO-2: NO bloquean el apagado (se anotan como «orden_huerfana» y
        se avisa 2, una vez por orden) una orden SIMULADA (la foto es de fase
        sombra: no existe en DAS) ni una SENDING sin id de DAS que este
        supervisor lleva viendo más de `ORDEN_HUERFANA_S` (DAS nunca la
        aceptó). Cualquier otra orden viva, o una que no es un objeto, sí.
        """
        try:
            texto = self.ruta_foto.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False
        except OSError:   # frontera de fichero
            return None
        try:
            foto = json.loads(texto)
        except ValueError:
            return None
        ordenes = foto.get("ordenes") if isinstance(foto, dict) else None
        if ordenes is not None:
            if not isinstance(ordenes, list):
                return None
            bloquean = self._ordenes_que_bloquean(ordenes, foto.get("fase"))
            if bloquean is None:
                return None
            if bloquean:
                return True
        else:
            self._sending_visto.clear()
        posiciones = foto.get("posiciones") if isinstance(foto, dict) else None
        if posiciones is None:
            return False
        if not isinstance(posiciones, dict):
            return None
        for pos in posiciones.values():
            if not isinstance(pos, dict):
                return None
            if pos.get("neta_das") not in (None, 0) or pos.get("neta_fills") not in (None, 0) \
                    or pos.get("intento") is not None:
                return True
        return False

    def _ordenes_que_bloquean(self, ordenes: list, fase: Any) -> Optional[bool]:
        """R2-PRO-2: ¿alguna orden viva de la foto impide el apagado? None si una no es un objeto (no se sabe).

        Las simuladas (foto de fase sombra) y las SENDING sin id de DAS vistas
        durante más de `ORDEN_HUERFANA_S` son huérfanas: se anotan y se avisa
        2 una vez por orden, y no bloquean.
        """
        ahora = self._reloj.mono()
        sombra = str(fase or "").strip().lower() == Fase.SOMBRA.value
        vistas: set[str] = set()
        bloquea = False
        for o in ordenes:
            if not isinstance(o, dict):
                return None
            clave = f"{o.get('token')!r}|{o.get('ticker')!r}"
            if sombra:
                self._orden_huerfana(clave, o, "simulada (fase sombra): no existe en DAS")
                continue
            if o.get("estado") == EstadoOrden.SENDING.value and o.get("id_das") is None:
                vistas.add(clave)
                primera = self._sending_visto.setdefault(clave, ahora)
                if ahora - primera > ORDEN_HUERFANA_S:
                    self._orden_huerfana(clave, o, f"SENDING sin id de DAS desde hace más de {ORDEN_HUERFANA_S:g} s")
                    continue
            bloquea = True
        for clave in [c for c in self._sending_visto if c not in vistas]:
            del self._sending_visto[clave]
        return bloquea

    def _orden_huerfana(self, clave: str, o: dict, motivo: str) -> None:
        if clave in self._huerfanas_avisadas:
            return
        self._huerfanas_avisadas.add(clave)
        self._diario.anotar("orden_huerfana", token=o.get("token"), ticker=o.get("ticker"), estado=o.get("estado"),
                            id_das=o.get("id_das"), proposito=o.get("proposito"), motivo=motivo,
                            regla="L4 / G2-04 / R2-PRO-2")
        self._avisar(Nivel.AVISO, f"Supervisor: la orden {o.get('token')} de {o.get('ticker')} ({o.get('estado')}) es "
                                  f"huérfana — {motivo}: no impide el apagado nocturno; revísala en DAS",
                     f"orden_huerfana:{clave}")

    # ── disco (R-J-07) ────────────────────────────────────────────────
    def _revisar_disco(self) -> None:
        ahora = self._reloj.mono()
        if self._disco_mirado_en is not None and ahora - self._disco_mirado_en < DISCO_CADA_S:
            return
        self._disco_mirado_en = ahora
        try:
            libre = self._libre_gb()
        except Exception as exc:  # noqa: BLE001 — frontera (medida inyectada o del SO)
            self._diario.anotar("disco_fallo", error=f"{type(exc).__name__}: {exc}")
            return
        if libre is None or libre >= self.disco_min_gb:
            return
        if self._disco_aviso_en is not None and ahora - self._disco_aviso_en < DISCO_AVISO_CADA_S:
            return
        self._disco_aviso_en = ahora
        self._diario.anotar("disco", libre_gb=round(float(libre), 2), minimo_gb=self.disco_min_gb, regla="R-J-07")
        self._avisar(Nivel.AVISO, f"Supervisor: quedan {float(libre):.1f} GB libres en el disco del bot (mínimo "
                                  f"{self.disco_min_gb:g} GB, R-J-07)", "disco")

    # ── avisos ────────────────────────────────────────────────────────
    def _avisar(self, nivel: Nivel, texto: str, clave: Optional[str]) -> None:
        """Aviso al grupo B con la fase delante (R-O-03) + `aviso` al diario. Nunca lanza."""
        if self._cfg is not None:
            texto = mod_avisos.con_prefijo_fase(texto, self._cfg.fase)
        self._poner_aviso(nivel, texto, clave)
        self._diario.anotar("aviso", nivel=int(nivel), grupo=Grupo.B.value, clave=clave, texto=texto)

    def _poner_aviso(self, nivel: Nivel, texto: str, clave: Optional[str]) -> None:
        log = logger.error if nivel is Nivel.MAXIMO else logger.warning if nivel is Nivel.AVISO else logger.info
        log("[SUPERVISOR] %s", texto)
        try:
            self._avisos.poner(Aviso(nivel=nivel, grupo=Grupo.B, texto=texto, clave=clave,
                                     creado_en=float(self._reloj.mono())))
        except Exception:  # noqa: BLE001 — frontera (cola de avisos): el aviso queda en el log y en el diario
            logger.exception("[SUPERVISOR] no se pudo encolar un aviso")


_SIGUE_VIVO: Any = object()


# ══════════════════════════════════════════════════════════════════════
# ayudas
# ══════════════════════════════════════════════════════════════════════
def _numero_valido(valor: Any, admite_cero: bool) -> bool:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        return False
    return valor >= 0 if admite_cero else valor > 0


def _numero_positivo(valor: Any, defecto: float) -> float:
    return float(valor) if _numero_valido(valor, admite_cero=False) else float(defecto)


def _hora_o(valor: Any, dia: date, defecto: str) -> datetime:
    """`a_hora_et(valor, dia)` o, con una hora mal escrita, la de `defecto` (la config valida el formato; red de seguridad)."""
    if isinstance(valor, str):
        try:
            return a_hora_et(valor, dia)
        except ValueError:
            pass
    return a_hora_et(defecto, dia)


def _firma_fichero(ruta: Path) -> Optional[tuple[int, int]]:
    try:
        st = Path(ruta).stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _tamano_fichero(ruta: Path) -> int:
    try:
        return Path(ruta).stat().st_size
    except OSError:
        return 0


def _flags_grupo_nuevo() -> int:
    """CREATE_NEW_PROCESS_GROUP en Windows (terminate limpio, el Ctrl+C de la consola no llega al hijo); 0 fuera."""
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


# ══════════════════════════════════════════════════════════════════════
# python -m app.bot_das.supervisor
# ══════════════════════════════════════════════════════════════════════
def directorio_bot() -> Path:
    """`BOT_DAS_DIR` (leída en la llamada) o el defecto de §1 (`config.DIR_BOT_POR_DEFECTO`)."""
    return Path(os.environ.get(ENV_DIR, "").strip() or mod_config.DIR_BOT_POR_DEFECTO)


def _cargar_dotenv(ruta: Path) -> None:
    """Carga `backend/.env` (solo si existe) SIN pisar el entorno del proceso. No lee ni muestra valores."""
    if not ruta.is_file():
        return
    try:
        from dotenv import load_dotenv   # perezoso: importar el módulo no carga dependencias opcionales
    except ImportError:
        return
    load_dotenv(ruta, override=False)


def _instalar_senales(supervisor: Supervisor) -> None:
    """Ctrl+C / Ctrl+Break / SIGTERM → parada ordenada del supervisor (los hijos siguen, riesgo 26)."""
    def manejador(signum: int, _frame: Any) -> None:
        supervisor.pedir_parada(f"señal {signum}", CODIGO_OK)

    if threading.current_thread() is not threading.main_thread():
        return
    for nombre in ("SIGINT", "SIGBREAK", "SIGTERM"):
        numero = getattr(signal, nombre, None)
        if numero is not None:
            try:
                signal.signal(numero, manejador)
            except (OSError, ValueError):  # frontera del SO: una señal que no se puede capturar se deja como está
                pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m app.bot_das.supervisor [--config ruta]` (§6.2.1): .env → logging con FiltroSecretos → correr → parar.

    Códigos: 0 parada ordenada, 3 otro supervisor en marcha, 5 entorno
    imposible, 1 error no previsto. El intérprete de los hijos es el mismo
    que corre el supervisor (`sys.executable`: el lanzador del venv; ver
    trampas). `DAS_EXE` (opcional) es la ruta de DAS Trader para EP-7.
    """
    parser = argparse.ArgumentParser(prog="python -m app.bot_das.supervisor", description="Supervisor del bot de DAS")
    parser.add_argument("--config", type=Path, default=None,
                        help="fichero del cuadro (defecto: BOT_DAS_DIR/config/bot_das_config.json)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    backend = Path(__file__).resolve().parents[2]
    _cargar_dotenv(RUTA_DOTENV if RUTA_DOTENV is not None else backend / ".env")
    dir_bot = directorio_bot()
    secretos = mod_avisos.secretos_desde_env()
    reloj = Reloj()
    try:
        for sub in SUBCARPETAS_BOT:
            (dir_bot / sub).mkdir(parents=True, exist_ok=True)
        mod_avisos.instalar_logging("supervisor", dir_bot / "logs", secretos, reloj=reloj)
    except OSError as exc:
        print(f"supervisor: no se puede preparar {dir_bot}: {type(exc).__name__}", file=sys.stderr)
        return CODIGO_CONFIG
    try:
        ruta_cfg = args.config or dir_bot / "config" / mod_config.NOMBRE_FICHERO_CONFIG
        cfg: Optional[Config]
        try:
            cfg = mod_config.cargar(ruta_cfg, os.environ.get(ENV_CUENTA, "").strip() or CUENTA_SOLO_LECTURA)
        except mod_config.ConfigInvalida:
            cfg = None                                   # el supervisor la reintenta en cada vuelta (H-4)
        das_txt = os.environ.get(ENV_DAS_EXE, "").strip()
        filtro = mod_avisos.FiltroSecretos(secretos)
        try:
            avisos = mod_avisos.ColaAvisos(mod_avisos.canales_desde_env(cfg), reloj)
            diario = Diario(dir_bot / "diario", reloj, "supervisor", VERSION,
                            cfg.fase if cfg is not None else Fase.SOMBRA, limpiar=filtro.limpiar)
            supervisor = Supervisor(ruta_cfg, reloj, avisos, sys.executable, backend,
                                    Path(das_txt) if das_txt else None, dir_bot / "estado", diario)
        except (ValueError, TypeError, OSError) as exc:
            logger.error("[SUPERVISOR] no arranca: %s: %s", type(exc).__name__, exc)
            return CODIGO_CONFIG
        _instalar_senales(supervisor)
        codigo = CODIGO_ERROR
        try:
            codigo = supervisor.correr()
        except Exception:  # noqa: BLE001 — frontera del proceso: se registra; los hijos siguen (riesgo 26)
            logger.exception("[SUPERVISOR] error no previsto")
            codigo = CODIGO_ERROR
        finally:
            supervisor.parar()
        logger.info("[SUPERVISOR] sale con código %d", codigo)
        return codigo
    finally:
        mod_avisos.desinstalar_logging()


if __name__ == "__main__":
    sys.exit(main())
