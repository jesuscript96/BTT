"""Catalogo de genes: que puede elegir el genetico y con que valores.

Es DATOS, no logica: cada entrada dice como se llama el indicador para el
motor (`IndicatorType` del frontend / `compute_indicator` del backend), que
parametros admite y de que lista salen, contra que se compara y con que
comparadores. Ampliar el catalogo = anadir una entrada.

LOS NOMBRES NO SE INVENTAN. Cada `nombre` tiene que existir tal cual en
`IndicatorType` (frontend/src/types/strategy.ts) Y resolverse en
`indicators.py`. Un nombre que no exista NO da error: la condicion se evalua
como falsa, el individuo no opera nunca y el genetico lo descarta por malo. Se
pierde un gen entero sin que nadie se entere. Lo comprueba
`tests/test_genetico_catalogo.py`.

CADA PARAMETRO CON VARIAS OPCIONES SE SORTEA POR INDIVIDUO. Poner
`{"band_line": ["Upper", "Lower"]}` NO significa elegir uno: significa que el
genetico probara los dos a lo largo de la poblacion y se quedara con el que
funcione. Es la respuesta a la duda de Jaume del 2026-09-04 sobre el Darvas —
si se mete, prueba por arriba y por abajo, no se queda en uno.

Regla de la v1 (Jaume): indicadores simples. Fuera «High/Low of last X days»
(necesita el lago) y los de distancia (se haran como indicador directo mas
adelante).
"""
from __future__ import annotations

from dataclasses import dataclass, field

GT, LT, GTE, LTE = "GREATER_THAN", "LESS_THAN", "GREATER_THAN_OR_EQUAL", "LESS_THAN_OR_EQUAL"
CRUZA_ARRIBA, CRUZA_ABAJO = "CROSSES_ABOVE", "CROSSES_BELOW"

SIMBOLO = {GT: ">", LT: "<", GTE: "≥", LTE: "≤", "EQUAL": "=",
           CRUZA_ARRIBA: "cruza arriba", CRUZA_ABAJO: "cruza abajo"}

# Familias para agrupar la lista en la pagina. Sin esto son treinta casillas
# seguidas y no hay forma de elegir: hay que poder marcar «volumen» de un
# vistazo sin leerse la lista entera. El orden de aqui es el de la pantalla.
FAMILIAS = (
    ("precio", "Precio y niveles"),
    ("momento", "Momento"),
    ("patrones", "Patrones y velas"),
    ("caidas", "Caídas y gaps"),
    ("volumen", "Volumen"),
    ("tiempo", "Tiempo"),
    # Los del 9 y 10-sep-2026: regresion, absorcion, mecha, retroceso, pivote y
    # perfil de volumen. Mismo bloque aparte que en el constructor de
    # condiciones, y por la misma razon: mezclados con RSI y SMA se esconden.
    ("alternativos", "Alternativos"),
)


@dataclass(frozen=True)
class Indicador:
    nombre: str
    # A que grupo va en la pantalla. Una de las claves de FAMILIAS.
    familia: str = "precio"
    # parametro -> lista de valores posibles (cada uno es un gen)
    params: dict = field(default_factory=dict)
    # rejilla de numeros contra los que comparar (vacia = no se compara con numero)
    valores: tuple = ()
    # otros indicadores del catalogo validos como lado derecho (vacia = ninguno)
    objetivos: tuple = ()
    comparadores: tuple = (GT, LT)
    # Una linea para la pantalla: que hace y para que sirve, no la formula.
    ayuda: str = ""
    # Si viene marcado al abrir la pagina. SOLO los siete de la v1, que son
    # los que Jaume ya venia usando, y los nueve niveles base (que siempre
    # entraron como destino; la casilla es para poder QUITARLOS). Marcar los
    # demas dispararia el espacio de busqueda y contradice lo que dice la
    # propia pantalla: «menos indicadores bien elegidos buscan mejor que el
    # catalogo entero, cada uno que no aporta anyade formas de encontrar
    # casualidades».
    por_defecto: bool = False
    # NIVEL OPCIONAL: no forma condiciones por si mismo («Punto de control > 3»
    # no dice nada). Marcarlo en la pagina lo mete como DESTINO de Bar Close /
    # High Bar / Low Bar; sin marcar, no aparece en ninguna receta. Asi los
    # niveles del perfil de volumen y el pivote no cambian las corridas de
    # quien no los pida — la lista de destinos de siempre sigue igual.
    solo_destino: bool = False

    def etiqueta(self, params: dict) -> str:
        return etiqueta(self.nombre, params)


def etiqueta(nombre: str, params: dict | None) -> str:
    """«RSI(14)», «Darvas Box(Lower, 3)»… y para la familia de picos «Pico
    nº2(3, up)»: el numero de giro va fuera del parentesis porque es lo que
    distingue «Pico nº1 < Pico nº2» de «Pico nº2 < Pico nº1», y entre tres
    parametros sueltos no se leia."""
    params = params or {}
    rank = params.get("pivot_rank")
    resto = [f"{v}" for k, v in sorted(params.items()) if v is not None and k != "pivot_rank"]
    base = f"{nombre} nº{rank}" if rank is not None else nombre
    return f"{base}({', '.join(resto)})" if resto else base


# Indicadores que solo sirven como lado DERECHO (niveles / velas previas).
#
# Son NIVELES: un precio contra el que cruzar. No van de lado izquierdo porque
# «Prev. Bar Low > 3» no dice nada — lo que interesa es que el precio los cruce.
NIVELES = ("Prev. Bar Low", "Prev. Bar High", "Prev. Bar Close", "Prev. Bar Open",
           "VWAP", "PM High", "PM Low", "Previous max", "Previous min")
# 21-sep-2026: estos nueve tambien salen en la pagina, con su casilla y marcados
# de serie (Jaume: «no tiene en cuenta ... previous max y min, Prev. Bar
# close...»; no era que no entraran, era que no se veian ni se podian quitar).
# Ver `objetivos_permitidos`: un config sin `niveles_explicitos` (los
# anteriores a hoy) sigue sorteando los nueve como siempre.
NIVELES_BASE = NIVELES

