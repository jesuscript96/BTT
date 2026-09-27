"""Diario JSONL del bot: write-ahead por proceso, relectura y reconstrucción del estado.

QUÉ HACE. `Diario` escribe UNA línea JSON por registro en
`diario/diario_{proceso}_AAAA-MM-DD.jsonl` (un fichero por día Y por proceso,
corrección 3 del juez), con `flush` en cada línea y `fsync` en los tipos de
`FSYNC` y en la cabecera `arranque` (los que preceden a algo irreversible: M6,
«se escribe ANTES de enviar»). `LectorDiario` relee los ficheros del día
(ejecutor + vigilante) ordenados por `(t, proceso, seq)` y tolera la última
línea partida. `reconstruir` es PURA (H-2): a partir de los registros devuelve
el `EstadoBot` con el que el ejecutor continúa tras un reinicio sin reentrar en
una señal ya operada, sin reutilizar un token y sin recomprar un locate.

POR QUÉ ESTÁ AQUÍ. R-N-01 (el diario: todo lo que decidió el bot, escrito
ANTES de enviar y DESPUÉS de la respuesta), H-2 (estado persistido tras un
reinicio), M6 (write-ahead), R-A-05 (idempotencia: `senales_vistas`) y R-O-01
(cabecera `arranque` con versión de código y hashes de motor y estrategias).
La política cuando el disco falla la fija la corrección 4: `anotar` NUNCA
lanza; marca `degradado`, guarda en `pendientes` y el decisor decide qué puede
salir sin registro (stops, cancelaciones, cierres) y qué no (entradas,
pirámides, locates).

LAS TRAMPAS.
  * `Registro` (tipos.py) solo tiene `v, seq, t, proceso, tipo, datos`. Los
    campos `mono` y `ticker` de la línea (§8 los pone FUERA de `datos`) se
    devuelven al releer DENTRO de `datos` bajo esas mismas claves; al escribir
    se sacan de `datos` si vienen. `registro_a_linea` hace el camino inverso.
  * `Decimal` va como CADENA (nunca float: 10·1,03 = 10,299999… en float,
    riesgo 12); `datetime`/`date` en ISO; `Enum` por su valor; `set` como
    lista ORDENADA (el JSON debe ser reproducible); dataclasses como dict;
    un float no finito (NaN/inf) como cadena (`json.dumps` produciría `NaN`,
    que NO es JSON). Cualquier otro objeto se vuelca con `str()` antes que
    perder el registro.
  * Los secretos (riesgo 20): TODA cadena de `datos` (valores y claves, a
    cualquier profundidad), el `tipo` y el `ticker` pasan por `limpiar`
    (inyectado, ajuste (h); por defecto identidad). Si el limpiador LANZA, la
    cadena se sustituye por un marcador: nunca se escribe texto sin limpiar.
  * Fallo de disco (riesgo 23): `anotar` no lanza; devuelve el `seq` (que
    sigue creciendo), pone `degradado = True`, guarda el registro en
    `pendientes` (tope `PENDIENTES_TOPE`; pasado el tope se descarta el MÁS
    VIEJO y se cuenta en `perdidos`) y en cada llamada posterior reintenta
    abrir el fichero y volcar los pendientes ANTES del registro nuevo, para
    que el orden en el fichero siga siendo el de `seq`. Tras un fallo a
    medio `write` (disco lleno) puede quedar media línea: al reabrir se mira
    el último byte y, si no es un salto, se escribe uno antes del vuelco.
    Si el día cambia con pendientes, van al fichero del día NUEVO (cada
    línea conserva su `t`); el bot no opera de madrugada, así que no pasa.
  * Reinicio a mitad de día (H-2, riesgo 22): el proceso relanzado abre el
    MISMO fichero en append. `abrir_dia` (a) CONTINÚA el `seq` desde el
    máximo que ya hay en el fichero (si volviera a 1, `LectorDiario.seguir`
    del vigilante no vería nada nuevo hasta superar el seq viejo) y (b) si el
    fichero acaba en una línea partida (crash a medio `write`) escribe antes
    un salto de línea: sin él, el primer registro nuevo quedaría PEGADO a la
    línea rota y se perdería con ella.
  * `seguir` (el vigilante lee mientras el ejecutor escribe) IGNORA el trozo
    final sin salto de línea: puede ser una línea a medio escribir, no un
    registro; la llamada siguiente la verá entera. `leer` (arranque) sí lo
    anota como `diario_linea_partida` (§8). Una línea partida recibe el `seq`
    del registro anterior (no uno nuevo que chocaría con el siguiente real).
  * `fsync` en Windows es `os.fsync(fd)` sobre el descriptor del fichero
    abierto; se hace SOLO en los tipos de `FSYNC` y en la cabecera porque
    cuesta milisegundos y el resto no precede a nada irreversible.
  * `ultimo_seq_token`: §8 lo pide «por origen», pero `EstadoBot` lo guarda
    como UN `int`. `ultimo_seq_por_origen` lo calcula por origen y en
    `EstadoBot.ultimo_seq_token` va el MÁXIMO de los dos orígenes del
    ejecutor (`EJECUTOR` y `EJECUTOR_LOCATE`): el ejecutor puede arrancar sus
    dos `GeneradorTokens` con ese valor sin colisión posible. El vigilante
    pide el suyo a `ultimo_seq_por_origen`. Solo cuentan tokens de HOY
    (`tokens.es_nuestro`): uno de ayer lleva otro día dentro y no colisiona.
  * `reconstruir` no mira el reloj ni ficheros ni entorno: recibe `hoy` y los
    registros (en cualquier orden: los ordena), no los modifica, y descarta
    registros DUPLICADOS (mismo proceso, seq, t y tipo), así que leer dos
    veces el mismo tramo no suma dos veces un locate ni un informe de BS:
    reconstruir(x + x) == reconstruir(x) == reconstruir(x).
  * Un fill sin token NUESTRO (orden ajena o token que no cuadra) NO suma a
    `neta_fills` ni entra en `fills`: `neta_fills` es «suma signada de fills
    por token» (corrección 2) y las ajenas las reconcilia `%POS` (R-K-02).
    Un fill con lado desconocido tampoco la mueve (mejor que la reconciliación
    lo corrija que sumarlo con el signo equivocado). Los fills SIMULADOS solo
    cuentan si la fase reconstruida es SOMBRA (es la posición que el decisor
    llevaba en seco); en canario/real solo cuentan los reales.
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
import re
import threading
from collections.abc import Callable, Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import IO, Any, Optional

from app.bot_das import tokens as mod_tokens
from app.bot_das.tipos import (
    EstadoBot,
    EstadoBS,
    EstadoLote,
    EstadoOrden,
    EstadoTicker,
    Fase,
    Fill,
    Lado,
    Locate,
    Lote,
    Orden,
    Origen,
    PosicionTicker,
    Proposito,
    Registro,
    TipoOrden,
)

VERSION_FORMATO = 1                       # `v` de cada línea (§8)
PROCESOS = ("ejecutor", "vigilante", "supervisor")
FSYNC = frozenset({"orden_intencion", "orden_enviada", "cancel_intencion", "replace_intencion",
                   "locate_intencion", "cierre_humano", "lote"})
TIPO_ARRANQUE = "arranque"                # §8: la cabecera también se sincroniza
PENDIENTES_TOPE = 1_000                   # §3.7: tope de `pendientes` con el disco caído
TIPO_LINEA_PARTIDA = "diario_linea_partida"
TIPOS_SENAL_VISTA = frozenset({"senal", "senal_repetida", "senal_descartada"})
LOCATE_LOCATED = "Located"                # estado de `%SLOrder` que cobra (§5.22)
TEXTO_LIMPIAR_FALLO = "[texto retirado: el limpiador de secretos falló]"
_TEXTO_PARTIDO_MAX = 200                  # caracteres de la línea rota que se conservan en el registro
_RE_SEQ = re.compile(rb'^\{"v":\d+,"seq":(\d+),', re.MULTILINE)
_RE_SEQ_TEXTO = re.compile(r'^(\{"v":\d+,"seq":)\d+,')

# `%OrderAct` → estado de la orden que implica (manual L434-494: Sending, Send_Rej, Accept, Canceling,
# Canceled, CancelRej, TimeOut, Execute, Close, Replaced, Replacing, ReplaceRej). `Execute` lo deciden
# los fills; las acciones intermedias (Canceling, Replacing…) no cambian el estado.
_ESTADO_POR_ACCION = {
    "Accept": EstadoOrden.ACCEPTED,
    "Canceled": EstadoOrden.CANCELED,
    "Send_Rej": EstadoOrden.REJECTED,
    "Close": EstadoOrden.CLOSED,
}
_LADOS_COMPRA = frozenset({"B", "BUY"})
_LADOS_VENTA = frozenset({"S", "SS", "SELL", "SHRT", "SHORT"})


class DiarioNoDisponible(RuntimeError):
    """El diario no pudo abrirse: SOLO la lanza `abrir_dia(estricto=True)`; `anotar` nunca."""


def nombre_fichero(proceso: str, dia: date) -> str:
    """`diario_{proceso}_AAAA-MM-DD.jsonl` (§8; un fichero por día y por proceso, corrección 3).

    Lanza `ValueError` con un proceso fuera de `PROCESOS` (evita un fichero
    con un nombre que nadie relee).
    """
    if proceso not in PROCESOS:
        raise ValueError(f"proceso desconocido: {proceso!r} (esperado uno de {PROCESOS})")
    return f"diario_{proceso}_{dia.isoformat()}.jsonl"


# ── serialización ──────────────────────────────────────────────────────
def _identidad(texto: str) -> str:
    return texto


def _clave_json(clave: Any, limpiar: Callable[[str], str]) -> str:
    """Las claves de un objeto JSON son cadenas: Enum por su valor, el resto con `str()`, y todas limpias."""
    if isinstance(clave, Enum):
        clave = clave.value
    return limpiar(str(clave))


def a_json_seguro(valor: Any, limpiar: Callable[[str], str] = _identidad) -> Any:
    """Convierte cualquier valor en algo que `json.dumps` acepta sin `default` y sin `NaN` (§8, riesgo 12).

    Decimal → str; datetime/date → isoformat; Enum → value (IntEnum → int,
    str-Enum → str); set/frozenset → lista ordenada; dataclass → dict; tuple
    → list; float no finito → str; bytes → repr; Path → str; cualquier otro
    objeto → str(). Toda cadena (valor o clave) pasa por `limpiar` (riesgo
    20). Nunca lanza salvo que lance `limpiar` (el `Diario` le pasa uno que
    no lanza).
    """
    if valor is None or isinstance(valor, bool):
        return valor
    if isinstance(valor, Enum):
        return a_json_seguro(valor.value, limpiar)
    if isinstance(valor, str):
        return limpiar(str(valor))
    if isinstance(valor, int):
        return int(valor)
    if isinstance(valor, float):
        return valor if math.isfinite(valor) else limpiar(str(valor))
    if isinstance(valor, Decimal):
        return limpiar(str(valor))
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {_clave_json(k, limpiar): a_json_seguro(v, limpiar) for k, v in valor.items()}
    if isinstance(valor, (set, frozenset)):
        elementos = [a_json_seguro(v, limpiar) for v in valor]
        return sorted(elementos, key=lambda e: json.dumps(e, sort_keys=True, ensure_ascii=False))
    if isinstance(valor, (list, tuple)):
        return [a_json_seguro(v, limpiar) for v in valor]
    if dataclasses.is_dataclass(valor) and not isinstance(valor, type):
        return {campo.name: a_json_seguro(getattr(valor, campo.name), limpiar) for campo in dataclasses.fields(valor)}
    if isinstance(valor, (bytes, bytearray)):
        return limpiar(repr(bytes(valor)))
    if isinstance(valor, Path):
        return limpiar(str(valor))
    try:
        texto = str(valor)
    except Exception as exc:  # noqa: BLE001  — frontera de serialización: un __str__ roto no puede tumbar el diario (H-5)
        return f"<no serializable: {type(valor).__name__}: {type(exc).__name__}>"
    return limpiar(texto)


def _linea_json(objeto: dict) -> str:
    return json.dumps(objeto, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"


def _estado_fichero(ruta: Path) -> tuple[int, bool]:
    """(máximo `seq` escrito, acaba sin salto de línea) de un diario existente; (0, False) si no existe.

    Lee los bytes y busca `{"v":N,"seq":M,` al principio de cada línea (es el
    formato que escribe `Diario`: rápido y sin parsear JSON). Propaga OSError.
    """
    if not ruta.exists():
        return 0, False
    datos = ruta.read_bytes()
    maximo = max((int(m.group(1)) for m in _RE_SEQ.finditer(datos)), default=0)
    return maximo, bool(datos) and not datos.endswith(b"\n")


def _cola_partida(ruta: Path) -> bool:
    """True si el fichero existe, no está vacío y su último byte no es un salto de línea. Propaga OSError."""
    if not ruta.exists():
        return False
    with open(ruta, "rb") as fichero:
        fichero.seek(0, os.SEEK_END)
        if fichero.tell() == 0:
            return False
        fichero.seek(-1, os.SEEK_END)
        return fichero.read(1) != b"\n"


# ── escritura ──────────────────────────────────────────────────────────
class Diario:
    """Write-ahead JSONL de UN proceso (R-N-01, M6, correcciones 3 y 4).

    `directorio` es la carpeta `diario/` del bot; `reloj` da `ahora()` (aware
    ET), `mono()` y `hoy()`; `proceso` ∈ PROCESOS; `version_codigo` y `fase`
    van a la cabecera (R-O-01). `limpiar` es el limpiador de secretos (ajuste
    (h): `avisos.FiltroSecretos.limpiar` inyectado; por defecto identidad).
    Seguro entre hilos (un cerrojo interno serializa las escrituras).
    """

    def __init__(self, directorio: Path, reloj: Any, proceso: str, version_codigo: str, fase: Fase,
                 limpiar: Optional[Callable[[str], str]] = None) -> None:
        if proceso not in PROCESOS:
            raise ValueError(f"proceso desconocido: {proceso!r} (esperado uno de {PROCESOS})")
        if not isinstance(fase, Fase):
            raise ValueError(f"fase debe ser Fase, no {fase!r}")
        if limpiar is not None and not callable(limpiar):
            raise TypeError("limpiar debe ser callable(texto) -> texto")
        self._directorio = Path(directorio)
        self._reloj = reloj
        self._proceso = proceso
        self._version_codigo = str(version_codigo)
        self._fase = fase
        self._limpiar_usuario: Callable[[str], str] = limpiar if limpiar is not None else _identidad
        self._cerrojo = threading.RLock()
        self._seq = 0
        self._dia: Optional[date] = None
        self._fichero: Optional[IO[str]] = None
        self._seq_continuado = False             # el seq ya siguió al máximo del fichero del día
        self._revisar_cola = False               # tras un fallo de escritura pudo quedar media línea
        self._degradado = False
        self._pendientes: list[tuple[int, str, bool]] = []   # (seq, línea, fsync)
        self._perdidos = 0
        self._ultimo_error: Optional[str] = None
        self._escritos = 0

    # ── propiedades ──
    @property
    def seq(self) -> int:
        """Último `seq` asignado (0 si nada)."""
        return self._seq

    @property
    def degradado(self) -> bool:
        """True mientras haya registros sin llegar al disco (riesgo 23: el decisor no abre con esto en True)."""
        return self._degradado

    @property
    def pendientes(self) -> list[tuple[int, str, bool]]:
        """Copia de los registros que no pudieron escribirse: (seq, línea, fsync), en orden de seq."""
        with self._cerrojo:
            return list(self._pendientes)

    @property
    def perdidos(self) -> int:
        """Registros descartados por pasar `PENDIENTES_TOPE` con el disco caído."""
        return self._perdidos

    @property
    def ultimo_error(self) -> Optional[str]:
        """Texto (limpio) del último fallo de disco, o None."""
        return self._ultimo_error

    @property
    def escritos(self) -> int:
        """Líneas que llegaron al fichero."""
        return self._escritos

    @property
    def dia(self) -> Optional[date]:
        return self._dia

    @property
    def proceso(self) -> str:
        return self._proceso

    @property
    def ruta(self) -> Optional[Path]:
        """Fichero del día, o None antes de `abrir_dia`."""
        return None if self._dia is None else self._directorio / nombre_fichero(self._proceso, self._dia)

    # ── ciclo de vida ──
    def abrir_dia(self, dia: date, motor_hash: Optional[str] = None, config_version: Optional[int] = None,
                  estrategias_hash: Optional[str] = None, reloj_desvio_s: Optional[float] = None,
                  estricto: bool = False) -> int:
        """Abre `diario_{proceso}_{dia}.jsonl` en append y escribe la cabecera `arranque` (R-O-01, §8).

        Datos de la cabecera: version, fase, motor_hash, config_version,
        estrategias_hash, pid, reloj_desvio_s. Los hashes son opcionales (el
        supervisor no tiene config). Si ya había un día abierto se cierra
        antes. Si el fichero ya existe (reinicio a mitad de día) el `seq`
        continúa desde su máximo y una línea partida final se cierra con un
        salto (trampas del módulo). Devuelve el `seq` de la cabecera. Con
        `estricto=True` lanza `DiarioNoDisponible` si la cabecera no llegó al
        disco (el ejecutor prefiere no arrancar a arrancar ciego); por defecto
        no lanza y queda `degradado`.
        """
        with self._cerrojo:
            self.cerrar()
            self._dia = dia
            self._seq_continuado = False
            self._revisar_cola = False
            self._abrir_fichero()
            seq = self.anotar(TIPO_ARRANQUE, version=self._version_codigo, fase=self._fase, motor_hash=motor_hash,
                              config_version=config_version, estrategias_hash=estrategias_hash, pid=os.getpid(),
                              reloj_desvio_s=reloj_desvio_s)
            if estricto and self._degradado:
                raise DiarioNoDisponible(f"no se puede escribir {self.ruta}: {self._ultimo_error}")
            return seq

    def cerrar(self) -> None:
        """Vuelca lo pendiente si puede y cierra el fichero. Idempotente; nunca lanza."""
        with self._cerrojo:
            if self._fichero is not None:
                self._volcar_pendientes()
            if self._fichero is not None:
                try:
                    self._fichero.close()
                except (OSError, ValueError) as exc:   # frontera de fichero: cerrar no tumba al proceso (riesgo 23)
                    self._registrar_fallo(exc)
                self._fichero = None

    def __enter__(self) -> "Diario":
        return self

    def __exit__(self, *_: Any) -> None:
        self.cerrar()

    # ── escritura ──
    def anotar(self, tipo: str, /, **datos: Any) -> int:
        """Escribe un registro (write-ahead, M6, R-N-01) y devuelve su `seq`. NUNCA lanza (corrección 4).

        `tipo` es POSICIONAL: así `anotar("senal", tipo="entrada")` funciona
        (§8: los datos de `senal` llevan su propio `tipo`).
        Línea: `{"v","seq","t","mono","proceso","tipo"[,"ticker"],"datos"}`
        (§8). `t` = hora ET aware ISO con milisegundos; `mono` = monotónico
        del reloj; `ticker` sale de `datos` si viene y no es None. `flush`
        siempre; `fsync` si `tipo ∈ FSYNC` o es la cabecera. Sin `abrir_dia`
        previo se abre el día de `reloj.hoy()` (con su cabecera) antes.
        Cuando la función vuelve, la línea YA está en el fichero (o en
        `pendientes` con `degradado=True` si el disco falla: riesgo 23).
        """
        with self._cerrojo:
            try:
                if self._dia is None:
                    self.abrir_dia(self._reloj.hoy())
                if self._fichero is None:
                    self._abrir_fichero()
                self._seq += 1
                seq = self._seq
                sincronizar = tipo in FSYNC or tipo == TIPO_ARRANQUE
                linea = self._componer_linea(seq, tipo, datos)
                if self._fichero is not None and self._volcar_pendientes() and self._escribir(linea, sincronizar):
                    return seq
                self._encolar(seq, linea, sincronizar)
                return seq
            except Exception as exc:  # noqa: BLE001  — frontera: anotar NUNCA lanza (corrección 4); p. ej. un reloj roto
                self._registrar_fallo(exc)
                self._degradado = True
                self._perdidos += 1
                return self._seq

    # ── internos ──
    def _limpiar(self, texto: str) -> str:
        """El limpiador inyectado, protegido: si lanza o no devuelve texto, se retira la cadena (riesgo 20)."""
        try:
            resultado = self._limpiar_usuario(texto)
        except Exception:  # noqa: BLE001  — frontera de callback: mejor perder el texto que escribir un secreto
            return TEXTO_LIMPIAR_FALLO
        return resultado if isinstance(resultado, str) else TEXTO_LIMPIAR_FALLO

    def _componer_linea(self, seq: int, tipo: str, datos: dict) -> str:
        cuerpo = dict(datos)
        ticker = cuerpo.pop("ticker", None)
        objeto: dict[str, Any] = {
            "v": VERSION_FORMATO,
            "seq": seq,
            "t": self._reloj.ahora().isoformat(timespec="milliseconds"),
            "mono": float(self._reloj.mono()),
            "proceso": self._proceso,
            "tipo": self._limpiar(str(tipo)),
        }
        if ticker is not None:
            objeto["ticker"] = a_json_seguro(ticker, self._limpiar)
        objeto["datos"] = a_json_seguro(cuerpo, self._limpiar)
        return _linea_json(objeto)

    def _abrir_fichero(self) -> bool:
        """Abre el fichero del día en append; la primera vez continúa el seq y repara una cola partida."""
        if self._fichero is not None:
            return True
        ruta = self.ruta
        if ruta is None:
            return False
        try:
            self._directorio.mkdir(parents=True, exist_ok=True)
            if not self._seq_continuado:
                maximo, cola_partida = _estado_fichero(ruta)
                self._continuar_seq(maximo)
                self._seq_continuado = True
            else:
                cola_partida = self._revisar_cola and _cola_partida(ruta)
            fichero = open(ruta, "a", encoding="utf-8", newline="\n")  # noqa: SIM115 — el descriptor se guarda para fsync
            if cola_partida:
                try:
                    fichero.write("\n")
                    fichero.flush()
                except (OSError, ValueError):
                    self._fichero = fichero
                    self._descartar_fichero()
                    raise
            self._fichero = fichero
            self._revisar_cola = False
            return True
        except (OSError, ValueError) as exc:   # frontera de fichero (riesgo 23): disco lleno, solo lectura, bloqueado
            self._registrar_fallo(exc)
            self._fichero = None
            self._degradado = True
            return False

    def _continuar_seq(self, maximo: int) -> None:
        """El seq sigue al máximo del fichero (reinicio a mitad de día, riesgo 22).

        Si ya había registros en `pendientes` (el disco falló ANTES de poder
        leer el fichero) con seq ≤ `maximo`, se renumeran detrás de él para
        que el fichero no tenga seq repetidos ni hacia atrás.
        """
        if self._pendientes and self._pendientes[0][0] <= maximo:
            desplazamiento = maximo - self._pendientes[0][0] + 1
            renumerados = []
            for seq, linea, sincronizar in self._pendientes:
                nuevo = seq + desplazamiento
                linea = _RE_SEQ_TEXTO.sub(lambda m, n=nuevo: f'{m.group(1)}{n},', linea, count=1)
                renumerados.append((nuevo, linea, sincronizar))
            self._pendientes = renumerados
            self._seq += desplazamiento
        self._seq = max(self._seq, maximo)

    def _escribir(self, linea: str, sincronizar: bool) -> bool:
        fichero = self._fichero
        if fichero is None:
            return False
        try:
            fichero.write(linea)
            fichero.flush()
            if sincronizar:
                os.fsync(fichero.fileno())
            self._escritos += 1
            return True
        except (OSError, ValueError) as exc:   # frontera de fichero (riesgo 23); ValueError = descriptor cerrado
            self._registrar_fallo(exc)
            self._descartar_fichero()
            self._degradado = True
            return False

    def _descartar_fichero(self) -> None:
        """Cierra el descriptor tras un fallo; el búfer de texto que no llegó se tira (el registro sigue en pendientes)."""
        fichero = self._fichero
        self._fichero = None
        if fichero is None:
            return
        self._revisar_cola = True   # un disco lleno puede haber dejado media línea: se cierra al reabrir
        try:
            fichero.close()
        except (OSError, ValueError):   # el búfer no se puede vaciar: es justo lo que falló
            try:
                os.close(fichero.fileno())
            except (OSError, ValueError):
                pass

    def _volcar_pendientes(self) -> bool:
        """Escribe los pendientes en orden de seq; True si no queda ninguno (y entonces sale de `degradado`)."""
        while self._pendientes:
            if self._fichero is None and not self._abrir_fichero():
                return False
            _, linea, sincronizar = self._pendientes[0]
            if not self._escribir(linea, sincronizar):
                return False
            self._pendientes.pop(0)
        if self._fichero is not None:
            self._degradado = False
        return self._fichero is not None

    def _encolar(self, seq: int, linea: str, sincronizar: bool) -> None:
        self._degradado = True
        self._pendientes.append((seq, linea, sincronizar))
        while len(self._pendientes) > PENDIENTES_TOPE:
            self._pendientes.pop(0)
            self._perdidos += 1

    def _registrar_fallo(self, exc: BaseException) -> None:
        self._ultimo_error = self._limpiar(f"{type(exc).__name__}: {exc}")


# ── lectura ────────────────────────────────────────────────────────────
def _registro_de_linea(objeto: dict) -> Registro:
    """Línea de §8 → `Registro`; `mono` y `ticker` (fuera de `datos` en el fichero) pasan a `datos`."""
    datos = objeto.get("datos")
    datos = dict(datos) if isinstance(datos, dict) else {"datos": datos}
    if "ticker" in objeto and "ticker" not in datos:
        datos["ticker"] = objeto["ticker"]
    if "mono" in objeto and "mono" not in datos:
        datos["mono"] = objeto["mono"]
    seq = objeto.get("seq")
    v = objeto.get("v")
    return Registro(
        v=v if isinstance(v, int) and not isinstance(v, bool) else VERSION_FORMATO,
        seq=seq if isinstance(seq, int) and not isinstance(seq, bool) else 0,
        t=str(objeto.get("t", "")),
        proceso=str(objeto.get("proceso", "")),
        tipo=str(objeto.get("tipo", "")),
        datos=datos,
    )


def registro_a_linea(registro: Registro) -> dict:
    """Inverso de la lectura: el objeto JSON de §8 (con `ticker` y `mono` fuera de `datos`). Para tests y herramientas."""
    datos = dict(registro.datos)
    objeto: dict[str, Any] = {"v": registro.v, "seq": registro.seq, "t": registro.t}
    if "mono" in datos:
        objeto["mono"] = datos.pop("mono")
    objeto["proceso"] = registro.proceso
    objeto["tipo"] = registro.tipo
    if "ticker" in datos:
        objeto["ticker"] = datos.pop("ticker")
    objeto["datos"] = datos
    return objeto


def _clave_orden(registro: Registro) -> tuple[str, str, int]:
    return registro.t, registro.proceso, registro.seq


def leer_texto(texto: str, proceso: str, origen: str = "", cola_sin_fin: bool = True) -> list[Registro]:
    """Parsea el contenido de un diario, en orden de fichero. PURO.

    Una línea que no es un objeto JSON con `tipo` se convierte en un registro
    `diario_linea_partida` (datos: proceso, posicion, fichero, texto recortado)
    con el `t` y el `seq` del registro anterior, sin lanzar (§8). Con
    `cola_sin_fin=False` el trozo final SIN salto de línea se ignora (una
    línea que el escritor aún no ha terminado: la usa `seguir`). Se parte por
    "\\n" y no con `splitlines`, que cortaría dentro de una cadena con U+2028.
    """
    registros: list[Registro] = []
    ultimo_t = ""
    ultimo_seq = 0
    trozos = texto.split("\n")
    if not cola_sin_fin and trozos:
        trozos = trozos[:-1]   # lo que sigue al último "\n" (vacío si el fichero acaba bien)
    for posicion, linea in enumerate(trozos, start=1):
        if linea.strip() == "":
            continue
        try:
            objeto: Any = json.loads(linea)
        except ValueError:
            objeto = None
        if not isinstance(objeto, dict) or "tipo" not in objeto:
            registros.append(Registro(v=VERSION_FORMATO, seq=ultimo_seq, t=ultimo_t, proceso=proceso,
                                      tipo=TIPO_LINEA_PARTIDA,
                                      datos={"proceso": proceso, "posicion": posicion, "fichero": origen,
                                             "texto": linea[:_TEXTO_PARTIDO_MAX]}))
            continue
        registro = _registro_de_linea(objeto)
        if registro.proceso == "":
            registro = dataclasses.replace(registro, proceso=proceso)
        registros.append(registro)
        ultimo_t = registro.t or ultimo_t
        ultimo_seq = registro.seq
    return registros


class LectorDiario:
    """Relee los diarios del día (§8): une procesos, ordena por (t, proceso, seq) y tolera líneas partidas."""

    def __init__(self, directorio: Path) -> None:
        self._directorio = Path(directorio)

    @property
    def directorio(self) -> Path:
        return self._directorio

    def ruta(self, dia: date, proceso: str) -> Path:
        return self._directorio / nombre_fichero(proceso, dia)

    def leer(self, dia: date, procesos: tuple[str, ...] = ("ejecutor", "vigilante")) -> list[Registro]:
        """Registros de `dia` de todos los `procesos` ordenados por (t, proceso, seq) (§8, H-2).

        Un fichero ausente o ilegible cuenta como vacío (el vigilante sin
        diario del ejecutor trata toda posición como desconocida: riesgo 22).
        Una línea rota (crash a medio `write`) se devuelve como
        `diario_linea_partida` y NO lanza. El orden es estable.
        """
        registros: list[Registro] = []
        for proceso in procesos:
            registros.extend(self._leer_fichero(dia, proceso, cola_sin_fin=True))
        registros.sort(key=_clave_orden)
        return registros

    def seguir(self, dia: date, proceso: str, desde_seq: int) -> list[Registro]:
        """Lo nuevo de `proceso` con `seq > desde_seq`, en orden de fichero (el vigilante sigue al ejecutor, riesgo 22).

        La línea final sin salto (a medio escribir) NO se devuelve: la verá
        la llamada siguiente, entera. El llamante guarda el mayor `seq`
        recibido como `desde_seq` de la próxima vez.
        """
        return [r for r in self._leer_fichero(dia, proceso, cola_sin_fin=False) if r.seq > desde_seq]

    def _leer_fichero(self, dia: date, proceso: str, cola_sin_fin: bool) -> list[Registro]:
        ruta = self.ruta(dia, proceso)
        try:
            with open(ruta, "r", encoding="utf-8", errors="replace", newline="") as fichero:
                texto = fichero.read()
        except FileNotFoundError:
            return []
        except OSError:   # frontera de fichero: un diario ilegible es «vacío» para quien relee (riesgo 22)
            return []
        return leer_texto(texto, proceso, str(ruta), cola_sin_fin=cola_sin_fin)


# ── reconstrucción (PURA, H-2) ──────────────────────────────────────────
def _decimal(valor: Any) -> Optional[Decimal]:
    """Cadena/entero del diario → Decimal; None si no hay o no es numérico (nunca float en aritmética, riesgo 12)."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, Decimal):
        return valor if valor.is_finite() else None
    try:
        resultado = Decimal(str(valor).strip())
    except (InvalidOperation, ValueError):
        return None
    return resultado if resultado.is_finite() else None


