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
    # los que Jaume ya venia usando. Marcar los 26 dispararia el espacio de
    # busqueda y contradice lo que dice la propia pantalla: «menos
    # indicadores bien elegidos buscan mejor que el catalogo entero, cada
    # uno que no aporta anyade formas de encontrar casualidades».
    por_defecto: bool = False

    def etiqueta(self, params: dict) -> str:
        if not params:
            return self.nombre
        partes = [f"{v}" for _, v in sorted(params.items()) if v is not None]
        return f"{self.nombre}({', '.join(partes)})" if partes else self.nombre


# Indicadores que solo sirven como lado DERECHO (niveles / velas previas).
#
# Son NIVELES: un precio contra el que cruzar. No van de lado izquierdo porque
# «Prev. Bar Low > 3» no dice nada — lo que interesa es que el precio los cruce.
NIVELES = ("Prev. Bar Low", "Prev. Bar High", "Prev. Bar Close", "Prev. Bar Open",
           "VWAP", "PM High", "PM Low", "Previous max", "Previous min")

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
}

TODOS_LOS_NIVELES = NIVELES + tuple(NIVELES_CON_PARAMS)


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
        ayuda="Cuánto abarca la vela de máximo a mínimo, en % del precio. Sirve "
              "para exigir movimiento o para exigir calma.",
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
        params={"fade_ref": ["previous_max", "vwap_cross"], "ap_session": [None, "ap.PM", "ap.RTH"]},
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
}


# ── Gestion de riesgo ───────────────────────────────────────────────────────

STOP_PCT = (2, 3, 5, 8, 12, 20)
STOP_OFFSET_PCT = (0, 3, 5, 10, 15)
# Niveles estructurales del motor (RiskManagement.tsx): el stop de un corto va
# ARRIBA (maximos), el de un largo ABAJO (minimos). Operador como en las
# estrategias guardadas de Jaume.
STOP_NIVELES = {
    "short": (("HOD", ">="), ("PMH", ">="), ("Previous Max", ">=")),
    "long": (("LOD", "<="), ("PML", "<="), ("Previous Min", "<=")),
}
TP_PCT = (3, 5, 6, 8, 10, 15, 20, 30)
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
)