# Niveles que ADEMAS tienen parametros propios. El cromosoma se los sortea igual
# que al lado izquierdo: sin esto un Donchian saldria siempre con el periodo por
# defecto y no se probaria nada.
NIVELES_CON_PARAMS: dict[str, dict] = {
    "SMA": {"period": [9, 20, 50, 200]},
    "EMA": {"period": [9, 20, 50, 200]},
    # Las tres lineas de cada banda se sortean: probando solo la de arriba se
    # quedaria media herramienta sin usar.
    "Bollinger Bands": {"period": [14, 20], "std_dev": [1.5, 2.0, 2.5],
                        "band_line": ["Upper", "Lower", "Basis"]},
    "Donchian": {"period": [10, 20, 55], "band_line": ["Upper", "Lower", "Basis"]},
    # `period` = velas de confirmacion de la caja (3 es el Darvas clasico).
    "Darvas Box": {"period": [3, 5], "band_line": ["Upper", "Lower", "Basis"]},
    # "Overhead last X days": el techo (o suelo) que dejo un dia pasado, sobre
    # velas DIARIAS. Se sortean los cuatro parametros: sin esto saldria siempre
    # con 20 dias, el High y sin condicion de volumen, que es UNA de las 120
    # combinaciones posibles.
    "Overhead last X days": {
        "days_lookback": [5, 20, 60, 120, 250],
        "overhead_extreme": ["max", "min"],
        "overhead_ref": ["high", "low", "open", "close"],
        "overhead_vol_rule": ["none", "gt", "lt"],
    },
}

# NIVELES OPCIONALES (10-sep-2026): el ultimo pivote y el perfil de volumen.
# Son precios como los de arriba, pero NO entran de serie como destino: solo
# si se marcan en la pagina (ver `Indicador.solo_destino` y
# `objetivos_permitidos`). Dos razones. Una, no cambiar las corridas de quien
# no los pida: con cuatro destinos mas, uno de cada cinco «Bar Close cruza…»
# saldrian contra el perfil aunque nadie lo quisiera. Dos, que se pueda
# comparar una corrida CON el perfil y otra SIN, que es la unica forma de
# saber si aporta.
#
# Los parametros se sortean igual que los de SMA o Darvas:
#   · `bin_pct` («Detalle %»): anchura de la franja, % del primer precio del
#     dia. Acotado a 5 en la UI desde que un 90 dio un POC fuera del rango.
#   · `zona_pct`: % del volumen del dia que encierra la zona de valor.
#   · `pivot_window`: velas de confirmacion a cada lado; `swing_dir` techos o suelos.
#
# «Nodo de arriba» y «Nodo de abajo» NO estan, y es a proposito: son RELATIVOS
# al precio (la primera zona por encima / por debajo de donde esta el cierre),
# asi que el cierre esta SIEMPRE al otro lado y nunca los cruza. Medido en un
# dia sintetico de 600 velas: Bar Close cruza el nodo 0 veces; solo la mecha
# de su lado lo pincha (High Bar contra el de arriba, Low Bar contra el de
# abajo). En el genetico serian dos de cada tres condiciones muertas de
# nacimiento. El punto de control y la zona de valor llevan la misma
# informacion y si se cruzan.
NIVELES_OPCIONALES: dict[str, dict] = {
    "Ultimo pivote": {"pivot_window": [2, 3, 5], "swing_dir": ["up", "down"]},
    # El pico/valle ENUMERADO (PRD 18-sep-2026) como destino de Bar Close /
    # High / Low: «Bar Close cruza arriba Pico nº2» = recupera el techo
    # anterior. El nº1 es exactamente «Ultimo pivote», asi que aqui se sortean
    # del 2 al 4: ofrecer el 1 seria el mismo gen dos veces con dos huellas
    # distintas (se evaluaria dos veces lo mismo). Como lado IZQUIERDO
    # («Pico nº1 < Pico nº2», maximos decrecientes) va en CATALOGO con su
    # propia rejilla, que si incluye el 1.
    "Pico": {"pivot_window": [2, 3, 5], "swing_dir": ["up", "down"], "pivot_rank": [2, 3, 4]},
    "Punto de control": {"bin_pct": [0.5, 1.0, 2.0]},
    "Zona alta": {"bin_pct": [0.5, 1.0, 2.0], "zona_pct": [50, 70, 85]},
    "Zona baja": {"bin_pct": [0.5, 1.0, 2.0], "zona_pct": [50, 70, 85]},
}
NIVELES_CON_PARAMS.update(NIVELES_OPCIONALES)

# «Previous max/min» tienen un parametro que CAMBIA el resultado y que el
# genetico nunca sorteo: `ap_session`, desde cuando cuenta el maximo corrido.
# Sin el, el motor cuenta desde las 04:00 (ap.PM), mientras que el constructor
# de condiciones pone ap.RTH (desde las 09:30) por defecto — o sea que la misma
# receta guardada desde el genetico y hecha a mano no eran la misma estrategia.
# Lo cazo test_no_queda_ninguna_rama_del_indicador_sin_probar al darles casilla
# (21-sep-2026). Se sortean las dos.
NIVELES_CON_PARAMS["Previous max"] = {"ap_session": ["ap.PM", "ap.RTH"]}
NIVELES_CON_PARAMS["Previous min"] = {"ap_session": ["ap.PM", "ap.RTH"]}

# Los nueve de siempre primero y en su orden, y despues los que llevan
# parametros (sin repetir Previous max/min, que estan en las dos listas).
TODOS_LOS_NIVELES = NIVELES + tuple(n for n in NIVELES_CON_PARAMS if n not in NIVELES)


# ── Parametros FIJADOS por el usuario en la pagina (21-sep-2026) ───────────
#
# Jaume: «previous max y min tienen que tener en cuenta la sesion en la que
# fijo que se corran las pruebas, y mejor si puedo seleccionar el periodo en el
# que quiero que se enfoquen (igual que el fade, que no lo tiene)».
#
# El motor calcula los indicadores sobre el DIA ENTERO y recorta la sesion
# despues (backtest_service: «indicators have full-day context»), asi que en
# una corrida RTH un «Previous max» con ap.PM incluye el maximo del premercado:
# es otro indicador. `config["params_fijos"]` = {nombre: {param: valor}} con
# valor:
#   "auto"   -> segun la sesion de la corrida (`sesion_de_referencia`)
#   "*"      -> sortear toda la rejilla del catalogo (lo de antes)
#   otro     -> ese valor fijo ("ap.PM", "ap.RTH", "ap.AM")
# Sin la clave (corridas antiguas) se sortea la rejilla, como siempre.
PARAMS_FIJABLES = {
    "ap_session": ("Previous max", "Previous min", "% Fade"),
}
AUTO, SORTEAR = "auto", "*"
# Lo que ofrece el desplegable de la pagina para cada parametro fijable, en
# este orden. El primero es el defecto.
OPCIONES_FIJABLES = {
    "ap_session": (
        # Cortas a proposito: el desplegable vive en una columna de ~180 px.
        (AUTO, "Sesión de la corrida"),
        ("ap.PM", "Desde 04:00 (con PM)"),
        ("ap.RTH", "Desde 09:30 (RTH)"),
        ("ap.AM", "Desde 16:00 (after)"),
        (SORTEAR, "Sortear 04:00 / 09:30"),
    ),
}