def _decimal_o(valor: Any, defecto: Decimal) -> Decimal:
    resultado = _decimal(valor)
    return defecto if resultado is None else resultado


def _entero(valor: Any) -> Optional[int]:
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    try:
        return int(str(valor).strip())
    except ValueError:
        return None


def _entero_o(valor: Any, defecto: int) -> int:
    resultado = _entero(valor)
    return defecto if resultado is None else resultado


def _flotante(valor: Any) -> Optional[float]:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        resultado = float(valor)
    except (TypeError, ValueError):
        return None
    return resultado if math.isfinite(resultado) else None


def _enum(clase: type, valor: Any, defecto: Any) -> Any:
    if isinstance(valor, clase):
        return valor
    try:
        return clase(valor)
    except ValueError:
        return defecto


def _texto_o(valor: Any, defecto: Optional[str]) -> Optional[str]:
    return defecto if valor is None else str(valor)


def _token_de_hoy(valor: Any, hoy: date) -> Optional[int]:
    token = _entero(valor)
    return token if token is not None and mod_tokens.es_nuestro(token, hoy) else None


def ultimo_seq_por_origen(registros: Iterable[Registro], hoy: date) -> dict[Origen, int]:
    """Máximo `seq` de token por `Origen` entre los tokens nuestros y de HOY del diario (R-A-05, R-C-07, tokens.py).

    Mira `datos.token` (y `token_agregar`/`token_cruce`) de CUALQUIER tipo de
    registro: un token que salió alguna vez no se reutiliza aunque falte su
    `orden_intencion`. Orígenes sin token → 0. PURA.
    """
    maximos = {origen: 0 for origen in Origen}
    for registro in registros:
        for clave in ("token", "token_agregar", "token_cruce"):
            token = _token_de_hoy(registro.datos.get(clave), hoy)
            if token is None:
                continue
            partes = mod_tokens.descomponer(token)
            if partes is not None:
                origen, _, seq = partes
                maximos[origen] = max(maximos[origen], seq)
    return maximos


