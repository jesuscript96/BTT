"""Grabadora de órdenes que cumple el Protocol `CanalOrdenes` (documento §10, injerto 6).

QUÉ HACE. `CanalOrdenes` es lo que el ejecutor necesita de un cliente de DAS
(`ClienteDAS` y `ClienteSombra` lo cumplen): `enviar`, `invalidar` y
`conectado`. `CanalFalso` lo implementa grabando: cada línea enviada con su
serie y versión, cada serie invalidada, una secuencia ÚNICA `eventos` con
las dos cosas en el orden en que llegaron, y una cola de respuestas
sintéticas que el test inyecta con `responder_con` y recoge con
`respuestas_pendientes`.

POR QUÉ ESTÁ AQUÍ. Permite probar `reglas/*` y el decisor sin simulador ni
socket (lotes D, E y G corren sin el lote A).

LAS TRAMPAS.
  * Graba TODO, también con `conectado=False`: el cliente real encola igual
    (§3.2, `enviar` no bloquea); el test decide qué asertar.
  * No descarta versiones viejas: eso es trabajo del emisor real. Aquí se
    graba el ORDEN de `invalidar` y `enviar` en `eventos` (L0-01), que es lo
    que hay que asertar («InvalidarSerie precede al nuevo plan», injerto
    §8.6, riesgo 7): `lineas` y `series_invalidadas` son dos listas
    separadas y por sí solas NO dicen qué fue antes. Para eso está
    `invalida_antes_de_enviar(serie, version)`.
  * `enviar` exige `str`: pasar un `OrdenNueva` sin serializar es un error de
    test, no una línea.
"""
from __future__ import annotations

from typing import Iterable, Optional, Protocol, runtime_checkable

EVENTO_ENVIAR = "enviar"
EVENTO_INVALIDAR = "invalidar"


@runtime_checkable
class CanalOrdenes(Protocol):
    """Lo que el ejecutor necesita de un cliente (ClienteDAS y ClienteSombra lo cumplen)."""

    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> None: ...

    def invalidar(self, serie: str, version: int) -> None: ...

    @property
    def conectado(self) -> bool: ...


class CanalFalso:
    """Grabadora: `lineas`, `series_invalidadas`, `eventos` (orden común), `conectado` configurable y respuestas."""

    def __init__(self, conectado: bool = True) -> None:
        self.lineas: list[tuple[str, Optional[str], int]] = []
        self.series_invalidadas: list[tuple[str, int]] = []
        # L0-01: UNA secuencia con los dos tipos de evento, en orden de llegada:
        # ("enviar", linea, serie, version) y ("invalidar", serie, version).
        self.eventos: list[tuple] = []
        self._conectado = bool(conectado)
        self._respuestas: list[str] = []

    @property
    def conectado(self) -> bool:
        return self._conectado

    @conectado.setter
    def conectado(self, valor: bool) -> None:
        self._conectado = bool(valor)

    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> None:
        if not isinstance(linea, str):
            raise TypeError(f"enviar espera una línea de texto, no {type(linea).__name__}")
        self.lineas.append((linea, serie, int(version)))
        self.eventos.append((EVENTO_ENVIAR, linea, serie, int(version)))

    def invalidar(self, serie: str, version: int) -> None:
        self.series_invalidadas.append((serie, int(version)))
        self.eventos.append((EVENTO_INVALIDAR, serie, int(version)))

    def enviadas(self) -> list[str]:
        """Solo las líneas, en orden (sin serie ni versión)."""
        return [linea for linea, _serie, _version in self.lineas]

    def indice_invalidar(self, serie: str, version: int) -> Optional[int]:
        """Posición en `eventos` del PRIMER `invalidar(serie, version)`, o None si no hubo."""
        for i, evento in enumerate(self.eventos):
            if evento[0] == EVENTO_INVALIDAR and evento[1] == serie and evento[2] == int(version):
                return i
        return None

    def indice_primer_envio(self, serie: str, version: Optional[int] = None) -> Optional[int]:
        """Posición en `eventos` del primer `enviar` de `serie` (y de `version` si se da), o None."""
        for i, evento in enumerate(self.eventos):
            if evento[0] == EVENTO_ENVIAR and evento[2] == serie and (version is None or evento[3] == int(version)):
                return i
        return None

    def invalida_antes_de_enviar(self, serie: str, version: int) -> bool:
        """Riesgo 7 / injerto §8.6 (L0-01): hubo `invalidar(serie, version)` y va ANTES del primer envío de esa
        serie y versión (si no hubo envío de esa versión, basta con que se invalidara)."""
        invalidar = self.indice_invalidar(serie, version)
        if invalidar is None:
            return False
        envio = self.indice_primer_envio(serie, version)
        return envio is None or invalidar < envio

    def responder_con(self, lineas: Iterable[str]) -> None:
        """Encola respuestas sintéticas de DAS (%OrderAct, %ORDER, %TRADE, …) que el test recogerá."""
        self._respuestas.extend(lineas)

    def respuestas_pendientes(self) -> list[str]:
        """Devuelve y vacía la cola de respuestas sintéticas."""
        pendientes, self._respuestas = self._respuestas, []
        return pendientes
