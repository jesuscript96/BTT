"""El individuo: sus genes, como nace al azar y como se traduce a una
estrategia que el motor entiende.

Un individuo es un dict plano (serializable a JSON tal cual):

    {"condiciones": [ {"ind": "RSI", "params": {"period": 14},
                       "comp": "GREATER_THAN", "objetivo": 70}, ... ],
     "stop": {"modo": "pct", "valor": 5}
          | {"modo": "estructura", "nivel": "Previous Max", "operador": ">=", "offset_pct": 10},
     "tp":   {"modo": "pct", "valor": 6} | {"modo": "hora", "valor": "09:00"}
          | {"modo": "tiempo", "valor": 60}}

`a_definicion` produce EXACTAMENTE la forma de `definition` que guardan las
estrategias en users.duckdb (misma que manda el panel), con las guardas
fijas del usuario delante de las condiciones buscadas.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random

from genetico import catalogo as C


# ── Nacimiento al azar ──────────────────────────────────────────────────────

def _condicion_aleatoria(rng: random.Random, nombres: list[str]) -> dict:
    ind = C.CATALOGO[rng.choice(nombres)]
    params = {k: rng.choice(v) for k, v in ind.params.items()}
    comp = rng.choice(ind.comparadores)
    opciones = []
    if ind.valores:
        opciones.append("numero")
    if ind.objetivos:
        opciones.append("indicador")
    tipo = rng.choice(opciones)
    if tipo == "numero":
        objetivo = rng.choice(ind.valores)
    else:
        # EL LADO DERECHO TAMBIEN LLEVA PARAMETROS SORTEADOS. Sin esto, un
        # Donchian o una Darvas saldrian siempre con el periodo por defecto y
        # con la linea de arriba: se ofreceria el indicador y se probaria UNA
        # sola de sus formas. Es justo lo que preguntaba Jaume del Darvas —
        # asi prueba por arriba, por abajo y por el centro.
        nivel = rng.choice(ind.objetivos)
        rejilla = C.NIVELES_CON_PARAMS.get(nivel, {})
        objetivo = {"ind": nivel,
                    "params": {k: rng.choice(v) for k, v in rejilla.items()}}
    return {"ind": ind.nombre, "params": params, "comp": comp, "objetivo": objetivo}


def _stop_aleatorio(rng: random.Random, modos: list[str], sesgo: str,
                    min_pct: float = 0.0) -> dict:
    """`min_pct` es el suelo del stop en % — solo afecta al modo porcentaje.

    PARA QUE (Jaume, 2026-09-04). Un stop del 2 % en una accion que se mueve un
    50 % al dia no es un stop: es ruido, y el genetico lo elige porque con
    «shares por distancia» reparte un tamano enorme y la R media sale preciosa
    hasta que un dia salta el hueco. El suelo lo prohibe de raiz en vez de
    dejar que lo descubra a base de curvas rotas.

    No toca los stops de ESTRUCTURA: alli la distancia la pone el mercado (donde
    este el maximo previo), no un numero que se pueda acotar.
    """
    modo = rng.choice(modos)
    if modo == "pct":
        rejilla = tuple(v for v in C.STOP_PCT if v >= min_pct) or (max(C.STOP_PCT),)
        return {"modo": "pct", "valor": rng.choice(rejilla)}
    nivel, operador = rng.choice(C.STOP_NIVELES[sesgo])
    return {"modo": "estructura", "nivel": nivel, "operador": operador,
            "offset_pct": rng.choice(C.STOP_OFFSET_PCT)}


def _tp_aleatorio(rng: random.Random, modos: list[str], min_pct: float = 0.0) -> dict:
    """`min_pct` es el objetivo minimo en % — solo afecta al modo porcentaje.

    Los modos por hora y por tiempo no llevan un % que acotar: cierran cuando
    toca, valga lo que valga. Si Jaume quiere exigir un objetivo minimo, lo que
    quiere es que no busque en la zona de objetivos ridiculos, y esa zona solo
    existe en el modo porcentaje.
    """
    modo = rng.choice(modos)
    if modo == "pct":
        rejilla = tuple(v for v in C.TP_PCT if v >= min_pct) or (max(C.TP_PCT),)
        return {"modo": "pct", "valor": rng.choice(rejilla)}
    if modo == "hora":
        return {"modo": "hora", "valor": rng.choice(C.TP_HORA)}
    return {"modo": "tiempo", "valor": rng.choice(C.TP_TIEMPO_MIN)}


def _parciales_aleatorios(rng: random.Random, modos: list[str],
                          activo: bool, min_pct: float = 0.0) -> list:
    """Take profits PARCIALES: cerrar un trozo antes y dejar correr el resto.

    Devuelve una lista de niveles, o vacia si no se usan. El genetico sortea
    CUANTOS pone (ninguno, uno o dos) para que pueda decidir que no compensan:
    si siempre pusiera dos, no se podria comparar contra no ponerlos.

    Los porcentajes de cierre se reparten sin pasarse del 100 %: dos niveles al
    75 % cerrarian mas posicion de la que hay.
    """
    if not activo:
        return []
    cuantos = rng.randint(0, C.TP_PARCIAL_MAX_NIVELES)
    niveles, cerrado = [], 0
    vistos: set = set()
    for _ in range(cuantos):
        cierre = rng.choice([c for c in C.TP_PARCIAL_CIERRE_PCT if cerrado + c <= 100]
                            or [100 - cerrado])
        if cierre <= 0:
            break
        # DOS PARCIALES EN EL MISMO SITIO NO SON DOS PARCIALES. El motor los
        # aplica en orden, asi que un segundo nivel con el mismo objetivo salta
        # justo detras del primero: cierra mas posicion de golpe y gasta un gen
        # en algo que no anyade una decision. Salio en la primera corrida con
        # esto puesto: «Parciales: 25% a las 12:00, 33% a las 12:00».
        objetivo = None
        for _intento in range(12):
            cand = _tp_aleatorio(rng, modos, min_pct)
            clave = (cand["modo"], cand["valor"])
            if clave not in vistos:
                objetivo, _ = cand, vistos.add(clave)
                break
        if objetivo is None:
            break          # sin objetivos libres: mejor un nivel menos que uno repetido
        cerrado += cierre
        niveles.append({**objetivo, "cierre_pct": cierre})
    return niveles


def aleatorio(config: dict, rng: random.Random) -> dict:
    nombres = list(config["catalogo"])
    n = int(config.get("n_condiciones", 2))
    conds = []
    usados = set()
    intentos = 0
    while len(conds) < n and intentos < 50:
        intentos += 1
        c = _condicion_aleatoria(rng, nombres)
        if c["ind"] in usados:
            continue  # un indicador por condicion: dos Squeeze no aportan, ensucian
        usados.add(c["ind"])
        conds.append(c)
    riesgo = config.get("riesgo", {})
    tps = list(config.get("tps", ["pct"]))
    tp_min = float(riesgo.get("tp_min_pct", 0) or 0)
    return {
        "condiciones": conds,
        "stop": _stop_aleatorio(rng, list(config.get("stops", ["pct"])),
                                config.get("sesgo", "short"),
                                float(riesgo.get("stop_min_pct", 0) or 0)),
        "tp": _tp_aleatorio(rng, tps, tp_min),
        "parciales": _parciales_aleatorios(
            rng, tps, bool(riesgo.get("tp_parciales", False)), tp_min),
    }


# ── Identidad y lectura humana ──────────────────────────────────────────────

def canonico(individuo: dict) -> dict:
    """Mismo individuo con las condiciones en orden fijo: un AND no depende del
    orden, y el cruce las baraja. Sin esto el mismo individuo se reevaluaba."""
    conds = sorted(individuo["condiciones"], key=lambda c: json.dumps(c, sort_keys=True))
    return {"condiciones": conds, "stop": individuo["stop"], "tp": individuo["tp"]}


def huella(individuo: dict) -> str:
    """Hash estable: dos individuos con los mismos genes son el mismo."""
    return hashlib.md5(json.dumps(canonico(individuo), sort_keys=True).encode()).hexdigest()[:12]


def _lee_tp(t: dict) -> str:
    return {"pct": lambda: f"{t['valor']}%", "hora": lambda: f"a las {t['valor']}",
            "tiempo": lambda: f"a los {t['valor']} min"}[t["modo"]]()


def receta(individuo: dict) -> str:
    partes = []
    for c in canonico(individuo)["condiciones"]:
        ind = C.CATALOGO[c["ind"]]
        izq = ind.etiqueta(c["params"])
        obj = c["objetivo"]
        if isinstance(obj, dict):
            # Con los parametros: un «Donchian» a secas no dice si es la banda
            # de arriba o la de abajo, y son estrategias opuestas.
            ps = [str(v) for _, v in sorted((obj.get("params") or {}).items()) if v is not None]
            der = f"{obj['ind']}({', '.join(ps)})" if ps else obj["ind"]
        else:
            der = str(obj)
        partes.append(f"{izq} {C.SIMBOLO.get(c['comp'], c['comp'])} {der}")
    s = individuo["stop"]
    stop = f"{s['valor']}%" if s["modo"] == "pct" else f"{s['nivel']} {s['operador']} +{s['offset_pct']}%"
    tp = _lee_tp(individuo["tp"])
    txt = f"Entrada: {'  AND  '.join(partes)}  ·  Stop: {stop}  ·  TP: {tp}"
    parciales = individuo.get("parciales") or []
    if parciales:
        txt += "  ·  Parciales: " + ", ".join(
            f"{p['cierre_pct']}% {_lee_tp(p)}" for p in parciales)
    return txt


# ── Traduccion al motor ─────────────────────────────────────────────────────

def _cfg_indicador(nombre: str, params: dict) -> dict:
    d = {"name": nombre, "offset": 0}
    d.update({k: v for k, v in params.items() if v is not None})
    return d


def _condicion_motor(c: dict) -> dict:
    obj = c["objetivo"]
    target = _cfg_indicador(obj["ind"], obj.get("params", {})) if isinstance(obj, dict) else float(obj)
    return {
        "type": "indicator_comparison",
        "source": _cfg_indicador(c["ind"], c["params"]),
        "comparator": c["comp"],
        "target": target,
        "timeframe": "1m",
    }


def _hard_stop(s: dict) -> dict:
    if s["modo"] == "pct":
        return {"type": "Percentage", "value": float(s["valor"])}
    return {"type": "Market Structure (HOD/LOD)", "value": s["nivel"], "operator": s["operador"],
            "offset_pct": float(s["offset_pct"])}


def _take_profit(t: dict) -> dict:
    if t["modo"] == "pct":
        return {"type": "Percentage", "value": float(t["valor"])}
    if t["modo"] == "hora":
        return {"type": "Hour", "value": str(t["valor"])}
    return {"type": "Time", "value": float(t["valor"])}


def _distancia_parcial(p: dict):
    """El `distance_pct` de un parcial, que NO siempre es un porcentaje.

    El motor (`_parse_partial_tps`) admite cuatro formas en el mismo campo:
    un numero (% de distancia), "HOUR:HH:MM", "TIME:minutos" y "EOD". Son
    CADENAS con prefijo, no un campo `type` aparte como en el take profit
    normal — de ahi que esto no se pueda reutilizar de `_take_profit`.
    """
    if p["modo"] == "pct":
        return float(p["valor"])
    if p["modo"] == "hora":
        return f"HOUR:{p['valor']}"          # "HOUR:09:30"
    return f"TIME:{float(p['valor'])}"       # "TIME:60.0"


def _parciales_motor(individuo: dict) -> list:
    """Los parciales del individuo, en la forma que espera el motor.

    `capital_pct` va en PORCENTAJE (50 = la mitad): el motor lo divide entre
    100 al compilar. Mandarlo ya en fraccion cerraria el 0,5 % de la posicion.
    """
    return [{"distance_pct": _distancia_parcial(p),
             "capital_pct": float(p["cierre_pct"])}
            for p in individuo.get("parciales") or []]


def a_definicion(individuo: dict, config: dict) -> dict:
    """Individuo + config de la corrida -> `definition` que entiende run_backtest."""
    riesgo = config.get("riesgo", {})
    conds = [copy.deepcopy(g) for g in config.get("guardas", [])]
    conds += [_condicion_motor(c) for c in individuo["condiciones"]]
    return {
        "bias": config.get("sesgo", "short"),
        "apply_day": "gap_day",
        "postgap_preconditions": None,
        "entry_logic": {
            "timeframe": "1m",
            "root_condition": {"type": "group", "operator": "AND", "conditions": conds},
            "entry_time_windows": config.get("ventana_entrada") or None,
            "candle_delay": None,
        },
        "exit_logic": None,
        "risk_management": {
            # EL HIBRIDO IMPLICA `size_by_sl`. Es «por distancia al stop, pero
            # con techo de exposición»: sin el size_by_sl no iria por distancia
            # y el techo no recortaria nada — quedaria puesto y sin efecto.
            "size_by_sl": bool(riesgo.get("size_by_sl", False)) or bool(riesgo.get("hybrid_stop", False)),
            "hybrid_stop": bool(riesgo.get("hybrid_stop", False)),
            "hybrid_black_swan_pct": riesgo.get("hybrid_black_swan_pct"),
            "hybrid_max_loss_pct": riesgo.get("hybrid_max_loss_pct"),
            "use_hard_stop": True,
            "use_take_profit": True,
            # «Partial» SOLO si de verdad hay niveles. El motor ignora
            # `partial_take_profits` en modo "Full", asi que dejarlo en Full con
            # la lista llena los tiraria en silencio — y al reves, ponerlo en
            # Partial con la lista vacia dejaria la estrategia sin objetivo.
            "take_profit_mode": "Partial" if individuo.get("parciales") else "Full",
            "accept_reentries": bool(riesgo.get("accept_reentries", True)),
            "max_reentries": int(riesgo.get("max_reentries", -1)),
            "hard_stop": _hard_stop(individuo["stop"]),
            "take_profit": _take_profit(individuo["tp"]),
            "partial_take_profits": _parciales_motor(individuo),
            "trailing_stop": {"active": False, "type": "Percentage", "buffer_pct": 0.5},
            "swing_option": {"active": False, "target_day": "gap_1_day"},
        },
        "market_sessions": list(config.get("sesiones", ["rth"])),
        "custom_start_time": config.get("hora_ini"),
        "custom_end_time": config.get("hora_fin"),
    }
