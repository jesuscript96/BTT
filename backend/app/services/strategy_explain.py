"""Qué hace DE VERDAD una estrategia, frente a lo que dice su JSON.

POR QUE EXISTE ESTO. El 2026-09-03 el bot piramido GELS a las 08:08 ET teniendo
la ventana de entradas cerrada a las 08:00. Al mirarlo aparecieron dos cosas
distintas que se confundian con facilidad:

1. Un bug de verdad (las piramides no miraban `entry_time_windows`), ya
   arreglado.
2. Que en el JSON de 1B viven DOS `partial_take_profits` (30 % a las 09:00,
   70 % a las 12:20) que **el motor no usa**, porque solo se leen con
   `take_profit_mode == "Partial"` y ahi pone `"Full"`. Configuracion muerta,
   guardada y invisible.

Lo segundo no es un fallo del guardado: se auditó con un round-trip sobre la 1B
real (370 campos, 0 perdidos, 0 inventados, 0 alterados). El JSON se guarda tal
cual se manda. **El problema es que nadie puede ver que parte esta viva.**

Y eso importa mas de lo que parece: `partial_take_profits` no tiene interruptor
propio — se enciende cambiando OTRO campo. Basta con poner el modo en "Partial"
para resucitar unos parciales que nadie recuerda haber configurado, sin ningun
aviso, en una estrategia que manda ordenes reales.

QUE DEVUELVE. Para cada bloque: si esta ACTIVO, con que valores, y si no lo
esta, POR QUE. Las condiciones de activacion son las del motor, verificadas una
a una contra `strategy_engine.py` (lineas 404-405, 476, 848-858) — si el motor
cambia, esto hay que cambiarlo con el.
"""
from __future__ import annotations

from typing import Any, Optional

# Métricas de universo que el radar del bot sabe evaluar en vivo. Se importa
# perezosamente para no atar este módulo al bot.
def _soportadas_en_vivo() -> dict:
    try:
        from app.services.bot_alerts_universo import SOPORTADAS
        return SOPORTADAS
    except Exception:
        return {}


def _cond(nodo: Any, salida: list, prof: int = 0) -> None:
    """Aplana un árbol de condiciones a una lista legible."""
    if not isinstance(nodo, dict):
        return
    tipo = nodo.get("type")
    if tipo == "group":
        for c in nodo.get("conditions") or []:
            _cond(c, salida, prof)
        return
    if tipo:
        salida.append(_texto_condicion(nodo))
    for k in ("root_condition",):
        if isinstance(nodo.get(k), dict):
            _cond(nodo[k], salida, prof)


def _nombre(x: Any) -> str:
    if isinstance(x, dict):
        n = x.get("name") or "?"
        p = x.get("period")
        return f"{n}({p})" if p else str(n)
    return str(x)


_OPS = {
    "GREATER_THAN": ">", "GREATER_THAN_OR_EQUAL": ">=",
    "LESS_THAN": "<", "LESS_THAN_OR_EQUAL": "<=",
    "EQUAL": "=", "NOT_EQUAL": "!=",
    "DISTANCE_LT": "a menos de", "DISTANCE_GT": "a más de",
}


def _texto_condicion(c: dict) -> str:
    """Una condición en una línea que se pueda leer sin saber el esquema."""
    src = _nombre(c.get("source"))
    op = _OPS.get(str(c.get("comparator")), str(c.get("comparator") or "?"))
    if c.get("type") == "price_level_distance":
        lado = c.get("position") or ""
        return f"{src} {op} {c.get('value_pct')}% de {_nombre(c.get('level'))} {lado}".strip()
    return f"{src} {op} {_nombre(c.get('target'))}"