def _posicion(estado: EstadoBot, ticker: str) -> PosicionTicker:
    pos = estado.posiciones.get(ticker)
    if pos is None:
        pos = PosicionTicker(ticker=ticker)
        estado.posiciones[ticker] = pos
    return pos


def _ticker_de(registro: Registro) -> Optional[str]:
    ticker = registro.datos.get("ticker")
    if ticker is None or str(ticker).strip() == "":
        return None
    return str(ticker).strip()


def _mono(registro: Registro) -> Optional[float]:
    return _flotante(registro.datos.get("mono"))


def _aplicar_lote(estado: EstadoBot, registro: Registro) -> None:
    """`lote`: el último registro por `lote_id` manda; los campos que no trae se conservan del anterior (§8)."""
    datos = registro.datos
    lote_id = datos.get("lote_id")
    if lote_id is None or str(lote_id) == "":
        return
    lote_id = str(lote_id)
    ticker = _ticker_de(registro) or lote_id.split("|", 1)[0]
    pos = _posicion(estado, ticker)
    viejo = pos.lotes.get(lote_id) or Lote(id=lote_id, strategy_id="", estrategia="", ticker=ticker, direccion="",
                                           pedidas=0)
    principal = datos.get("principal_consumido")
    pos.lotes[lote_id] = Lote(
        id=lote_id,
        strategy_id=_texto_o(datos.get("strategy_id"), viejo.strategy_id),
        estrategia=_texto_o(datos.get("estrategia"), viejo.estrategia),
        ticker=ticker,
        direccion=_texto_o(datos.get("direccion"), viejo.direccion),
        pedidas=_entero_o(datos.get("pedidas"), viejo.pedidas),
        llenas=_entero_o(datos.get("llenas"), viejo.llenas),
        precio_medio=_decimal_o(datos.get("precio_medio"), viejo.precio_medio),
        nivel_stop=_decimal(datos["nivel_stop"]) if datos.get("nivel_stop") is not None else viejo.nivel_stop,
        riesgo_usd=_decimal_o(datos.get("riesgo_usd"), viejo.riesgo_usd),
        estado=_enum(EstadoLote, datos.get("estado"), viejo.estado),
        reentrada_n=_entero_o(datos.get("reentrada_n"), viejo.reentrada_n),
        entrada_idx=_entero(datos["entrada_idx"]) if datos.get("entrada_idx") is not None else viejo.entrada_idx,
        nivel_piramide=(_entero(datos["nivel_piramide"]) if datos.get("nivel_piramide") is not None
                        else viejo.nivel_piramide),
        hora_salida=_texto_o(datos.get("hora_salida"), viejo.hora_salida),
        eod=_texto_o(datos.get("eod"), viejo.eod),
        tp_pendiente=_entero_o(datos.get("tp_pendiente"), viejo.tp_pendiente),
        principal_consumido=bool(principal) if principal is not None else viejo.principal_consumido,
        version_estrategia=_texto_o(datos.get("version_estrategia"), viejo.version_estrategia),
    )


