
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Union, Literal, Annotated
from uuid import uuid4
from enum import Enum
from datetime import datetime

# --- Enums ---
class IndicatorType(str, Enum):
    # Trend / MA
    SMA = "SMA"
    EMA = "EMA"
    WMA = "WMA"
    VWAP = "VWAP"
    VWAP_SD_PLUS = "VWAP Sd+"
    VWAP_SD_MINUS = "VWAP Sd-"
    LINEAR_REGRESSION = "Linear Regression"
    ZIG_ZAG = "Zig Zag"
    ICHIMOKU = "Ichimoku Clouds"

    # Momentum
    RSI = "RSI"
    MACD = "MACD"
    # Las tres lineas del MACD son NOMBRES distintos, no un parametro: asi las
    # tiene `services/indicators.py` y asi las despacha la via rapida
    # (`_RAW_INDICATOR_DISPATCH`). Faltaban en el enum, asi que guardar una
    # estrategia con la Signal o el Histograma habria rebotado 422 — el mismo
    # fallo que tuvo Darvas Box en su dia.
    MACD_SIGNAL = "MACD Signal"
    MACD_HISTOGRAM = "MACD Histogram"
    STOCHASTIC = "Stochastic"
    MOMENTUM = "Momentum"
    CCI = "CCI"
    ROC = "ROC"
    DMI_PLUS = "DMI+"
    DMI_MINUS = "DMI-"
    WILLIAMS_R = "Williams %R"
    # Squeeze: % que ha movido el precio en una ventana de RELOJ (minutos).
    # Solo se compara contra una cifra fija; no es un nivel de precio.
    SQUEEZE = "Squeeze"
    REG_SLOPE = "Reg. Slope"
    REG_R2 = "Reg. R2"
    ATR_EXTENSION = "ATR Extension"
    # Absorcion: millones de $ por cada 1% de recorrido (profundidad).
    # Profundidad del retroceso desde el maximo del impulso, en % del impulso.
    # Ultimo pivote confirmado: el ultimo techo (o suelo) que dejo el mercado.
    # A DIFERENCIA de los otros indicadores nuevos, este SI es un nivel de
    # precio: se compara con otros indicadores y sirve de stop estructural.
    # Perfil de volumen intradia. El primero es una MEDIDA (percentil 0-100);
    # los otros tres son NIVELES DE PRECIO y sirven de stop estructural.
    VOL_BIN_PCT = "Vol. de la franja"
    VOL_POC = "Punto de control"
    VOL_NODE_UP = "Nodo de arriba"
    VOL_NODE_DOWN = "Nodo de abajo"
    # La ZONA DE VALOR: los dos bordes de la banda donde se ha negociado casi
    # todo. NO depende de donde este el precio, al contrario que los nodos.
    VOL_ZONE_HIGH = "Zona alta"
    VOL_ZONE_LOW = "Zona baja"
    LAST_PIVOT = "Ultimo pivote"
    RETRACEMENT = "Retroceso (%)"
    ABSORPTION = "Absorption"
    WICK_RATIO = "Wick Ratio"
    ABSORPTION_WICK = "Absorption + Wick"
    TIME_VS_LEVEL = "Time vs Level"

    # Volatility
    ATR = "ATR"
    ADX = "ADX"
    BOLLINGER_BANDS = "Bollinger Bands"
    DONCHIAN = "Donchian"
    # Banda NIVEL (techo/suelo de la caja), mismo uso que Donchian; el nombre
    # es el canonico de indicators.py ("Darvas Box", con alias "Darvas",
    # "Caja Darvas"). El motor lo soporta desde 5fa80b9 pero faltaba aqui:
    # guardar una estrategia con una condicion Darvas rebotaba en Pydantic.
    DARVAS_BOX = "Darvas Box"
    PARABOLIC_SAR = "Parabolic SAR"

    # Volume
    OBV = "OBV"
    VOLUME = "Volume"
    RVOL = "RVOL by bar"
    AVOLUME = "Accumulated Volume"
    ADVOLUME = "Accumulated Dollar Volume"
    DVOLUME = "Dollar Volume"
    SMA_VOLUME = "SMA Volume"

    # Price Variables
    BAR_CLOSE = "Bar Close"
    BAR_OPEN = "Bar Open"
    HIGH_BAR = "High Bar"
    LOW_BAR = "Low Bar"
    PMH = "PM High"
    PML = "PM Low"
    PM_OPEN = "PM Open"
    AM_OPEN = "AM Open"
    RTH_HIGH = "RTH High"
    RTH_LOW = "RTH Low"
    RTH_OPEN = "RTH Open"
    Y_HIGH = "Yesterday High"
    Y_LOW = "Yesterday Low"
    Y_OPEN = "Yesterday Open"
    Y_CLOSE = "Yesterday Close"
    Y_VOLUME = "Yesterday Volume"
    MAX_X_DAYS = "High of last X days"
    MIN_X_DAYS = "Low of last X days"
    # El de verdad, con los cuatro parametros. Los dos de arriba se quedan
    # SOLO por compatibilidad con JSON antiguos: comparten motor, y unicamente
    # fijan otros defectos.
    OVERHEAD_X_DAYS = "Overhead last X days"
    PREVIOUS_MAX = "Previous max"
    PREVIOUS_MIN = "Previous min"
    PREV_BAR_CLOSE = "Prev. Bar Close"
    PREV_BAR_OPEN = "Prev. Bar Open"
    PREV_BAR_HIGH = "Prev. Bar High"
    PREV_BAR_LOW = "Prev. Bar Low"

    # Behavior Variables
    CONSECUTIVE_HIGHER_HIGHS = "Consecutive Higher Highs"
    CONSECUTIVE_LOWER_LOWS = "Consecutive Lower Lows"
    CONSECUTIVE_RED_CANDLES = "Consecutive Red Candles"
    CONSECUTIVE_GREEN_CANDLES = "Consecutive Green Candles"
    CONSECUTIVE_HIGHER_LOWS = "Consecutive Higher Lows"
    CONSECUTIVE_LOWER_HIGHS = "Consecutive Lower Highs"
    OPENING_RANGE_PLUS = "Opening Range +"
    OPENING_RANGE_MINUS = "Opening Range -"
    OPENING_RANGE_AM_PLUS = "Opening Range AM +"
    OPENING_RANGE_AM_MINUS = "Opening Range AM -"
    HEIKIN_ASHI = "Heikin-Ashi"
    HA_CLOSE = "HA Close"
    HA_OPEN = "HA Open"
    HA_HIGH = "HA High"
    HA_LOW = "HA Low"
    PRICE = "Bar Close"
    CLOSE = "Bar Close"
    OPEN = "Bar Open"
    HIGH = "High Bar"
    LOW = "Low Bar"
    AVWAP = "AVWAP"
    CURRENT_OPEN = "Current Open"
    CUSTOM = "Custom"
    DAY_OPEN = "Day Open"
    HOD = "High of Day"
    LOD = "Low of Day"
    MAX_N_BARS = "Max N Bars"
    PREV_CLOSE = "Previous Close"
    RET_PCT_AM = "Ret % AM"
    CANDLE_RANGE_PCT = "Candle Range %"
    # Recorrido de la vela CON SIGNO: (cierre - apertura) / apertura * 100.
    # Es `Candle Range %` sin el `abs()`: y el signo es justo el dato que hace
    # falta para escalpear: `> 3` es "subio mas de un 3%" y `< -2` es "bajo mas
    # de un 2%". Sin parametro de direccion a proposito (decision de Jaume,
    # 7-sep-2026): el signo ya la lleva.
    RECORRIDO_PCT = "Recorrido (%)"
    ELAPSED_TIME_LAST_HIGH = "Elapsed time from last High"
    ELAPSED_TIME = "Elapsed Time"
    TRIANGLE_ASCENDING = "Triangle Ascending"
    TRIANGLE_DESCENDING = "Triangle Descending"
    TRIANGLE_SYMMETRIC = "Triangle Symmetric"
    PM_HIGH_GAP = "PM High Gap (%)"
    CURRENT_GAP = "Current Gap (%)"
    # Gap con el que ABRIO el mercado (apertura RTH vs cierre de ayer). Fijo
    # todo el dia, y NaN antes de las 09:30 a proposito: en premercado todavia
    # no se sabe a cuanto abre.
    OPEN_GAP = "Open Gap (%)"
    # Caida de una sesion entera, congelada: del maximo de la sesion a la
    # apertura de la siguiente (PM->open de mercado, o RTH->open del after).
    SESSION_FADE = "% Session Fade"
    # Caida viva desde una referencia que se reancla sola: el maximo previo o
    # el VWAP en la vela en que el precio lo cruzo.
    FADE = "% Fade"

    # Time / Others
    TIME_OF_DAY = "Time of Day"
    RANGE_OF_TIME = "Range of Time"
    HIGH_LOW_FROM_TIME = "High/Low from x time"
    HIGH_LOW_FROM_HOUR_TIME = "High/Low from hour-time"

    # Existing / Retained Returns
    RET_PCT_PM = "Ret % PM"
    RET_PCT_RTH = "Ret % RTH"

