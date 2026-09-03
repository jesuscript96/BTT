"""Vocabulario de campos que una alarma sabe mirar.

Dos familias, y la diferencia define CUÁNDO se evalúa una alarma:

  * INSTANT — sale del estado en RAM del screener (precio, volumen del día, gap...).
    Se puede comprobar en cualquier momento; es lo que ya hacían las alarmas
    sonoras client-side.
  * BAR — necesita la serie de barras de un minuto del día (VWAP, distancia al
    VWAP, medias...). Solo tiene sentido sobre una barra CERRADA.

El modo de disparo de una alarma se DEDUCE de los campos que usa: si toca un solo
campo BAR, la alarma pasa a evaluarse al cierre de cada minuto. Así el usuario no
tiene que entender la distinción para configurarla, pero la ficha se la enseña.

Lista reducida (recorte de producto, 2026-09): del catálogo amplio se conserva
solo lo que la operativa usa de verdad. Las medias ya no son 7 fijas: hay UNA
`ema` y UNA `sma` a las que se les escribe el periodo (sobre velas de 1 minuto).
En una condición se guardan como clave concreta `ema_<n>` / `sma_<n>` (p. ej.
`ema_9`), que el motor calcula a demanda desde los cierres de la sesión.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

INSTANT = "instant"
BAR = "bar"


class Field:
    __slots__ = ("key", "label", "kind", "unit", "help", "param", "default_period")

    def __init__(self, key: str, label: str, kind: str, unit: str = "", help: str = "",
                 param: Optional[str] = None, default_period: Optional[int] = None):
        self.key = key
        self.label = label
        self.kind = kind            # INSTANT | BAR
        self.unit = unit            # "$" | "%" | "acciones" | ""
        self.help = help
        self.param = param          # None, o "period" para las medias configurables
        self.default_period = default_period

    def as_dict(self) -> Dict[str, object]:
        d: Dict[str, object] = {"key": self.key, "label": self.label, "kind": self.kind,
                                "unit": self.unit, "help": self.help}
        if self.param:
            d["param"] = self.param
            d["default_period"] = self.default_period
        return d


# ── Campos instantáneos ──────────────────────────────────────────────────────
# Salen de TickerLiveState / _metrics del live screener.
_INSTANT: List[Field] = [
    Field("price", "Precio", INSTANT, "$", "Último precio negociado."),
    Field("change_pct", "Change %", INSTANT, "%", "Variación sobre el cierre de ayer."),
    Field("volume", "Volumen acumulado", INSTANT, "acciones", "Volumen acumulado de la sesión."),
    Field("gap_pct", "Gap de apertura", INSTANT, "%", "Apertura de mercado contra el cierre de ayer."),
    Field("pmh_gap_pct", "Gap del máximo de premarket", INSTANT, "%",
          "Máximo de premarket contra el cierre de ayer. El filtro clásico de gapper."),
    Field("prev_close", "Cierre de ayer", INSTANT, "$", "Cierre de la sesión anterior."),
    Field("day_high", "Máximo del día", INSTANT, "$", "Máximo de toda la sesión."),
    Field("day_low", "Mínimo del día", INSTANT, "$", "Mínimo de toda la sesión."),
]

# ── Campos de barra ──────────────────────────────────────────────────────────
_BAR: List[Field] = [
    Field("dollar_volume", "Dollar volume", BAR, "$",
          "Precio x volumen de la barra, en dólares."),
    Field("vwap", "VWAP", BAR, "$", "Precio medio ponderado por volumen, desde las 4:00 ET."),
    Field("dist_vwap_pct", "Distancia al VWAP", BAR, "%",
          "Cuánto se separa el precio del VWAP, con signo."),
    # Medias configurables: se elige el periodo. En una condición se guardan como
    # `ema_<n>` / `sma_<n>`; estas dos entradas son solo la plantilla del formulario.
    Field("ema", "EMA (M1)", BAR, "$", "Media exponencial. Escribe el periodo (velas de 1 minuto).",
          param="period", default_period=9),
    Field("sma", "SMA (M1)", BAR, "$", "Media simple. Escribe el periodo (velas de 1 minuto).",
          param="period", default_period=20),
]

ALL_FIELDS: List[Field] = _INSTANT + _BAR
BY_KEY: Dict[str, Field] = {f.key: f for f in ALL_FIELDS}

INSTANT_KEYS = {f.key for f in _INSTANT}
BAR_KEYS = {f.key for f in _BAR}

# Alias de compatibilidad: la alarma sonora client-side guardaba `pre_pct` como
# «Premarket High Gap», misma fórmula que pmh_gap_pct. Se normaliza al leer.
ALIASES: Dict[str, str] = {
    "pre_pct": "pmh_gap_pct",
    "day_change_pct": "change_pct",
    "day_volume": "volume",
}

# ── Medias configurables ─────────────────────────────────────────────────────
# Una condición referencia una media por su clave concreta con periodo: `ema_9`,
# `sma_20`… El motor la calcula a demanda desde los cierres de la sesión.
_MA_RE = re.compile(r"^(ema|sma)_(\d+)$")
MAX_MA_PERIOD = 400   # tope defensivo: en M1 no hay tantas barras en una sesión


def parse_ma(key: str) -> Optional[Tuple[str, int]]:
    """('ema'|'sma', periodo) si `key` es una media configurable, si no None."""
    m = _MA_RE.match((key or "").strip())
    if not m:
        return None
    period = int(m.group(2))
    if period < 1 or period > MAX_MA_PERIOD:
        return None
    return m.group(1), period


def normalize_key(key: str) -> str:
    """Devuelve la clave canónica de un campo (resolviendo alias)."""
    k = (key or "").strip()
    return ALIASES.get(k, k)


def is_known(key: str) -> bool:
    k = normalize_key(key)
    return k in BY_KEY or parse_ma(k) is not None


def kind_of(key: str) -> Optional[str]:
    k = normalize_key(key)
    f = BY_KEY.get(k)
    if f is not None:
        return f.kind
    return BAR if parse_ma(k) else None


def label_of(key: str) -> str:
    """Etiqueta legible de un campo, incluidas las medias con periodo."""
    k = normalize_key(key)
    f = BY_KEY.get(k)
    if f is not None:
        return f.label
    ma = parse_ma(k)
    if ma:
        return f"{ma[0].upper()} {ma[1]}"
    return k


# ── Operadores ───────────────────────────────────────────────────────────────
# `crosses_above` / `crosses_below` necesitan el valor de la barra anterior, así
# que solo valen en modo BAR (donde «anterior» es la barra previa, reproducible).
OPERATORS = {
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}
CROSS_OPERATORS = ("crosses_above", "crosses_below")
ALL_OPERATORS = tuple(OPERATORS.keys()) + CROSS_OPERATORS

OPERATOR_ALIASES = {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "eq": "=="}


def normalize_operator(op: str) -> str:
    o = (op or "").strip()
    return OPERATOR_ALIASES.get(o, o)


def catalog() -> Dict[str, object]:
    """Catálogo que consume el constructor de reglas del frontend."""
    return {
        "fields": [f.as_dict() for f in ALL_FIELDS],
        "operators": [
            {"key": ">", "label": "es mayor que"},
            {"key": ">=", "label": "es mayor o igual que"},
            {"key": "<", "label": "es menor que"},
            {"key": "<=", "label": "es menor o igual que"},
            {"key": "==", "label": "es igual a"},
            {"key": "crosses_above", "label": "cruza hacia arriba", "bar_only": True},
            {"key": "crosses_below", "label": "cruza hacia abajo", "bar_only": True},
        ],
    }
