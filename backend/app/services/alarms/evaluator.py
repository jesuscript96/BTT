"""Evaluación de reglas de alarma.

Gramática deliberadamente plana: una condición es `{left, op, right}` donde
`left` es siempre un campo y `right` es un número o el nombre de otro campo. Las
condiciones de una lista se combinan con AND.

No hay grupos anidados ni OR. Es una decisión, no una limitación pendiente: el
constructor del backtester ya tiene ese árbol y es caro de entender; aquí una
alarma se lee de un vistazo. Quien necesite un OR configura dos alarmas.

Regla dura: un campo sin valor (None) hace que la condición NO se cumpla. Nunca
se sustituye por cero — un 0 silencioso convierte «volumen > X» en «siempre
falso» pero «precio < X» en «siempre verdadero», y eso dispara avisos falsos que
nadie sabría explicar.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import fields as F


class RuleError(ValueError):
    """Definición de regla inválida (se devuelve como 422 al configurar)."""


def normalize_condition(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza y valida una condición. Acepta el modelo client-side antiguo
    (`{field, op:"gte", value}`) y el nuevo (`{left, op, right}`)."""
    if not isinstance(raw, dict):
        raise RuleError("Cada condición debe ser un objeto.")

    left = raw.get("left", raw.get("field"))
    left = F.normalize_key(str(left or ""))
    if not F.is_known(left):
        raise RuleError(f"Campo desconocido: «{raw.get('left', raw.get('field'))}».")

    op = F.normalize_operator(str(raw.get("op", raw.get("operator", ""))))
    if op not in F.ALL_OPERATORS:
        raise RuleError(f"Operador no soportado: «{raw.get('op')}».")

    right = raw.get("right", raw.get("value"))
    right_field: Optional[str] = None
    right_value: Optional[float] = None
    if isinstance(right, str) and right.strip() and not _looks_numeric(right):
        rf = F.normalize_key(right)
        if not F.is_known(rf):
            raise RuleError(f"Campo desconocido a la derecha: «{right}».")
        right_field = rf
    else:
        try:
            right_value = float(right)
        except (TypeError, ValueError):
            raise RuleError(f"«{right}» no es ni un número ni un campo conocido.")

    if op in F.CROSS_OPERATORS:
        # El cruce compara con la barra anterior; en modo instantáneo «anterior»
        # sería el último tick, que ni es reproducible ni auditable.
        if F.kind_of(left) != F.BAR:
            raise RuleError(
                f"«{F.BY_KEY[left].label}» es un campo instantáneo y los cruces "
                "solo se pueden usar sobre campos de barra."
            )

    return {"left": left, "op": op, "right_field": right_field, "right_value": right_value}


def _looks_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def normalize_conditions(raw_list: Any) -> List[Dict[str, Any]]:
    if raw_list in (None, ""):
        return []
    if not isinstance(raw_list, list):
        raise RuleError("Las condiciones deben venir en una lista.")
    return [normalize_condition(c) for c in raw_list]


def mode_of(conditions: List[Dict[str, Any]]) -> str:
    """INSTANT si todas las condiciones usan campos instantáneos; BAR si alguna
    toca la serie de barras. El usuario no elige esto: se deduce."""
    for c in conditions:
        if F.kind_of(c["left"]) == F.BAR:
            return F.BAR
        rf = c.get("right_field")
        if rf and F.kind_of(rf) == F.BAR:
            return F.BAR
        if c["op"] in F.CROSS_OPERATORS:
            return F.BAR
    return F.INSTANT


def describe(condition: Dict[str, Any]) -> str:
    """Frase legible de una condición, para el mensaje del aviso."""
    left = F.BY_KEY[condition["left"]].label
    op_labels = {">": ">", ">=": "≥", "<": "<", "<=": "≤", "==": "=",
                 "crosses_above": "cruza arriba", "crosses_below": "cruza abajo"}
    op = op_labels.get(condition["op"], condition["op"])
    if condition.get("right_field"):
        right = F.BY_KEY[condition["right_field"]].label
    else:
        right = _fmt(condition.get("right_value"))
    return f"{left} {op} {right}"


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.2f}M".replace(".00M", "M")
    if abs(v) >= 1_000:
        return f"{v/1_000:.1f}k".replace(".0k", "k")
    return f"{v:g}"


def evaluate(
    conditions: List[Dict[str, Any]],
    ctx: Dict[str, Optional[float]],
    prev_lookup=None,
) -> Tuple[bool, List[str]]:
    """Evalúa una lista de condiciones (AND) contra un contexto de valores.

    `prev_lookup(key) -> Optional[float]` da el valor de la barra anterior; solo
    se usa para los operadores de cruce. Devuelve (se_cumple, [frases de las
    condiciones evaluadas]) — las frases van al mensaje del aviso para que el
    usuario vea POR QUÉ saltó, no solo que saltó.
    """
    if not conditions:
        return False, []   # una alarma sin condiciones no dispara nunca

    reasons: List[str] = []
    for c in conditions:
        lv = ctx.get(c["left"])
        if lv is None:
            return False, reasons
        if c.get("right_field"):
            rv = ctx.get(c["right_field"])
        else:
            rv = c.get("right_value")
        if rv is None:
            return False, reasons

        op = c["op"]
        if op in F.CROSS_OPERATORS:
            if prev_lookup is None:
                return False, reasons
            prev_l = prev_lookup(c["left"])
            prev_r = prev_lookup(c["right_field"]) if c.get("right_field") else c.get("right_value")
            if prev_l is None or prev_r is None:
                return False, reasons
            ok = (prev_l <= prev_r and lv > rv) if op == "crosses_above" else (prev_l >= prev_r and lv < rv)
        else:
            ok = F.OPERATORS[op](lv, rv)

        if not ok:
            return False, reasons
        reasons.append(f"{describe(c)} ({_fmt(lv)})")

    return True, reasons
