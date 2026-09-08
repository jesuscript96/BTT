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

# La SESION DE MERCADO no es una ruta: son tres claves de la definicion a la vez
# (`market_sessions` + las dos horas personalizadas). Y va en TRES genes, no en
# uno:
#
#   __sesion_tipo__   categorico: "rth", "pre+rth", "custom"…
#   __sesion_desde__  hora, en minutos desde medianoche
#   __sesion_hasta__  hora, en minutos desde medianoche
#
# POR QUE TRES Y NO UNO. La primera version era un solo gen categorico con una
# lista cerrada de sesiones, y Jaume dio con el agujero enseguida: «me refiero a
# elegir entre que horas quiero que mire, quizas quiero ver si cerrando a las 11
# es mejor que a las 12». Con una lista cerrada eso no se puede barrer. Con las
# horas como genes numericos, si — y con el mismo tratamiento que la ventana de
# entrada, que ya funcionaba asi.
GEN_SESION_TIPO = "__sesion_tipo__"
GEN_SESION_DESDE = "__sesion_desde__"
GEN_SESION_HASTA = "__sesion_hasta__"
# Genes de ESTRUCTURA de los parciales: no afinan un numero, cambian la
# estrategia (cuantos parciales hay y de que tipo es cada uno). Peticion
# explicita de Jaume: «quiero probar que pasa si añado 3 o 5 parciales, ya sea
# por hora, minutos o distancia... aunque modifique la estrategia».
GEN_PARCIALES_N = "__parciales_n__"      # cuantos niveles
GEN_PARCIAL = "__parcial__"              # "__parcial__:{i}" -> el nivel i
PARCIALES_MAX = 5


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
        # Disparador de un parcial: "pct:6" -> "al +6 %". Viaja codificado para
        # poder ordenarlo como rejilla, pero en la receta se lee en cristiano.
        txt = str(valor)
        tipo, _, resto = txt.partition(":")
        if tipo == "pct" and resto:
            return f"al +{resto} %"
        if tipo == "hora" and resto:
            return f"a las {resto}"
        if tipo == "tiempo" and resto:
            return f"a los {resto} min"
        return txt
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
    gs = _por_id(config)
    vals = individuo.get("valores") or {}

    # LOS PARCIALES VAN PRIMERO, porque reconstruyen la lista entera. Si un gen
    # de ruta (`partial_take_profits.0.distance_pct`) escribiera despues sobre
    # una lista recien creada, `_encode_tp_value` releeria la forma NUEVA: un
    # nivel puesto a "HOUR:10:30" al que luego se le escribe un 6 saldria como
    # "HOUR:00:06". Por eso, si hay estructura, las rutas de parciales se
    # ignoran — la estructura manda y no hay dos genes peleandose por lo mismo.
    hay_estructura = _aplicar_parciales(base, vals, gs)
    _aplicar_sesiones(base, vals, gs)

    for gid, valor in vals.items():
        g = gs.get(gid)
        if not g or valor is None:
            continue
        ruta = g.get("path")
        if ruta in (GEN_SESION_TIPO, GEN_SESION_DESDE, GEN_SESION_HASTA):
            continue          # se aplican juntos, mas abajo
        if not ruta or str(ruta).startswith(GEN_PARCIAL) or ruta == GEN_PARCIALES_N:
            continue
        if hay_estructura and "partial_take_profits" in ruta:
            continue
        v = int(round(float(valor))) if _es_entero(g) else valor
        try:
            _set_nested_value(base, ruta, v)
        except Exception:
            # Una ruta que ya no existe en la definicion (la estrategia se
            # edito despues de configurar la corrida) NO puede tumbar la
            # evaluacion entera: se ignora ese gen y el resto sigue.
            continue

    # LAS GUARDAS VAN LAS ULTIMAS, DESPUES DE ESCRIBIR LOS GENES. No es una
    # preferencia de estilo: `_meter_guardas` las mete DELANTE de la logica de
    # entrada, asi que corre todos los indices del grupo raiz. Los genes traen
    # rutas por POSICION (`...conditions.4.source.offset`) calculadas sobre la
    # estrategia SIN guardas, en `extract_parameters`. Metiendolas antes, cada
    # gen escribia en la condicion equivocada.
    #
    # Lo que pasaba de verdad (Jaume, 7-sep-2026, 4 guardas): el gen
    # "PM High Gap (%) Target Value = 50" caia en `conditions.0`, que ya no era
    # el PM High Gap sino la primera guarda `Bar Close > 0.7`, y la convertia en
    # `Bar Close > 50`. En small caps de 1-7 $ eso no lo pasa casi nadie: la
    # estrategia bajaba de 1.721 operaciones a 21, TODA la poblacion se quedaba
    # por debajo del minimo de trades y la corrida entera daba fitness 0. Sin
    # una sola excepcion y sin nada raro en la pantalla.
    _meter_guardas(base, config.get("guardas") or [])
    return base


