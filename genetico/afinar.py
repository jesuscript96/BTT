"""Modo «MEJORAR»: el genetico afina UNA estrategia en vez de buscar otras.

EL MODO «EXPLORAR» NO SE TOCA. Este modulo es una segunda especie de cromosoma
que vive al lado del de `cromosoma.py`, con las MISMAS funciones publicas
(`aleatorio`, `mutar`, `cruzar`, `canonico`, `huella`, `receta`,
`a_definicion`). `motor.py` elige una u otra segun `config["modo"]`, asi que el
explorador corre exactamente por donde corria.

POR QUE UN CROMOSOMA DISTINTO Y NO REUTILIZAR EL DE EXPLORAR. `cromosoma.
a_definicion()` va en un solo sentido y da mucho por fijo:

    "exit_logic": None,  "postgap_preconditions": None,
    "apply_day": "gap_day",  "timeframe": "1m",  trailing y swing apagados

Convertir una estrategia hecha a mano a ese cromosoma le arrancaria su logica
de salida, sus precondiciones, su temporalidad y su retardo de velas — y en
silencio, que es como duelen. Aqui el individuo ES la definicion de la
estrategia: se parte de la semilla INTACTA y solo se escriben las rutas que el
usuario haya marcado. Lo que no se marca queda congelado tal cual.

QUE ES UN GEN. Una ruta dentro de la definicion (`risk_management.hard_stop.
value`, `entry_logic.entry_time_windows.0.from_time`, …) con su rejilla de
valores. La lista sale del propio `extract_parameters` del optimizador 3D, que
ya sabe leer los indicadores y parametros de una estrategia con su rango, su
paso y su unidad. Escribir de vuelta lo hace `_set_nested_value`, que ademas
reescribe "HH:MM" donde toca. Las dos funciones ya estaban probadas.

EL RANGO LO ELIGE EL USUARIO, como en el optimizador 3D: cada gen llega con su
`min`/`max`/`step` (o su lista de `opciones` si es categorico).
"""
from __future__ import annotations

import copy
import hashlib
import json
import random

# Gen categorico que NO es una ruta: la sesion de mercado son varias claves de
# la definicion a la vez (`market_sessions` + las horas personalizadas).
GEN_SESIONES = "__sesiones__"


def _es_entero(gen: dict) -> bool:
    """Minutos de reloj y periodos no tienen decimales."""
    if gen.get("is_int"):
        return True
    return str(gen.get("unit") or "") in ("minutes", "time_of_day")


def _rejilla(gen: dict) -> list:
    """Los valores que puede tomar un gen. Es una LISTA, no un rango continuo:

    el genetico muta «un escalon», y para eso hace falta saber cual es el
    escalon de al lado. Es la misma idea que las rejillas del catalogo del
    explorador (`_vecino`).
    """
    if gen.get("opciones"):
        return list(gen["opciones"])
    lo = float(gen.get("min", 0))
    hi = float(gen.get("max", lo))
    paso = float(gen.get("step") or 0) or (hi - lo) / 10 or 1.0
    if hi < lo:
        lo, hi = hi, lo
    entero = _es_entero(gen)
    vals, v, tope = [], lo, 0
    # El tope de 500 es un cinturon: un paso de 0,001 sobre un rango de 100
    # generaria 100.000 valores y el «escalon de al lado» dejaria de significar
    # nada. No es un limite de diseno, es un guardarrail.
    while v <= hi + 1e-9 and tope < 500:
        vals.append(int(round(v)) if entero else round(v, 6))
        v += paso
        tope += 1
    if not vals:
        vals = [int(round(lo)) if entero else lo]
    # Ordenados y sin repetidos: con paso entero y rango corto salen duplicados.
    return sorted(set(vals))


def genes(config: dict) -> list[dict]:
    """Los genes de la corrida, ya normalizados y con su rejilla resuelta.

    Se cachea en el propio config porque esto se llama en cada mutacion y en
    cada cruce, miles de veces por generacion.
    """
    cache = config.get("_genes_resueltos")
    if cache is not None:
        return cache
    out = []
    for g in config.get("genes") or []:
        g = dict(g)
        g["_rejilla"] = _rejilla(g)
        out.append(g)
    config["_genes_resueltos"] = out
    return out


def _por_id(config: dict) -> dict:
    return {g["id"]: g for g in genes(config)}


# ── Individuos ──────────────────────────────────────────────────────────────