def sesion_de_referencia(config: dict | None) -> str:
    """El `ap_session` que corresponde a la sesion de la corrida.

    rth -> ap.RTH (desde las 09:30) · pre -> ap.PM (desde la primera vela) ·
    post -> ap.AM (desde las 16:00) · custom -> segun la hora de inicio ·
    varias sesiones -> la mas temprana (el maximo tiene que incluir todo lo que
    ve el simulador).
    """
    cfg = config or {}
    sesiones = [str(x).lower() for x in (cfg.get("sesiones") or ["rth"])]
    if "custom" in sesiones or "all" in sesiones:
        try:
            h, _, m = str(cfg.get("hora_ini") or "09:30").partition(":")
            mins = int(h) * 60 + int(m)
        except (TypeError, ValueError):
            mins = 570
        if "all" in sesiones or mins < 570:
            return "ap.PM"
        return "ap.RTH" if mins < 960 else "ap.AM"
    if "pre" in sesiones:
        return "ap.PM"
    if "rth" in sesiones:
        return "ap.RTH"
    if "post" in sesiones:
        return "ap.AM"
    return "ap.RTH"


def rejilla_params(nombre: str, config: dict | None, base: dict | None = None) -> dict:
    """La rejilla de parametros de `nombre` en ESTA corrida: la del catalogo
    (`base`, o `CATALOGO[nombre].params` si no se da) con los fijados por el
    usuario reducidos a un solo valor."""
    if base is None:
        base = CATALOGO[nombre].params if nombre in CATALOGO else NIVELES_CON_PARAMS.get(nombre, {})
    rej = {k: list(v) for k, v in base.items()}
    fijos = ((config or {}).get("params_fijos") or {}).get(nombre) or {}
    for k, v in fijos.items():
        if k not in rej or v is None or v == SORTEAR:
            continue
        rej[k] = [sesion_de_referencia(config) if v == AUTO else v]
    return rej


# ── Prioridades por indicador (21-sep-2026) ─────────────────────────────────
#
# Jaume: los niveles base salian 0-1 veces por corrida porque el sorteo los
# trata como una opcion mas de Bar Close (1 de 27 a la izquierda, cara o cruz
# contra numero, 1 de ~20 destinos). La pagina pinta un desplegable por
# indicador marcado y manda config["prioridades"] = {nombre: "alta"|"baja"};
# «normal» no viaja. El peso multiplica la probabilidad de salir en CADA
# sorteo donde el nombre compite (lado izquierdo, destino, cambio de indicador
# al mutar). Con todo en «normal» el sorteo es EXACTAMENTE `rng.choice`: misma
# semilla, misma corrida que antes de existir esto.
PESO_PRIORIDAD = {"alta": 3.0, "normal": 1.0, "baja": 1.0 / 3.0}


def peso(nombre: str, config: dict | None) -> float:
    pri = ((config or {}).get("prioridades") or {}).get(nombre, "normal")
    return PESO_PRIORIDAD.get(pri, 1.0)


def elegir(rng, opciones, config: dict | None, pesos: list[float] | None = None):
    """`rng.choice(opciones)` con las prioridades de la pagina (o con `pesos`
    ya calculados). Si todos los pesos son iguales se llama a `rng.choice` tal
    cual (mismo consumo de azar)."""
    opciones = list(opciones)
    if pesos is None:
        pesos = [peso(n, config) for n in opciones]
    if len(set(pesos)) <= 1:
        return rng.choice(opciones)
    return rng.choices(opciones, weights=pesos, k=1)[0]


def lado_izquierdo(nombres) -> list[str]:
    """Los marcados que pueden ir a la izquierda de una condicion: todo menos
    los niveles opcionales. Si Jaume marca solo «Punto de control», esto
    devuelve vacio y quien llama tiene que quejarse, no sortear un nivel a la
    izquierda de un «>» sin nada contra lo que comparar."""
    return [n for n in nombres if not CATALOGO[n].solo_destino]


def objetivos_permitidos(ind: "Indicador", marcados, explicitos=None) -> tuple:
    """Los destinos de `ind` que valen en ESTA corrida, EN EL ORDEN DE SIEMPRE.

    `marcados` es el catalogo elegido en la pagina (config["catalogo"]).

    - Los niveles OPCIONALES (pivote, Pico, perfil) entran solo si estan marcados.
    - Los niveles BASE (Prev. Bar..., Previous max/min, VWAP, PM High/Low)
      entran todos SALVO que la corrida los elija uno a uno (`explicitos`):
      desde el 21-sep-2026 la pagina los pinta con casilla y manda
      `niveles_explicitos: true`, y entonces solo entran los marcados.
    - `explicitos=None` (config antiguo, tests, consola): se deduce. Si en
      `marcados` hay algun nivel base es que quien lo mando sabia que existian
      las casillas; si no hay ninguno, es un config de antes y se sortean los
      nueve como siempre — misma lista, mismo orden, misma semilla.
    - SMA/EMA/bandas/Donchian/Darvas/Overhead siguen entrando siempre: nadie
      pidio quitarlos y son lo que garantiza que la lista nunca quede vacia.
    """
    m = set(marcados or ())
    if explicitos is None:
        explicitos = bool(m & set(NIVELES_BASE))
    out = []
    for o in ind.objetivos:
        if o in NIVELES_OPCIONALES:
            if o in m:
                out.append(o)
        elif o in NIVELES_BASE:
            if o in m or not explicitos:
                out.append(o)
        else:
            out.append(o)
    return tuple(out)