class Comparator(str, Enum):
    GT = "GREATER_THAN"
    LT = "LESS_THAN"
    GTE = "GREATER_THAN_OR_EQUAL"
    LTE = "LESS_THAN_OR_EQUAL"
    EQ = "EQUAL"
    CROSSES_ABOVE = "CROSSES_ABOVE"
    CROSSES_BELOW = "CROSSES_BELOW"
    # Special for price vs level distance
    DISTANCE_GT = "DISTANCE_GREATER_THAN"
    DISTANCE_LT = "DISTANCE_LESS_THAN"

class CandlePattern(str, Enum):
    RV = "RED_VOLUME" # Close < Open
    RV_PLUS = "RED_VOLUME_PLUS" # Close < Open AND Close < Prev Close
    GV = "GREEN_VOLUME" # Close > Open
    GV_PLUS = "GREEN_VOLUME_PLUS" # Close > Open AND Close > Prev Close
    DOJI = "DOJI"
    HAMMER = "HAMMER"
    SHOOTING_STAR = "SHOOTING_STAR"

class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    D1 = "1d"

class RiskType(str, Enum):
    FIXED = "Fixed Amount"
    PERCENTAGE = "Percentage"
    ATR = "ATR Multiplier"
    MARKET_STRUCTURE = "Market Structure (HOD/LOD)"