def desde_semilla(config: dict) -> dict:
    """El individuo que ES la estrategia de partida, tal cual esta hoy.

    Es la LINEA BASE de la corrida: sin ella no se puede saber si el genetico
    ha mejorado algo o solo ha encontrado otro sitio parecido.
    """
    vals = {}
    for g in genes(config):
        actual = g.get("current_value")
        rej = g["_rejilla"]
        if actual is None:
            vals[g["id"]] = rej[len(rej) // 2]
            continue
        if g.get("opciones"):
            vals[g["id"]] = actual if actual in rej else rej[0]
        else:
            # El valor de hoy puede no caer en la rejilla que ha elegido el
            # usuario: se coge el escalon mas cercano, no se inventa uno nuevo.
            vals[g["id"]] = min(rej, key=lambda x: abs(float(x) - float(actual)))
    return {"valores": vals}


def aleatorio(config: dict, rng: random.Random) -> dict:
    return {"valores": {g["id"]: rng.choice(g["_rejilla"]) for g in genes(config)}}


def _vecino(valor, rejilla: list, rng: random.Random):
    """Un escalon arriba o abajo (70%) o cualquier valor (30%).

    Misma regla que el explorador. El 70% es lo que hace que el genetico
    RECORRA la rejilla en vez de saltar al azar, que es justo lo que se necesita
    para que una meseta se note.
    """
    if valor in rejilla and len(rejilla) > 1 and rng.random() < 0.7:
        i = rejilla.index(valor)
        j = max(0, min(len(rejilla) - 1, i + rng.choice((-1, 1))))
        return rejilla[j]
    return rng.choice(rejilla)


def mutar(ind: dict, config: dict, rng: random.Random) -> dict:
    """Cada gen muta con probabilidad `p_mutacion`; al menos uno muta siempre.

    Lo de «al menos uno» no es cosmetico: sin eso la mutacion puede devolver un
    clon, el clon ya esta en la cache y la generacion se queda sin individuos
    nuevos que evaluar.
    """
    gs = genes(config)
    if not gs:
        return copy.deepcopy(ind)
    p = float(config.get("p_mutacion", 0.25))
    nuevo = {"valores": dict(ind["valores"])}
    tocado = False
    for g in gs:
        if rng.random() < p:
            antes = nuevo["valores"].get(g["id"])
            despues = _vecino(antes, g["_rejilla"], rng)
            nuevo["valores"][g["id"]] = despues
            # `tocado` tiene que significar CAMBIO, no intento: `_vecino`
            # sortea de toda la rejilla un 30 % de las veces y puede devolver
            # el mismo valor. Marcandolo como tocado, el respaldo de abajo no
            # se ejecutaba y salia un clon.
            if despues != antes:
                tocado = True
    if not tocado:
        # OJO: aqui NO vale `_vecino`. Un 30 % de las veces sortea de toda la
        # rejilla y puede caer en el MISMO valor — o sea que el «al menos uno
        # muta» no garantizaba nada, y el clon resultante ya esta en la cache:
        # la generacion se queda sin individuos nuevos que evaluar y el
        # genetico se estanca sin dar ningun error. Cazado por
        # test_mutar_siempre_cambia_algo.
        for g in rng.sample(gs, len(gs)):
            rej = g["_rejilla"]
            if len(rej) < 2:
                continue
            actual = nuevo["valores"].get(g["id"])
            otros = [v for v in rej if v != actual]
            if otros:
                # Se prefiere un escalon contiguo, como en `_vecino`.
                if actual in rej:
                    i = rej.index(actual)
                    contiguos = [rej[j] for j in (i - 1, i + 1) if 0 <= j < len(rej)]
                    nuevo["valores"][g["id"]] = rng.choice(contiguos or otros)
                else:
                    nuevo["valores"][g["id"]] = rng.choice(otros)
                break
    return nuevo


def cruzar(a: dict, b: dict, config: dict, rng: random.Random) -> dict:
    """Cruce uniforme: cada gen se coge de un padre a cara o cruz."""
    va, vb = a["valores"], b["valores"]
    return {"valores": {g["id"]: (va if rng.random() < 0.5 else vb).get(g["id"])
                        for g in genes(config)}}


# ── Identidad ───────────────────────────────────────────────────────────────

def canonico(individuo: dict) -> dict:
    return {"valores": {k: individuo["valores"][k] for k in sorted(individuo["valores"])}}


def huella(individuo: dict) -> str:
    return hashlib.md5(
        json.dumps(canonico(individuo), sort_keys=True, default=str).encode()
    ).hexdigest()[:12]


def _leer(gen: dict, valor) -> str:
    if valor is None:
        return "—"
    if str(gen.get("unit") or "") == "time_of_day":
        m = int(round(float(valor))) % 1440
        return f"{m // 60:02d}:{m % 60:02d}"
    if gen.get("opciones"):
        return str(valor)
    v = float(valor)
    return str(int(v)) if abs(v - round(v)) < 1e-9 else f"{v:g}"


def receta(individuo: dict, config: dict | None = None) -> str:
    """Lectura humana. Sin `config` no hay etiquetas: se cae al id del gen,
    que es feo pero no revienta (la pagina siempre pasa el config)."""
    gs = _por_id(config) if config else {}
    partes = []
    for k in sorted(individuo.get("valores", {})):
        g = gs.get(k, {"label": k})
        partes.append(f"{g.get('label', k)} {_leer(g, individuo['valores'][k])}")
    return "  ·  ".join(partes) if partes else "(sin genes)"


# ── Traduccion al motor ─────────────────────────────────────────────────────

def a_definicion(individuo: dict, config: dict) -> dict:
    """Semilla INTACTA + los genes escritos encima.

    Todo lo que el usuario no haya marcado queda exactamente como estaba: esa
    es la diferencia con el modo explorar, donde la definicion se construye
    entera desde el cromosoma.
    """
    from app.services.optimization_service import _set_nested_value

    base = copy.deepcopy(config.get("estrategia_base") or {})
    _meter_guardas(base, config.get("guardas") or [])
    gs = _por_id(config)
    for gid, valor in (individuo.get("valores") or {}).items():
        g = gs.get(gid)
        if not g or valor is None:
            continue
        if gid == GEN_SESIONES or g.get("path") == GEN_SESIONES:
            _aplicar_sesiones(base, valor)
            continue
        ruta = g.get("path")
        if not ruta:
            continue
        v = int(round(float(valor))) if _es_entero(g) else valor
        try:
            _set_nested_value(base, ruta, v)
        except Exception:
            # Una ruta que ya no existe en la definicion (la estrategia se
            # edito despues de configurar la corrida) NO puede tumbar la
            # evaluacion entera: se ignora ese gen y el resto sigue.
            continue
    return base


def _aplicar_sesiones(base: dict, valor) -> None:
    """El gen de sesion toca TRES claves a la vez, por eso no es una ruta.

    Formato del valor: "rth", "pre+rth", o "custom:04:00-11:30".
    """
    txt = str(valor)
    if txt.startswith("custom:"):
        rango = txt.split(":", 1)[1]
        desde, _, hasta = rango.partition("-")
        base["market_sessions"] = ["custom"]
        base["custom_start_time"] = desde.strip()
        base["custom_end_time"] = hasta.strip()
        return
    base["market_sessions"] = [s for s in txt.split("+") if s]
    # Sin «custom» las horas personalizadas sobran: dejarlas puestas seria
    # sembrar el mismo lio de la union de sesiones que se arreglo el 6-sep.
    base.pop("custom_start_time", None)
    base.pop("custom_end_time", None)


def indices(individuo: dict, config: dict) -> tuple:
    """Posicion del individuo en la rejilla, gen a gen.

    Es lo que permite medir «a cuantos escalones esta» un individuo de otro, y
    con eso puntuar por VECINDARIO en vez de por su propio numero: un pico
    aislado tiene vecinos malos, una meseta no. Es el «robust plateau» del
    optimizador 3D, pero en tantas dimensiones como genes haya.
    """
    out = []
    for g in genes(config):
        rej = g["_rejilla"]
        v = individuo.get("valores", {}).get(g["id"])
        try:
            out.append(rej.index(v))
        except ValueError:
            # Un valor fuera de rejilla (config cambiada a mitad de corrida):
            # se le da el escalon mas cercano en vez de romper la comparacion.
            if g.get("opciones") or not rej:
                out.append(0)
            else:
                out.append(min(range(len(rej)),
                               key=lambda i: abs(float(rej[i]) - float(v or 0))))
    return tuple(out)


def _meter_guardas(base: dict, guardas: list) -> None:
    """Las guardas fijas de la corrida, delante de la logica de entrada.

    Mismas casillas que en el modo explorar (precio minimo, liquidez…): filtros
    que tienen que cumplirse SIEMPRE y que el genetico no toca.

    OJO CON EL OPERADOR. Meterlas dentro del grupo raiz solo vale si ese grupo
    es un AND. Si la estrategia entra con un OR, colar una guarda dentro la
    convertiria en «o esto o la guarda», que es lo contrario de una guarda. En
    ese caso se envuelve: AND(guardas…, logica original).
    """
    if not guardas:
        return
    el = base.setdefault("entry_logic", {})
    raiz = el.get("root_condition") or {"type": "group", "operator": "AND", "conditions": []}
    gs = [copy.deepcopy(g) for g in guardas]
    if str(raiz.get("operator", "AND")).upper() == "AND":
        raiz = dict(raiz)
        raiz["conditions"] = gs + list(raiz.get("conditions") or [])
    else:
        raiz = {"type": "group", "operator": "AND", "conditions": gs + [raiz]}
    el["root_condition"] = raiz