PRESETS_SESION = {
    "pre": (240, 570), "rth": (570, 960), "post": (960, 1200),
}


def _hora(mins) -> str:
    m = int(round(float(mins))) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _minutos(txt, defecto: int) -> int:
    try:
        h, _, mi = str(txt).partition(":")
        return int(h) * 60 + int(mi)
    except (TypeError, ValueError):
        return defecto


def _aplicar_sesiones(base: dict, vals: dict, gs: dict) -> None:
    """La sesion de mercado: tipo + las dos horas, aplicadas JUNTAS.

    Reglas, y estan escritas asi porque cada una tapa un agujero:

    1. Si el gen de TIPO esta marcado, el manda.
    2. Si NO lo esta pero si alguna HORA, la sesion pasa a personalizada: pedir
       «prueba a cerrar a las 11 o a las 12» solo tiene sentido con horas
       propias, y dejarla en RTH haria que el barrido no cambiara nada — sin
       error, con las N corridas dando el mismo numero.
    3. La punta que no se barre se queda en la que tenga hoy la estrategia.
    4. Fuera de personalizada, las horas se BORRAN. Dejarlas puestas es el lio
       de la union de sesiones del 6-sep.
    """
    ids = {g.get("path"): gid for gid, g in gs.items()}
    id_tipo = ids.get(GEN_SESION_TIPO)
    id_desde = ids.get(GEN_SESION_DESDE)
    id_hasta = ids.get(GEN_SESION_HASTA)
    if not (id_tipo or id_desde or id_hasta):
        return

    sesiones_hoy = list(base.get("market_sessions") or ["rth"])
    if "custom" in sesiones_hoy:
        d_hoy = _minutos(base.get("custom_start_time"), 570)
        h_hoy = _minutos(base.get("custom_end_time"), 960)
    else:
        rangos = [PRESETS_SESION[s] for s in sesiones_hoy if s in PRESETS_SESION] or [(570, 960)]
        d_hoy = min(r[0] for r in rangos)
        h_hoy = max(r[1] for r in rangos)

    tipo = str(vals.get(id_tipo)) if id_tipo and vals.get(id_tipo) is not None else None
    hay_horas = (id_desde and vals.get(id_desde) is not None) or                 (id_hasta and vals.get(id_hasta) is not None)

    if tipo is None and hay_horas:
        tipo = "custom"
    if tipo is None:
        return

    if tipo != "custom":
        base["market_sessions"] = [x for x in tipo.split("+") if x]
        base.pop("custom_start_time", None)
        base.pop("custom_end_time", None)
        return

    desde = vals.get(id_desde) if id_desde is not None else None
    hasta = vals.get(id_hasta) if id_hasta is not None else None
    d = int(round(float(desde))) if desde is not None else d_hoy
    h = int(round(float(hasta))) if hasta is not None else h_hoy
    if h <= d:
        # Una sesion invertida no da error: recorta el dia a CERO velas y el
        # individuo sale con 0 operaciones, o sea nota 0. Se deja pasar a
        # proposito (el genetico lo descarta solo) pero al menos no se escribe
        # una sesion imposible: se le da un minuto.
        h = d + 1
    base["market_sessions"] = ["custom"]
    base["custom_start_time"] = _hora(d)
    base["custom_end_time"] = _hora(h)


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