CATALOGO: dict[str, Indicador] = {
    # ── Precio y niveles ────────────────────────────────────────────────
    "Bar Close": Indicador(
        nombre="Bar Close", familia="precio", por_defecto=True,
        objetivos=TODOS_LOS_NIVELES,
        comparadores=(GT, LT, CRUZA_ARRIBA, CRUZA_ABAJO),
        ayuda="El cierre de la vela contra cualquier nivel: medias, bandas, "
              "máximos previos, VWAP, la caja de Darvas… Es el gen más "
              "productivo del catálogo, porque de él salen todos los cruces.",
    ),
    "High Bar": Indicador(
        nombre="High Bar", familia="precio",
        objetivos=TODOS_LOS_NIVELES,
        comparadores=(GT, LT, CRUZA_ARRIBA, CRUZA_ABAJO),
        ayuda="El máximo de la vela. Contra un nivel detecta el pinchazo que el "
              "cierre no ve: la mecha pasó por encima aunque cerrara debajo.",
    ),
    "Low Bar": Indicador(
        nombre="Low Bar", familia="precio",
        objetivos=TODOS_LOS_NIVELES,
        comparadores=(GT, LT, CRUZA_ARRIBA, CRUZA_ABAJO),
        ayuda="El mínimo de la vela. El espejo del anterior, para pinchazos por abajo.",
    ),

    # ── Momento ─────────────────────────────────────────────────────────
    "RSI": Indicador(
        nombre="RSI", familia="momento", por_defecto=True,
        params={"period": [7, 14, 21]},
        valores=(20, 30, 40, 60, 70, 80),
        comparadores=(GT, LT, CRUZA_ARRIBA, CRUZA_ABAJO),
        ayuda="Sobrecompra y sobreventa clásicas. Con cruces detecta el momento "
              "en que se pasa de zona, que suele valer más que estar en ella.",
    ),
    "MACD": Indicador(
        nombre="MACD", familia="momento",
        params={"period": [8, 12], "period2": [21, 26]},
        objetivos=("MACD Signal",), valores=(0,),
        comparadores=(GT, LT, CRUZA_ARRIBA, CRUZA_ABAJO),
        ayuda="La línea MACD. Contra su Signal da el cruce clásico; contra 0, si "
              "el momento es alcista o bajista.",
    ),
    "MACD Signal": Indicador(
        nombre="MACD Signal", familia="momento",
        params={"period": [8, 12], "period2": [21, 26], "period3": [5, 9]},
        valores=(0,), comparadores=(GT, LT),
        ayuda="La media de la MACD. Suele usarse como el nivel que la MACD cruza, "
              "pero también vale sola contra cero.",
    ),
    "MACD Histogram": Indicador(
        nombre="MACD Histogram", familia="momento",
        params={"period": [8, 12], "period2": [21, 26], "period3": [5, 9]},
        valores=(0,), comparadores=(GT, LT, CRUZA_ARRIBA, CRUZA_ABAJO),
        ayuda="La diferencia entre MACD y Signal. Cruzar cero es el mismo cruce, "
              "pero se ve una vela antes de que las líneas se toquen.",
    ),

    # ── Patrones y velas ────────────────────────────────────────────────
    "Consecutive red candles": Indicador(
        nombre="Consecutive red candles", familia="patrones", por_defecto=True,
        valores=(2, 3, 4, 5), comparadores=(GTE,),
        ayuda="Velas rojas seguidas. Mide agotamiento o continuación según lo que lleve delante.",
    ),
    "Consecutive green candles": Indicador(
        nombre="Consecutive green candles", familia="patrones", por_defecto=True,
        valores=(2, 3, 4, 5), comparadores=(GTE,),
        ayuda="Velas verdes seguidas.",
    ),
    "Consecutive higher highs": Indicador(
        nombre="Consecutive higher highs", familia="patrones",
        valores=(2, 3, 4, 5), comparadores=(GTE,),
        ayuda="Máximos crecientes seguidos. Es estructura, no color: una vela roja "
              "puede hacer un máximo más alto.",
    ),
    "Consecutive lower lows": Indicador(
        nombre="Consecutive lower lows", familia="patrones",
        valores=(2, 3, 4, 5), comparadores=(GTE,),
        ayuda="Mínimos decrecientes seguidos.",
    ),
    "Consecutive lower highs": Indicador(
        nombre="Consecutive lower highs", familia="patrones",
        valores=(2, 3, 4, 5), comparadores=(GTE,),
        ayuda="Máximos decrecientes: techos cada vez más bajos. Es la señal de que "
              "la subida se está quedando sin fuelle.",
    ),
    "Consecutive higher lows": Indicador(
        nombre="Consecutive higher lows", familia="patrones",
        valores=(2, 3, 4, 5), comparadores=(GTE,),
        ayuda="Mínimos crecientes: suelos cada vez más altos.",
    ),
    "Candle Range %": Indicador(
        nombre="Candle Range %", familia="patrones", por_defecto=True,
        valores=(1, 2, 3, 5, 8), comparadores=(GT, LT),
        # OJO: la ayuda decía "de máximo a mínimo" y era FALSO. El motor calcula
        # `abs((cierre - apertura) / apertura) * 100` — el CUERPO en valor
        # absoluto, sin mechas y sin dirección (indicators.py::_compute_raw).
        ayuda="Cuánto se mueve la vela de apertura a cierre, en %, SIN signo: da "
              "igual si subió o bajó. Sirve para exigir movimiento o calma. Si "
              "necesitas la dirección, usa «Recorrido (%)».",
    ),
    "Recorrido (%)": Indicador(
        nombre="Recorrido (%)", familia="patrones", por_defecto=True,
        valores=(-8, -5, -3, -2, -1, 1, 2, 3, 5, 8), comparadores=(GT, LT),
        ayuda="Recorrido de la vela CON SIGNO: lo que se mueve de apertura a "
              "cierre, en %. Positivo si subió, negativo si bajó. «> 3» pide una "
              "vela que suba más de un 3%; «< -2» una que caiga más de un 2%.",
    ),
    "Squeeze": Indicador(
        nombre="Squeeze", familia="patrones", por_defecto=True,
        params={"range_minutes": [3, 5, 10, 15, 30], "squeeze_direction": ["up", "down"]},
        valores=(3, 5, 8, 10, 15, 20, 30), comparadores=(GT,),
        ayuda="Lo que ha movido el precio en una ventana de RELOJ (no de velas). Se "
              "sortean las dos direcciones y el indicador devuelve siempre positivo, "
              "así que la condición se lee igual arriba que abajo.",
    ),
    "Triangle Ascending": Indicador(
        nombre="Triangle Ascending", familia="patrones",
        params={"pivot_window": [3, 5], "tri_lookback": [20, 35, 50],
                "slope_tolerance": [0.5, 1.5], "min_r_squared": [0.5, 0.65, 0.8],
                "min_pivots": [2, 3]},
        valores=(1,), comparadores=(GTE,),
        ayuda="Triángulo ascendente: techo plano y suelos que suben. Devuelve 1 "
              "cuando el patrón está formado, por eso se compara con «≥ 1».",
    ),
    "Triangle Descending": Indicador(
        nombre="Triangle Descending", familia="patrones",
        params={"pivot_window": [3, 5], "tri_lookback": [20, 35, 50],
                "slope_tolerance": [0.5, 1.5], "min_r_squared": [0.5, 0.65, 0.8],
                "min_pivots": [2, 3]},
        valores=(1,), comparadores=(GTE,),
        ayuda="Triángulo descendente: suelo plano y techos que bajan.",
    ),
    "Triangle Symmetric": Indicador(
        nombre="Triangle Symmetric", familia="patrones",
        params={"pivot_window": [3, 5], "tri_lookback": [20, 35, 50],
                "slope_tolerance": [0.5, 1.5], "min_r_squared": [0.5, 0.65, 0.8],
                "min_pivots": [2, 3]},
        valores=(1,), comparadores=(GTE,),
        ayuda="Triángulo simétrico: se estrecha por los dos lados.",
    ),

    # ── Caídas y gaps ───────────────────────────────────────────────────
    "% Fade": Indicador(
        nombre="% Fade", familia="caidas", por_defecto=True,
        # `ap_session` None y "ap.PM" son lo mismo para el motor (desde la primera
        # vela): se sortean solo los dos distintos. Fijable en la pagina.
        params={"fade_ref": ["previous_max", "vwap_cross"], "ap_session": ["ap.PM", "ap.RTH"]},
        valores=(3, 5, 8, 10, 15, 20, 25, 30, 40, 50),
        comparadores=(GT, LT),
        ayuda="Caída VIVA desde una referencia que se reancla sola: el máximo previo, "
              "o el VWAP en la vela donde el precio lo cruzó. Se sortean las dos "
              "referencias y las tres sesiones.",
    ),
    "% Session Fade": Indicador(
        nombre="% Session Fade", familia="caidas",
        params={"session_ref": ["pm", "rth"]},
        valores=(5, 10, 15, 20, 30, 40, 50), comparadores=(GT, LT),
        ayuda="Caída de una sesión ENTERA, ya congelada: del máximo de la sesión a la "
              "apertura de la siguiente. No cambia dentro del día, al revés que el «% Fade».",
    ),
    "Current Gap (%)": Indicador(
        nombre="Current Gap (%)", familia="caidas",
        valores=(20, 30, 50, 70, 100, 150), comparadores=(GT, LT),
        ayuda="Dónde está el precio AHORA respecto al cierre de ayer. Sube y baja "
              "durante el día, al revés que el PM High Gap.",
    ),
    "PM High Gap (%)": Indicador(
        nombre="PM High Gap (%)", familia="caidas",
        valores=(30, 50, 70, 100, 150, 200), comparadores=(GT, LT),
        ayuda="Máximo de premercado contra el cierre de ayer. Es ACUMULADO: no baja "
              "aunque el precio se dé la vuelta.",
    ),

    # ── Volumen ─────────────────────────────────────────────────────────
    "RVOL by bar": Indicador(
        nombre="RVOL by bar", familia="volumen",
        params={"period": [10, 20, 50]},
        valores=(1, 2, 3, 5, 10), comparadores=(GT, LT),
        ayuda="Volumen de la vela contra su media reciente. Un 3 significa el triple "
              "de lo normal para esa hora.",
    ),
    "Dollar Volume": Indicador(
        nombre="Dollar Volume", familia="volumen",
        valores=(50_000, 100_000, 250_000, 500_000, 1_000_000), comparadores=(GT, LT),
        ayuda="Dólares movidos en ESTA vela (precio × volumen). Filtra el movimiento "
              "sin dinero detrás.",
    ),
    "Accumulated Dollar Volume": Indicador(
        nombre="Accumulated Dollar Volume", familia="volumen",
        valores=(1_000_000, 5_000_000, 10_000_000, 25_000_000, 50_000_000),
        comparadores=(GT, LT),
        ayuda="Dólares movidos en lo que va de día. Es el que suele ir de guarda fija "
              "para exigir liquidez.",
    ),

    # ── Tiempo ──────────────────────────────────────────────────────────
    "Elapsed time from last High": Indicador(
        nombre="Elapsed time from last High", familia="tiempo",
        params={"session_ref": ["full", "pm", "rth"]},
        valores=(5, 10, 15, 30, 60, 120), comparadores=(GT, LT),
        ayuda="Minutos desde el último máximo. Mucho tiempo sin hacer máximos es la "
              "definición operativa de que la subida murió.",
    ),

    # ── Alternativos (9 y 10-sep-2026) ──────────────────────────────────
    #
    # Las rejillas de valores NO son inventadas: absorcion y mecha salen de los
    # percentiles medidos sobre 2.476 velas reales del bot (8-9 sep 2026,
    # ventana de 5 min); pendiente, R2, retroceso y extension salen de los
    # ordenes de magnitud del descriptivo del constructor de condiciones.
    #
    # «Absorption + Wick» NO esta a proposito: es «Absorption > a AND Wick
    # Ratio > w» sobre la misma ventana, y el genetico ya busca 2-3 condiciones
    # en AND. Como dos genes sueltos prueba mas combinaciones que el combinado.
    "Reg. Slope": Indicador(
        nombre="Reg. Slope", familia="alternativos",
        params={"range_minutes": [5, 10, 20, 30]},
        valores=(-0.5, -0.25, -0.1, -0.05, 0.05, 0.1, 0.25, 0.5),
        comparadores=(GT, LT),
        ayuda="Pendiente de la recta ajustada al precio en los últimos X minutos "
              "de RELOJ, en % por minuto y normalizada por el precio, así que el "
              "mismo umbral vale para un ticker de 0,60 $ y uno de 45 $. Negativa "
              "= cae. Con 20 min: ±0,05 es plano, ±0,10 a ±0,25 tendencia clara, "
              "±0,5 un desplome o un spike.",
    ),
    "Reg. R2": Indicador(
        nombre="Reg. R2", familia="alternativos",
        params={"range_minutes": [10, 20, 30]},
        valores=(0.3, 0.5, 0.7, 0.85), comparadores=(GT, LT),
        ayuda="Calidad del ajuste de esa misma recta, de 0 a 1: escalera (cerca de "
              "1) o sierra (cerca de 0). Un tramo limpio admite un stop cerca; una "
              "sierra te saca varias veces por el camino. Va bien EMPAREJADO con "
              "Reg. Slope: pendiente dice hacia dónde, R² dice si es de fiar.",
    ),
    "ATR Extension": Indicador(
        nombre="ATR Extension", familia="alternativos",
        # `period` es el del ATR; 14 es el canónico y 7 uno rápido. La referencia
        # se sortea: al VWAP es el clásico del fade, a PMH y al cierre de ayer
        # miden si el gap se está deshaciendo, y al máximo del día (siempre ≤ 0)
        # cuántos ATR lleva caídos desde el techo.
        params={"period": [7, 14], "ref_level": ["vwap", "pmh", "prev_close", "hod"]},
        valores=(-4, -3, -2, -1, 1, 2, 3, 4, 6), comparadores=(GT, LT),
        ayuda="Cuántos ATR separan al precio de la referencia (VWAP, PM High, cierre "
              "de ayer o máximo del día; se sortea). Positivo = por encima. De 0 a 1 "
              "es la zona normal; 2-3 estirado; 4-6 la extensión fuerte del fade "
              "clásico. Es el «está un 8 % sobre el VWAP» hecho comparable entre "
              "tickers.",
    ),
    "Time vs Level": Indicador(
        nombre="Time vs Level", familia="alternativos",
        params={"ref_level": ["vwap", "pmh", "pml", "prev_close", "rth_open"],
                "level_dir": ["above", "below"]},
        valores=(5, 10, 15, 30, 60), comparadores=(GT, LT),
        ayuda="Minutos SEGUIDOS por encima (o por debajo) del nivel: la aceptación. "
              "Para «precio > PM High» son iguales 2 minutos arriba y 90, y son "
              "situaciones opuestas. 0 cuando no se cumple; se reinicia cada sesión. "
              "Se sortean el nivel y el lado.",
    ),
    # VOLUMEN CONTRA EL UNIVERSO (22-sep-2026). El unico de los tres que
    # necesita algo de fuera es «RVOL universo»: el perfil del universo
    # (backend/scripts/perfil_volumen_universo.py). Sin el vale NaN y la
    # condicion no se cumple nunca — la corrida no falla, pero ese gen no
    # sirve para nada; comprobarlo antes de marcarlo en una corrida larga.
    # ROTACION: el volumen del dia contra las ACCIONES EN CIRCULACION (no el
    # float: ese dato no existe con historico). Necesita la tabla que construye
    # backend/scripts/acciones_circulacion_etl.py; sin ella vale NaN y el gen
    # no sirve — comprobarlo antes de marcarlo en una corrida larga.
    "Rotacion": Indicador(
        nombre="Rotacion", familia="volumen",
        params={},
        valores=(0.5, 1, 2, 3, 5, 10), comparadores=(GT, LT),
        ayuda="Cuantas veces se han cambiado de manos hoy TODAS las acciones que "
              "existen (volumen del dia / acciones en circulacion). Rotacion 3 = "
              "casi nadie que la tenga la compro por debajo del precio de hoy, y esa "
              "es la gente que vende en cuanto se gira. < 0,5 dia normal · 1-3 el "
              "papel ya cambio de manos entero · > 5 pump de manual. OJO: es "
              "CIRCULACION, no float: el float es menor, asi que la rotacion real es "
              "MAYOR que este numero.",
    ),
    "Rotacion en X min": Indicador(
        nombre="Rotacion en X min", familia="volumen",
        params={"range_minutes": [15, 30, 60]},
        valores=(0.05, 0.1, 0.3, 0.5), comparadores=(GT, LT),
        ayuda="La rotacion de los ultimos X minutos: la VELOCIDAD, no el total. "
              "0,5 en media hora es media empresa cambiando de manos en media hora "
              "— el climax en directo. < 0,05 esta parado. Mismo aviso: circulacion, "
              "no float.",
    ),
    "RVOL universo": Indicador(
        nombre="RVOL universo", familia="alternativos",
        params={"range_minutes": [5, 10, 30]},
        valores=(0.5, 0.8, 1.5, 3, 5, 10), comparadores=(GT, LT),
        ayuda="Cuanto volumen hay AHORA frente al que toca A ESTA HORA en un dia de "
              "gap (1 = normal, 3 = el triple, 0,4 = seco). No es el RVOL de siempre: "
              "la referencia son LOS DEMAS GAPPERS, no los dias previos del ticker "
              "(un gapper del +50 % no tiene dias normales). Perfil medido en 14.418 "
              "ticker-dias de 2019-2023, o sea fuera de muestra para 2024 en "
              "adelante. < 0,5 seco · 0,8-1,5 normal · > 3 climax. MEDIDO sobre "
              "24.750 maximos del dia reales: con RVOL < 0,5 el corto toca -8 % "
              "antes que +8 % el 72,7 % de las veces (base 64 %) y solo sube un "
              "5,8 % en contra; con RVOL > 10 acierta igual que la base pero la "
              "subida mediana en contra es del 22,9 % — el climax parece la senal "
              "buena y es la trampa.",
    ),
    "Minutos desde el pico de volumen": Indicador(
        nombre="Minutos desde el pico de volumen", familia="alternativos",
        params={},
        valores=(5, 10, 20, 40, 60), comparadores=(GT, LT),
        ayuda="Minutos desde la vela de mas volumen del dia. En un gapper el pico de "
              "VOLUMEN llega antes que el maximo del PRECIO: ese hueco es donde vive "
              "el corto. MEDIDO sobre 24.750 maximos del dia reales: con el pico a "
              "< 5 min el corto toca -8 % antes que +8 % el 65,7 % de las veces pero "
              "sube un 13,5 % en contra; a 15-60 min acierta el 60,5 % con solo un "
              "7 % en contra. Esperar no mejora el acierto: baja el RIESGO. Causal: "
              "el maximo es corrido.",
    ),
    "Pendiente del volumen": Indicador(
        nombre="Pendiente del volumen", familia="alternativos",
        params={"range_minutes": [5, 10, 20]},
        valores=(0.3, 0.6, 1, 2, 3), comparadores=(GT, LT),
        ayuda="Volumen de los ultimos X minutos entre el de los X anteriores: si el "
              "volumen acelera (> 2) o se apaga (< 0,5). Con el precio subiendo y la "
              "pendiente baja, sube por falta de vendedores y no por compras. OJO: "
              "medido sobre 24.750 maximos del dia reales, apenas separa (58-65 % "
              "frente al 64 % de base) y la pendiente baja sale algo PEOR que la "
              "alta: compara con hace un rato, no con lo normal del dia. Para «se ha "
              "secado» usa «RVOL universo». No necesita tabla ninguna.",
    ),
    "Absorption": Indicador(
        nombre="Absorption", familia="alternativos",
        params={"range_minutes": [3, 5, 10]},
        # p50 = 0,26 · p75 = 0,85 · p90 = 2,62 · p95 = 5,08 · p99 = 17,5
        valores=(0.25, 0.85, 2.5, 5, 10), comparadores=(GT, LT),
        ayuda="Millones de $ que hicieron falta para mover el precio un 1 % neto en "
              "la ventana. Alto = alguien absorbe (un ATM, un insider colocando "
              "papel). Medido en el universo real con 5 min: la mediana es 0,25 y "
              "solo 1 de cada 10 velas pasa de 2,5.",
    ),
    "Wick Ratio": Indicador(
        nombre="Wick Ratio", familia="alternativos",
        params={"range_minutes": [3, 5, 10], "wick_side": ["upper", "lower"]},
        # mecha arriba: p50 = 0,21 · p75 = 0,29 · p90 = 0,37 · p95 = 0,43
        valores=(0.2, 0.3, 0.4, 0.5), comparadores=(GT, LT),
        ayuda="Fracción del recorrido de la ventana devuelta en mecha, de 0 a 1. "
              "Arriba = rechazo de las subidas; abajo = de las caídas. OJO A LA "
              "ESCALA: en un día normal siempre se devuelve una quinta parte (0,2), "
              "eso no significa nada; 0,4 ya es el 10 % más rechazado.",
    ),
    "Retroceso (%)": Indicador(
        nombre="Retroceso (%)", familia="alternativos",
        # 0 = el impulso del día entero (lo normal); 30 y 60 = solo lo que se
        # movió en la última media hora u hora. `swing_dir` up mide cuánto se
        # ha devuelto de la SUBIDA; down, cuánto ha rebotado de la CAÍDA.
        params={"range_minutes": [0, 30, 60], "swing_dir": ["up", "down"]},
        valores=(10, 20, 38, 50, 62, 80, 100), comparadores=(GT, LT),
        ayuda="Qué parte del impulso se ha devuelto ya, en % del impulso (no del "
              "precio): de 10 a 15 y luego a 13 es un 40. Cerca de 0 está en "
              "máximos; 100 ha vuelto a la base; más de 100 la ha perforado. Se "
              "reancla al hacer un máximo nuevo. No confundir con «Recorrido (%)», "
              "que es el cuerpo de UNA vela.",
    ),
    "Vol. de la franja": Indicador(
        nombre="Vol. de la franja", familia="alternativos",
        params={"bin_pct": [0.5, 1.0, 2.0]},
        valores=(20, 50, 80, 95), comparadores=(GT, LT),
        ayuda="Qué porcentaje de las franjas de precio del día tienen MENOS volumen "
              "que la franja donde está el precio ahora, de 0 a 100. Alto = está "
              "en una zona muy negociada (freno); bajo = en el vacío, donde el "
              "precio se mueve rápido porque nadie compró ahí.",
    ),

    # ── Picos y valles ENUMERADOS (PRD 18-sep-2026; en el genetico 21-sep) ──
    #
    # «Pico» tiene DOS papeles y los dos van con el mismo interruptor:
    #   · a la izquierda, contra otro Pico: «Pico nº1 < Pico nº2» son maximos
    #     decrecientes, «Valle nº1 > Valle nº2» minimos crecientes. El destino
    #     se sortea con la MISMA ventana y direccion que el origen y OTRO
    #     numero de giro (cromosoma.objetivo_aleatorio): un techo contra un
    #     suelo es siempre verdad y el mismo giro contra si mismo siempre
    #     falso — dos condiciones muertas que no hay que sortear.
    #   · como destino de Bar Close / High Bar / Low Bar (NIVELES_OPCIONALES):
    #     «Bar Close cruza arriba Pico nº2» = recupera el techo anterior.
    # Las dos medidas de la familia van contra una cifra, como en el
    # constructor. Los tres se reinician cada dia y valen NaN hasta que hay N
    # giros confirmados: con 2-3 velas de confirmacion eso es pronto.
    "Pico": Indicador(
        nombre="Pico", familia="alternativos",
        params={"pivot_window": [2, 3, 5], "swing_dir": ["up", "down"], "pivot_rank": [1, 2, 3]},
        objetivos=("Pico",), comparadores=(GT, LT),
        ayuda="El techo (o suelo, con «down») nº N de la lista de giros del día, "
              "como PRECIO: nº1 es el último confirmado (= «Ultimo pivote»), nº2 el "
              "anterior… Se compara con OTRO giro de la misma lista: «Pico nº1 < "
              "Pico nº2» son máximos decrecientes, «Valle nº1 > Valle nº2» suelos "
              "crecientes; con nº3 caben un hombro-cabeza-hombro o un doble techo. "
              "Marcado, entra ADEMÁS como destino de Bar Close / High Bar / Low Bar "
              "(«Bar Close cruza arriba Pico nº2»), con los giros nº2-4: el nº1 ya "
              "lo cubre «Ultimo pivote». Un giro es una vela con el máximo por "
              "encima de las N velas de cada lado, y se conoce N velas después.",
    ),
    "Edad del pico": Indicador(
        nombre="Edad del pico", familia="alternativos",
        params={"pivot_window": [2, 3, 5], "swing_dir": ["up", "down"], "pivot_rank": [1, 2, 3]},
        valores=(5, 10, 15, 30, 60, 120), comparadores=(GT, LT),
        ayuda="Minutos de RELOJ desde que se formó el giro nº N (nº1 = el último "
              "techo o suelo confirmado). Crece cada minuto mientras el giro siga "
              "en la lista. «> 30» = el último techo lleva media hora aguantando; "
              "«nº3 < 90» = las tres cimas caben en hora y media. NaN hasta que "
              "existe el giro nº N; se reinicia cada día.",
    ),
    "Volumen del pico": Indicador(
        nombre="Volumen del pico", familia="alternativos",
        params={"pivot_window": [2, 3, 5], "swing_dir": ["up", "down"], "pivot_rank": [1, 2, 3]},
        # En ACCIONES, que es como viaja en la definicion (el constructor
        # escribe la casilla en millones y multiplica por 10^6 al guardar).
        valores=(100_000, 250_000, 500_000, 1_000_000, 2_500_000), comparadores=(GT, LT),
        ayuda="Volumen (en acciones) de la vela en la que se formó el giro nº N. "
              "Dice si el techo se hizo con dinero de verdad o fue una mecha en un "
              "libro vacío: dos techos a la misma altura son cosas distintas si uno "
              "negoció 2 millones y el otro 50.000. Rejilla de 100 k a 2,5 M. NaN "
              "hasta que existe el giro nº N; se reinicia cada día.",
    ),
}