class TakeProfitMode(str, Enum):
    FULL = "Full"
    PARTIAL = "Partial"

# --- Component Models ---

class UniverseFilters(BaseModel):
    model_config = {"extra": "allow"}

    min_market_cap: Optional[float] = Field(None, description="Min Market Cap in USD")
    max_market_cap: Optional[float] = Field(None, description="Max Market Cap in USD")
    min_price: Optional[float] = Field(None, description="Min Price")
    max_price: Optional[float] = Field(None, description="Max Price")
    min_volume: Optional[float] = Field(None, description="Min Daily Volume")
    max_shares_float: Optional[float] = Field(None, description="Max Float shares")
    require_shortable: bool = Field(True, description="Must be HTB/ETB")
    exclude_dilution: bool = Field(True, description="Exclude active S-3/F-3")
    whitelist_sectors: List[str] = Field(default_factory=list)
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    rules: Optional[List[dict]] = None

class IndicatorConfig(BaseModel):
    name: IndicatorType
    period: Optional[int] = None  # For SMA, EMA, RSI, etc.

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v):
        if isinstance(v, str):
            # Alias map para compatibilidad con estrategias antiguas
            LEGACY_ALIASES = {
                "pre-market high": "PM High",
                "pre-market low": "PM Low",
                "max of last x days": "High of last X days",
                "min of last x days": "Low of last X days",
                "donchian channels": "Donchian",
                "pmh": "PM High",
                "pml": "PM Low",
                "rvol": "RVOL by bar",
                "rvol by bar": "RVOL by bar",
            }
            val_lower = v.lower()
            if val_lower in LEGACY_ALIASES:
                v = LEGACY_ALIASES[val_lower]
            for item in IndicatorType:
                if item.value.lower() == v.lower():
                    return item
        return v
    period2: Optional[int] = None # Fast period, signal period, etc.
    period3: Optional[int] = None # Slow period, etc.
    stdDev: Optional[float] = None # Standard Deviation for BB
    multiplier: Optional[float] = None  # For bands, ATR, etc.
    offset: Optional[int] = 0  # Bars back (0 = current)
    overbought: Optional[float] = None  # e.g. RSI 70, Williams %R -20
    oversold: Optional[float] = None  # e.g. RSI 30, Williams %R -80
    consecutive_count: Optional[int] = None  # For consecutive red/highs/lows
    time_hour: Optional[int] = None  # For Time of Day (0-23)
    time_minute: Optional[int] = None  # For Time of Day (0-59)
    time_condition: Optional[Literal["BEFORE", "AFTER"]] = None
    days_lookback: Optional[int] = None
    calc_on_heikin: Optional[bool] = False

    # Added specific parameters
    # AJUSTE FANTASMA: nadie lee `macd_line`. No llega a `compute_indicator` ni
    # existe alli como parametro. La linea del MACD se elige por el NOMBRE del
    # indicador ("MACD" / "MACD Signal" / "MACD Histogram"). Se conserva el campo
    # para no invalidar estrategias antiguas que lo lleven en su JSON, pero NO
    # conectarle una UI: no haria nada.
    macd_line: Optional[Literal["Signal", "MACD Line", "Histogram"]] = None
    band_line: Optional[Literal["Upper", "Lower", "Basis"]] = None
    orb_minutes: Optional[int] = None
    ha_option: Optional[Literal["Close Bar", "Open Bar", "High Bar", "Low Bar", "Consecutive Green", "Consecutive Red"]] = None
    time_from_hour: Optional[int] = None
    time_from_minute: Optional[int] = None
    range_minutes: Optional[int] = None
    return_pct: Optional[float] = None
    # Squeeze: direccion del spike que se quiere medir. El indicador devuelve
    # SIEMPRE positivo el movimiento en la direccion elegida, para que la
    # condicion se lea igual arriba que abajo ("Squeeze > 10").
    squeeze_direction: Optional[Literal["up", "down"]] = None

    # New indicator-specific parameters
    deviationLevel: Optional[int] = None       # Linear Regression deviation (1, 2, 3)
    reversionPercentage: Optional[float] = None  # Zig Zag reversion %
    ichimoku_line: Optional[str] = None          # "Tenkan", "Kijun", "Senkou A", "Senkou B", "Chikou"
    min_af: Optional[float] = None               # Parabolic SAR min acceleration factor
    max_af: Optional[float] = None               # Parabolic SAR max acceleration factor
    ap_session: Optional[Literal["ap.PM", "ap.RTH", "ap.AM"]] = None
    elapsed_minutes: Optional[int] = None
    pivot_window: Optional[int] = None
    tri_lookback: Optional[int] = None
    slope_tolerance: Optional[float] = None
    min_r_squared: Optional[float] = None
    min_pivots: Optional[int] = None
    # "Elapsed time from last High": ancla del reloj — "full" (día completo,
    # comportamiento histórico), "pm" (PMH del día) o "rth" (máximo RTH).
    # "% Session Fade" reutiliza este campo para elegir la sesión que se desinfla:
    # "pm" (PM High -> apertura de mercado) o "rth" (máximo RTH -> apertura del
    # after). "full" no aplica ahí y se trata como "pm".
    session_ref: Optional[Literal["full", "pm", "rth"]] = None
    # "% Fade": desde dónde se mide la caída. "previous_max" usa el máximo previo
    # (con la sesión de `ap_session`); "vwap_cross" usa el precio del VWAP en la
    # vela en que el precio lo cruzó por última vez.
    fade_ref: Optional[Literal["previous_max", "vwap_cross"]] = None
    # "Overhead last X days". DECLARADOS AQUI A PROPOSITO: pydantic va con
    # extra="ignore", asi que un campo sin declarar se tira SIN error, SIN log
    # y SIN 422.
    #   overhead_extreme   que dia se busca: el del maximo mas alto o el del
    #                      minimo mas bajo.
    #   overhead_ref       que precio DE ESE DIA es el nivel. El maximo suele
    #                      ser una mecha; el cierre si es resistencia.
    #   overhead_vol_rule  el volumen de ese dia frente al acumulado de hoy:
    #                      "gt" mayor, "lt" menor, "none" sin condicion.
    overhead_extreme: Optional[Literal["max", "min"]] = None
    overhead_ref: Optional[Literal["high", "low", "open", "close"]] = None
    overhead_vol_rule: Optional[Literal["none", "gt", "lt"]] = None

    # "ATR Extension" y "Time vs Level": contra que nivel se mide.
    #   ref_level  cual es el nivel. Si es "sma"/"ema", su periodo sale de
    #              `period2` (en "ATR Extension" `period` es el del ATR).
    #   level_dir  solo para "Time vs Level": si el reloj corre mientras el
    #              precio esta POR ENCIMA ("above") o POR DEBAJO ("below").
    # DECLARADOS AQUI A PROPOSITO: pydantic va con extra="ignore", asi que un
    # campo sin declarar se tira SIN error, SIN log y SIN 422.
    ref_level: Optional[Literal[
        "vwap", "sma", "ema", "day_open", "rth_open", "pmh", "pml",
        "prev_close", "previous_max", "previous_min", "hod", "lod",
    ]] = None
    level_dir: Optional[Literal["above", "below"]] = None

    # "Wick Ratio": que mecha se mide, la de arriba (rechazo de las subidas) o
    # la de abajo (rechazo de las caidas).
    wick_side: Optional[Literal["upper", "lower"]] = None
    # "Absorption + Wick": los dos umbrales van DENTRO del indicador porque la
    # condicion solo tiene un `target`. Devuelve 1 si se cumplen los dos.
    abs_op: Optional[Literal["gt", "lt"]] = None
    abs_level: Optional[float] = None
    wick_op: Optional[Literal["gt", "lt"]] = None
    wick_level: Optional[float] = None
    # "Retroceso (%)": si el impulso que se mide es al alza (retroceso desde el
    # maximo, el caso de un gapper) o a la baja (rebote desde el minimo).
    swing_dir: Optional[Literal["up", "down"]] = None
    # Perfil de volumen:
    #   bin_pct     anchura de cada franja, en % del primer precio del dia.
    #   liston_pct  cuanto volumen tiene que tener una franja para contar como
    #               nodo, en % del volumen del POC. El numero de zonas lo pone
    #               el DIA, no un parametro.
    bin_pct: Optional[float] = None
    liston_pct: Optional[float] = None
    # "Zona alta"/"Zona baja": que % del volumen del dia abarca la banda (70 es
    # lo clasico). OJO: es distinto de `liston_pct`, que es el % del volumen del
    # POC que necesita UNA franja para contar como nodo.
    zona_pct: Optional[float] = None

