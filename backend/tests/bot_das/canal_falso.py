"""Grabadora de órdenes que cumple el Protocol `CanalOrdenes` (documento §10, injerto 6).

QUÉ HACE. `CanalOrdenes` es lo que el ejecutor necesita de un cliente de DAS
(`ClienteDAS` y `ClienteSombra` lo cumplen): `enviar`, `invalidar` y
`conectado`. `CanalFalso` lo implementa grabando: cada línea enviada con su
serie y versión, cada serie invalidada, y una cola de respuestas sintéticas
que el test inyecta con `responder_con` y recoge con `respuestas_pendientes`.

POR QUÉ ESTÁ AQUÍ. Permite probar `reglas/*` y el decisor sin simulador ni
socket (lotes D, E y G corren sin el lote A).

LAS TRAMPAS.
  * Graba TODO, también con `conectado=False`: el cliente real encola igual
    (§3.2, `enviar` no bloquea); el test decide qué asertar.
  * No descarta versiones viejas: eso es trabajo del emisor real. Aquí se
    graba el ORDEN de `invalidar` y `enviar`, que es lo que hay que asertar
    («InvalidarSerie precede al nuevo plan», injerto §8.6).
  * `enviar` exige `str`: pasar un `OrdenNueva` sin serializar es un error de
    test, no una línea.
"""
from __future__ import annotations

from typing import Iterable, Optional, Protocol, runtime_checkable


@runtime_checkable
class CanalOrdenes(Protocol):
    """Lo que el ejecutor necesita de un cliente (ClienteDAS y ClienteSombra lo cumplen)."""

    def enviar(self, linea: str, serie: Optional[str] = None, version: int = 0) -> None: ...

    def invalidar(self, serie: str, version: int) -> None: ...

    @property
    def conectado(self) -> bool: ...


class CanalFalso:
    """Grabadora: `lineas`, `series_invalidadas`, `conectado` configurable, `responder_con` / `respuestas_pendientes`."""

    def __init__(self, conectado: bool = True) -> None:
        self.lineas: list[tuple[str, Optional[str], int]] = []
        self.series_invalidadas: list[tuple[str, int]] = []
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

    def invalidar(self, serie: str, version: int) -> None:
        self.series_invalidadas.append((serie, int(version)))

    def enviadas(self) -> list[str]:
        """Solo las líneas, en orden (sin serie ni versión)."""
        return [linea for linea, _serie, _version in self.lineas]

    def responder_con(self, lineas: Iterable[str]) -> None:
        """Encola respuestas sintéticas de DAS (%OrderAct, %ORDER, %TRADE, …) que el test recogerá."""
        self._respuestas.extend(lineas)

    def respuestas_pendientes(self) -> list[str]:
        """Devuelve y vacía la cola de respuestas sintéticas."""
        pendientes, self._respuestas = self._respuestas, []
        return pendientes