# Los NUEVE NIVELES BASE, con casilla (21-sep-2026). Marcados de serie, para
# que una corrida recien abierta sortee exactamente lo de siempre; desmarcar
# uno lo quita de los destinos de Bar Close / High Bar / Low Bar. Son
# `solo_destino` como los opcionales: «Prev. Bar Low > 3» no dice nada.
_AYUDA_NIVELES_BASE = {
    "Prev. Bar Low": "El mínimo de la vela ANTERIOR. «Bar Close < Prev. Bar Low» es la rotura clásica del mínimo previo.",
    "Prev. Bar High": "El máximo de la vela anterior. Espejo del anterior, para roturas al alza.",
    "Prev. Bar Close": "El cierre de la vela anterior. Contra el cierre actual dice si la vela subió o bajó respecto a la de antes.",
    "Prev. Bar Open": "La apertura de la vela anterior.",
    "VWAP": "Precio medio ponderado por volumen del día. El nivel de referencia del fade: por encima manda el comprador, por debajo el vendedor.",
    "PM High": "Máximo del premercado. Perderlo o recuperarlo es la referencia de casi todos los gaps.",
    "PM Low": "Mínimo del premercado.",
    "Previous max": "El máximo corrido de la sesión HASTA LA VELA ANTERIOR: solo sube. No es «Ultimo pivote» (aquel baja al confirmarse un techo nuevo). Se sortea desde cuándo cuenta: ap.PM (desde las 04:00, con premercado) o ap.RTH (desde las 09:30).",
    "Previous min": "El mínimo corrido de la sesión hasta la vela anterior: solo baja. Se sortea desde cuándo cuenta (ap.PM / ap.RTH), igual que el máximo.",
}
for _n in NIVELES_BASE:
    CATALOGO[_n] = Indicador(nombre=_n, familia="precio", comparadores=(),
                             params=dict(NIVELES_CON_PARAMS.get(_n, {})),
                             ayuda=_AYUDA_NIVELES_BASE[_n], solo_destino=True, por_defecto=True)