def _aplicar_orden_intencion(estado: EstadoBot, registro: Registro, hoy: date) -> None:
    """`orden_intencion`/`orden_simulada`: la orden existe por su token (R-C-07 «quién la puso»).

    El `Origen` sale del primer dígito del token (tokens.py), no del campo
    `origen` de los datos. Una intención sin `orden_enviada` queda en
    SENDING con `enviada_en = 0`: «puede haber salido» y la reconciliación la
    casa por token (riesgo 3). Si el token ya existía se conserva lo que DAS
    ya había dicho de él.
    """
    datos = registro.datos
    token = _token_de_hoy(datos.get("token"), hoy)
    ticker = _ticker_de(registro)
    if token is None or ticker is None:
        return
    partes = mod_tokens.descomponer(token)
    if partes is None:
        return
    anterior = estado.ordenes.get(token)
    orden = Orden(
        token=token,
        ticker=ticker,
        lado=_enum(Lado, datos.get("lado"), Lado.COMPRA),
        tipo=_enum(TipoOrden, datos.get("tipo_orden"), TipoOrden.LIMITE),
        qty=_entero_o(datos.get("qty"), 0),
        precio=_decimal(datos.get("precio")),
        stop=_decimal(datos.get("stop")),
        ruta=_texto_o(datos.get("ruta"), "") or "",
        proposito=_enum(Proposito, datos.get("proposito"), Proposito.DESCONOCIDA),
        lote_id=_texto_o(datos.get("lote_id"), None),
        nivel=_decimal(datos.get("nivel")),
        origen=partes[0],
        version=_entero_o(datos.get("version"), 0),
        intentos=_entero_o(datos.get("intentos"), 0),
    )
    mono = _mono(registro)
    if mono is not None:
        orden.primer_intento_en = mono
    if anterior is not None:
        orden.id_das, orden.estado = anterior.id_das, anterior.estado
        orden.lvqty, orden.llenas, orden.cxlqty = anterior.lvqty, anterior.llenas, anterior.cxlqty
        orden.enviada_en, orden.ultima_act, orden.notas = anterior.enviada_en, anterior.ultima_act, anterior.notas
        orden.tipo_das_crudo = anterior.tipo_das_crudo
        orden.primer_intento_en = anterior.primer_intento_en or orden.primer_intento_en
    estado.ordenes[token] = orden
    _posicion(estado, ticker)


