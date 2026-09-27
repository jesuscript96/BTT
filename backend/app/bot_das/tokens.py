"""Tokens de orden: enteros de 32 bits con origen, día del año y secuencia.

QUÉ HACE. Compone y descompone el `token` que viaja en cada NEWORDER /
SLNEWORDER (manual L583-598: «Token is stored in c data type int, so Token
range is [MIN_INT, MAX_INT]») y decide si un token que vuelve de DAS es
NUESTRO y de HOY. `GeneradorTokens` da el siguiente token de un proceso y
continúa desde el último `seq` que el diario recuerda (H-2).

POR QUÉ ESTÁ AQUÍ. R-A-05 (idempotencia hasta DAS: un token por intento) y
R-C-07 («cada orden lleva en su token quién la puso» para que el neteo entre
ejecutor y vigilante sea inequívoco). El esquema es `origen·10^8 + dia·10^5 +
seq`: el máximo posible es 3·10^8 + 366·10^5 + 99 999 = 336 699 999, que cabe
en el int32 de DAS (2 147 483 647) (corrección 9 del juez).

LAS TRAMPAS.
  * `es_nuestro` rechaza A PROPÓSITO los tokens de AYER: las órdenes DAY+
    caducan a las 20:00 (API 2f.5: «Con TIF DAY+ el stop desaparece a las
    20:00»). Una orden con token de ayer que siga viva en DAS es AJENA para el
    bot de hoy: la trata R-K-02 (protección + aviso) y nunca la adopta.
  * Un número al final de las `notes` de `%OrderAct` puede parecer un token
    (riesgo 2): `descomponer` valida origen, día y rango antes de aceptarlo;
    lo que no cuadra es `None` y la orden se cruza por `id_das`.
  * `bool` es `int` para `isinstance`: aquí se exige `type(x) is int`.
  * El generador NO lleva cerrojo: lo usa solo el hilo que decide (§6.1, un
    solo mutador); cada proceso tiene el suyo con su `Origen`.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.bot_das.tipos import Origen

MAX_TOKEN = 2**31 - 1            # int32 de DAS (manual L595-597)
MAX_SEQ = 99_999                 # cinco cifras de secuencia por origen y día
_BASE_ORIGEN = 10**8
_BASE_DIA = 10**5
DIA_MAX = 366


class TokensAgotados(RuntimeError):
    """Se pasó de MAX_SEQ en un día: aviso nivel 3, no se opera más ese día."""


def componer(origen: Origen, dia_del_anyo: int, seq: int) -> int:
    """origen·10^8 + dia·10^5 + seq (R-A-05, R-C-07).

    `seq` ∈ [1, MAX_SEQ], `dia_del_anyo` ∈ [1, 366]; el máximo es 336 699 999
    < MAX_TOKEN (corrección 9). Lanza `ValueError` fuera de rango.
    """
    if not isinstance(origen, Origen):
        raise ValueError(f"origen debe ser Origen, no {origen!r}")
    if type(dia_del_anyo) is not int or not (1 <= dia_del_anyo <= DIA_MAX):
        raise ValueError(f"dia_del_anyo fuera de [1, {DIA_MAX}]: {dia_del_anyo!r}")
    if type(seq) is not int or not (1 <= seq <= MAX_SEQ):
        raise ValueError(f"seq fuera de [1, {MAX_SEQ}]: {seq!r}")
    token = int(origen) * _BASE_ORIGEN + dia_del_anyo * _BASE_DIA + seq
    assert token <= MAX_TOKEN   # 336_699_999 < 2**31 - 1 por construcción
    return token


def descomponer(token: int) -> Optional[tuple[Origen, int, int]]:
    """(origen, dia_del_anyo, seq) o None si el número no cuadra con el esquema.

    Riesgo 2: un entero cualquiera (número final de `notes`, id de DAS) no
    pasa: origen ∉ {1, 2, 3}, día 0 o > 366, seq 0 → None. Solo acepta `int`
    puros (ni `bool` ni `float`).
    """
    if type(token) is not int or token <= 0 or token > MAX_TOKEN:
        return None
    origen_n, resto = divmod(token, _BASE_ORIGEN)
    dia, seq = divmod(resto, _BASE_DIA)
    try:
        origen = Origen(origen_n)
    except ValueError:
        return None
    if not (1 <= dia <= DIA_MAX) or not (1 <= seq <= MAX_SEQ):
        return None
    return origen, dia, seq


def es_nuestro(token: Optional[int], hoy: date) -> bool:
    """True solo si el token cuadra con el esquema Y es del día `hoy`.

    A PROPÓSITO rechaza tokens de AYER: las órdenes DAY+ caducan a las 20:00
    (2f.5), así que una orden con token de ayer que siga viva es AJENA para el
    bot de hoy y la trata R-K-02 (protección + aviso), nunca la adopta.
    """
    if token is None:
        return False
    partes = descomponer(token)
    if partes is None:
        return False
    return partes[1] == hoy.timetuple().tm_yday


class GeneradorTokens:
    """Siguiente token de un proceso (`origen`) para el día `hoy`.

    `ultimo_seq` viene del diario (H-2, `EstadoBot.ultimo_seq_token`): tras un
    reinicio se sigue contando y ningún token del día se repite.
    """

    def __init__(self, origen: Origen, hoy: date, ultimo_seq: int = 0) -> None:
        if not isinstance(origen, Origen):
            raise ValueError(f"origen debe ser Origen, no {origen!r}")
        if type(ultimo_seq) is not int or not (0 <= ultimo_seq <= MAX_SEQ):
            raise ValueError(f"ultimo_seq fuera de [0, {MAX_SEQ}]: {ultimo_seq!r}")
        self._origen = origen
        self._hoy = hoy
        self._seq = ultimo_seq

    @property
    def origen(self) -> Origen:
        return self._origen

    @property
    def hoy(self) -> date:
        return self._hoy

    @property
    def ultimo_seq(self) -> int:
        """Último `seq` emitido (0 si ninguno): es lo que el diario guarda."""
        return self._seq

    def siguiente(self) -> int:
        """Lanza `TokensAgotados` pasado MAX_SEQ (aviso nivel 3: no se opera más ese día)."""
        if self._seq >= MAX_SEQ:
            raise TokensAgotados(f"{self._origen.name}: agotados los {MAX_SEQ} tokens del día {self._hoy}")
        self._seq += 1
        return componer(self._origen, self._hoy.timetuple().tm_yday, self._seq)

    def cambiar_dia(self, hoy: date) -> None:
        """Día nuevo → la secuencia vuelve a 0 (el día va en el token: no hay colisión). Mismo día → nada."""
        if hoy != self._hoy:
            self._hoy = hoy
            self._seq = 0