# ── Parciales: cuantos y de que tipo ────────────────────────────────────────

def _decodifica_parcial(txt: str):
    """"pct:6" -> 6.0 · "hora:10:30" -> "HOUR:10:30" · "tiempo:30" -> "TIME:30"

    Devuelve el `distance_pct` con la forma EXACTA que espera el motor (ver
    `_decode_tp_value` en optimization_service). Una forma mal escrita no da
    error: el parcial se descarta y la estrategia sale sin el.
    """
    tipo, _, valor = str(txt).partition(":")
    tipo = tipo.strip().lower()
    valor = valor.strip()
    if tipo == "hora":
        return f"HOUR:{valor}"
    if tipo == "tiempo":
        return f"TIME:{int(float(valor))}"
    try:
        return float(valor)
    except ValueError:
        return None


def _reparto_capital(n: int) -> list[float]:
    """A partes iguales, y el ULTIMO se lleva el resto.

    El motor exige que los parciales sumen exactamente 100 % — si no, o deja
    posicion sin cerrar o cierra de mas. Repartir a partes iguales lo garantiza
    sin meter n dimensiones mas de sobreajuste. Para repartos desiguales estan
    los genes de ruta `partial_take_profits.i.capital_pct`, que se usan cuando
    NO se toca la estructura.
    """
    if n <= 0:
        return []
    base = round(100.0 / n, 2)
    reparto = [base] * n
    reparto[-1] = round(100.0 - base * (n - 1), 2)
    return reparto


def _aplicar_parciales(base: dict, vals: dict, gs: dict) -> bool:
    """Reconstruye `partial_take_profits` si hay genes de estructura.

    Devuelve True si ha tocado algo (y entonces las rutas de parciales se
    ignoran aguas arriba).
    """
    id_n = next((gid for gid, g in gs.items()
                 if g.get("path") == GEN_PARCIALES_N), None)
    ids_nivel = sorted(
        ((gid, g) for gid, g in gs.items()
         if str(g.get("path", "")).startswith(GEN_PARCIAL + ":")),
        key=lambda kv: int(str(kv[1]["path"]).split(":", 1)[1]))
    if id_n is None and not ids_nivel:
        return False

    rm = base.setdefault("risk_management", {})
    if id_n is not None and vals.get(id_n) is not None:
        n = max(0, int(round(float(vals[id_n]))))
    else:
        n = len(rm.get("partial_take_profits") or [])
    n = min(n, PARCIALES_MAX, max(1, len(ids_nivel)) if ids_nivel else PARCIALES_MAX)

    niveles = []
    reparto = _reparto_capital(n)
    for i in range(n):
        if i < len(ids_nivel):
            crudo = vals.get(ids_nivel[i][0])
        else:
            crudo = None
        distancia = _decodifica_parcial(crudo) if crudo is not None else None
        if distancia is None:
            # Sin gen para ese hueco se conserva el que ya tenia la estrategia;
            # y si tampoco lo hay, el nivel no se inventa.
            previos = rm.get("partial_take_profits") or []
            if i < len(previos):
                distancia = previos[i].get("distance_pct")
            if distancia is None:
                continue
        niveles.append({"distance_pct": distancia, "capital_pct": reparto[i]})

    if niveles:
        # Reajuste por si algun nivel se cayo: los que quedan tienen que sumar
        # 100, o el motor deja posicion abierta sin objetivo.
        r = _reparto_capital(len(niveles))
        for lv, cap in zip(niveles, r):
            lv["capital_pct"] = cap
        rm["partial_take_profits"] = niveles
        rm["take_profit_mode"] = "Partial"
    else:
        # CERO parciales es una opcion legitima: es la comparacion contra no
        # ponerlos. En «Full» el motor ignora la lista y manda `take_profit`.
        rm["partial_take_profits"] = []
        rm["take_profit_mode"] = "Full"
    return True