def _orden_por_registro(estado: EstadoBot, datos: dict, hoy: date) -> Optional[Orden]:
    """La orden de un registro por su token de hoy o, sin él, por el id de DAS ya casado (riesgo 2)."""
    token = _token_de_hoy(datos.get("token"), hoy)
    if token is None:
        id_das = _entero(datos.get("id", datos.get("id_das")))
        token = estado.id_a_token.get(id_das) if id_das is not None else None
        if token is None:
            return None
    return estado.ordenes.get(token)


def _casar_id(estado: EstadoBot, orden: Orden, id_das: Optional[int]) -> None:
    if id_das is not None:
        orden.id_das = id_das
        estado.id_a_token[id_das] = orden.token


def _aplicar_orden_enviada(estado: EstadoBot, registro: Registro, hoy: date) -> None:
    orden = _orden_por_registro(estado, registro.datos, hoy)
    mono = _mono(registro)
    if orden is not None and mono is not None:
        orden.enviada_en = mono
        orden.ultima_act = mono


def _aplicar_orden_estado(estado: EstadoBot, registro: Registro, hoy: date) -> None:
    """`orden_estado` (`%ORDER`): último estado, qty (tras un REPLACE), lvqty/cxlqty, id y tipo crudo (§8, riesgo 1)."""
    datos = registro.datos
    orden = _orden_por_registro(estado, datos, hoy)
    if orden is None:
        return
    _casar_id(estado, orden, _entero(datos.get("id", datos.get("id_das"))))
    orden.estado = _enum(EstadoOrden, datos.get("estado"), orden.estado)
    orden.qty = _entero_o(datos.get("qty"), orden.qty)
    orden.lvqty = _entero_o(datos.get("lvqty"), orden.lvqty)
    orden.cxlqty = _entero_o(datos.get("cxlqty"), orden.cxlqty)
    if datos.get("tipo_das_crudo") is not None:
        orden.tipo_das_crudo = str(datos["tipo_das_crudo"])
    elif isinstance(datos.get("tipo"), str):
        orden.tipo_das_crudo = datos["tipo"]
    mono = _mono(registro)
    if mono is not None:
        orden.ultima_act = mono