class ComparisonCondition(BaseModel):
    type: Literal["indicator_comparison"] = "indicator_comparison"
    source: IndicatorConfig
    comparator: Comparator
    target: Union[IndicatorConfig, float]
    timeframe: Optional[Timeframe] = None

class PriceLevelDistanceCondition(BaseModel):
    type: Literal["price_level_distance"] = "price_level_distance"
    source: IndicatorConfig
    level: IndicatorConfig
    comparator: Literal["DISTANCE_GT", "DISTANCE_LT"]
    value_pct: float
    position: Optional[Literal["above", "below", "any"]] = "any"
    timeframe: Optional[Timeframe] = None

class CandleCondition(BaseModel):
    type: Literal["candle_pattern"] = "candle_pattern"
    pattern: CandlePattern
    lookback: int = 1
    consecutive_count: int = 1
    timeframe: Optional[Timeframe] = None
    calc_on_heikin: Optional[bool] = False

# Recursive Entry Logic
AnyCondition = Annotated[
    Union[ComparisonCondition, PriceLevelDistanceCondition, CandleCondition],
    Field(discriminator="type")
]

class ConditionGroup(BaseModel):
    type: Literal["group"] = "group"
    operator: Literal["AND", "OR"] = "AND"
    conditions: List[
        Annotated[
            Union['ConditionGroup', ComparisonCondition, PriceLevelDistanceCondition, CandleCondition],
            Field(discriminator="type")
        ]
    ]