del _n

# Los niveles opcionales (cuatro: el pivote, el punto de control y la zona de
# valor), como entradas del catalogo para que salgan en la pagina con su casilla. No forman condiciones solos (`solo_destino`): marcarlos
# los anyade a los destinos de Bar Close / High Bar / Low Bar, y «Ultimo pivote»
# ademas al sorteo del stop de estructura.
_AYUDA_NIVELES = {
    "Ultimo pivote":
        "El último techo (o suelo) CONFIRMADO, como precio. No es «Previous max»: "
        "aquel es el máximo corrido y nunca baja; con 10 → 15 → 12 → 14 → 11 el "
        "pivote alto es 14 y el bajo 12. Aparece N velas después de ocurrir (es lo "
        "que lo hace causal). Marcado, entra como destino de los cruces del precio "
        "Y como nivel del stop de estructura (con 3 velas de confirmación).",
    "Punto de control":
        "El precio donde más volumen se ha cruzado hoy. No es una media: salta a "
        "saltos de franja. Cruzarlo hacia abajo es perder el precio que el mercado "
        "aceptó como justo.",
    "Zona alta":
        "Borde superior de la banda donde se negoció casi todo el día. NO se mueve "
        "con el precio: es el marco estable de la sesión (cambia la mitad de "
        "veces que los nodos).",
    "Zona baja":
        "Borde inferior de esa misma banda. Perderlo es entrar donde casi nadie "
        "compró.",
}
for _n, _rejilla in NIVELES_OPCIONALES.items():
    if _n in CATALOGO:
        continue      # «Pico» ya esta arriba con su papel de lado izquierdo
    CATALOGO[_n] = Indicador(nombre=_n, familia="alternativos", params=dict(_rejilla),
                             comparadores=(), ayuda=_AYUDA_NIVELES[_n], solo_destino=True)