def _aplicar_orden_act(estado: EstadoBot, registro: Registro, hoy: date) -> None:
    """`orden_act` (`%OrderAct`): id de DAS, notas y el estado que implica la acción (manual L434-494).

    `cxlqty` NO se toca: la cantidad cancelada sale de `cxlqty` de `%ORDER`
    (injerto §8.7), nunca del `qty` del `%OrderAct`.
    """
    datos = registro.datos
    orden = _orden_por_registro(estado, datos, hoy)
    if orden is None:
        return
    _casar_id(estado, orden, _entero(datos.get("id", datos.get("id_das"))))
    nuevo = _ESTADO_POR_ACCION.get(str(datos.get("accion", "")))
    if nuevo is not None:
        orden.estado = nuevo
    if datos.get("notas") is not None:
        orden.notas = str(datos["notas"])
    mono = _mono(registro)
    if mono is not None:
        orden.ultima_act = mono


def _signo(lado: Optional[str]) -> Optional[int]:
    """+1 compra, −1 venta o corto, None si el lado no se reconoce (entonces no se mueve la neta)."""
    if lado is None:
        return None
    lado = lado.strip().upper()
    if lado in _LADOS_COMPRA:
        return 1
    if lado in _LADOS_VENTA:
        return -1
    return None


def _aplicar_fill(estado: EstadoBot, registro: Registro, hoy: date, vistos: set[int]) -> None:
    """`fill`: libro por token con dedupe por `id_trade`; `neta_fills` = suma signada (corrección 2, riesgo 8).

    Sin token en el registro se busca por `id_orden` en `id_a_token` (el
    `%TRADE` no trae token). Ajeno → no cuenta. Simulado → solo en SOMBRA.
    """
    datos = registro.datos
    id_trade = _entero(datos.get("id_trade"))
    if id_trade is None or id_trade in vistos:
        return
    id_orden = _entero(datos.get("id_orden"))
    token = _token_de_hoy(datos.get("token"), hoy)
    if token is None and id_orden is not None:
        token = estado.id_a_token.get(id_orden)
    if token is None:
        return   # ajena o sin token: la reconcilia %POS (R-K-02)
    orden = estado.ordenes.get(token)
    ticker = _ticker_de(registro) or (orden.ticker if orden is not None else None)
    if ticker is None:
        return
    vistos.add(id_trade)
    lado = _texto_o(datos.get("lado"), orden.lado.value if orden is not None else None)
    qty = _entero_o(datos.get("qty"), 0)
    fill = Fill(
        id_trade=id_trade,
        token=token,
        id_orden=id_orden,
        ticker=ticker,
        lado=lado or "",
        qty=qty,
        precio=_decimal_o(datos.get("precio"), Decimal("0")),
        ruta=_texto_o(datos.get("ruta"), "") or "",
        hora=_texto_o(datos.get("hora"), "") or "",
        liq=_texto_o(datos.get("liq"), None),
        ecn_fee=_decimal(datos.get("ecn_fee")),
        simulado=bool(datos.get("simulado", False)),
    )
    estado.fills.setdefault(token, []).append(fill)
    pos = _posicion(estado, ticker)
    signo = _signo(lado)
    cuenta = (not fill.simulado) or estado.fase is Fase.SOMBRA
    if cuenta and signo is not None:
        pos.neta_fills += signo * qty
    pos.version_stops += 1
    mono = _mono(registro)
    if orden is not None:
        orden.llenas += qty
        if orden.qty > 0 and orden.llenas >= orden.qty:
            orden.estado = EstadoOrden.EXECUTED
        elif orden.estado not in (EstadoOrden.CANCELED, EstadoOrden.REJECTED, EstadoOrden.CLOSED):
            orden.estado = EstadoOrden.PARTIAL
        _casar_id(estado, orden, id_orden)
        if mono is not None:
            orden.ultima_act = mono
    if mono is not None:
        estado.ultimo_fill_en = mono if estado.ultimo_fill_en is None else max(estado.ultimo_fill_en, mono)


def _locate(estado: EstadoBot, ticker: str, strategy_id: str) -> Locate:
    clave = (ticker, strategy_id)
    locate = estado.locates.get(clave)
    if locate is None:
        locate = Locate(ticker=ticker, strategy_id=strategy_id, pedidas=0)
        estado.locates[clave] = locate
    return locate


def _datos_comunes_locate(locate: Locate, datos: dict, hoy: date) -> None:
    qty = _entero(datos.get("qty_ajustada"))
    if qty is None:
        qty = _entero(datos.get("qty"))
    if qty is not None:
        locate.pedidas = max(locate.pedidas, qty)
    token = _token_de_hoy(datos.get("token"), hoy)
    if token is not None:
        locate.token = token
    precio = _decimal(datos.get("precio_accion"))
    if precio is not None:
        locate.precio_accion = precio