class EntryTimeWindow(BaseModel):
    from_time: str
    to_time: str

class EntryLogic(BaseModel):
    timeframe: Timeframe = Timeframe.M1
    root_condition: ConditionGroup
    entry_time_windows: Optional[List[EntryTimeWindow]] = None
    candle_delay: Optional[int] = None

class ExitLogic(BaseModel):
    timeframe: Timeframe = Timeframe.M1
    root_condition: ConditionGroup
    candle_delay: Optional[int] = None

class PartialTakeProfit(BaseModel):
    distance_pct: Union[float, str]
    capital_pct: float

class RiskManagement(BaseModel):
    # Dimensionar la posicion como riesgo / distancia real al stop ("Calculo de
    # Shares por Distancia al SL" en la interfaz). NO estaba declarado, y
    # pydantic va con extra="ignore": el frontend lo mandaba, el esquema lo
    # tiraba sin error ni log, y la estrategia guardada salia siempre con la
    # opcion desactivada. Ver la nota de las TRES CAPAS.
    size_by_sl: Optional[bool] = False
    # STOP HIBRIDO (2026-09-03). Va por `size_by_sl` pero con techo de
    # exposicion: `(hybrid_max_loss_pct% x capital) / hybrid_black_swan_pct%`
    # da los DOLARES maximos de posicion, que se pasan a acciones al precio de
    # la barra. Resuelve el punto ciego del modo por SL: con el stop muy cenido
    # el tamano se dispara y un hueco brutal deja debiendo dinero.
    #
    # Los dos porcentajes viven AQUI, en la estrategia, y no solo en el panel
    # del backtest — decision de Jaume: «afecta DIRECTAMENTE al resultado por
    # backtest». Si vivieran fuera se podria backtestear con unos numeros y
    # operar con otros sin que nada avisara.
    #
    # DECLARADOS AQUI A PROPOSITO (ver «TRES CAPAS» en docs/MEMORIA_MADRE.md
    # §4): pydantic va con extra="ignore", asi que un campo sin declarar se
    # tira SIN error, SIN log y SIN 422 — es justo lo que le paso a `size_by_sl`
    # y por eso las estrategias salian con la opcion apagada.
    hybrid_stop: Optional[bool] = False
    hybrid_black_swan_pct: Optional[float] = None
    hybrid_max_loss_pct: Optional[float] = None
    # ESTILO CANGREJO (2026-09-08, PRD de Alvaro `docs/PRD_ESTILO_CANGREJO.md`).
    # Acota cada trade "o por recorrido del SL, o por perdida maxima". Con SL
    # por estructura la distancia entry->SL cambia en cada entrada, asi que con
    # el mismo market value unos stops cuestan poco y otros muchisimo; estos dos
    # modos le ponen techo, cada uno por un lado:
    #   MODO A `cangrejo_max_sl_dist_pct`   -> el stop nunca a mas de ese % del
    #     entry. Se APRIETA el stop: cambia DONDE se sale, no cuanto se pone.
    #   MODO B `cangrejo_max_loss_at_sl_pct`-> el SL nunca cuesta mas de ese %
    #     de la cuenta. Se encoge el TAMANO: cambia CUANTO se pone, no donde.
    # Son EXCLUYENTES entre si en la UI (`cangrejo_mode` dice cual se ve) y
    # EXCLUYENTES con el stop hibrido; si un payload trajera los dos, el motor
    # arbitra a favor de Cangrejo. Son TECHOS: solo recortan, nunca agrandan.
    #
    # DECLARADOS AQUI DESDE EL DIA 1 por la leccion de las TRES CAPAS: pydantic
    # va con extra="ignore" y un campo sin declarar se cae SIN error, SIN log y
    # SIN 422 — es lo que le paso a `size_by_sl`.
    cangrejo_active: Optional[bool] = False
    cangrejo_mode: Optional[Literal['recorrido', 'perdida']] = None
    cangrejo_max_sl_dist_pct: Optional[float] = None
    cangrejo_max_loss_at_sl_pct: Optional[float] = None
    # INERTES, sin UI. La primera version de la tarjeta tenia cuatro topes
    # sueltos y resulto poco intuitiva (PRD 3); se dejan ADMITIDOS por si algun
    # dia vuelven, para que un borrador viejo no reviente, pero NINGUN motor los
    # lee. No anadir logica que dependa de ellos sin actualizar el PRD.
    cangrejo_max_mv_entry_pct: Optional[float] = None
    cangrejo_max_mv_pyr_pct: Optional[float] = None
    use_hard_stop: Optional[bool] = True
    use_take_profit: Optional[bool] = True
    take_profit_mode: Optional[TakeProfitMode] = TakeProfitMode.FULL
    accept_reentries: Optional[bool] = True
    max_reentries: Optional[int] = -1
    hard_stop: Optional[dict] = Field(default_factory=lambda: {"type": RiskType.PERCENTAGE, "value": 2.0})
    take_profit: Optional[dict] = Field(default_factory=lambda: {"type": RiskType.PERCENTAGE, "value": 6.0})
    partial_take_profits: Optional[List[PartialTakeProfit]] = Field(default_factory=list)
    trailing_stop: Optional[dict] = Field(default_factory=lambda: {"active": False, "type": "Percentage", "buffer_pct": 0.5})
    swing_option: Optional[dict] = Field(default_factory=lambda: {"active": False, "target_day": "gap_1_day"})
    max_drawdown_daily: Optional[float] = None  # Circuit breaker
    # OJO: `max_drawdown_daily` de arriba NO lo lee ningun motor — la interfaz lo
    # pinta ("Max DD Diario") pero no hace nada. Se deja por compatibilidad y
    # para no cambiar en silencio el resultado de estrategias ya guardadas.
    #
    # El cortacircuitos de verdad es este (2026-08-24). Bloque y no un float
    # porque necesita tres cosas: unidad, valor y que hacer con las posiciones
    # abiertas al saltar.
    #   {"enabled": bool,
    #    "unit": "CASH" | "PCT",          # PCT = % del capital de apertura del dia
    #    "value": float,
    #    "on_open_positions": "LET_RUN" | "CLOSE_ALL"}
    daily_loss_limit: Optional[dict] = None