del _n, _rejilla


# ── Gestion de riesgo ───────────────────────────────────────────────────────

STOP_PCT = (2, 3, 5, 8, 12, 20)
STOP_OFFSET_PCT = (0, 3, 5, 10, 15)
# Niveles estructurales del motor (RiskManagement.tsx): el stop de un corto va
# ARRIBA (maximos), el de un largo ABAJO (minimos). Operador como en las
# estrategias guardadas de Jaume.
# 2026-09-20: HOD/LOD fuera del sorteo; en su lugar «Previous Max/Min (vela de
# la señal)», que es lo mismo (maximo corrido CON la vela de la senal). «Previous
# Max» a secas sigue siendo el de siempre (hasta la vela anterior).
STOP_NIVELES = {
    "short": (("PMH", ">="), ("Previous Max", ">="), ("Previous Max (vela de la señal)", ">=")),
    "long": (("PML", "<="), ("Previous Min", "<="), ("Previous Min (vela de la señal)", "<=")),
}
# El ultimo pivote como stop de estructura (10-sep-2026), SOLO si «Ultimo
# pivote» esta marcado en el catalogo: es el mismo interruptor que lo mete como
# destino, para que una corrida sin el se sortee exactamente como antes. Los
# valores son los mismos que ofrece RiskManagement.tsx (VALORES_PIVOTE en
# portfolio_sim.py); sin `pivot_window` en el hard_stop el motor usa 3, y si
# aun no hay pivote confirmado cae al respaldo del 5 %.
STOP_NIVELES_OPCIONALES = {
    "short": (("Ultimo pivote alto", ">="),),
    "long": (("Ultimo pivote bajo", "<="),),
}
STOP_NIVEL_INTERRUPTOR = "Ultimo pivote"