def _aplicar_locate_intencion(estado: EstadoBot, registro: Registro, hoy: date) -> None:
    """`locate_intencion` (antes de `SLNEWORDER`, fsync): pedidas, token y precio; estado «comprando» (R-H-01)."""
    datos = registro.datos
    ticker = _ticker_de(registro)
    if ticker is None or datos.get("strategy_id") is None:
        return
    locate = _locate(estado, ticker, str(datos["strategy_id"]))
    _datos_comunes_locate(locate, datos, hoy)
    if locate.estado == "buscando":
        locate.estado = "comprando"


def _aplicar_locate_estado(estado: EstadoBot, registro: Registro, hoy: date) -> None:
    """`locate_estado`: último estado por (ticker, estrategia); cada `Located` suma `coste_nuevo` al gasto del día (R-H-03).

    Una actualización de `usadas` trae `coste_nuevo` 0 (o no lo trae).
    `compras` cuenta ENTRADAS en Located (R-H-02: dos → deshabilitar).
    """
    datos = registro.datos
    ticker = _ticker_de(registro)
    if ticker is None or datos.get("strategy_id") is None:
        return
    locate = _locate(estado, ticker, str(datos["strategy_id"]))
    estado_previo = locate.estado
    if datos.get("estado") is not None:
        locate.estado = str(datos["estado"])
    locate.localizadas = _entero_o(datos.get("localizadas"), locate.localizadas)
    locate.usadas = _entero_o(datos.get("usadas"), locate.usadas)
    id_das = _entero(datos.get("id_das"))
    if id_das is not None:
        locate.id_das = id_das
    _datos_comunes_locate(locate, datos, hoy)
    if datos.get("reutilizable") is not None:
        locate.reutilizable = bool(datos["reutilizable"])
    coste_total = _decimal(datos.get("coste_total"))
    if locate.estado == LOCATE_LOCATED:
        coste_nuevo = _decimal_o(datos.get("coste_nuevo"), Decimal("0"))
        estado.gasto_locates_dia += coste_nuevo
        locate.coste = coste_total if coste_total is not None else locate.coste + coste_nuevo
        if estado_previo != LOCATE_LOCATED:
            locate.compras += 1
            mono = _mono(registro)
            if mono is not None:
                locate.comprado_en = mono
    elif coste_total is not None:
        locate.coste = coste_total


def _aplicar_pausa(estado: EstadoBot, registro: Registro) -> None:
    """`pausa` (F8, R-B-07, R-M-03): con `ticker` pausa ese ticker (o el `estado` que traiga); sin ticker, `pausa_global`."""
    datos = registro.datos
    ticker = _ticker_de(registro)
    if ticker is None:
        estado.pausa_global = True
        if datos.get("control_humano") is True:
            estado.control_humano = True
        return
    pos = _posicion(estado, ticker)
    nuevo = _enum(EstadoTicker, datos.get("estado"), EstadoTicker.PAUSADO)
    pos.estado = EstadoTicker.PAUSADO if nuevo is EstadoTicker.NORMAL else nuevo
    pos.motivo_estado = _texto_o(datos.get("motivo"), "") or ""
    pos.desde = _mono(registro)
    if datos.get("intervencion_humana") is True:
        pos.intervencion_humana = True
    if datos.get("sin_reentrada_hasta_sigue") is True:
        pos.sin_reentrada_hasta_sigue = True


def _reanudar_ticker(pos: PosicionTicker, mono: Optional[float]) -> None:
    """Vuelve a NORMAL salvo un cisne negro vivo (R-G-03: el BS no se levanta con una reanudación)."""
    if pos.estado is not EstadoTicker.BS:
        pos.estado = EstadoTicker.NORMAL
        pos.motivo_estado = ""
        pos.desde = mono


def _aplicar_reanudar(estado: EstadoBot, registro: Registro) -> None:
    """`reanudar`: con `ticker` vuelve a NORMAL (salvo BS vivo); sin ticker levanta `pausa_global`."""
    ticker = _ticker_de(registro)
    if ticker is None:
        estado.pausa_global = False
        if registro.datos.get("control_humano") is True:
            estado.control_humano = False
        return
    _reanudar_ticker(_posicion(estado, ticker), _mono(registro))


def _aplicar_bs(estado: EstadoBot, registro: Registro) -> None:
    """`bs` (F7, R-G-01): `evento` = activado (defecto) | informe | silenciado | cerrado.

    Al cerrarse (`al_cerrar`) se marca `sin_reentrada_hasta_sigue` (R-G-03:
    sin reentrada hasta `/sigue TICKER`) y el ticker vuelve a NORMAL sin BS.
    """
    datos = registro.datos
    ticker = _ticker_de(registro)
    if ticker is None:
        return
    pos = _posicion(estado, ticker)
    evento = _texto_o(datos.get("evento"), "activado")
    mono = _mono(registro)
    if evento == "cerrado":
        pos.bs = None
        pos.sin_reentrada_hasta_sigue = True
        if pos.estado is EstadoTicker.BS:
            pos.estado = EstadoTicker.NORMAL
            pos.motivo_estado = ""
            pos.desde = mono
        return
    if pos.bs is None:
        activado = _flotante(datos.get("activado_en"))
        pos.bs = EstadoBS(activado_en=activado if activado is not None else (mono if mono is not None else 0.0),
                          primer_stop=_decimal_o(datos.get("primer_stop"), Decimal("0")),
                          emergencia_limite=_decimal_o(datos.get("emergencia_limite"), Decimal("0")),
                          max_visto=_decimal_o(datos.get("max_visto"), Decimal("0")))
        pos.desde = mono
    bs = pos.bs
    bs.primer_stop = _decimal_o(datos.get("primer_stop"), bs.primer_stop)
    bs.emergencia_limite = _decimal_o(datos.get("emergencia_limite"), bs.emergencia_limite)
    bs.max_visto = max(bs.max_visto, _decimal_o(datos.get("max_visto"), bs.max_visto))
    bs.informes = _entero_o(datos.get("informes"), bs.informes)
    bs.perdido_realizado = _decimal_o(datos.get("perdido_realizado"), bs.perdido_realizado)
    if evento == "informe" and mono is not None:
        bs.ultimo_informe = mono
    if evento == "silenciado":
        bs.silenciado = True
    elif datos.get("silenciado") is not None:
        bs.silenciado = bool(datos["silenciado"])
    pos.estado = EstadoTicker.BS
    pos.motivo_estado = _texto_o(datos.get("motivo"), pos.motivo_estado or "cisne negro") or "cisne negro"


def _aplicar_bs_informe(estado: EstadoBot, registro: Registro) -> None:
    """`bs_informe` (R-G-01 v2): cuenta de informes, máximo visto y hora del último (cadencia 60 s × 5, luego 300 s)."""
    ticker = _ticker_de(registro)
    pos = estado.posiciones.get(ticker) if ticker is not None else None
    if pos is None or pos.bs is None:
        return
    datos = registro.datos
    informes = _entero(datos.get("informes"))
    pos.bs.informes = informes if informes is not None else pos.bs.informes + 1
    pos.bs.max_visto = max(pos.bs.max_visto, _decimal_o(datos.get("max_visto"), pos.bs.max_visto))
    mono = _mono(registro)
    if mono is not None:
        pos.bs.ultimo_informe = mono