class PostGapPrecondition(BaseModel):
    id: str
    day: Literal['gap_day', 'gap_1_day']
    metric: Literal['volume', 'close_vs_open', 'close_vs_high_low', 'close_vs_pm_high', 'close_vs_pm_low', 'close_vs_high', 'close_vs_low', 'close_vs_vwap', 'close_vs_sma', 'candle_range_pct', 'candle_range_ratio_gap_1_vs_gap']
    operator: Literal['>', '<', '> High', '< Low']
    value: Optional[float] = None
    sma_period: Optional[int] = None

class StrategyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    bias: Literal['long', 'short'] = 'long'
    apply_day: Optional[Literal['gap_day', 'gap_1_day', 'gap_2_day']] = 'gap_day'
    postgap_preconditions: Optional[List[PostGapPrecondition]] = None
    universe_filters: Optional[UniverseFilters] = None
    entry_logic: EntryLogic
    exit_logic: Optional[ExitLogic] = None
    risk_management: RiskManagement
    is_wizard: Optional[bool] = None
    dataset_id: Optional[str] = None
    market_sessions: Optional[List[str]] = None
    custom_start_time: Optional[str] = None
    custom_end_time: Optional[str] = None
    # Piramidacion. Dict opaco (mismo criterio que `strategy_definition` en
    # BacktestRequest): el arbol de condiciones de cada nivel es el mismo que el
    # de entrada/salida y ya lo normaliza strategy_engine. Sin este campo,
    # pydantic lo descartaba en SILENCIO (extra="ignore" por defecto) y una
    # estrategia guardada no podia conservar su piramidacion.
    pyramiding: Optional[dict] = None
    # Modelos avanzados (XGBoost / HMM). Dict opaco por el mismo motivo que
    # `pyramiding`: la lista de features es el mismo tipo de arbol que las
    # condiciones y ya lo valida `advanced_backtest.parse_config`. Sin este
    # campo, pydantic lo descartaria en SILENCIO (extra="ignore" por defecto) y
    # una estrategia guardada perderia su modelo sin dar ningun error.
    advanced_model: Optional[dict] = None

class Strategy(StrategyCreate):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    # PRD_persistir_backtests_ANTIGRAVITY — Parte C: persistent flag for the
    # "Trading Incubator" watchlist (saved strategies under monitoring).
    in_incubator: Optional[bool] = False