def explicar_estrategia(definicion: dict) -> dict:
    """Lo que el motor va a hacer con esta definición, bloque a bloque.

    Pensado para pintarse en un desplegable: cada entrada de `inactivo` dice qué
    hay guardado y por qué no se aplica, para que configuración muerta no pase
    por configuración viva.
    """
    d = definicion or {}
    rm = d.get("risk_management") or {}
    el = d.get("entry_logic") or {}
    inactivo: list[dict] = []

    # ── Sesión ───────────────────────────────────────────────────────────
    sesiones = d.get("market_sessions") or []
    sesion = {"sesiones": sesiones}
    if "custom" in [str(s).lower() for s in sesiones]:
        sesion["desde"] = d.get("custom_start_time")
        sesion["hasta"] = d.get("custom_end_time")
    elif d.get("custom_start_time") or d.get("custom_end_time"):
        inactivo.append({
            "que": "Horario personalizado",
            "valor": f"{d.get('custom_start_time')}-{d.get('custom_end_time')}",
            "por_que": f"la sesión es {sesiones}, no 'custom'",
        })

    # ── Entradas ─────────────────────────────────────────────────────────
    cond_entrada: list = []
    _cond(el.get("root_condition"), cond_entrada)
    ventanas = el.get("entry_time_windows") or []
    entradas = {
        "condiciones": cond_entrada,
        "timeframe": el.get("timeframe"),
        # OJO: esto NO es la ventana de sesión. Limita cuándo se puede ABRIR
        # (entrada y pirámide); la sesión limita qué velas existen.
        "ventanas": [f"{v.get('from_time')}-{v.get('to_time')}" for v in ventanas],
    }

    # ── Dimensionamiento ─────────────────────────────────────────────────
    size_by_sl = bool(rm.get("size_by_sl", False))
    dimensionado = {
        "modo": "por distancia al stop" if size_by_sl else "por valor de mercado",
        "size_by_sl": size_by_sl,
    }
    if size_by_sl and not (rm.get("use_hard_stop") and rm.get("hard_stop")):
        inactivo.append({
            "que": "Dimensionar por distancia al stop",
            "valor": "size_by_sl: true",
            "por_que": "no hay stop duro activo, así que se cae a valor de mercado",
        })

    # ── Salidas ──────────────────────────────────────────────────────────
    salidas: list[str] = []
    if rm.get("use_hard_stop") and rm.get("hard_stop"):
        hs = rm["hard_stop"]
        off = hs.get("offset_pct")
        salidas.append(f"Stop: {hs.get('type')} · {hs.get('value')}"
                       + (f" · offset {off}%" if off else ""))
    elif rm.get("hard_stop"):
        inactivo.append({"que": "Stop duro", "valor": str(rm.get("hard_stop")),
                         "por_que": "use_hard_stop está desactivado"})

    trailing = rm.get("trailing_stop") or {}
    if trailing.get("active"):
        salidas.append(f"Trailing: {trailing.get('type')} {trailing.get('buffer_pct')}%")
    elif trailing:
        inactivo.append({"que": "Trailing stop",
                         "valor": f"{trailing.get('type')} {trailing.get('buffer_pct')}%",
                         "por_que": "active: false"})

    # El TP y los parciales comparten interruptor y se excluyen: ESTE es el
    # caso que motivó el módulo.
    if rm.get("use_take_profit") is not False:
        modo = rm.get("take_profit_mode", "Full")
        parciales = rm.get("partial_take_profits") or []
        if modo == "Partial" and parciales:
            for p in parciales:
                salidas.append(f"TP parcial: {p.get('capital_pct')}% en {p.get('distance_pct')}")
        else:
            tp = rm.get("take_profit") or {}
            if tp:
                salidas.append(f"TP: {tp.get('type')} {tp.get('value')}")
            if parciales:
                inactivo.append({
                    "que": f"{len(parciales)} take profit parciales",
                    "valor": ", ".join(f"{p.get('capital_pct')}% en {p.get('distance_pct')}"
                                       for p in parciales),
                    # El aviso importante: se encienden cambiando OTRO campo.
                    "por_que": f"take_profit_mode es '{modo}', no 'Partial'. "
                               "Cambiar ese campo los activaría sin más aviso",
                })
    else:
        if rm.get("take_profit") or rm.get("partial_take_profits"):
            inactivo.append({"que": "Take profit", "valor": str(rm.get("take_profit")),
                             "por_que": "use_take_profit: false"})

    swing = rm.get("swing_option") or {}
    if swing.get("active"):
        salidas.append(f"Swing: {swing.get('target_day')}")
    elif swing:
        inactivo.append({"que": "Swing", "valor": str(swing.get("target_day")),
                         "por_que": "active: false"})

    # ── Reentradas ───────────────────────────────────────────────────────
    if rm.get("accept_reentries"):
        n = rm.get("max_reentries", -1)
        reentradas = "ilimitadas" if n in (-1, None) else f"{n} por ticker-día"
    else:
        reentradas = "no"
        if rm.get("max_reentries") not in (None, 0):
            inactivo.append({"que": "Máximo de reentradas",
                             "valor": str(rm.get("max_reentries")),
                             "por_que": "accept_reentries está desactivado"})

    # ── Piramidación ─────────────────────────────────────────────────────
    pyr = d.get("pyramiding") or {}
    niveles = []
    for lv in (pyr.get("levels") or []):
        cond: list = []
        _cond(lv.get("root_condition"), cond)
        unidad = str(lv.get("unit", "pct")).lower()
        niveles.append({
            "accion": lv.get("action", "add"),
            "cantidad": (f"{lv.get('capital_pct')} $ de valor de mercado"
                         if unidad in ("usd", "$", "dollars")
                         else f"{lv.get('capital_pct')}% del equity"),
            "veces": lv.get("times", 1),
            "condiciones": cond,
        })

    # ── Universo, y qué puede vigilar el bot ─────────────────────────────
    reglas = ((d.get("universe_filters") or {}).get("rules")) or []
    soportadas = _soportadas_en_vivo()
    universo, no_vigilables = [], []
    for r in reglas:
        m = str(r.get("metric") or "")
        txt = f"{m} {_OPS.get(str(r.get('operator')), r.get('operator'))} {r.get('value')}"
        universo.append(txt)
        if soportadas and m not in soportadas:
            no_vigilables.append(m)

    return {
        "sesion": sesion,
        "entradas": entradas,
        "dimensionado": dimensionado,
        "salidas": salidas,
        "reentradas": reentradas,
        "piramidacion": niveles,
        "universo": universo,
        # Métricas que el bot NO sabe calcular en vivo: la estrategia se puede
        # backtestear, pero el radar no la podrá vigilar.
        "no_vigilable_en_vivo": no_vigilables,
        # Lo importante: qué hay guardado que el motor NO aplica.
        "inactivo": inactivo,
    }