def stop_niveles(sesgo: str, marcados=()) -> tuple:
    """Niveles de estructura sorteables en ESTA corrida."""
    base = STOP_NIVELES[sesgo]
    if STOP_NIVEL_INTERRUPTOR in set(marcados or ()):
        return base + STOP_NIVELES_OPCIONALES[sesgo]
    return base
# El techo era 30 y se subio a 40 el 7-sep-2026 a peticion de Jaume. El
# motivo salio de la corrida de anoche: la estrategia llevaba el take
# profit al 35 %, asi que NINGUN disparador de parcial podia colocarse por
# encima — el genetico probaba parciales (58 de 156 individuos) y perdian
# siempre, y no era que los parciales fueran malos: es que no cabian.
# Se anyade el 40 sin quitar el 30, que sigue siendo un escalon util.
TP_PCT = (3, 5, 6, 8, 10, 15, 20, 30, 40)
TP_HORA = ("09:00", "09:30", "10:00", "10:30", "11:00", "12:00", "15:30")
TP_TIEMPO_MIN = (15, 30, 60, 120, 240)

# TAKE PROFITS PARCIALES: cerrar un trozo antes y dejar correr el resto.
#
# El genetico sortea CUANTOS niveles pone y como es cada uno. Mas de dos no se
# ofrece: el motor los aplica en orden y con tres el tercero casi nunca llega a
# ejecutarse, asi que solo ensancharia el espacio de busqueda.
#
# OJO CON `take_profit_mode`. El motor solo lee `partial_take_profits` cuando el
# modo es "Partial"; en "Full" los ignora en silencio. De ahi que el cromosoma
# tenga que cambiar el modo, y no solo rellenar la lista.
TP_PARCIAL_CIERRE_PCT = (25, 33, 50, 75)
TP_PARCIAL_MAX_NIVELES = 2

# GUARDAS FIJAS que se pueden poner delante de las condiciones buscadas. No las
# busca el genetico: las fija Jaume y valen para todos los individuos, para que
# la busqueda no gaste generaciones redescubriendo que hace falta liquidez.
#
# (clave, nombre para el motor, etiqueta de la pantalla, comparador, ayuda)
GUARDAS = (
    ("precio", "Bar Close", "Precio mínimo", GT,
     "Descarta los chicharros por debajo de este precio."),
    ("volumen_acum", "Accumulated Dollar Volume", "Dollar volume acumulado mín.", GT,
     "Dólares movidos en lo que va de día. Es la guarda de liquidez de siempre."),
    ("dollar_volume", "Dollar Volume", "Dollar volume de la vela mín.", GT,
     "Dólares movidos en ESTA vela. Más estricta que la acumulada: exige que "
     "haya dinero en el momento de entrar, no que lo hubiera hace dos horas."),
    ("pm_high_gap", "PM High Gap (%)", "PM High Gap mín. (%)", GT,
     "Gap del máximo de premercado contra el cierre de ayer. Acota el universo "
     "al tipo de acción que se quiere operar."),
    ("open_gap", "Open Gap (%)", "Gap de apertura mín. (%)", GT,
     "Gap con el que ABRIÓ el mercado (apertura del RTH contra el cierre de "
     "ayer). A diferencia del de premercado, no depende de dónde llegó el PM. "
     "OJO: es NaN antes de las 09:30 — a las 08:00 nadie sabe todavía a cuánto "
     "va a abrir, así que en premercado esta guarda no deja pasar nada."),
)