def _aplicar_comando(estado: EstadoBot, registro: Registro) -> None:
    """`comando` confirmado (R-M-04, R-M-03, R-G-03, F7). Los no confirmados (`confirmado: false`) no cuentan.

    * `sigue TICKER` → levanta `sin_reentrada_hasta_sigue` e
      `intervencion_humana` de ESE ticker (R-G-03) y, si estaba en
      CONTROL_HUMANO, lo devuelve a NORMAL.
    * `sigue` sin ticker → levanta `pausa_global` e `intervencion_humana` de
      todos (R-M-03), pero NO el veto de reentrada tras un BS, que exige
      `/sigue TICKER` (R-G-03, lo conservador).
    * `pausar`/`reanudar` → `pausa_global`; `apagar`/`control_humano` →
      `control_humano = True`; `encender` → False; `reanudar_ticker X` y
      `reanudar_todo` → NORMAL salvo BS; `parar_avisos X BS` /
      `reanudar_avisos X BS` → `bs.silenciado`.
    """
    datos = registro.datos
    if datos.get("confirmado") is False:
        return
    nombre = str(datos.get("nombre", "")).strip().lower().lstrip("/")
    args = datos.get("args") or []
    args = [str(a) for a in args] if isinstance(args, list) else [str(args)]
    mono = _mono(registro)
    ticker = _ticker_de(registro) or (args[0].strip().upper() if args and args[0].strip() else None)
    if nombre == "sigue":
        if ticker is not None:
            pos = estado.posiciones.get(ticker)
            if pos is not None:
                pos.sin_reentrada_hasta_sigue = False
                pos.intervencion_humana = False
                if pos.estado is EstadoTicker.CONTROL_HUMANO:
                    _reanudar_ticker(pos, mono)
        else:
            estado.pausa_global = False
            for pos in estado.posiciones.values():
                pos.intervencion_humana = False
    elif nombre == "pausar":
        estado.pausa_global = True
    elif nombre == "reanudar":
        estado.pausa_global = False
    elif nombre in ("apagar", "control_humano"):
        estado.control_humano = True
    elif nombre == "encender":
        estado.control_humano = False
    elif nombre == "reanudar_ticker" and ticker is not None and ticker in estado.posiciones:
        _reanudar_ticker(estado.posiciones[ticker], mono)
    elif nombre == "reanudar_todo":
        for pos in estado.posiciones.values():
            _reanudar_ticker(pos, mono)
    elif nombre in ("parar_avisos", "reanudar_avisos") and ticker is not None:
        pos = estado.posiciones.get(ticker)
        if pos is not None and pos.bs is not None and any(a.strip().upper() == "BS" for a in args[1:]):
            pos.bs.silenciado = nombre == "parar_avisos"


def _aplicar_discrepancia(estado: EstadoBot, registro: Registro) -> None:
    """Caso 6 de la reconciliación (F10, M7): el decisor hizo `neta_fills := neta_das` y lo anotó; se reproduce."""
    ticker = _ticker_de(registro)
    neta_das = _entero(registro.datos.get("neta_das"))
    if ticker is None or neta_das is None:
        return
    pos = _posicion(estado, ticker)
    pos.neta_fills = neta_das
    pos.neta_das = neta_das
    mono = _mono(registro)
    if mono is not None:
        pos.neta_das_en = mono


def _aplicar_pos(estado: EstadoBot, registro: Registro) -> None:
    """`pos` (`%POS`): solo lo que DAS dijo (neta_das, avg, tipo); NO toca `neta_fills` (corrección 2)."""
    ticker = _ticker_de(registro)
    neta = _entero(registro.datos.get("neta"))
    if ticker is None or neta is None:
        return
    pos = _posicion(estado, ticker)
    pos.neta_das = neta
    pos.avg_das = _decimal(registro.datos.get("avg"))
    pos.tipo_das = _entero(registro.datos.get("tipo"))
    pos.neta_das_en = _mono(registro)


def _sin_duplicados(registros: list[Registro]) -> list[Registro]:
    """Quita registros repetidos (mismo proceso, seq, t y tipo), p. ej. un tramo leído dos veces. Los de seq 0 se quedan."""
    vistos: set[tuple[str, int, str, str]] = set()
    unicos: list[Registro] = []
    for registro in registros:
        if registro.seq > 0:
            clave = (registro.proceso, registro.seq, registro.t, registro.tipo)
            if clave in vistos:
                continue
            vistos.add(clave)
        unicos.append(registro)
    return unicos


def reconstruir(registros: Iterable[Registro], hoy: date) -> EstadoBot:
    """Estado del bot a partir de los registros del día (PURA, H-2, §8). Idempotente; no modifica los registros.

    `fase` sale del último `arranque` (sin él: SOMBRA, lo más conservador) y
    `dia` de `hoy`. Reproduce: senales_vistas (senal/senal_repetida/
    senal_descartada, R-A-05); lotes (último `lote` por lote_id); órdenes por
    token (orden_intencion/orden_simulada + orden_enviada/orden_estado/
    orden_act; una intención sin `orden_enviada` queda SENDING = «puede haber
    salido», riesgo 3); id_a_token; fills y neta_fills (dedupe por id_trade,
    corrección 2); version_stops (sube con cada fill, injerto §8.6);
    ultimo_fill_en; ultimo_seq_token (máximo de EJECUTOR y EJECUTOR_LOCATE;
    por origen en `ultimo_seq_por_origen`); locates, gasto_locates_dia
    (R-H-03) y locates_deshabilitados (`locates_deshabilitar`, R-H-02);
    neta_das (`pos`) y el caso 6 (`discrepancia`); pausas por ticker y
    global, control humano, BS, intervención humana y
    sin_reentrada_hasta_sigue (pausa/reanudar/bs/bs_informe/comando);
    config_version (último `config`). NO reconstruye lo vivo (conexión,
    cotizaciones, modo_degradado): eso lo mide el proceso al arrancar.
    """
    lista = _sin_duplicados(sorted(registros, key=_clave_orden))
    fase = Fase.SOMBRA
    for registro in lista:
        if registro.tipo == TIPO_ARRANQUE:
            fase = _enum(Fase, registro.datos.get("fase"), fase)
    estado = EstadoBot(fase=fase, dia=hoy)
    trades_vistos: set[int] = set()
    for registro in lista:
        tipo = registro.tipo
        datos = registro.datos
        if tipo in TIPOS_SENAL_VISTA:
            if datos.get("senal_id") is not None:
                estado.senales_vistas.add(str(datos["senal_id"]))
        elif tipo == "lote":
            _aplicar_lote(estado, registro)
        elif tipo in ("orden_intencion", "orden_simulada"):
            _aplicar_orden_intencion(estado, registro, hoy)
        elif tipo == "orden_enviada":
            _aplicar_orden_enviada(estado, registro, hoy)
        elif tipo == "orden_estado":
            _aplicar_orden_estado(estado, registro, hoy)
        elif tipo == "orden_act":
            _aplicar_orden_act(estado, registro, hoy)
        elif tipo == "fill":
            _aplicar_fill(estado, registro, hoy, trades_vistos)
        elif tipo == "pos":
            _aplicar_pos(estado, registro)
        elif tipo == "discrepancia":
            _aplicar_discrepancia(estado, registro)
        elif tipo == "locate_intencion":
            _aplicar_locate_intencion(estado, registro, hoy)
        elif tipo == "locate_estado":
            _aplicar_locate_estado(estado, registro, hoy)
        elif tipo == "locates_deshabilitar":
            estado.locates_deshabilitados = True
        elif tipo == "pausa":
            _aplicar_pausa(estado, registro)
        elif tipo == "reanudar":
            _aplicar_reanudar(estado, registro)
        elif tipo == "bs":
            _aplicar_bs(estado, registro)
        elif tipo == "bs_informe":
            _aplicar_bs_informe(estado, registro)
        elif tipo == "comando":
            _aplicar_comando(estado, registro)
        elif tipo == "config":
            version = _entero(datos.get("config_version"))
            if version is not None:
                estado.config_version = version
    maximos = ultimo_seq_por_origen(lista, hoy)
    estado.ultimo_seq_token = max(maximos[Origen.EJECUTOR], maximos[Origen.EJECUTOR_LOCATE])
    return estado
