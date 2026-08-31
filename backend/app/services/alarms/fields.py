"""Vocabulario de campos que una alarma sabe mirar.

Dos familias, y la diferencia define CUÁNDO se evalúa una alarma:

  * INSTANT — sale del estado en RAM del screener (precio, volumen del día, gap...).
    Se puede comprobar en cualquier momento; es lo que ya hacían las alarmas
    sonoras client-side.
  * BAR — necesita la serie de barras de un minuto del día (VWAP, mínimo de la
    barra anterior, EMA, minutos desde el último máximo...). Solo tiene sentido
    sobre una barra CERRADA.

El modo de disparo de una alarma se DEDUCE de los campos que usa: si toca un solo
campo BAR, la alarma pasa a evaluarse al cierre de cada minuto. Así el usuario no
tiene que entender la distinción para configurarla, pero la ficha se la enseña.
"""

from __future__ import annotations

from typing import Dict, List, Optional

INSTANT = "instant"
BAR = "bar"


class Field:
    __slots__ = ("key", "label", "kind", "unit", "help")

    def __init__(self, key: str, label: str, kind: str, unit: str = "", help: str = ""):
        self.key = key
        self.label = label
        self.kind = kind       # INSTANT | BAR
        self.unit = unit       # "$" | "%" | "acciones" | "min" | ""
        self.help = help

    def as_dict(self) -> Dict[str, str]:
        return {"key": self.key, "label": self.label, "kind": self.kind,
                "unit": self.unit, "help": self.help}


# ── Campos instantáneos ──────────────────────────────────────────────────────
# Salen de TickerLiveState / _metrics del live screener. Los cinco primeros son
# exactamente los que ya existían en las alarmas sonoras: las reglas guardadas en
# localStorage migran a este modelo sin traducción.
_INSTANT: List[Field] = [
    Field("price", "Precio", INSTANT, "$", "Último precio negociado."),
    Field("change_pct", "Change %", INSTANT, "%", "Variación sobre el cierre de ayer."),
    Field("volume", "Volumen del día", INSTANT, "acciones", "Volumen acumulado de la sesión."),
    Field("pmh_gap_pct", "Gap del máximo de premarket", INSTANT, "%",
          "Máximo de premarket contra el cierre de ayer. El filtro del 50% de la 1B."),
    Field("pre_volume", "Volumen de premarket", INSTANT, "acciones",
          "Acumulado desde las 4:00 ET. El filtro de los 2M de la 1B."),
    Field("pre_high", "Máximo de premarket", INSTANT, "$", ""),
    Field("gap_pct", "Gap de apertura", INSTANT, "%", "Apertura RTH contra el cierre de ayer."),
    Field("prev_close", "Cierre de ayer", INSTANT, "$", ""),
    Field("day_high", "Máximo del día", INSTANT, "$", ""),
    Field("day_low", "Mínimo del día", INSTANT, "$", ""),
    Field("rvol", "RVol", INSTANT, "x", "Volumen del día contra la media de 20 sesiones."),
]

# ── Campos de barra ──────────────────────────────────────────────────────────
_BAR: List[Field] = [
    Field("close", "Cierre de la barra", BAR, "$", "De la barra de 1 minuto que acaba de cerrar."),
    Field("open", "Apertura de la barra", BAR, "$", ""),
    Field("high", "Máximo de la barra", BAR, "$", ""),
    Field("low", "Mínimo de la barra", BAR, "$", ""),
    Field("bar_volume", "Volumen de la barra", BAR, "acciones", ""),
    Field("dollar_volume", "Dollar volume de la barra", BAR, "$",
          "Cierre x volumen de esa barra, en dólares."),
    Field("prev_bar_close", "Cierre de la barra anterior", BAR, "$", ""),
    Field("prev_bar_high", "Máximo de la barra anterior", BAR, "$", ""),
    Field("prev_bar_low", "Mínimo de la barra anterior", BAR, "$",
          "Permite «cierra por debajo del mínimo anterior»."),
    Field("vwap", "VWAP", BAR, "$", "Anclado a las 4:00 ET, incluye premarket."),
    Field("dist_vwap_pct", "Distancia al VWAP", BAR, "%",
          "Con signo: negativo si el precio está por debajo del VWAP."),
    Field("pm_high", "Máximo de premarket (corrido)", BAR, "$",
          "El máximo hasta este minuto, no el del día entero."),
    Field("pm_low", "Mínimo de premarket (corrido)", BAR, "$", ""),
    Field("previous_max", "Máximo previo de la sesión", BAR, "$",
          "Extremo corrido del día. Es la referencia del stop de la 1B."),
    Field("previous_min", "Mínimo previo de la sesión", BAR, "$", ""),
    Field("mins_since_high", "Minutos desde el último máximo", BAR, "min",
          "Cuánto lleva el precio sin hacer máximos nuevos."),
    Field("ema9", "EMA 9", BAR, "$", ""),
    Field("ema15", "EMA 15", BAR, "$", ""),
    Field("ema20", "EMA 20", BAR, "$", ""),
    Field("ema50", "EMA 50", BAR, "$", ""),
    Field("ema200", "EMA 200", BAR, "$", ""),
    Field("sma20", "SMA 20", BAR, "$", ""),
    Field("sma50", "SMA 50", BAR, "$", ""),
]

ALL_FIELDS: List[Field] = _INSTANT + _BAR
BY_KEY: Dict[str, Field] = {f.key: f for f in ALL_FIELDS}

INSTANT_KEYS = {f.key for f in _INSTANT}
BAR_KEYS = {f.key for f in _BAR}

# Alias de compatibilidad: la alarma sonora client-side guardaba `pre_pct` como
# «Premarket High Gap», que es la misma fórmula que pmh_gap_pct. Se normaliza al
# leer para que las reglas ya guardadas sigan funcionando.
ALIASES: Dict[str, str] = {
    "pre_pct": "pmh_gap_pct",
    "day_change_pct": "change_pct",
    "day_volume": "volume",
}


def normalize_key(key: str) -> str:
    """Devuelve la clave canónica de un campo (resolviendo alias)."""
    k = (key or "").strip()
    return ALIASES.get(k, k)


def is_known(key: str) -> bool:
    return normalize_key(key) in BY_KEY


def kind_of(key: str) -> Optional[str]:
    f = BY_KEY.get(normalize_key(key))
    return f.kind if f else None


# ── Operadores ───────────────────────────────────────────────────────────────
# `crosses_above` / `crosses_below` necesitan el valor de la evaluación anterior,
# así que solo están disponibles en modo BAR (donde «anterior» es la barra previa,
# un concepto estable). En modo instantáneo «anterior» sería el último tick, que
# no es reproducible ni auditable.
OPERATORS = {
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}
CROSS_OPERATORS = ("crosses_above", "crosses_below")
ALL_OPERATORS = tuple(OPERATORS.keys()) + CROSS_OPERATORS

# Compatibilidad con el modelo client-side anterior ("gte"/"lte").
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
