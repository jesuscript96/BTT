import React from 'react';
import { createPortal } from 'react-dom';
import {
    ConditionGroup,
    AnyCondition,
    IndicatorType,
    Comparator,
    IndicatorConfig,
    Timeframe
} from '@/types/strategy';
import { Plus, Trash2, GitBranch, Clock } from 'lucide-react';
import { getAllowedTargets, isOnlyTarget } from '@/lib/indicatorValidation';

// ----------------------------------------------------------------------
// Constants & Helpers
// ----------------------------------------------------------------------

const isTriangle = (name: string) =>
    name === IndicatorType.TRIANGLE_ASCENDING ||
    name === IndicatorType.TRIANGLE_DESCENDING ||
    name === IndicatorType.TRIANGLE_SYMMETRIC;

const isVolumeIndicator = (name?: string): boolean => {
    if (!name) return false;
    return (
        name === IndicatorType.VOLUME ||
        name === IndicatorType.ACCUMULATED_VOLUME ||
        name === IndicatorType.ACCUM_DOLLAR_VOLUME ||
        name === IndicatorType.DOLLAR_VOLUME ||
        name === IndicatorType.YESTERDAY_VOLUME
    );
};

/** Indicadores cuyo valor ES un porcentaje: el resumen de la condicion escribe
 *  "> 20%" en vez de "> 20". Antes esta lista estaba copiada literal en cinco
 *  sitios (aqui dos veces, InlineStrategyBuilder, StrategiesTable y el wizard) y
 *  ya se habian desincronizado: Squeeze solo llevaba el "%" en uno de ellos. */
export const isPercentIndicator = (name?: string): boolean => {
    if (!name) return false;
    return (
        name === IndicatorType.PM_HIGH_GAP ||
        name === IndicatorType.CURRENT_GAP ||
        name === IndicatorType.OPEN_GAP ||
        name === IndicatorType.SQUEEZE ||
        name === IndicatorType.SESSION_FADE ||
        name === IndicatorType.FADE
    );
};

/** Indicadores que solo admiten >, <, >= y <= contra una cifra fija: son una
 *  medida, no un nivel de precio, asi que cruzarlos no significa nada. Squeeze
 *  queda FUERA a proposito — su lista de destinos en indicatorValidation ya lo
 *  deja standalone y no se le tocan los comparadores. */
export const isMeasureIndicator = (name?: string): boolean => {
    if (!name) return false;
    return (
        name === IndicatorType.VOL_BIN_PCT ||
        name === IndicatorType.RETRACEMENT ||
        name === IndicatorType.ABSORPTION ||
        name === IndicatorType.WICK_RATIO ||
        name === IndicatorType.ABSORPTION_WICK ||
        name === IndicatorType.REG_SLOPE ||
        name === IndicatorType.REG_R2 ||
        name === IndicatorType.ATR_EXTENSION ||
        name === IndicatorType.TIME_VS_LEVEL ||
        name === IndicatorType.PM_HIGH_GAP ||
        name === IndicatorType.CURRENT_GAP ||
        name === IndicatorType.OPEN_GAP ||
        name === IndicatorType.SESSION_FADE ||
        name === IndicatorType.FADE
    );
};

const ALLOWED_CROSSES_INDICATORS: IndicatorType[] = [
    IndicatorType.BAR_CLOSE,
    IndicatorType.BAR_OPEN,
    IndicatorType.HIGH_BAR,
    IndicatorType.LOW_BAR,
    IndicatorType.SMA,
    IndicatorType.EMA,
    IndicatorType.VWAP,
    // El uso clasico del MACD ES un cruce (linea contra su señal, o el
    // histograma contra cero), asi que sin esto el indicador queda a medias.
    IndicatorType.MACD,
    IndicatorType.MACD_SIGNAL,
    IndicatorType.MACD_HISTOGRAM,
    // Y el RSI se cruza contra sus niveles (70/30).
    IndicatorType.RSI,
];

export const getDefaultParamsForIndicator = (name: IndicatorType): Partial<IndicatorConfig> => {
    switch (name) {
        case IndicatorType.SMA:
        case IndicatorType.EMA:
        case IndicatorType.ATR:
            return { period: 14 };
        case IndicatorType.RVOL:
            return { period: 20 };
        case IndicatorType.BOLLINGER_BANDS:
            return { period: 20, stdDev: 2, band_line: "Upper" };
        case IndicatorType.DONCHIAN:
            return { period: 20, band_line: "Upper" };
        // Darvas: 3 velas de confirmacion es el parametro clasico del metodo,
        // y "Upper" (la resistencia) es la linea que se usa casi siempre.
        case IndicatorType.DARVAS_BOX:
            return { period: 3, band_line: "Upper" };
        case IndicatorType.HIGH_X_DAYS:
        case IndicatorType.LOW_X_DAYS:
            return { days_lookback: 5 };
        // Overhead: 20 dias (un mes de cotizacion), el dia del maximo y su High
        // como nivel, sin condicion de volumen. Con estos defectos se comporta
        // como el clasico "maximo de los ultimos X dias", pero ajustado por splits.
        case IndicatorType.OVERHEAD_X_DAYS:
            return { days_lookback: 20, overhead_extreme: "max",
                     overhead_ref: "high", overhead_vol_rule: "none" };
        case IndicatorType.PREVIOUS_MAX:
        case IndicatorType.PREVIOUS_MIN:
            return { ap_session: "ap.RTH" };
        case IndicatorType.ELAPSED_TIME:
        case IndicatorType.ELAPSED_TIME_LAST_HIGH:
            return {};
        case IndicatorType.OPENING_RANGE_PLUS:
        case IndicatorType.OPENING_RANGE_MINUS:
        case IndicatorType.OPENING_RANGE_AM_PLUS:
        case IndicatorType.OPENING_RANGE_AM_MINUS:
            return { orb_minutes: 30 };
        case IndicatorType.TRIANGLE_ASCENDING:
        case IndicatorType.TRIANGLE_DESCENDING:
        case IndicatorType.TRIANGLE_SYMMETRIC:
            return { pivot_window: 5, tri_lookback: 35, slope_tolerance: 1.5, min_r_squared: 0.65, min_pivots: 2 };
        // Squeeze: 5 minutos de ventana y direccion "arriba" es el caso tipico
        // (cazar el disparo). La ventana va en MINUTOS DE RELOJ, no en velas.
        case IndicatorType.SQUEEZE:
            return { range_minutes: 5, squeeze_direction: "up" };
        // 20 minutos de ventana: suficiente para que la recta tenga velas que
        // ajustar en premercado y corto para no arrastrar el tramo anterior.
        case IndicatorType.REG_SLOPE:
        case IndicatorType.REG_R2:
            return { range_minutes: 20 };
        // ATR de 14 contra el VWAP: el caso que se mira a diario (cuanto se ha
        // estirado el precio de su media ponderada del dia).
        case IndicatorType.ATR_EXTENSION:
            return { period: 14, ref_level: "vwap", period2: 20 };
        case IndicatorType.TIME_VS_LEVEL:
            return { ref_level: "vwap", level_dir: "above", period2: 20 };
        // 5 minutos de ventana. Los umbrales por defecto son el PERCENTIL 90
        // medido sobre el universo real del bot (absorcion 2,62 y mecha 0,374
        // sobre 2.461 lecturas del 8-9 sep 2026): asi el defecto ya marca "esto
        // es raro" en vez de disparar en cualquier vela.
        // range_minutes 0 = el impulso del DIA entero, que es el caso normal.
        case IndicatorType.RETRACEMENT:
            return { range_minutes: 0, swing_dir: "up" };
        // 3 velas de confirmacion: un equilibrio razonable entre pivotes de
        // ruido (1-2) y pivotes fiables pero tardios (8+).
        case IndicatorType.LAST_PIVOT:
            return { pivot_window: 3, swing_dir: "up" };
        // Franjas del 1 % del precio y liston al 60 % del POC: con eso salen
        // las dos o tres zonas de verdad de un dia normal.
        case IndicatorType.VOL_BIN_PCT:
        case IndicatorType.VOL_POC:
            return { bin_pct: 1.0 };
        case IndicatorType.VOL_NODE_UP:
        case IndicatorType.VOL_NODE_DOWN:
            return { bin_pct: 1.0, liston_pct: 60 };
        // 70 % del volumen es el clasico de la zona de valor.
        case IndicatorType.VOL_ZONE_HIGH:
        case IndicatorType.VOL_ZONE_LOW:
            return { bin_pct: 1.0, zona_pct: 70 };
        case IndicatorType.ABSORPTION:
            return { range_minutes: 5 };
        case IndicatorType.WICK_RATIO:
            return { range_minutes: 5, wick_side: "upper" };
        case IndicatorType.ABSORPTION_WICK:
            return { range_minutes: 5, wick_side: "upper", abs_op: "gt",
                     abs_level: 2.5, wick_op: "gt", wick_level: 0.4 };
        case IndicatorType.RSI:
            return { period: 14 };
        // MACD: rapida 12, lenta 26, señal 9 — los periodos clasicos. Los tres
        // se pasan igual para las tres lineas, porque las tres salen del mismo
        // calculo; lo unico que cambia es cual de las tres se devuelve.
        case IndicatorType.MACD:
        case IndicatorType.MACD_SIGNAL:
        case IndicatorType.MACD_HISTOGRAM:
            return { period: 12, period2: 26, period3: 9 };
        // Fade de premercado: es el caso que se mira a diario (cuanto se
        // desinflo el PM antes de abrir el mercado).
        case IndicatorType.SESSION_FADE:
            return { session_ref: "pm" };
        // Fade vivo contra el maximo previo, con la misma sesion por defecto que
        // "Previous Max" para que los dos digan lo mismo cuando se combinan.
        case IndicatorType.FADE:
            return { fade_ref: "previous_max", ap_session: "ap.RTH" };
        default:
            return {};
    }
};

export const INDICATOR_CATEGORIES: Record<string, IndicatorType[]> = {
    "Price Variables": [
        IndicatorType.BAR_CLOSE, IndicatorType.BAR_OPEN,
        IndicatorType.HIGH_BAR, IndicatorType.LOW_BAR,
        IndicatorType.PM_OPEN, IndicatorType.PM_HIGH, IndicatorType.PM_LOW,
        IndicatorType.RTH_OPEN, IndicatorType.RTH_HIGH, IndicatorType.RTH_LOW,
        IndicatorType.AM_OPEN,
        IndicatorType.PREVIOUS_MAX, IndicatorType.PREVIOUS_MIN,
        IndicatorType.LAST_PIVOT,
        IndicatorType.VOL_POC, IndicatorType.VOL_NODE_UP,
        IndicatorType.VOL_NODE_DOWN,
        IndicatorType.VOL_ZONE_HIGH, IndicatorType.VOL_ZONE_LOW,
        IndicatorType.ELAPSED_TIME_LAST_HIGH,
        IndicatorType.ELAPSED_TIME,
        IndicatorType.YESTERDAY_OPEN, IndicatorType.YESTERDAY_CLOSE,
        IndicatorType.YESTERDAY_HIGH, IndicatorType.YESTERDAY_LOW,
        IndicatorType.OVERHEAD_X_DAYS,
        IndicatorType.HIGH_X_DAYS, IndicatorType.LOW_X_DAYS,
        IndicatorType.PREV_BAR_CLOSE, IndicatorType.PREV_BAR_OPEN,
        IndicatorType.PREV_BAR_HIGH, IndicatorType.PREV_BAR_LOW,
    ],
    "Behaviour & Patterns": [
        IndicatorType.CONSEC_HIGHER_HIGHS, IndicatorType.CONSEC_LOWER_LOWS,
        IndicatorType.CONSEC_LOWER_HIGHS, IndicatorType.CONSEC_HIGHER_LOWS,
        IndicatorType.CONSEC_GREEN_CANDLES, IndicatorType.CONSEC_RED_CANDLES,
        IndicatorType.CANDLE_RANGE_PCT,
        IndicatorType.RECORRIDO_PCT,
        IndicatorType.OPENING_RANGE_PLUS, IndicatorType.OPENING_RANGE_MINUS,
        IndicatorType.OPENING_RANGE_AM_PLUS, IndicatorType.OPENING_RANGE_AM_MINUS,
        IndicatorType.TRIANGLE_ASCENDING, IndicatorType.TRIANGLE_DESCENDING,
        IndicatorType.TRIANGLE_SYMMETRIC,
        IndicatorType.PM_HIGH_GAP,
        IndicatorType.CURRENT_GAP,
        IndicatorType.OPEN_GAP,
        IndicatorType.SESSION_FADE,
        IndicatorType.FADE,
    ],
    "Indicators": [
        IndicatorType.SMA, IndicatorType.EMA, IndicatorType.VWAP,
        IndicatorType.DONCHIAN, IndicatorType.DARVAS_BOX,
        IndicatorType.BOLLINGER_BANDS,
        IndicatorType.ACCUMULATED_VOLUME,
        IndicatorType.ACCUM_DOLLAR_VOLUME,
        IndicatorType.DOLLAR_VOLUME,
        IndicatorType.RVOL, IndicatorType.VOLUME, IndicatorType.ATR,
        IndicatorType.SQUEEZE,
        IndicatorType.RSI, IndicatorType.MACD,
        IndicatorType.MACD_SIGNAL, IndicatorType.MACD_HISTOGRAM,
    ],
    // Bloque aparte a peticion de Jaume (9-sep-2026): son medidas que no
    // existen en ninguna plataforma comercial, asi que mezclarlas con SMA o
    // RSI las esconde. Todas son MEDIDAS (solo se comparan contra una cifra),
    // todas resuelven sus ventanas por RELOJ y no por velas, y todas llevan el
    // descriptivo largo con ejemplo y niveles medidos.
    "Alternativos": [
        IndicatorType.VOL_BIN_PCT,
        IndicatorType.REG_SLOPE, IndicatorType.REG_R2,
        IndicatorType.ATR_EXTENSION,
        IndicatorType.ABSORPTION, IndicatorType.WICK_RATIO,
        IndicatorType.ABSORPTION_WICK,
        IndicatorType.RETRACEMENT,
        IndicatorType.TIME_VS_LEVEL,
    ],
};

// Human-readable labels for comparators using symbols
export const COMPARATOR_LABELS: Record<string, string> = {
    [Comparator.GT]: ">",
    [Comparator.LT]: "<",
    [Comparator.GTE]: "≥",
    [Comparator.LTE]: "≤",
    [Comparator.EQ]: "=",
    [Comparator.CROSSES_ABOVE]: "↗ Crosses Above",
    [Comparator.CROSSES_BELOW]: "↘ Crosses Below",
};

export const INDICATOR_LABELS: Record<string, string> = {
    // Price Variables
    [IndicatorType.BAR_CLOSE]: "Bar Close",
    [IndicatorType.BAR_OPEN]: "Bar Open",
    [IndicatorType.HIGH_BAR]: "High Bar",
    [IndicatorType.LOW_BAR]: "Low Bar",
    [IndicatorType.PM_OPEN]: "PM Open",
    [IndicatorType.PM_HIGH]: "PM High",
    [IndicatorType.PM_LOW]: "PM Low",
    [IndicatorType.RTH_OPEN]: "RTH Open",
    [IndicatorType.RTH_HIGH]: "RTH High",
    [IndicatorType.RTH_LOW]: "RTH Low",
    [IndicatorType.AM_OPEN]: "AM Open",
    [IndicatorType.PREVIOUS_MAX]: "Previous Max",
    [IndicatorType.PREVIOUS_MIN]: "Previous Min",
    [IndicatorType.YESTERDAY_OPEN]: "Yesterday Open",
    [IndicatorType.YESTERDAY_CLOSE]: "Yesterday Close",
    [IndicatorType.YESTERDAY_HIGH]: "Yesterday High",
    [IndicatorType.YESTERDAY_LOW]: "Yesterday Low",
    [IndicatorType.OVERHEAD_X_DAYS]: "Overhead last X days",
    [IndicatorType.HIGH_X_DAYS]: "High of last X days",
    [IndicatorType.LOW_X_DAYS]: "Low of last X days",
    [IndicatorType.PREV_BAR_CLOSE]: "Prev. Bar Close",
    [IndicatorType.PREV_BAR_OPEN]: "Prev. Bar Open",
    [IndicatorType.PREV_BAR_HIGH]: "Prev. Bar High",
    [IndicatorType.PREV_BAR_LOW]: "Prev. Bar Low",
    [IndicatorType.ELAPSED_TIME_LAST_HIGH]: "Elapsed Time Last High",
    [IndicatorType.ELAPSED_TIME]: "Elapsed Time",
    // Behaviour & Patterns
    [IndicatorType.CONSEC_HIGHER_HIGHS]: "Consec Higher Highs",
    [IndicatorType.CONSEC_LOWER_LOWS]: "Consec Lower Lows",
    [IndicatorType.CONSEC_LOWER_HIGHS]: "Consec Lower Highs",
    [IndicatorType.CONSEC_HIGHER_LOWS]: "Consec Higher Lows",
    [IndicatorType.CONSEC_GREEN_CANDLES]: "Consec Green Candles",
    [IndicatorType.CONSEC_RED_CANDLES]: "Consec Red Candles",
    [IndicatorType.CANDLE_RANGE_PCT]: "Candle Range %",
    [IndicatorType.RECORRIDO_PCT]: "Recorrido (%)",
    [IndicatorType.OPENING_RANGE_PLUS]: "Opening Range +",
    [IndicatorType.OPENING_RANGE_MINUS]: "Opening Range -",
    [IndicatorType.OPENING_RANGE_AM_PLUS]: "Opening Range AM +",
    [IndicatorType.OPENING_RANGE_AM_MINUS]: "Opening Range AM -",
    [IndicatorType.TRIANGLE_ASCENDING]: "▲ Triangle Ascending",
    [IndicatorType.TRIANGLE_DESCENDING]: "▼ Triangle Descending",
    [IndicatorType.TRIANGLE_SYMMETRIC]: "◇ Triangle Symmetric",
    [IndicatorType.PM_HIGH_GAP]: "PM High Gap (%)",
    [IndicatorType.CURRENT_GAP]: "Current Gap (%)",
    [IndicatorType.OPEN_GAP]: "Open Gap (%)",
    [IndicatorType.SESSION_FADE]: "% Session Fade",
    [IndicatorType.FADE]: "% Fade",
    // Indicators
    [IndicatorType.SMA]: "SMA",
    [IndicatorType.EMA]: "EMA",
    [IndicatorType.VWAP]: "VWAP",
    [IndicatorType.DONCHIAN]: "Donchian",
    [IndicatorType.DARVAS_BOX]: "Darvas Box",
    [IndicatorType.BOLLINGER_BANDS]: "Bollinger Bands",
    [IndicatorType.ACCUMULATED_VOLUME]: "Accum. Volume",
    [IndicatorType.ACCUM_DOLLAR_VOLUME]: "Acum. Dollar Volume",
    [IndicatorType.DOLLAR_VOLUME]: "Dollar Volume",
    [IndicatorType.YESTERDAY_VOLUME]: "Yesterday Volume",
    [IndicatorType.RVOL]: "RVOL by bar",
    [IndicatorType.VOLUME]: "Volume",
    [IndicatorType.ATR]: "ATR",
    [IndicatorType.SQUEEZE]: "Squeeze",
    [IndicatorType.REG_SLOPE]: "Reg. Slope (%/min)",
    [IndicatorType.REG_R2]: "Reg. R²",
    [IndicatorType.ATR_EXTENSION]: "ATR Extension",
    [IndicatorType.VOL_BIN_PCT]: "Vol. de la franja (percentil)",
    [IndicatorType.VOL_POC]: "Punto de control",
    [IndicatorType.VOL_NODE_UP]: "Nodo de arriba",
    [IndicatorType.VOL_NODE_DOWN]: "Nodo de abajo",
    [IndicatorType.VOL_ZONE_HIGH]: "Zona alta (borde superior)",
    [IndicatorType.VOL_ZONE_LOW]: "Zona baja (borde inferior)",
    [IndicatorType.LAST_PIVOT]: "\u00daltimo pivote",
    [IndicatorType.RETRACEMENT]: "Retroceso (%)",
    [IndicatorType.ABSORPTION]: "Absorción (M$ por 1%)",
    [IndicatorType.WICK_RATIO]: "Ratio de mecha",
    [IndicatorType.ABSORPTION_WICK]: "Absorción + Mecha",
    [IndicatorType.TIME_VS_LEVEL]: "Time vs Level (min)",
    [IndicatorType.RSI]: "RSI",
    [IndicatorType.MACD]: "MACD",
    [IndicatorType.MACD_SIGNAL]: "MACD Signal",
    [IndicatorType.MACD_HISTOGRAM]: "MACD Histograma",
};

interface TooltipContextType {
    setActiveTooltip: (tooltip: { text: string; x: number; y: number; width?: number; title?: string; } | null) => void;
    containerRef: React.RefObject<HTMLDivElement | null>;
}
const TooltipContext = React.createContext<TooltipContextType | null>(null);

export const INDICATOR_DESCRIPTIONS: Record<string, string> = {
    [IndicatorType.BAR_CLOSE]: "Precio de cierre de la barra actual.",
    [IndicatorType.BAR_OPEN]: "Precio de apertura de la barra actual.",
    [IndicatorType.HIGH_BAR]: "Precio máximo de la barra actual.",
    [IndicatorType.LOW_BAR]: "Precio mínimo de la barra actual.",
    [IndicatorType.PM_OPEN]: "Apertura del Premarket (04:00).",
    [IndicatorType.PM_HIGH]: "Máximo de la sesión de Premarket.",
    [IndicatorType.PM_LOW]: "Mínimo de la sesión de Premarket.",
    [IndicatorType.RTH_OPEN]: "Precio de apertura de la sesión ordinaria de mercado (RTH, 09:30).",
    [IndicatorType.RTH_HIGH]: "Máximo de la sesión ordinaria de mercado (RTH).",
    [IndicatorType.RTH_LOW]: "Mínimo de la sesión ordinaria de mercado (RTH).",
    [IndicatorType.AM_OPEN]: "Apertura de la sesión After Market (16:00).",
    [IndicatorType.PREVIOUS_MAX]: "Último Máximo desde la apertura de la sesión de referencia y la vela actual",
    [IndicatorType.PREVIOUS_MIN]: "Último Mínimo desde la apertura de la sesión de referencia y la vela actual",
    [IndicatorType.ELAPSED_TIME_LAST_HIGH]: "Minutos transcurridos desde el último máximo de la sesión.",
    [IndicatorType.ELAPSED_TIME]: "Tiempo transcurrido desde la apertura de la orden (en minutos) para forzar su cierre.",
    [IndicatorType.YESTERDAY_OPEN]: "Precio de apertura de ayer.",
    [IndicatorType.YESTERDAY_CLOSE]: "Precio de cierre de ayer.",
    [IndicatorType.YESTERDAY_HIGH]: "Precio máximo de ayer.",
    [IndicatorType.YESTERDAY_LOW]: "Precio mínimo de ayer.",
    [IndicatorType.OVERHEAD_X_DAYS]: "El nivel que dejó el día más extremo de los últimos X días de cotización, sobre velas DIARIAS de sesión regular (sin premercado ni after). Funciona en dos pasos: primero busca el día del máximo más alto (o el del mínimo más bajo) y después mira el volumen DE ESE DÍA. Ojo: si el máximo lo hizo un día flojo, la señal se descarta — no se baja al siguiente techo. «Nivel» elige qué precio de ese día usas: el High suele ser una mecha que nadie defendió, mientras que el Close del día del spike sí es resistencia de verdad. Todo va ajustado por splits, así que un contrasplit ya no deja el nivel 20 veces por debajo del precio. Si pones condición de volumen, el nivel puede aparecer o desaparecer durante el día, porque el volumen de hoy va creciendo.",
    [IndicatorType.HIGH_X_DAYS]: "Versión antigua, se mantiene solo para estrategias ya guardadas: el máximo de los últimos X días SIN ajustar por splits. Usa «Overhead last X days».",
    [IndicatorType.LOW_X_DAYS]: "Versión antigua, se mantiene solo para estrategias ya guardadas: el mínimo de los últimos X días SIN ajustar por splits. Usa «Overhead last X days» con «Día del mínimo».",
    [IndicatorType.PREV_BAR_CLOSE]: "El precio de cierre de la barra inmediatamente anterior",
    [IndicatorType.PREV_BAR_OPEN]: "El precio de apertura de la barra inmediatamente anterior",
    [IndicatorType.PREV_BAR_HIGH]: "El precio máximo de la barra inmediatamente anterior",
    [IndicatorType.PREV_BAR_LOW]: "El precio mínimo de la barra inmediatamente anterior",
    
    // Behaviour & Patterns
    [IndicatorType.CONSEC_HIGHER_HIGHS]: "Número de máximos consecutivos más altos (velas consecutivas subiendo).",
    [IndicatorType.CONSEC_LOWER_LOWS]: "Número de mínimos consecutivos más bajos.",
    [IndicatorType.CONSEC_LOWER_HIGHS]: "Número de velas consecutivas con máximos más bajos.",
    [IndicatorType.CONSEC_HIGHER_LOWS]: "Número de velas consecutivas con mínimos más altos.",
    [IndicatorType.CONSEC_GREEN_CANDLES]: "Número de velas consecutivas alcistas (cierre > apertura).",
    [IndicatorType.CONSEC_RED_CANDLES]: "Número de velas consecutivas bajistas (cierre < apertura).",
    [IndicatorType.CANDLE_RANGE_PCT]: "Cuánto se mueve la vela de apertura a cierre, en %, SIN signo: da igual si subió o bajó. (La descripción anterior decía «High vs Low» y era falsa: el motor no mira las mechas.) Si necesitas saber la dirección, usa «Recorrido (%)».",
    [IndicatorType.RECORRIDO_PCT]: "Recorrido de la vela CON SIGNO: lo que se mueve de apertura a cierre, en %. Positivo si subió, negativo si bajó, así que el signo te da la dirección y no hace falta elegirla aparte. «Recorrido (%) > 3» pide una vela que suba más de un 3%; «< -2», una que caiga más de un 2%. Mide el cuerpo, no las mechas: una vela que se dispara y lo devuelve todo cuenta como lo que cerró. Se compara solo contra una cifra, y respeta el timeframe del bloque (en 5m mide la vela de 5m).",
    [IndicatorType.OPENING_RANGE_PLUS]: "Rompimiento alcista del rango de apertura (ej. los primeros 5/15/30 mins).",
    [IndicatorType.OPENING_RANGE_MINUS]: "Rompimiento bajista del rango de apertura.",
    [IndicatorType.OPENING_RANGE_AM_PLUS]: "Rompimiento alcista en After Market.",
    [IndicatorType.OPENING_RANGE_AM_MINUS]: "Rompimiento bajista en After Market.",
    [IndicatorType.TRIANGLE_ASCENDING]: "Patrón de triángulo ascendente.",
    [IndicatorType.TRIANGLE_DESCENDING]: "Patrón de triángulo descendente.",
    [IndicatorType.TRIANGLE_SYMMETRIC]: "Patrón de triángulo simétrico.",
    [IndicatorType.PM_HIGH_GAP]: "El máximo gap hecho durante la sesión de premercado, es decir, el % de diferencia entre el cierre de ayer y el máximo del premarket high.",
    [IndicatorType.OPEN_GAP]: "Gap con el que ABRIÓ el mercado: % de diferencia entre la apertura del RTH (09:30) y el cierre del día anterior. A diferencia del PM High Gap no depende de dónde llegó el premercado, y a diferencia del Current Gap no se mueve: una vez abre, se queda fijo todo el día. OJO: antes de las 09:30 vale NaN y cualquier condición sobre él es falsa — en premercado todavía no se sabe a cuánto va a abrir, y darlo por sabido sería mirar el futuro.",
    [IndicatorType.CURRENT_GAP]: "Gap vivo del precio respecto al cierre de ayer: % de diferencia entre el precio actual (cierre de la vela que se evalúa) y el cierre del día anterior. A diferencia del PM High Gap, sigue al precio durante todo el día (PM y RTH) y baja si el precio baja.",
    [IndicatorType.SESSION_FADE]: "Cuánto se desinfló una sesión ENTERA, en positivo (20 = cayó un 20%). Con «Premarket» mide del PM High a la apertura de mercado; con «Mercado (RTH)», del máximo de la sesión regular a la apertura del After. Es un número congelado: nace en el instante en que abre la sesión siguiente y ya no cambia en todo el día. Antes de ese instante NO existe, así que cualquier condición que lo use es falsa (no se puede saber el fade del premercado a las 07:00). Sale negativo si la apertura fue por encima del máximo.",
    [IndicatorType.FADE]: "Cuánto ha caído el precio AHORA desde una referencia, en positivo (20 = está un 20% por debajo). Con «Máximo previo» la referencia es el máximo hecho hasta la vela anterior, así que se reancla sola: cada nuevo máximo devuelve el fade a cero. Con «Cruce del VWAP» la referencia es el precio del VWAP en la vela en que el precio lo cruzó por última vez, y se mantiene fija hasta el cruce siguiente (por eso el fade sigue creciendo aunque el VWAP baje). Negativo = el precio está por encima de la referencia.",

    // Technical Indicators
    [IndicatorType.SMA]: "Media Móvil Simple.",
    [IndicatorType.EMA]: "Media Móvil Exponencial.",
    [IndicatorType.VWAP]: "Precio Medio Ponderado por Volumen de la sesión.",
    [IndicatorType.DONCHIAN]: "Canales de Donchian.",
    [IndicatorType.DARVAS_BOX]: "Caja de Darvas: resistencia (Upper) y soporte (Lower) horizontales. El techo se valida cuando N velas seguidas no lo superan; el suelo, cuando N velas seguidas no lo perforan. Las mechas construyen la caja; solo un CIERRE fuera la rompe.",
    [IndicatorType.BOLLINGER_BANDS]: "Bandas de Bollinger.",
    [IndicatorType.ACCUMULATED_VOLUME]: "Volumen total acumulado desde el inicio de la sesión en Premarket hasta la vela actual",
    [IndicatorType.ACCUM_DOLLAR_VOLUME]: "Suma acumulada, desde el inicio de la sesión hasta la vela actual, del volumen de cada vela multiplicado por su cierre (Σ de volumen × Close de cada vela).",
    [IndicatorType.DOLLAR_VOLUME]: "Valor en dólares de la vela actual: su volumen multiplicado por su cierre (volumen × Close), sin acumular.",
    [IndicatorType.YESTERDAY_VOLUME]: "Volumen total registrado el día de ayer.",
    [IndicatorType.RVOL]: "Volumen relativo de la barra respecto a su hora histórica.",
    [IndicatorType.VOLUME]: "Volumen individual de la barra actual.",
    [IndicatorType.ATR]: "Rango Medio Verdadero.",
    [IndicatorType.RSI]: "Índice de Fuerza Relativa (0-100). Mide si el precio viene subiendo con más fuerza de la que baja en las últimas N velas. Por encima de 70 se considera sobrecomprado y por debajo de 30 sobrevendido, pero en un pump esos niveles se saturan durante horas: úsalo como medida de agotamiento, no como señal por sí solo.",
    [IndicatorType.MACD]: "Línea MACD: diferencia entre la media exponencial rápida (12) y la lenta (26). Por encima de cero el impulso es alcista; por debajo, bajista. Lo clásico es cruzarla con su Señal.",
    [IndicatorType.MACD_SIGNAL]: "Señal del MACD: media exponencial (9) de la propia línea MACD. Sola no dice mucho — su uso natural es que la línea MACD la cruce por arriba (impulso al alza) o por abajo (a la baja).",
    [IndicatorType.MACD_HISTOGRAM]: "Histograma del MACD: la distancia entre la línea MACD y su Señal. Cuando cruza el cero es exactamente el cruce de las otras dos, y su tamaño dice cuánta fuerza tiene el movimiento. Es el más cómodo de los tres para una condición contra una cifra.",
    [IndicatorType.SQUEEZE]: "Spike de precio: cuánto se ha movido el cierre respecto al de hace X MINUTOS DE RELOJ (no velas). Devuelve el porcentaje SIEMPRE en positivo en la dirección elegida, así que «Squeeze > 10» significa «se ha disparado más de un 10%» tanto arriba como abajo. Solo se compara contra una cifra. Ojo: mide punta a punta, así que un zigzag dentro de la ventana cuenta el neto (100→110→104,5→114,95 son +15%), pero una caída seguida de una subida dentro de la misma ventana se compensan.",
    [IndicatorType.REG_SLOPE]: "Pendiente de la recta de mínimos cuadrados ajustada al PRECIO de los últimos X MINUTOS DE RELOJ (no velas). Se ajusta sobre el precio y no sobre una media a propósito: una EMA va retrasada y la recta no. Sale en % POR MINUTO y está normalizada por el precio medio de la ventana, así que el mismo umbral vale para un ticker de 0,60 $ y para uno de 45 $. Positiva = sube; negativa = baja, así que para cortos se busca NEGATIVA. Órdenes de magnitud con ventana de 20 minutos: por debajo de ±0,05 %/min está plano (un 1% en 20 min); de ±0,10 a ±0,25 es tendencia clara (2-5% en 20 min); ±0,50 es un movimiento fuerte (10% en 20 min); por encima de ±1,00 %/min es vertical y no suele durar. Ojo: la pendiente NO distingue una subida limpia de una sierra que sube dando bandazos — para eso está Reg. R², y lo normal es usar los dos juntos.",
    [IndicatorType.REG_R2]: "Calidad del ajuste de esa MISMA recta, de 0 a 1: qué parte del movimiento explica la tendencia y qué parte es ruido. Dos tramos que suben exactamente lo mismo pueden ser una escalera (R² ≈ 0,95) o una sierra que va y viene cuatro veces (R² ≈ 0,15) — y esa segunda te saca del stop varias veces por el camino. Referencias: por encima de 0,80 el movimiento es muy limpio y admite un stop cerca; de 0,50 a 0,80 es una tendencia normal con ruido; por debajo de 0,30 no hay tendencia, es un rango agitado. No tiene unidades, así que el umbral vale igual en cualquier ticker y a cualquier hora. DOS AVISOS: un precio plano también da R² alto (la recta horizontal lo explica entero), así que hay que combinarlo SIEMPRE con Reg. Slope; y un R² que cae mientras la pendiente sigue positiva es el primer aviso de que el impulso se deshace — llega antes que el giro de la pendiente.",
    [IndicatorType.ATR_EXTENSION]: "Cuántos ATR separan al precio de su referencia (el VWAP por defecto). Positivo = por encima de la referencia; negativo = por debajo. Es la versión comparable de «está un 8% sobre el VWAP»: un 8% es una barbaridad en un ticker que se mueve un 2% al día y es ruido en uno que se mueve un 30%, así que un umbral en % no vale para el universo entero y uno en ATR sí. Referencias con ATR de 14: de 0 a 1 ATR es la zona normal de trabajo; de 2 a 3 ATR ya está estirado; de 4 a 6 ATR es una extensión fuerte, que es el terreno clásico del fade; por encima de 8 ATR es un spike vertical. Para cortar un gap estirado se suele pedir > 3 o > 4. El primer campo es el periodo del ATR; el segundo, el periodo de la media SOLO si la referencia es SMA o EMA.",
    [IndicatorType.TIME_VS_LEVEL]: "Minutos SEGUIDOS que el precio lleva por encima (o por debajo) del nivel elegido. Es la «aceptación», y es lo que una condición normal no puede decir: para «precio > PM High» son idénticos un precio que lleva 2 minutos arriba y uno que lleva 90, y son situaciones opuestas. Devuelve 0 cuando la condición no se cumple, y se reinicia en cada sesión — una racha nunca se arrastra de un día al siguiente. Cuenta MINUTOS DE RELOJ, no velas: si el ticker se queda media hora sin cotizar, esa media hora cuenta igual. Vale NaN mientras el nivel todavía no existe (antes de las 09:30 no hay RTH Open) y comparar contra NaN da falso, así que no hay señal sin referencia. Referencias: menos de 3 minutos es un pinchazo que puede ser solo una mecha; de 10 a 20 minutos ya es aceptación real; más de 45 minutos es un cambio de régimen.",
    [IndicatorType.VOL_ZONE_HIGH]: "El borde SUPERIOR de la zona de valor: la banda de precios donde se ha negociado la mayor parte del día. Es un PRECIO, así que se cruza, se compara y sirve de stop. CÓMO SE CONSTRUYE: se arranca en la franja con más volumen (el punto de control) y se van añadiendo las franjas vecinas más gordas, arriba o abajo, hasta juntar el % del volumen que le pidas (70 es lo clásico). Los dos extremos de esa banda son «Zona alta» y «Zona baja». EN QUÉ SE DIFERENCIA DE «Nodo de arriba», que es la duda habitual: el nodo es RELATIVO AL PRECIO — es la primera zona que hay por encima de donde estás ahora, así que salta cada vez que el precio cruza una franja y parece que te persigue. La zona de valor NO mira dónde está el precio: son las bandas del día, y solo se mueven cuando cambia el reparto del volumen. Medido en OLB (9-sep): la zona alta cambió 22 veces en 223 velas y el nodo de arriba 43, el doble. PARA QUÉ: para ver de un vistazo si el precio está DENTRO de la zona (movimiento pesado, hay gente) o se ha salido por arriba o por abajo. En OLB el precio acabó el día en 0,3394 con la zona en 0,3860-0,4403: fuera y por debajo, que es donde no hay nada que frene. Vale NaN en la primera vela del día y se reinicia cada sesión.",
    [IndicatorType.VOL_ZONE_LOW]: "El borde INFERIOR de la misma banda. Todo lo dicho en «Zona alta» vale igual aquí: se construye desde el punto de control hacia fuera hasta juntar el % de volumen que pidas, y NO se mueve con el precio. USO NATURAL EN CORTO: mientras el precio esté por encima de este borde, sigue dentro de la zona negociada y cuesta que se caiga. Cuando lo pierde, entra en terreno donde casi nadie ha comprado — y ahí no hay soporte. La condición «Bar Close cruza por debajo de Zona baja» es exactamente ese momento. COMBINACIONES: con «Absorción» baja, la caída es limpia porque no hay nadie parando; con «Absorción» alta, alguien está recogiendo ahí abajo y el corto es más peligroso. Y con «Vol. de la franja» por debajo de 30 confirmas que estás en el vacío y no en otra cresta.",
    [IndicatorType.VOL_BIN_PCT]: "Qué porcentaje de las franjas de precio con volumen del día tienen MENOS volumen que la franja donde está el precio ahora mismo. De 0 a 100. QUÉ ES UNA FRANJA: el perfil de volumen reparte todo lo negociado del día por PRECIOS en vez de por tiempo — «a 0,42 se cruzaron 2 millones de acciones» en lugar de «a las 10:15 se cruzaron 40.000». Cada vela reparte su volumen entre todas las franjas que toca, de su mínimo a su máximo, porque una vela que recorre un 5% no dejó todo su volumen en un solo precio. PARA QUÉ SIRVE: donde se cruzó mucho volumen hay mucha gente con su coste, y esa gente vende cuando el precio vuelve a su break-even; por eso ahí el precio se mueve pesado. Donde no se cruzó nada no hay nadie, y el precio atraviesa esa zona rápido en cualquier dirección. EJEMPLO REAL (OLB, 9-sep-2026): a las 12:33 el precio estaba en el percentil 95, pegado a la zona más negociada del día, y llevaba horas dando vueltas ahí. A las 13:33 bajó al 39 y a las 14:33 al 27: había salido al vacío. Entre esos dos momentos se fue de 0,39 a 0,34 — un 20% — porque debajo no quedaba nadie que lo frenara. NIVELES: por encima de 80 estás en zona cargada (el corto tiene ayuda, pero cuesta que se mueva); de 40 a 70 es terreno normal; por debajo de 30 es un vacío, y ahí el precio se va rápido en cualquier dirección — bueno si corre a tu favor, malo si va en contra. COMBINACIONES: con «Absorción» alta, la zona tiene un vendedor de verdad detrás y no es solo estadística; con «Absorción» baja y percentil bajo, no hay nada que frene la caída. EL PARÁMETRO es la anchura de cada franja en % del precio: 1 es un punto de partida sensato; más pequeño da más detalle y más ruido. Se recalcula en cada vela con lo que va del día, y se reinicia cada sesión.",
    [IndicatorType.VOL_POC]: "El precio de la franja con MÁS volumen del día: el sitio donde más gente tiene su coste. Es un PRECIO, así que se puede cruzar contra el Bar Close, comparar con el VWAP o usarse de stop y de objetivo. Funciona como imán: cuanto más lejos está el precio, más tensión hay hacia volver, porque el que compró ahí y está en pérdidas vende en cuanto recupera. EJEMPLO REAL (OLB, 9-sep-2026): el punto de control estuvo todo el día entre 0,4194 y 0,4236, que es donde el precio pasó la mañana entera; cuando lo abandonó por abajo ya no volvió. USO NATURAL: como objetivo de un corto que entra estirado por arriba, y como referencia de «esto está caro o barato respecto a donde está la gente». Combinado con «ATR Extension» te dice esa distancia en unidades comparables entre tickers. OJO, Y ESTO IMPORTA: un día puede tener DOS zonas de volumen y el punto de control solo señala la más gorda. Si el precio está en la segunda cresta, el punto de control dirá que está «lejos» cuando en realidad está rodeado de gente. Para eso están «Nodo de arriba» y «Nodo de abajo», que no dan por hecho que el perfil tenga una sola joroba. Vale NaN en la primera vela del día y se reinicia cada sesión.",
    [IndicatorType.VOL_NODE_UP]: "El precio de la primera franja POR ENCIMA de la actual que tiene volumen suficiente para contar como zona: la resistencia real del día, la que sale del dinero cruzado y no de unir dos máximos con una regla. Es un PRECIO: se cruza, se compara y sirve de stop de estructura. EL LISTÓN es lo que decide qué cuenta como zona — una franja es nodo si tiene al menos ese % del volumen de la franja más gorda. Con 85 solo pasan las zonas grandes; con 60 salen las de verdad (dos o tres en un día normal); con 30 pasa casi todo y aparece ruido. Fíjate en que NO le dices cuántas zonas quieres: le dices cuánto tiene que pesar una franja para contar, y el número de zonas lo pone el día. Si hubo una zona sale una, si hubo tres salen tres. USO NATURAL EN CORTO: es el stop. Por encima hay oferta acumulada que te protege, así que el stop tiene una razón detrás en vez de ser una distancia inventada. EJEMPLO REAL (OLB, 9-sep-2026, listón 60): a las 14:33, con el precio en 0,3624, el nodo de arriba estaba en 0,4027 — todo el papel que se había acumulado por la mañana. VALE NaN cuando por encima no hay ninguna zona, y eso es un aviso en sí mismo: no hay techo conocido por delante. Comparar contra NaN da falso, así que una condición con este indicador no dispara mientras no haya nodo.",
    [IndicatorType.VOL_NODE_DOWN]: "Lo mismo hacia abajo: el primer precio con volumen suficiente por DEBAJO del actual. El soporte real del día. Es un PRECIO y sirve de stop, de objetivo y de cruce. Y AQUÍ ESTÁ LA SEÑAL MÁS ÚTIL DE TODO EL PERFIL: cuando vale NaN significa que POR DEBAJO NO HAY NADIE. No queda gente con su coste ahí, así que no hay nada que frene una caída. EJEMPLO REAL (OLB, 9-sep-2026, listón 60): a las 12:33 el nodo de abajo estaba en 0,4194, justo debajo del precio. A las 13:33 desapareció. Entre ese momento y el cierre el precio se fue de 0,3895 a 0,3394. La DESAPARICIÓN del soporte llegó antes que la caída. USOS: como objetivo de un corto (ahí es donde se va a frenar), como stop de un largo, y sobre todo el cruce — «Bar Close cruza por debajo del Nodo de abajo» es literalmente «acaba de comerse el soporte real y entra en el vacío». COMBINACIONES: con «Absorción» baja no hay nadie que lo pare y la caída es limpia; con «Absorción» alta hay alguien recogiendo abajo y el corto es mucho más peligroso. El listón funciona igual que en «Nodo de arriba».",
    [IndicatorType.LAST_PIVOT]: "El último techo (o suelo) que dejó el mercado, como PRECIO. Un techo es una vela cuyo máximo es mayor que el de las N velas de su izquierda Y el de las N de su derecha; el suelo es el espejo con los mínimos. NO ES LO MISMO QUE «Previous max», y la diferencia importa: aquel es el máximo corrido del día y NUNCA baja. Con la secuencia 10 → 15 → 12 → 14 → 11, «Previous max» se queda en 15 para siempre, mientras que el último pivote alto es 14 (el techo que el mercado acaba de dejar) y el último pivote bajo es 12 (el suelo, cuando «Previous min» daría 10). Para un stop eso lo cambia todo: 15 está lejísísimos y 14 está pegado. EL PARÁMETRO son las velas de CONFIRMACIÓN a cada lado, y es un intercambio real: con 1 o 2 salen pivotes de ruido; con 8 o más son fiables pero llegan tarde. 3 es un punto de partida razonable. OJO AL RETARDO, que no es un defecto sino la naturaleza de la cosa: un pivote no se puede confirmar hasta que pasan N velas sin superarlo, así que el nivel aparece N velas DESPUÉS de haber ocurrido. Eso es justo lo que lo hace causal: nunca se mira una vela que aún no existe. Vale NaN hasta que se confirma el primero del día, y se reinicia cada sesión. Como es un precio y no una medida, se puede comparar contra el precio y contra otros niveles, y también se puede elegir como stop de estructura.",
    [IndicatorType.RETRACEMENT]: "Qué fracción del impulso se ha devuelto ya, en % del propio impulso (no del precio). EJEMPLO: el precio sube de 10,00 a 15,00 — ha ganado 5,00. Si baja a 14,00 ha devuelto 1 de 5, o sea 20. A 13,00 son 40. A 11,00 son 80 y el impulso está prácticamente roto. Por encima de 100 ha perforado la base de la que salió. Al hacer un máximo nuevo el impulso se reancla y vuelve casi a 0, igual que «Previous max» se actualiza vela a vela. CÓMO SE DEFINE EL IMPULSO, y esto importa: el máximo es el mayor high corrido y la base es el menor low ANTERIOR a la vela en que se hizo ese máximo. Todo pasado, así que NO mira al futuro — a diferencia de un pivote clásico, que necesita ver N velas por delante para confirmarse. POR QUÉ NO ES LO MISMO QUE «% Fade»: el fade mide la caída en % del PRECIO, así que un 8% significa cosas distintas en un ticker que se movió un 10% y en uno que se movió un 200%. Esto lo normaliza por el tamaño del impulso, y por eso el mismo umbral vale para todo el universo. NIVELES ORIENTATIVOS: por debajo de 30 el impulso aguanta y el comprador sigue ahí; entre 40 y 60 es un retroceso normal; por encima de 70 el que compró arriba está atrapado y la continuación es bastante menos probable. Los números de Fibonacci (38,2 y 61,8) no tienen ninguna evidencia detrás: mide dónde está el corte real en TU universo, que para eso tienes el lago. La ventana en minutos limita el impulso a ese tramo de reloj; déjala en 0 para medir el impulso del día entero. Vale NaN mientras no haya impulso que medir (primera vela del día, o precio plano).",
    [IndicatorType.ABSORPTION]: "Cuántos MILLONES de dólares hicieron falta para mover el precio un 1%, en una ventana de X MINUTOS DE RELOJ. Es la profundidad del mercado y se lee al derecho: cuanto MÁS ALTO, más caro es moverlo, o sea más absorción. EJEMPLO: en 5 minutos se negocian 2 millones de dólares y el precio acaba un 0,35% por encima de donde empezó → 2 / 0,35 = 5,7. Eso no es calma, es que alguien está poniendo a la venta exactamente tanto como le compran; en una small cap suele ser un ATM, un insider o un fondo saliendo — gente sin prisa y con tamaño que colocar, y por eso el nivel aguanta. NIVELES MEDIDOS sobre 2.461 lecturas reales del universo del bot (8-9 sep 2026, ventana de 5 min): la mitad están por debajo de 0,26; el percentil 75 es 0,85; el 90 es 2,6; el 95 es 5,1 y el 99 es 17,5. Léelo así: por debajo de 0,3 el precio se mueve con nada (código de barras); a partir de 2,5 hay alguien al otro lado; por encima de 5 es un muro. OJO al denominador: es el desplazamiento NETO de la ventana, no el rango. Una vela que sube y vuelve al mismo sitio ha avanzado cero y por eso puntúa alto — que es justo lo que se busca. Vale NaN si la ventana solo tiene una vela.",
    [IndicatorType.WICK_RATIO]: "Qué fracción de todo lo que recorrió el precio en la ventana se devolvió en forma de mecha, de 0 a 1. Con «arriba» mide el rechazo de las subidas (alguien vende cada empujón); con «abajo», el de las caídas (alguien compra cada hundimiento). EJEMPLO: una vela abre en 5,00, sube a 5,40 y cierra en 5,05, con mínimo en 4,98. Recorrido total 0,42, mecha superior 0,35 → 0,83: le devolvieron el 83% de lo que subió. Se suma sobre toda la ventana para no depender de una vela suelta, que puede ser un mal print. NIVELES MEDIDOS sobre 2.474 lecturas reales (8-9 sep 2026, ventana de 5 min, mecha superior): la MEDIANA es 0,21 — en un día normal siempre se devuelve una quinta parte del recorrido y eso no significa nada; el percentil 75 es 0,29; el 90 es 0,37; el 95 es 0,43 y el 99 es 0,58. Pedir «> 0,5» deja fuera al 97% de las lecturas y casi no dispara nunca: para un filtro que salte de vez en cuando, 0,40 es un punto de partida razonable.",
    [IndicatorType.ABSORPTION_WICK]: "Devuelve 1 cuando se cumplen LAS DOS condiciones a la vez y 0 cuando no (se compara contra 0: «> 0» es «se cumplen las dos»). Existe porque por separado ninguna de las dos dice gran cosa — la lectura de una depende de cómo esté la otra: ▸ ABSORCIÓN ALTA + MECHA ALTA = hay un vendedor real y además defendido; ese nivel es el techo. Es la combinación que se busca para cortar. ▸ ABSORCIÓN ALTA + MECHA BAJA = alguien absorbe pero sin rechazo visible; puede ser acumulación, y ahí cortarse es peligroso. ▸ ABSORCIÓN BAJA + MECHA ALTA = mecha sin dinero detrás; es ruido de libro vacío y no significa nada. ▸ ABSORCIÓN BAJA + MECHA BAJA = sube sin encontrar resistencia, no hay nadie vendiendo; NO es sitio para cortos. Fíjate en que la cuarta combinación te evita más pérdidas de las que ganancias te da la primera, que suele ser el reparto real de este negocio. Los umbrales por defecto (2,5 y 0,40) son el percentil 90 de cada medida sobre el universo real del bot, así que de salida marcan «esto es raro» en vez de dispararse en cualquier vela."
};

const PARAM_FIELD_STYLE: React.CSSProperties = {
    backgroundColor: 'var(--color-ec-bg-sidebar)',
    border: '0.5px solid var(--color-ec-border)',
    borderRadius: 5,
    padding: '5px 10px',
    fontSize: 'var(--ec-fs-select)',
    fontWeight: 500,
    color: 'var(--color-ec-text-primary)',
    fontFamily: 'var(--color-ec-sans)',
    outline: 'none',
};

/** Niveles de referencia de "ATR Extension" y "Time vs Level". El backend
 *  resuelve cada uno llamando al indicador que ya existe, asi que no hay una
 *  segunda formula del VWAP o del PM High que pueda divergir de la primera. */
const REF_LEVEL_OPTIONS: { value: string; label: string }[] = [
    { value: "vwap", label: "VWAP" },
    { value: "sma", label: "SMA" },
    { value: "ema", label: "EMA" },
    { value: "day_open", label: "Apertura del día" },
    { value: "rth_open", label: "Apertura RTH (09:30)" },
    { value: "pmh", label: "PM High" },
    { value: "pml", label: "PM Low" },
    { value: "prev_close", label: "Cierre de ayer" },
    { value: "previous_max", label: "Máximo previo" },
    { value: "previous_min", label: "Mínimo previo" },
    { value: "hod", label: "Máximo del día" },
    { value: "lod", label: "Mínimo del día" },
];

const ALLOWED_OFFSET_INDICATORS: IndicatorType[] = [
    IndicatorType.BAR_CLOSE,
    IndicatorType.BAR_OPEN,
    IndicatorType.HIGH_BAR,
    IndicatorType.LOW_BAR,
    IndicatorType.CONSEC_HIGHER_HIGHS,
    IndicatorType.CONSEC_LOWER_LOWS,
    IndicatorType.CONSEC_LOWER_HIGHS,
    IndicatorType.CONSEC_HIGHER_LOWS,
    IndicatorType.CONSEC_GREEN_CANDLES,
    IndicatorType.CONSEC_RED_CANDLES,
    IndicatorType.CANDLE_RANGE_PCT,
    IndicatorType.RECORRIDO_PCT,
    IndicatorType.SMA,
    IndicatorType.EMA,
    IndicatorType.VWAP,
    IndicatorType.ACCUMULATED_VOLUME,
    IndicatorType.ACCUM_DOLLAR_VOLUME,
    IndicatorType.DOLLAR_VOLUME,
    IndicatorType.BOLLINGER_BANDS,
    IndicatorType.DONCHIAN,
    IndicatorType.DARVAS_BOX,
    IndicatorType.RVOL,
    IndicatorType.VOLUME,
    IndicatorType.ATR
];

const isOffsetAllowed = (name: IndicatorType | string): boolean => {
    return ALLOWED_OFFSET_INDICATORS.includes(name as IndicatorType);
};

/**
 * Ayuda de las OPCIONES de un parámetro, visible sin pasar el ratón.
 *
 * Jaume, 7-sep-2026: «lo del fade y este tipo de cosas, cuando pongas la
 * descripción en los desplegables hay que ponerla para que lo vea, porque si
 * no no sé cómo configurarlo en un backtest más tarde».
 *
 * Un `title=` no vale: solo sale al pasar el ratón por encima y nadie lo hace.
 * El tooltip del indicador tampoco, porque describe el indicador entero y no
 * cambia con la opción que tienes puesta. Esto se pinta DEBAJO del selector y
 * dice lo que hace la opción elegida ahora mismo.
 *
 * Los textos salen de leer el motor, no de la intuición:
 * `_ap_session_started` e `_vwap_cross_ref_series` en `indicators.py`.
 */
export const AYUDA_OPCION: Record<string, string> = {
    // % Session Fade — qué sesión se desinfla
    "session_ref.pm": "Del PM High a la apertura de mercado. Nace a las 09:30 y ya no cambia en todo el día; antes de esa hora NO existe y la condición es falsa.",
    "session_ref.rth": "Del máximo de la sesión regular a la apertura del After (16:00). Nace a las 16:00; antes no existe.",
    "session_ref.full": "Del máximo del día ENTERO (premercado y mercado juntos, el que sea más alto) a la apertura del After. En un gap que se muere el máximo suele ser el PM High, así que éste y el de RTH dan números muy distintos.",
    // % Fade — desde dónde se mide la caída
    "fade_ref.previous_max": "La referencia es el máximo hecho hasta la vela ANTERIOR — la actual no cuenta, así que comparar contra él no es circular. Cada máximo nuevo devuelve el fade a cero. Desde cuándo empieza a contar ese máximo lo eliges en el selector de al lado.",
    "fade_ref.vwap_cross": "La referencia es el VWAP DE LA VELA en que el precio lo cruzó por última vez, y se queda fija hasta el cruce siguiente: por eso el fade sigue creciendo aunque el VWAP baje. Ese VWAP es acumulativo desde la primera vela del día (04:00, premercado incluido) y NO se reinicia al abrir el mercado. Antes del primer cruce del día no existe. Aquí la sesión de referencia no se usa.",
    // Overhead — la regla de volumen y qué precio del día es el nivel
    "overhead_vol_rule.none": "El nivel vale siempre, mire lo que mire el volumen.",
    "overhead_vol_rule.gt": "Solo cuenta si AQUEL día movió MÁS volumen que el que llevas acumulado hoy hasta esta vela. Ojo: como el volumen de hoy va creciendo, por la mañana esto se cumple casi siempre y por la tarde casi nunca — si no quieres que acabe siendo un filtro horario encubierto, acótalo con tu filtro de volumen mínimo o con la ventana de entrada.",
    "overhead_vol_rule.lt": "Solo cuenta si aquel día movió MENOS volumen que el acumulado de hoy: el techo se hizo con poca gente y hoy estás moviendo más. Por la mañana casi nunca se cumple.",
    "overhead_ref.high": "El máximo de aquel día. Es el nivel clásico, pero muchas veces es una mecha que nadie defendió.",
    "overhead_ref.low": "El mínimo de aquel día. En un día de spike, el suelo desde el que arrancó.",
    "overhead_ref.open": "La apertura de aquel día.",
    "overhead_ref.close": "El cierre de aquel día: donde se quedó el precio al cerrar el mercado. Suele aguantar mejor como resistencia que el máximo.",
    // ap_session — desde cuándo cuenta el máximo/mínimo
    "ap_session.ap.PM": "Cuenta desde la primera vela del día (04:00): el máximo incluye el premercado.",
    "ap_session.ap.RTH": "Empieza a contar a las 09:30: solo la sesión regular, sin premercado.",
    "ap_session.ap.AM": "Empieza a contar a las 16:00: solo el after.",
};

// Estilo comun de los cinco controles de "Overhead last X days". Van con
// flexWrap: entran dos por fila y la regla de volumen ocupa la suya entera.
const SELECT_OVERHEAD: React.CSSProperties = {
    flex: '1 1 45%',
    minWidth: 0,
    backgroundColor: 'var(--color-ec-bg-sidebar)',
    border: '0.5px solid var(--color-ec-border)',
    borderRadius: 5,
    padding: '5px 10px',
    fontSize: 'var(--ec-fs-select)',
    fontWeight: 500,
    color: 'var(--color-ec-text-primary)',
    fontFamily: 'var(--color-ec-sans)',
    outline: 'none',
};

// El campo de dias con su etiqueta al lado: el `placeholder` desaparece en
// cuanto tiene valor, y el indicador nace con 20 puesto, asi que sin etiqueta
// se veria un numero pelado.
const CAMPO_OVERHEAD: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 5, flex: '1 1 100%', minWidth: 0,
};

const ETIQUETA_OVERHEAD: React.CSSProperties = {
    fontSize: 10, fontWeight: 700, letterSpacing: 0.4, whiteSpace: 'nowrap',
    textTransform: 'uppercase', color: 'var(--color-ec-text-muted)',
};

const AyudaOpcion = ({ clave }: { clave: string }) => {
    const texto = AYUDA_OPCION[clave];
    if (!texto) return null;
    return (
        <span style={{
            flexBasis: '100%', fontSize: 10, lineHeight: 1.4,
            color: 'var(--color-ec-text-muted)',
        }}>
            {texto}
        </span>
    );
};

const TooltipIcon = ({ indicatorName, customText }: { indicatorName?: IndicatorType; customText?: string }) => {
    const context = React.useContext(TooltipContext);
    if (!context) return null;

    const { setActiveTooltip } = context;
    const description = customText || (indicatorName ? INDICATOR_DESCRIPTIONS[indicatorName] : undefined);
    if (!description) return null;

    return (
        <span
            onMouseEnter={(e) => {
                setActiveTooltip({
                    text: description,
                    x: e.clientX,
                    y: e.clientY,
                    width: 185,
                    title: indicatorName ? (INDICATOR_LABELS[indicatorName] || indicatorName) : undefined
                });
                e.currentTarget.style.color = "var(--color-ec-text-primary)";
                e.currentTarget.style.borderColor = "var(--color-ec-text-muted)";
                e.currentTarget.style.backgroundColor = "var(--color-ec-bg-surface)";
            }}
            onMouseLeave={(e) => {
                setActiveTooltip(null);
                e.currentTarget.style.color = "var(--color-ec-text-muted)";
                e.currentTarget.style.borderColor = "var(--color-ec-border)";
                e.currentTarget.style.backgroundColor = "var(--color-ec-bg-elevated)";
            }}
            style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 14,
                height: 14,
                borderRadius: "50%",
                backgroundColor: "var(--color-ec-bg-elevated)",
                border: "0.5px solid var(--color-ec-border)",
                color: "var(--color-ec-text-muted)",
                fontSize: 9,
                fontWeight: 700,
                cursor: "help",
                flexShrink: 0,
                userSelect: "none",
                transition: "all 150ms ease",
            }}
        >
            ?
        </span>
    );
};

const FIXED_VALUE_KEY = "__FIXED_VALUE__";

export const getInitialTargetForSource = (sourceName: IndicatorType): IndicatorConfig | number => {
    const allowed = getAllowedTargets(sourceName, 'indicator_comparison');
    if (allowed.length === 0) {
        return 0; // Fixed value
    }
    if (allowed.includes(IndicatorType.VWAP)) {
        return { name: IndicatorType.VWAP, offset: 0 };
    }
    return { name: allowed[0], offset: 0 };
};

// ----------------------------------------------------------------------
// Generic Selector
// ----------------------------------------------------------------------
export const IndicatorSelector = ({ 
    value, 
    onChange, 
    isTarget,
    allowedTargets,
    exclude = [],
    width = '100%'
}: { 
    value: string, 
    onChange: (val: string) => void, 
    isTarget?: boolean,
    allowedTargets?: IndicatorType[],
    exclude?: IndicatorType[],
    width?: string | number
}) => {
    const [isOpen, setIsOpen] = React.useState(false);
    const dropdownRef = React.useRef<HTMLDivElement>(null);

    React.useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const selectedLabel = value === FIXED_VALUE_KEY ? '── Fixed Value ──' : (INDICATOR_LABELS[value as IndicatorType] || value);

    return (
        <div 
            ref={dropdownRef} 
            style={{ 
                position: 'relative', 
                width: width,
                display: 'inline-block'
            }}
        >
            <div
                onClick={() => setIsOpen(!isOpen)}
                style={{
                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                    border: '0.5px solid var(--color-ec-border)',
                    borderRadius: 5,
                    padding: '5px 10px',
                    fontSize: 'var(--ec-fs-select)',
                    fontWeight: 500,
                    color: 'var(--color-ec-text-primary)',
                    fontFamily: 'var(--color-ec-sans)',
                    width: '100%',
                    cursor: 'pointer',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    userSelect: 'none',
                    boxSizing: 'border-box'
                }}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden', flex: 1 }}>
                    <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{selectedLabel}</span>
                    {value !== FIXED_VALUE_KEY && (
                        <span onClick={(e) => e.stopPropagation()} style={{ display: 'inline-flex', alignItems: 'center' }}>
                            <TooltipIcon indicatorName={value as IndicatorType} />
                        </span>
                    )}
                </div>
                <span style={{ fontSize: 8, color: 'var(--color-ec-text-muted)', marginLeft: 6 }}>
                    {isOpen ? '▲' : '▼'}
                </span>
            </div>

            {isOpen && (
                <div style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    marginTop: 4,
                    width: '100%',
                    minWidth: 220,
                    maxHeight: 280,
                    overflowY: 'auto',
                    backgroundColor: 'var(--color-ec-bg-elevated)',
                    border: '0.5px solid var(--color-ec-border)',
                    borderRadius: 5,
                    boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
                    zIndex: 9999, // Ensure it floats above everything
                    fontFamily: 'var(--color-ec-sans)',
                }}>
                    {Object.entries(INDICATOR_CATEGORIES).map(([category, indicators]) => {
                        const filtered = indicators.filter(t => 
                            (allowedTargets ? allowedTargets.includes(t) : true) && 
                            !exclude.includes(t)
                        );
                        if (filtered.length === 0) return null;
                        
                        return (
                            <div key={category}>
                                <div style={{
                                    padding: '5px 10px',
                                    fontSize: 9,
                                    fontWeight: 700,
                                    color: 'var(--color-ec-text-muted)',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.08em',
                                    backgroundColor: 'rgba(255,255,255,0.01)',
                                    borderBottom: '0.5px solid var(--color-ec-border)',
                                    borderTop: '0.5px solid var(--color-ec-border)',
                                }}>
                                    {category}
                                </div>
                                {filtered.map(t => {
                                    const isSelected = value === t;
                                    return (
                                        <div 
                                             key={t}
                                             style={{
                                                 display: 'flex',
                                                 alignItems: 'center',
                                                 justifyContent: 'flex-start',
                                                 backgroundColor: isSelected ? 'rgba(216, 122, 61, 0.08)' : 'transparent',
                                                 borderLeft: isSelected ? '3px solid var(--color-ec-copper)' : '3px solid transparent',
                                                 padding: '4px 10px',
                                             }}
                                             onMouseEnter={(e) => {
                                                 if (!isSelected) e.currentTarget.style.backgroundColor = 'var(--color-ec-bg-surface)';
                                             }}
                                             onMouseLeave={(e) => {
                                                 if (!isSelected) e.currentTarget.style.backgroundColor = 'transparent';
                                             }}
                                         >
                                             <div 
                                                 onClick={() => { onChange(t); setIsOpen(false); }}
                                                 style={{
                                                     flex: 1,
                                                     display: 'flex',
                                                     alignItems: 'center',
                                                     gap: 6,
                                                     cursor: 'pointer',
                                                     color: isSelected ? 'var(--color-ec-copper-bright)' : 'var(--color-ec-text-primary)',
                                                     fontWeight: isSelected ? 600 : 400,
                                                     fontSize: 11.5,
                                                     minWidth: 0,
                                                 }}
                                             >
                                                 <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                                                     {INDICATOR_LABELS[t] || t}
                                                 </span>
                                                 <span 
                                                     onClick={(e) => e.stopPropagation()} 
                                                     style={{ display: 'inline-flex', alignItems: 'center' }}
                                                 >
                                                     <TooltipIcon indicatorName={t} />
                                                 </span>
                                             </div>
                                         </div>
                                    );
                                })}
                            </div>
                        );
                    })}
                    {isTarget && (
                        <div 
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                backgroundColor: value === FIXED_VALUE_KEY ? 'rgba(216, 122, 61, 0.08)' : 'transparent',
                                borderLeft: value === FIXED_VALUE_KEY ? '3px solid var(--color-ec-copper)' : '3px solid transparent',
                                borderTop: '0.5px solid var(--color-ec-border)',
                            }}
                            onMouseEnter={(e) => {
                                if (value !== FIXED_VALUE_KEY) e.currentTarget.style.backgroundColor = 'var(--color-ec-bg-surface)';
                            }}
                            onMouseLeave={(e) => {
                                if (value !== FIXED_VALUE_KEY) e.currentTarget.style.backgroundColor = 'transparent';
                            }}
                        >
                            <div 
                                onClick={() => { onChange(FIXED_VALUE_KEY); setIsOpen(false); }}
                                style={{
                                    flex: 1,
                                    padding: '6px 10px',
                                    cursor: 'pointer',
                                    color: value === FIXED_VALUE_KEY ? 'var(--color-ec-copper-bright)' : 'var(--color-ec-text-primary)',
                                    fontWeight: value === FIXED_VALUE_KEY ? 600 : 400,
                                    fontSize: 11.5,
                                }}
                            >
                                ── Fixed Value ──
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

// ----------------------------------------------------------------------
// Dynamic Inputs specific to Indicator
// ----------------------------------------------------------------------
export const IndicatorParams = ({
    value,
    onChange,
    hideOffset = false
}: {
    value: IndicatorConfig;
    onChange: (val: IndicatorConfig) => void;
    hideOffset?: boolean;
}) => {
    return (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', width: '100%' }}>
            {/* Specific Params */}
            {(() => {
                switch (value.name) {
                    case IndicatorType.MACD:
                    case IndicatorType.MACD_SIGNAL:
                    case IndicatorType.MACD_HISTOGRAM: {
                        // Tres periodos: rapida, lenta y señal. Las tres lineas
                        // salen del MISMO calculo, asi que los tres campos
                        // aparecen igual en las tres — lo unico que cambia es
                        // cual de las tres series se devuelve.
                        const campo = (
                            clave: "period" | "period2" | "period3",
                            etiqueta: string, defecto: number, ayuda: string,
                        ) => (
                            <input
                                key={clave}
                                type="number"
                                min={1}
                                value={value[clave] ?? ''}
                                onChange={(e) => onChange({ ...value, [clave]: e.target.value === '' ? undefined : Number(e.target.value) })}
                                onFocus={(e) => e.target.select()}
                                placeholder={etiqueta}
                                title={`${ayuda} (por defecto ${defecto})`}
                                style={{
                                    flex: '1 1 60px',
                                    minWidth: '60px',
                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                    border: '0.5px solid var(--color-ec-border)',
                                    borderRadius: 5,
                                    padding: '5px 10px',
                                    fontSize: 'var(--ec-fs-select)',
                                    fontWeight: 500,
                                    color: 'var(--color-ec-text-primary)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    outline: 'none',
                                }}
                            />
                        );
                        return (
                            <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap', alignItems: 'center' }}>
                                {campo("period", "Rápida", 12, "Media exponencial rápida")}
                                {campo("period2", "Lenta", 26, "Media exponencial lenta")}
                                {campo("period3", "Señal", 9, "Media de la propia línea MACD")}
                            </div>
                        );
                    }
                    case IndicatorType.SMA:
                    case IndicatorType.EMA:
                    case IndicatorType.ATR:
                    case IndicatorType.RVOL:
                    case IndicatorType.RSI:
                        return (
                            <input
                                type="number"
                                value={value.period ?? ''}
                                onChange={(e) => onChange({ ...value, period: e.target.value === '' ? undefined : Number(e.target.value) })}
                                onFocus={(e) => e.target.select()}
                                placeholder="Period"
                                style={{
                                    width: '100%',
                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                    border: '0.5px solid var(--color-ec-border)',
                                    borderRadius: 5,
                                    padding: '5px 10px',
                                    fontSize: 'var(--ec-fs-select)',
                                    fontWeight: 500,
                                    color: 'var(--color-ec-text-primary)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    outline: 'none',
                                }}
                                title="Period"
                            />
                        );
                    case IndicatorType.BOLLINGER_BANDS:
                    case IndicatorType.DONCHIAN:
                    case IndicatorType.DARVAS_BOX:
                        return (
                            <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap' }}>
                                <input
                                    type="number"
                                    value={value.period ?? ''}
                                    onChange={(e) => onChange({ ...value, period: e.target.value === '' ? undefined : Number(e.target.value) })}
                                    onFocus={(e) => e.target.select()}
                                    // En Darvas el periodo no es una ventana movil: son las
                                    // velas de CONFIRMACION que el techo (o el suelo) tiene que
                                    // aguantar para validarse. Merece su propia etiqueta.
                                    placeholder={value.name === IndicatorType.DARVAS_BOX ? "Velas" : "Period"}
                                    style={{
                                        flex: '1 1 70px',
                                        minWidth: '70px',
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 'var(--ec-fs-select)',
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                    }}
                                    title={value.name === IndicatorType.DARVAS_BOX
                                        ? "Velas de confirmación: cuántas velas seguidas tienen que respetar el nivel para que quede validado"
                                        : "Period"}
                                />
                                {value.name === IndicatorType.BOLLINGER_BANDS && (
                                    <input
                                        type="number"
                                        value={value.stdDev ?? ''}
                                        onChange={(e) => onChange({ ...value, stdDev: e.target.value === '' ? undefined : Number(e.target.value) })}
                                        onFocus={(e) => e.target.select()}
                                        placeholder="Std Dev"
                                        style={{
                                            flex: '1 1 70px',
                                            minWidth: '70px',
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: '5px 10px',
                                            fontSize: 'var(--ec-fs-select)',
                                            fontWeight: 500,
                                            color: 'var(--color-ec-text-primary)',
                                            fontFamily: 'var(--color-ec-sans)',
                                            outline: 'none',
                                        }}
                                        title="Standard Deviation"
                                    />
                                )}
                                <select
                                    value={value.band_line || 'Upper'}
                                    onChange={(e) => onChange({ ...value, band_line: e.target.value as "Upper" | "Lower" | "Basis" })}
                                    style={{
                                        flex: '1 1 90px',
                                        minWidth: '90px',
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 'var(--ec-fs-select)',
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                        cursor: 'pointer',
                                    }}
                                >
                                    {/* El valor que viaja al backend es siempre Upper/Lower/Basis
                                        (band_line). Solo cambia la etiqueta: en Darvas "banda
                                        superior" no dice nada y "resistencia" sí. */}
                                    {value.name === IndicatorType.DARVAS_BOX ? (
                                        <>
                                            <option value="Upper">Darvas superior (resistencia)</option>
                                            <option value="Lower">Darvas inferior (soporte)</option>
                                            <option value="Basis">Centro de la caja</option>
                                        </>
                                    ) : (
                                        <>
                                            <option value="Upper">Upper</option>
                                            <option value="Lower">Lower</option>
                                            <option value="Basis">Basis</option>
                                        </>
                                    )}
                                </select>
                            </div>
                        );
                    case IndicatorType.SQUEEZE:
                        return (
                            <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap', alignItems: 'center' }}>
                                <input
                                    type="number"
                                    min={1}
                                    value={value.range_minutes ?? ''}
                                    onChange={(e) => onChange({ ...value, range_minutes: e.target.value === '' ? undefined : Number(e.target.value) })}
                                    onFocus={(e) => e.target.select()}
                                    placeholder="Minutos"
                                    style={{
                                        flex: '1 1 70px',
                                        minWidth: '70px',
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 'var(--ec-fs-select)',
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                    }}
                                    title="Ventana en MINUTOS DE RELOJ: en cuánto tiempo se tiene que haber producido el movimiento. No son velas — con temporalidad de 5m, 15 minutos siguen siendo 15 minutos."
                                />
                                <select
                                    value={value.squeeze_direction || 'up'}
                                    onChange={(e) => onChange({ ...value, squeeze_direction: e.target.value as "up" | "down" })}
                                    style={{
                                        flex: '1 1 90px',
                                        minWidth: '90px',
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 'var(--ec-fs-select)',
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                        cursor: 'pointer',
                                    }}
                                    title="Dirección del spike. El valor sale SIEMPRE positivo en la dirección elegida, así que la condición se escribe igual en las dos: «> 10» es «más de un 10%»."
                                >
                                    <option value="up">Hacia arriba</option>
                                    <option value="down">Hacia abajo</option>
                                </select>
                            </div>
                        );
                    case IndicatorType.REG_SLOPE:
                    case IndicatorType.REG_R2:
                        return (
                            <input
                                type="number"
                                min={1}
                                value={value.range_minutes ?? ''}
                                onChange={(e) => onChange({ ...value, range_minutes: e.target.value === '' ? undefined : Number(e.target.value) })}
                                onFocus={(e) => e.target.select()}
                                placeholder="Minutos"
                                style={{ ...PARAM_FIELD_STYLE, flex: '1 1 70px', minWidth: '70px' }}
                                title="Ventana en MINUTOS DE RELOJ sobre la que se ajusta la recta. No son velas: con temporalidad de 5m, 20 minutos siguen siendo 20 minutos. Necesita al menos 3 velas dentro de la ventana; con menos vale NaN."
                            />
                        );
                    case IndicatorType.VOL_BIN_PCT:
                    case IndicatorType.VOL_POC:
                    case IndicatorType.VOL_NODE_UP:
                    case IndicatorType.VOL_NODE_DOWN:
                    case IndicatorType.VOL_ZONE_HIGH:
                    case IndicatorType.VOL_ZONE_LOW: {
                        const llevaListon = value.name === IndicatorType.VOL_NODE_UP
                            || value.name === IndicatorType.VOL_NODE_DOWN;
                        const llevaZona = value.name === IndicatorType.VOL_ZONE_HIGH
                            || value.name === IndicatorType.VOL_ZONE_LOW;
                        return (
                            <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap', alignItems: 'center' }}>
                                <div className="relative" style={{ flex: '1 1 96px', minWidth: '96px' }}>
                                    <input
                                        type="number"
                                        step={0.1}
                                        min={0.05}
                                        value={value.bin_pct ?? ''}
                                        onChange={(e) => onChange({ ...value, bin_pct: e.target.value === '' ? undefined : Number(e.target.value) })}
                                        onFocus={(e) => e.target.select()}
                                        placeholder="1"
                                        style={{ ...PARAM_FIELD_STYLE, width: '100%', paddingRight: 44 }}
                                        title="Anchura de cada franja de precio, en % del primer precio del dia. Con 1, un ticker de 0,40 $ tiene franjas de 0,004. Mas pequeno da mas detalle y mas ruido."
                                    />
                                    <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-bold text-muted-foreground/40">
                                        FRANJA
                                    </span>
                                </div>
                                {llevaZona && (
                                    <div className="relative" style={{ flex: '1 1 96px', minWidth: '96px' }}>
                                        <input
                                            type="number"
                                            step={5}
                                            min={10}
                                            max={100}
                                            value={value.zona_pct ?? ''}
                                            onChange={(e) => onChange({ ...value, zona_pct: e.target.value === '' ? undefined : Number(e.target.value) })}
                                            onFocus={(e) => e.target.select()}
                                            placeholder="70"
                                            style={{ ...PARAM_FIELD_STYLE, width: '100%', paddingRight: 40 }}
                                            title="Que % del volumen del dia abarca la banda. Se arranca en el punto de control y se van sumando las franjas vecinas mas gordas hasta llegar a ese porcentaje. 70 es lo clasico: mas alto ensancha la zona, mas bajo la aprieta alrededor del punto de control."
                                        />
                                        <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-bold text-muted-foreground/40">
                                            ZONA
                                        </span>
                                    </div>
                                )}
                                {llevaListon && (
                                    <div className="relative" style={{ flex: '1 1 96px', minWidth: '96px' }}>
                                        <input
                                            type="number"
                                            step={5}
                                            min={0}
                                            max={100}
                                            value={value.liston_pct ?? ''}
                                            onChange={(e) => onChange({ ...value, liston_pct: e.target.value === '' ? undefined : Number(e.target.value) })}
                                            onFocus={(e) => e.target.select()}
                                            placeholder="60"
                                            style={{ ...PARAM_FIELD_STYLE, width: '100%', paddingRight: 44 }}
                                            title="El LISTON: cuanto volumen tiene que tener una franja para contar como zona, en % del volumen de la franja mas gorda. 85 = solo las zonas grandes. 60 = las de verdad, dos o tres en un dia normal. 30 = casi todo, con ruido. No fijas CUANTAS zonas hay: fijas cuanto tienen que pesar, y el numero lo pone el dia."
                                        />
                                        <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-bold text-muted-foreground/40">
                                            LIST\u00d3N
                                        </span>
                                    </div>
                                )}
                            </div>
                        );
                    }
                    case IndicatorType.LAST_PIVOT:
                        return (
                            <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap', alignItems: 'center' }}>
                                <input
                                    type="number"
                                    min={1}
                                    value={value.pivot_window ?? ''}
                                    onChange={(e) => onChange({ ...value, pivot_window: e.target.value === '' ? undefined : Number(e.target.value) })}
                                    onFocus={(e) => e.target.select()}
                                    placeholder="Velas"
                                    style={{ ...PARAM_FIELD_STYLE, flex: '1 1 80px', minWidth: '80px' }}
                                    title="Velas de CONFIRMACION a cada lado. Con 1 o 2 salen pivotes de ruido; con 8 o mas son fiables pero llegan tarde. El nivel aparece estas velas DESPUES de que ocurriera el giro: ese retardo es lo que lo hace causal."
                                />
                                <select
                                    value={value.swing_dir || 'up'}
                                    onChange={(e) => onChange({ ...value, swing_dir: e.target.value as "up" | "down" })}
                                    style={{ ...PARAM_FIELD_STYLE, flex: '1 1 150px', minWidth: '150px', cursor: 'pointer' }}
                                    title="Techo (maximo local) o suelo (minimo local)."
                                >
                                    <option value="up">Pivote alto (techo)</option>
                                    <option value="down">Pivote bajo (suelo)</option>
                                </select>
                            </div>
                        );
                    case IndicatorType.RETRACEMENT:
                        return (
                            <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap', alignItems: 'center' }}>
                                <input
                                    type="number"
                                    min={0}
                                    value={value.range_minutes ?? ''}
                                    onChange={(e) => onChange({ ...value, range_minutes: e.target.value === '' ? undefined : Number(e.target.value) })}
                                    onFocus={(e) => e.target.select()}
                                    placeholder="0 = dia"
                                    style={{ ...PARAM_FIELD_STYLE, flex: '1 1 80px', minWidth: '80px' }}
                                    title="Minutos de RELOJ a los que se limita el impulso. Deja 0 para medir el impulso del dia entero, que es el caso normal. El impulso nunca cruza de un dia al siguiente."
                                />
                                <select
                                    value={value.swing_dir || 'up'}
                                    onChange={(e) => onChange({ ...value, swing_dir: e.target.value as "up" | "down" })}
                                    style={{ ...PARAM_FIELD_STYLE, flex: '1 1 130px', minWidth: '130px', cursor: 'pointer' }}
                                    title="Al alza mide el retroceso desde el maximo (el caso de un gapper que se desinfla); a la baja, el rebote desde el minimo."
                                >
                                    <option value="up">Impulso al alza</option>
                                    <option value="down">Impulso a la baja</option>
                                </select>
                            </div>
                        );
                    case IndicatorType.ABSORPTION:
                    case IndicatorType.WICK_RATIO:
                    case IndicatorType.ABSORPTION_WICK: {
                        const esCombi = value.name === IndicatorType.ABSORPTION_WICK;
                        const llevaMecha = esCombi || value.name === IndicatorType.WICK_RATIO;
                        return (
                            <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap', alignItems: 'center' }}>
                                <input
                                    type="number"
                                    min={1}
                                    value={value.range_minutes ?? ''}
                                    onChange={(e) => onChange({ ...value, range_minutes: e.target.value === '' ? undefined : Number(e.target.value) })}
                                    onFocus={(e) => e.target.select()}
                                    placeholder="Minutos"
                                    style={{ ...PARAM_FIELD_STYLE, flex: '1 1 70px', minWidth: '70px' }}
                                    title="Ventana en MINUTOS DE RELOJ, no en velas. Los percentiles de la descripcion son para una ventana de 5 minutos: si la cambias, cambian."
                                />
                                {llevaMecha && (
                                    <select
                                        value={value.wick_side || 'upper'}
                                        onChange={(e) => onChange({ ...value, wick_side: e.target.value as "upper" | "lower" })}
                                        style={{ ...PARAM_FIELD_STYLE, flex: '1 1 110px', minWidth: '110px', cursor: 'pointer' }}
                                        title="Arriba mide el rechazo de las subidas (vendedor); abajo, el de las caidas (comprador)."
                                    >
                                        <option value="upper">Mecha arriba</option>
                                        <option value="lower">Mecha abajo</option>
                                    </select>
                                )}
                                {esCombi && (
                                    <>
                                        <select
                                            value={value.abs_op || 'gt'}
                                            onChange={(e) => onChange({ ...value, abs_op: e.target.value as "gt" | "lt" })}
                                            style={{ ...PARAM_FIELD_STYLE, flex: '0 1 70px', minWidth: '70px', cursor: 'pointer' }}
                                            title="Absorcion: mayor o menor que el umbral."
                                        >
                                            <option value="gt">Abs &gt;</option>
                                            <option value="lt">Abs &lt;</option>
                                        </select>
                                        <input
                                            type="number"
                                            step={0.1}
                                            value={value.abs_level ?? ''}
                                            onChange={(e) => onChange({ ...value, abs_level: e.target.value === '' ? undefined : Number(e.target.value) })}
                                            onFocus={(e) => e.target.select()}
                                            placeholder="2.5"
                                            style={{ ...PARAM_FIELD_STYLE, flex: '0 1 65px', minWidth: '65px' }}
                                            title="Umbral de absorcion, en millones de $ por cada 1%. Medido: p75=0,85 p90=2,6 p95=5,1 p99=17,5."
                                        />
                                        <select
                                            value={value.wick_op || 'gt'}
                                            onChange={(e) => onChange({ ...value, wick_op: e.target.value as "gt" | "lt" })}
                                            style={{ ...PARAM_FIELD_STYLE, flex: '0 1 80px', minWidth: '80px', cursor: 'pointer' }}
                                            title="Mecha: mayor o menor que el umbral."
                                        >
                                            <option value="gt">Mecha &gt;</option>
                                            <option value="lt">Mecha &lt;</option>
                                        </select>
                                        <input
                                            type="number"
                                            step={0.05}
                                            value={value.wick_level ?? ''}
                                            onChange={(e) => onChange({ ...value, wick_level: e.target.value === '' ? undefined : Number(e.target.value) })}
                                            onFocus={(e) => e.target.select()}
                                            placeholder="0.4"
                                            style={{ ...PARAM_FIELD_STYLE, flex: '0 1 65px', minWidth: '65px' }}
                                            title="Umbral de mecha, de 0 a 1. Medido: mediana=0,21 p75=0,29 p90=0,37 p95=0,43."
                                        />
                                    </>
                                )}
                            </div>
                        );
                    }
                    case IndicatorType.ATR_EXTENSION:
                    case IndicatorType.TIME_VS_LEVEL: {
                        const needsPeriod = value.ref_level === 'sma' || value.ref_level === 'ema';
                        return (
                            <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap', alignItems: 'center' }}>
                                {value.name === IndicatorType.ATR_EXTENSION && (
                                    <input
                                        type="number"
                                        min={1}
                                        value={value.period ?? ''}
                                        onChange={(e) => onChange({ ...value, period: e.target.value === '' ? undefined : Number(e.target.value) })}
                                        onFocus={(e) => e.target.select()}
                                        placeholder="ATR"
                                        style={{ ...PARAM_FIELD_STYLE, flex: '1 1 60px', minWidth: '60px' }}
                                        title="Periodo del ATR con el que se mide la distancia (14 por defecto)."
                                    />
                                )}
                                <select
                                    value={value.ref_level || 'vwap'}
                                    onChange={(e) => onChange({ ...value, ref_level: e.target.value as IndicatorConfig['ref_level'] })}
                                    style={{ ...PARAM_FIELD_STYLE, flex: '1 1 110px', minWidth: '110px', cursor: 'pointer' }}
                                    title="Nivel contra el que se mide."
                                >
                                    {REF_LEVEL_OPTIONS.map(o => (
                                        <option key={o.value} value={o.value}>{o.label}</option>
                                    ))}
                                </select>
                                {needsPeriod && (
                                    <input
                                        type="number"
                                        min={1}
                                        value={value.period2 ?? ''}
                                        onChange={(e) => onChange({ ...value, period2: e.target.value === '' ? undefined : Number(e.target.value) })}
                                        onFocus={(e) => e.target.select()}
                                        placeholder="Media"
                                        style={{ ...PARAM_FIELD_STYLE, flex: '1 1 60px', minWidth: '60px' }}
                                        title="Periodo de la SMA/EMA de referencia. Va aparte del periodo del ATR a proposito: son dos cosas distintas."
                                    />
                                )}
                                {value.name === IndicatorType.TIME_VS_LEVEL && (
                                    <select
                                        value={value.level_dir || 'above'}
                                        onChange={(e) => onChange({ ...value, level_dir: e.target.value as "above" | "below" })}
                                        style={{ ...PARAM_FIELD_STYLE, flex: '1 1 100px', minWidth: '100px', cursor: 'pointer' }}
                                        title="Hacia que lado corre el reloj: cuenta los minutos que el precio lleva SEGUIDOS por encima o por debajo del nivel."
                                    >
                                        <option value="above">Por encima</option>
                                        <option value="below">Por debajo</option>
                                    </select>
                                )}
                            </div>
                        );
                    }
                    case IndicatorType.SESSION_FADE:
                        return (
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, width: '100%' }}>
                            <select
                                value={value.session_ref || 'pm'}
                                onChange={(e) => onChange({ ...value, session_ref: e.target.value as "full" | "pm" | "rth" })}
                                style={{
                                    width: '100%',
                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                    border: '0.5px solid var(--color-ec-border)',
                                    borderRadius: 5,
                                    padding: '5px 10px',
                                    fontSize: 'var(--ec-fs-select)',
                                    fontWeight: 500,
                                    color: 'var(--color-ec-text-primary)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    outline: 'none',
                                    cursor: 'pointer',
                                }}
                                title="Qué sesión se desinfla. Premarket: del PM High a la apertura de mercado (existe a partir de las 09:30). Mercado: del máximo del RTH a la apertura del After. Día completo: del máximo del día ENTERO (premarket y mercado juntos, el que sea más alto) a la apertura del After — el desinflado real del día."
                            >
                                <option value="pm">Premarket → apertura de mercado</option>
                                <option value="rth">Mercado (RTH) → apertura del After</option>
                                <option value="full">Día completo (PM + RTH) → apertura del After</option>
                            </select>
                            <AyudaOpcion clave={`session_ref.${value.session_ref || 'pm'}`} />
                            </div>
                        );
                    case IndicatorType.FADE:
                        return (
                            <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap', alignItems: 'center' }}>
                                <select
                                    value={value.fade_ref || 'previous_max'}
                                    onChange={(e) => onChange({ ...value, fade_ref: e.target.value as "previous_max" | "vwap_cross" })}
                                    style={{
                                        flex: '1 1 130px',
                                        minWidth: '130px',
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 'var(--ec-fs-select)',
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                        cursor: 'pointer',
                                    }}
                                    title="Desde dónde se mide la caída. El máximo previo se reancla en cada máximo nuevo; el cruce del VWAP, en cada cruce."
                                >
                                    <option value="previous_max">Desde el máximo previo</option>
                                    <option value="vwap_cross">Desde el cruce del VWAP</option>
                                </select>
                                {/* La sesión solo pinta con "máximo previo": el cruce del VWAP
                                    se ancla en el cruce, no en el arranque de una sesión. */}
                                {(value.fade_ref || 'previous_max') === 'previous_max' && (
                                    <select
                                        value={value.ap_session || 'ap.RTH'}
                                        onChange={(e) => onChange({ ...value, ap_session: e.target.value as "ap.PM" | "ap.RTH" | "ap.AM" })}
                                        style={{
                                            flex: '1 1 90px',
                                            minWidth: '90px',
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: '5px 10px',
                                            fontSize: 'var(--ec-fs-select)',
                                            fontWeight: 500,
                                            color: 'var(--color-ec-text-primary)',
                                            fontFamily: 'var(--color-ec-sans)',
                                            outline: 'none',
                                            cursor: 'pointer',
                                        }}
                                        title="Desde cuándo empieza a contar el máximo, igual que en «Previous Max»."
                                    >
                                        <option value="ap.PM">ap.PM · 04:00</option>
                                        <option value="ap.RTH">ap.RTH · 09:30</option>
                                        <option value="ap.AM">ap.AM · 16:00</option>
                                    </select>
                                )}
                                <AyudaOpcion clave={`fade_ref.${value.fade_ref || 'previous_max'}`} />
                                {(value.fade_ref || 'previous_max') === 'previous_max' && (
                                    <AyudaOpcion clave={`ap_session.${value.ap_session || 'ap.RTH'}`} />
                                )}
                            </div>
                        );
                    case IndicatorType.OPENING_RANGE_PLUS:
                    case IndicatorType.OPENING_RANGE_MINUS:
                    case IndicatorType.OPENING_RANGE_AM_PLUS:
                    case IndicatorType.OPENING_RANGE_AM_MINUS:
                        return (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%' }}>
                                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>Mins:</span>
                                <input
                                    type="number"
                                    value={value.orb_minutes ?? ''}
                                    onChange={(e) => onChange({ ...value, orb_minutes: e.target.value === '' ? undefined : Number(e.target.value) })}
                                    onFocus={(e) => e.target.select()}
                                    placeholder="Minutes"
                                    style={{
                                        flex: 1,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 'var(--ec-fs-select)',
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                    }}
                                    title="Reference minutes (ex. 30 for 30min ORB)"
                                />
                            </div>
                        );

                    case IndicatorType.HIGH_X_DAYS:
                    case IndicatorType.LOW_X_DAYS:
                        return (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%' }}>
                                <input
                                    type="number"
                                    value={value.days_lookback ?? ''}
                                    onChange={(e) => onChange({ ...value, days_lookback: e.target.value === '' ? undefined : Number(e.target.value) })}
                                    onFocus={(e) => e.target.select()}
                                    placeholder="Days"
                                    style={{
                                        flex: 1,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 'var(--ec-fs-select)',
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                    }}
                                    title="Number of Days Back"
                                />
                                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>días</span>
                            </div>
                        );
                    case IndicatorType.OVERHEAD_X_DAYS:
                        return (
                            <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6, width: '100%' }}>
                                <div style={CAMPO_OVERHEAD} title="Cuántos días de cotización se miran hacia atrás. Hoy nunca entra. 250 son aproximadamente un año.">
                                    <span style={ETIQUETA_OVERHEAD}>Mirar</span>
                                    <input
                                        type="number"
                                        value={value.days_lookback ?? ''}
                                        onChange={(e) => onChange({ ...value, days_lookback: e.target.value === '' ? undefined : Number(e.target.value) })}
                                        onFocus={(e) => e.target.select()}
                                        style={{ ...SELECT_OVERHEAD, flex: 1 }}
                                    />
                                    <span style={ETIQUETA_OVERHEAD}>días</span>
                                </div>
                                <select
                                    value={value.overhead_extreme || 'max'}
                                    onChange={(e) => onChange({ ...value, overhead_extreme: e.target.value as "max" | "min" })}
                                    style={{ ...SELECT_OVERHEAD, cursor: 'pointer' }}
                                >
                                    <option value="max">Día del máximo</option>
                                    <option value="min">Día del mínimo</option>
                                </select>
                                <select
                                    value={value.overhead_ref || 'high'}
                                    onChange={(e) => onChange({ ...value, overhead_ref: e.target.value as "high" | "low" | "open" | "close" })}
                                    style={{ ...SELECT_OVERHEAD, cursor: 'pointer' }}
                                >
                                    <option value="high">Nivel: High</option>
                                    <option value="low">Nivel: Low</option>
                                    <option value="open">Nivel: Open</option>
                                    <option value="close">Nivel: Close</option>
                                </select>
                                <select
                                    value={value.overhead_vol_rule || 'none'}
                                    onChange={(e) => onChange({ ...value, overhead_vol_rule: e.target.value as "none" | "gt" | "lt" })}
                                    style={{ ...SELECT_OVERHEAD, flex: '1 1 100%', cursor: 'pointer' }}
                                >
                                    <option value="none">Volumen: sin condición</option>
                                    <option value="gt">Volumen: aquel día MAYOR que hoy</option>
                                    <option value="lt">Volumen: aquel día MENOR que hoy</option>
                                </select>
                                <AyudaOpcion clave={`overhead_vol_rule.${value.overhead_vol_rule || 'none'}`} />
                                <AyudaOpcion clave={`overhead_ref.${value.overhead_ref || 'high'}`} />
                            </div>
                        );
                    case IndicatorType.PREVIOUS_MAX:
                    case IndicatorType.PREVIOUS_MIN:
                        return (
                            <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6, width: '100%' }}>
                                <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                                    Session:
                                </span>
                                <select
                                    value={value.ap_session || "ap.RTH"}
                                    onChange={(e) => onChange({ ...value, ap_session: e.target.value as "ap.PM" | "ap.RTH" | "ap.AM" })}
                                    style={{
                                        flex: 1,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 'var(--ec-fs-select)',
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                        cursor: 'pointer',
                                    }}
                                >
                                    <option value="ap.PM">ap.PM · 04:00</option>
                                    <option value="ap.RTH">ap.RTH · 09:30</option>
                                    <option value="ap.AM">ap.AM · 16:00</option>
                                </select>
                                <AyudaOpcion clave={`ap_session.${value.ap_session || 'ap.RTH'}`} />
                            </div>
                        );
                    default:
                        // Triangle Patterns
                        if (
                            value.name === IndicatorType.TRIANGLE_ASCENDING ||
                            value.name === IndicatorType.TRIANGLE_DESCENDING ||
                            value.name === IndicatorType.TRIANGLE_SYMMETRIC
                        ) {
                            return (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
                                    <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap' }}>
                                        <div style={{ flex: '1 1 60px', minWidth: '60px' }}>
                                            <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ec-text-muted)', display: 'block', marginBottom: 2 }}>Pivot Win.</span>
                                            <input
                                                type="number"
                                                value={value.pivot_window ?? ''}
                                                onChange={(e) => onChange({ ...value, pivot_window: e.target.value === '' ? undefined : Number(e.target.value) })}
                                                onBlur={() => {
                                                    const val = value.pivot_window;
                                                    if (val === undefined || isNaN(val)) {
                                                        onChange({ ...value, pivot_window: 5 });
                                                    } else {
                                                        onChange({ ...value, pivot_window: Math.max(2, Math.min(20, val)) });
                                                    }
                                                }}
                                                onFocus={(e) => e.target.select()}
                                                style={{
                                                    width: '100%',
                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    borderRadius: 5,
                                                    padding: '5px 8px',
                                                    fontSize: 'var(--ec-fs-select)',
                                                    fontWeight: 500,
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    outline: 'none',
                                                }}
                                                title="Pivot Window: candles to left and right required to confirm a Swing High/Low"
                                            />
                                        </div>
                                        <div style={{ flex: '1 1 60px', minWidth: '60px' }}>
                                            <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ec-text-muted)', display: 'block', marginBottom: 2 }}>Min Pivots</span>
                                            <input
                                                type="number"
                                                value={value.min_pivots ?? ''}
                                                onChange={(e) => onChange({ ...value, min_pivots: e.target.value === '' ? undefined : Number(e.target.value) })}
                                                onBlur={() => {
                                                    const val = value.min_pivots;
                                                    if (val === undefined || isNaN(val)) {
                                                        onChange({ ...value, min_pivots: 2 });
                                                    } else {
                                                        onChange({ ...value, min_pivots: Math.max(2, Math.min(50, val)) });
                                                    }
                                                }}
                                                onFocus={(e) => e.target.select()}
                                                style={{
                                                    width: '100%',
                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    borderRadius: 5,
                                                    padding: '5px 8px',
                                                    fontSize: 'var(--ec-fs-select)',
                                                    fontWeight: 500,
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    outline: 'none',
                                                }}
                                                title="Min Pivots: minimum swing highs and lows required to fit trend lines (min 2)"
                                            />
                                        </div>
                                        <div style={{ flex: '1 1 60px', minWidth: '60px' }}>
                                            <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ec-text-muted)', display: 'block', marginBottom: 2 }}>Lookback</span>
                                            <input
                                                type="number"
                                                value={value.tri_lookback ?? ''}
                                                onChange={(e) => onChange({ ...value, tri_lookback: e.target.value === '' ? undefined : Number(e.target.value) })}
                                                onBlur={() => {
                                                    const val = value.tri_lookback;
                                                    if (val === undefined || isNaN(val)) {
                                                        onChange({ ...value, tri_lookback: 35 });
                                                    } else {
                                                        onChange({ ...value, tri_lookback: Math.max(10, Math.min(200, val)) });
                                                    }
                                                }}
                                                onFocus={(e) => e.target.select()}
                                                style={{
                                                    width: '100%',
                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    borderRadius: 5,
                                                    padding: '5px 8px',
                                                    fontSize: 'var(--ec-fs-select)',
                                                    fontWeight: 500,
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    outline: 'none',
                                                }}
                                                title="Lookback: how many bars back to search for pivots"
                                            />
                                        </div>
                                    </div>
                                    <div style={{ display: 'flex', gap: 6, width: '100%', flexWrap: 'wrap', alignItems: 'flex-end' }}>
                                        <div style={{ flex: '1 1 90px', minWidth: '90px' }}>
                                            <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ec-text-muted)', display: 'block', marginBottom: 2 }}>Slope Tol. (%)</span>
                                            <input
                                                type="number"
                                                value={value.slope_tolerance ?? ''}
                                                onChange={(e) => onChange({ ...value, slope_tolerance: e.target.value === '' ? undefined : Number(e.target.value) })}
                                                onBlur={() => {
                                                    const val = value.slope_tolerance;
                                                    if (val === undefined || isNaN(val)) {
                                                        onChange({ ...value, slope_tolerance: 1.5 });
                                                    } else {
                                                        onChange({ ...value, slope_tolerance: Math.max(0.01, Math.min(10.0, val)) });
                                                    }
                                                }}
                                                onFocus={(e) => e.target.select()}
                                                style={{
                                                    width: '100%',
                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    borderRadius: 5,
                                                    padding: '5px 8px',
                                                    fontSize: 'var(--ec-fs-select)',
                                                    fontWeight: 500,
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    outline: 'none',
                                                }}
                                                title="Slope Tolerance (%): max total price change over the lookback window to consider a trend line 'flat'"
                                            />
                                        </div>
                                        <div style={{ flex: '1 2 110px', minWidth: '110px' }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 }}>
                                                <span style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--color-ec-text-muted)' }}>Min R²</span>
                                                <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--color-ec-text-primary)', fontFamily: 'var(--color-ec-sans)' }}>{(value.min_r_squared ?? 0.65).toFixed(2)}</span>
                                            </div>
                                            <input
                                                type="range"
                                                min={0}
                                                max={1}
                                                step={0.01}
                                                value={value.min_r_squared ?? 0.65}
                                                onChange={(e) => onChange({ ...value, min_r_squared: Number(e.target.value) })}
                                                style={{
                                                    width: '100%',
                                                    accentColor: 'var(--color-ec-copper)',
                                                    cursor: 'pointer',
                                                }}
                                                title="Minimum R-squared quality for trend lines (0 = no requirement, 1 = perfect fit)"
                                            />
                                        </div>
                                    </div>
                                </div>
                            );
                        }
                        return null;
                }
            })()}
            
            {/* Global Offset Param */}
            {!hideOffset && (
                <div className="flex items-center gap-1.5 ml-1 border-l border-border/30 pl-2">
                    <span style={{
                        fontSize: 9,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.1em',
                        color: 'var(--color-ec-copper)',
                        fontFamily: 'var(--color-ec-sans)',
                    }}>Bars Back (X):</span>
                    <input
                        type="number"
                        value={value.offset ?? ''}
                        onChange={(e) => onChange({ ...value, offset: e.target.value === '' ? undefined : Number(e.target.value) })}
                        onBlur={() => {
                            const val = value.offset;
                            if (val !== undefined && (isNaN(val) || val < 0)) {
                                onChange({ ...value, offset: 0 });
                            }
                        }}
                        onFocus={(e) => e.target.select()}
                        placeholder="0"
                        style={{
                            width: 52,
                            backgroundColor: 'color-mix(in srgb, var(--color-ec-copper) 10%, transparent)',
                            border: '0.5px solid color-mix(in srgb, var(--color-ec-copper) 30%, transparent)',
                            borderRadius: 4,
                            padding: '4px 8px',
                            fontSize: 11,
                            fontWeight: 700,
                            color: 'var(--color-ec-copper)',
                            fontFamily: 'var(--color-ec-sans)',
                            outline: 'none',
                        }}
                        title="Offset: 0 = current bar, 1 = previous bar, etc."
                    />
                </div>
            )}
        </div>
    );
};

// ----------------------------------------------------------------------
// Source Indicator Input (left side)
// ----------------------------------------------------------------------

export const SourceIndicatorInput = ({
    value,
    onChange,
    exclude = [],
    allowedTargets,
    hideOffset = false
}: {
    value: IndicatorConfig;
    onChange: (val: IndicatorConfig) => void;
    exclude?: IndicatorType[];
    allowedTargets?: IndicatorType[];
    hideOffset?: boolean;
}) => {
    return (
        <div className="flex flex-col gap-1.5 items-stretch bg-muted/5 border border-border/20 rounded p-1.5 w-full md:w-auto min-w-[200px]">
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <IndicatorSelector
                    value={value.name}
                    exclude={exclude}
                    allowedTargets={allowedTargets}
                    onChange={(nameStr) => {
                        const name = nameStr as IndicatorType;
                        const defaultParams = getDefaultParamsForIndicator(name);
                        onChange({ name, ...defaultParams });
                    }}
                />
            </div>
            <IndicatorParams value={value} onChange={onChange} hideOffset={hideOffset} />
        </div>
    );
};

// ----------------------------------------------------------------------
// Target Input (right side, after comparator)
// ----------------------------------------------------------------------

export const TargetInput = ({
    value,
    onChange,
    allowedTargets,
    hideOffset = false,
    sourceIndicatorName
}: {
    value: IndicatorConfig | number;
    onChange: (val: IndicatorConfig | number) => void;
    allowedTargets?: IndicatorType[];
    hideOffset?: boolean;
    sourceIndicatorName?: IndicatorType;
}) => {
    const isFixed = typeof value === 'number';
    const selectedKey = isFixed ? FIXED_VALUE_KEY : (value as IndicatorConfig).name;
    const isVol = isFixed && isVolumeIndicator(sourceIndicatorName);
    const isPercent = isFixed && isPercentIndicator(sourceIndicatorName);

    const [localText, setLocalText] = React.useState("");
    const [isFocused, setIsFocused] = React.useState(false);

    React.useEffect(() => {
        if (!isFixed && allowedTargets) {
            const currentName = (value as IndicatorConfig).name;
            if (allowedTargets.length === 0) {
                onChange(0);
            } else if (!allowedTargets.includes(currentName)) {
                if (allowedTargets.includes(IndicatorType.VWAP)) {
                    onChange({ name: IndicatorType.VWAP, offset: 0 });
                } else if (allowedTargets.length > 0) {
                    const name = allowedTargets[0];
                    const defaultParams = getDefaultParamsForIndicator(name);
                    onChange({ name, ...defaultParams });
                } else {
                    onChange(0);
                }
            }
        }
    }, [value, isFixed, allowedTargets, onChange]);

    React.useEffect(() => {
        if (isFixed && !isFocused) {
            if (isVol) {
                const clean = localText.trim().toLowerCase();
                const numericStr = clean.endsWith('m') ? clean.slice(0, -1) : clean;
                const parsedVal = parseFloat(numericStr) * 1000000;
                if (isNaN(parsedVal) || parsedVal !== value || localText === "") {
                    setLocalText(value === 0 && localText === "" ? "" : (value / 1000000).toString());
                }
            } else {
                const parsedVal = parseFloat(localText);
                if (isNaN(parsedVal) || parsedVal !== value || localText === "") {
                    setLocalText(value === 0 && localText === "" ? "" : value.toString());
                }
            }
        }
    }, [value, isFixed, isVol, isFocused]);

    const handleTextChange = (txt: string) => {
        setLocalText(txt);
        if (isVol) {
            const clean = txt.trim().toLowerCase();
            const numericStr = clean.endsWith('m') ? clean.slice(0, -1) : clean;
            const num = parseFloat(numericStr);
            if (!isNaN(num)) {
                onChange(num * 1000000);
            }
        } else {
            const num = parseFloat(txt);
            if (!isNaN(num)) {
                onChange(num);
            }
        }
    };

    const handleBlur = () => {
        setIsFocused(false);
        if (localText === "") {
            onChange(0);
        } else if (isVol) {
            const clean = localText.trim().toLowerCase();
            const numericStr = clean.endsWith('m') ? clean.slice(0, -1) : clean;
            const num = parseFloat(numericStr);
            if (isNaN(num)) {
                onChange(0);
            } else {
                onChange(num * 1000000);
            }
        } else {
            const num = parseFloat(localText);
            if (isNaN(num)) {
                onChange(0);
            } else {
                onChange(num);
            }
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <IndicatorSelector
                    isTarget
                    value={selectedKey}
                    allowedTargets={allowedTargets}
                    onChange={(key) => {
                        if (key === FIXED_VALUE_KEY) {
                            onChange(0);
                        } else {
                            const name = key as IndicatorType;
                            const defaultParams = getDefaultParamsForIndicator(name);
                            onChange({ name, ...defaultParams });
                        }
                    }}
                />
            </div>

            {!isFixed && (
                <IndicatorParams
                    value={value as IndicatorConfig}
                    onChange={(newVal) => onChange(newVal)}
                    hideOffset={hideOffset}
                />
            )}

            {isFixed && (
                isVol ? (
                    <div style={{ position: 'relative', width: '100%' }}>
                        <input
                            type="text"
                            value={localText}
                            onChange={(e) => handleTextChange(e.target.value)}
                            onFocus={(e) => { setIsFocused(true); e.target.select(); }}
                            onBlur={handleBlur}
                            placeholder="e.g. 1.5"
                            style={{
                                width: '100%',
                                backgroundColor: 'var(--color-ec-bg-sidebar)',
                                border: '0.5px solid var(--color-ec-border)',
                                borderRadius: 5,
                                padding: '5px 24px 5px 8px',
                                fontSize: 'var(--ec-fs-select)',
                                fontWeight: 500,
                                color: 'var(--color-ec-text-primary)',
                                fontFamily: 'var(--color-ec-sans)',
                                outline: 'none',
                            }}
                        />
                        <span style={{
                            position: 'absolute',
                            right: 8,
                            top: '50%',
                            transform: 'translateY(-50%)',
                            fontSize: 11,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                            opacity: 0.6,
                            pointerEvents: 'none',
                            fontFamily: 'var(--color-ec-sans)',
                        }}>
                            M
                        </span>
                    </div>
                ) : isPercent ? (
                    <div style={{ position: 'relative', width: '100%' }}>
                        <input
                            type="number"
                            step="any"
                            value={localText}
                            onChange={(e) => handleTextChange(e.target.value)}
                            onFocus={(e) => { setIsFocused(true); e.target.select(); }}
                            onBlur={handleBlur}
                            placeholder="e.g. 2.5"
                            style={{
                                width: '100%',
                                backgroundColor: 'var(--color-ec-bg-sidebar)',
                                border: '0.5px solid var(--color-ec-border)',
                                borderRadius: 5,
                                padding: '5px 24px 5px 8px',
                                fontSize: 'var(--ec-fs-select)',
                                fontWeight: 500,
                                color: 'var(--color-ec-text-primary)',
                                fontFamily: 'var(--color-ec-sans)',
                                outline: 'none',
                            }}
                        />
                        <span style={{
                            position: 'absolute',
                            right: 8,
                            top: '50%',
                            transform: 'translateY(-50%)',
                            fontSize: 11,
                            fontWeight: 700,
                            color: 'var(--color-ec-text-muted)',
                            opacity: 0.6,
                            pointerEvents: 'none',
                            fontFamily: 'var(--color-ec-sans)',
                        }}>
                            %
                        </span>
                    </div>
                ) : (
                    <input
                        type="number"
                        value={localText}
                        onChange={(e) => handleTextChange(e.target.value)}
                        onFocus={(e) => { setIsFocused(true); e.target.select(); }}
                        onBlur={handleBlur}
                        placeholder="Value"
                        style={{
                            width: '100%',
                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                            border: '0.5px solid var(--color-ec-border)',
                            borderRadius: 5,
                            padding: '5px 8px',
                            fontSize: 'var(--ec-fs-select)',
                            fontWeight: 500,
                            color: 'var(--color-ec-text-primary)',
                            fontFamily: 'var(--color-ec-sans)',
                            outline: 'none',
                        }}
                    />
                )
            )}
        </div>
    );
};

// ----------------------------------------------------------------------
// Condition Row Component
// ----------------------------------------------------------------------

export const ConditionRow = ({
    condition,
    onChange,
    onDelete,
    parentTimeframe = Timeframe.M1
}: {
    condition: AnyCondition;
    onChange: (c: AnyCondition) => void;
    onDelete: () => void;
    parentTimeframe?: Timeframe;
}) => {

    const currentTimeframe = condition.timeframe || parentTimeframe;

    const handleSourceChange = (newSource: IndicatorConfig) => {
        if (condition.type === 'indicator_comparison') {
            const allowed = getAllowedTargets(newSource.name as IndicatorType, 'indicator_comparison');
            const currentTargetKey = typeof condition.target === 'number' ? FIXED_VALUE_KEY : (condition.target as IndicatorConfig).name;
            const isTargetAllowed = currentTargetKey === FIXED_VALUE_KEY || allowed.includes(currentTargetKey as IndicatorType);
            
            if (isTriangle(newSource.name)) {
                onChange({
                    ...condition,
                    source: newSource,
                    comparator: Comparator.GT,
                    target: 0
                });
            } else if (newSource.name?.toLowerCase() === 'range of time') {
                onChange({
                    ...condition,
                    source: newSource,
                    comparator: Comparator.LT,
                    target: 30
                });
            } else if (isMeasureIndicator(newSource.name)) {
                const isValidComp = [Comparator.LT, Comparator.GT, Comparator.LTE, Comparator.GTE].includes(condition.comparator);
                onChange({
                    ...condition,
                    source: newSource,
                    comparator: isValidComp ? condition.comparator : Comparator.GT,
                    target: typeof condition.target === 'number' ? condition.target : 0
                });
            } else {
                const isCrossAllowed = ALLOWED_CROSSES_INDICATORS.includes(newSource.name as IndicatorType);
                let newComparator = condition.comparator;
                if (!isCrossAllowed && (newComparator === Comparator.CROSSES_ABOVE || newComparator === Comparator.CROSSES_BELOW)) {
                    newComparator = Comparator.GT;
                }
                onChange({
                    ...condition,
                    source: newSource,
                    comparator: newComparator,
                    target: isTargetAllowed ? condition.target : getInitialTargetForSource(newSource.name as IndicatorType)
                });
            }
        } else {
            onChange({ ...condition, source: newSource });
        }
    };

    const handleTargetChange = (newTarget: any) => {
        if (condition.type === 'indicator_comparison') {
            onChange({ ...condition, target: newTarget });
        }
    };

    const renderInputs = () => {
        switch (condition.type) {
            case 'indicator_comparison': {
                const isElapsed = condition.source.name === IndicatorType.ELAPSED_TIME_LAST_HIGH || condition.source.name === IndicatorType.ELAPSED_TIME;
                const isRangeOfTime = condition.source.name?.toLowerCase() === 'range of time';
                return (
                    <>
                        {/* SOURCE: indicator + params */}
                        <SourceIndicatorInput
                            value={condition.source}
                            onChange={handleSourceChange}
                            hideOffset={isElapsed || isRangeOfTime || isTriangle(condition.source.name)}
                            exclude={Object.values(IndicatorType).filter(isOnlyTarget)}
                        />

                        {isElapsed ? (
                            <div className="flex items-center gap-1">
                                <select
                                    value={condition.comparator}
                                    onChange={(e) => onChange({ ...condition, comparator: e.target.value as Comparator })}
                                    className="bg-muted/20 border border-border/50 rounded px-1.5 py-0.5 text-xs font-mono text-[var(--color-ec-copper)] outline-none"
                                >
                                    <option value={Comparator.EQ}>=</option>
                                    <option value={Comparator.GT}>&gt;</option>
                                    <option value={Comparator.LT}>&lt;</option>
                                    <option value={Comparator.GTE}>&ge;</option>
                                    <option value={Comparator.LTE}>&le;</option>
                                </select>
                                <input
                                    type="number"
                                    value={typeof condition.target === 'number' ? condition.target : ''}
                                    onChange={(e) => handleTargetChange(e.target.value === '' ? '' : Number(e.target.value))}
                                    onBlur={() => {
                                        const val = Number(condition.target);
                                        handleTargetChange(isNaN(val) || val < 1 ? 20 : Math.max(1, val));
                                    }}
                                    onFocus={(e) => e.target.select()}
                                    className="w-16 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs text-[var(--color-ec-copper)] font-mono outline-none"
                                />
                                <span className="text-xs text-muted-foreground font-semibold">mins</span>
                            </div>
                        ) : isRangeOfTime ? (
                            <div className="flex items-center gap-1.5">
                                {/* COMPARATOR: only <, >, <=, >= */}
                                <select
                                    value={condition.comparator}
                                    onChange={(e) => onChange({ ...condition, comparator: e.target.value as Comparator })}
                                    className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs font-mono text-[var(--color-ec-copper)]"
                                >
                                    <option value={Comparator.LT}>&lt;</option>
                                    <option value={Comparator.GT}>&gt;</option>
                                    <option value={Comparator.LTE}>&le;</option>
                                    <option value={Comparator.GTE}>&ge;</option>
                                </select>

                                {/* TARGET VALUE (Minutes) */}
                                <input
                                    type="number"
                                    value={typeof condition.target === 'number' ? condition.target : ''}
                                    onChange={(e) => handleTargetChange(e.target.value === '' ? '' : Number(e.target.value))}
                                    onBlur={() => {
                                        const val = Number(condition.target);
                                        handleTargetChange(isNaN(val) || val < 0 ? 30 : Math.max(0, val));
                                    }}
                                    onFocus={(e) => e.target.select()}
                                    placeholder="Minutos"
                                    className="w-20 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs text-[var(--color-ec-copper)] font-mono outline-none"
                                />
                                <span className="text-xs text-muted-foreground font-semibold">mins</span>
                            </div>
                        ) : isTriangle(condition.source.name) ? null : (
                            <>
                                {/* COMPARATOR: symbols */}
                                <select
                                    value={condition.comparator}
                                    onChange={(e) => onChange({ ...condition, comparator: e.target.value as Comparator })}
                                    className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs font-mono text-[var(--color-ec-copper)]"
                                >
                                    {Object.values(Comparator)
                                        .filter(c => {
                                            if (c.includes('DISTANCE')) return false;
                                            if (isMeasureIndicator(condition.source.name)) {
                                                return c === Comparator.LT || c === Comparator.GT || c === Comparator.LTE || c === Comparator.GTE;
                                            }
                                            if (c === Comparator.CROSSES_ABOVE || c === Comparator.CROSSES_BELOW) {
                                                return ALLOWED_CROSSES_INDICATORS.includes(condition.source.name as IndicatorType);
                                            }
                                            return true;
                                        })
                                        .map(c => (
                                            <option key={c} value={c}>{COMPARATOR_LABELS[c] || c}</option>
                                        ))
                                    }
                                </select>

                                {/* TARGET: indicator OR fixed value */}
                                <TargetInput
                                    value={condition.target}
                                    onChange={handleTargetChange}
                                    allowedTargets={getAllowedTargets(condition.source.name as IndicatorType, 'indicator_comparison')}
                                    sourceIndicatorName={condition.source.name}
                                />
                            </>
                        )}
                    </>
                );
            }
            case 'price_level_distance':
                return (
                    <>
                        <SourceIndicatorInput
                            value={condition.source}
                            exclude={[
                                ...Object.values(IndicatorType).filter(isOnlyTarget),
                                IndicatorType.TRIANGLE_ASCENDING,
                                IndicatorType.TRIANGLE_DESCENDING,
                                IndicatorType.TRIANGLE_SYMMETRIC
                            ]}
                            onChange={(val) => onChange({ ...condition, source: val })}
                        />
                        <div className="text-xs text-muted-foreground">is</div>
                        <select
                            value={condition.comparator}
                            onChange={(e) => onChange({ ...condition, comparator: e.target.value as 'DISTANCE_GT' | 'DISTANCE_LT' })}
                            className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs font-mono text-[var(--color-ec-copper)]"
                        >
                            <option value="DISTANCE_GT">&gt; than</option>
                            <option value="DISTANCE_LT">&lt; than</option>
                        </select>
                        <div className="flex items-center gap-1">
                            <input
                                type="number"
                                value={condition.value_pct}
                                onChange={(e) => onChange({ ...condition, value_pct: Number(e.target.value) })}
                                className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs text-[var(--color-ec-copper)] font-mono"
                            />
                            <span className="text-[10px] text-muted-foreground">%</span>
                        </div>
                        <div className="text-xs text-muted-foreground">from</div>
                        <SourceIndicatorInput
                            value={condition.level}
                            exclude={[
                                IndicatorType.TRIANGLE_ASCENDING,
                                IndicatorType.TRIANGLE_DESCENDING,
                                IndicatorType.TRIANGLE_SYMMETRIC
                            ]}
                            allowedTargets={getAllowedTargets(
                                condition.source?.name as IndicatorType,
                                'price_level_distance'
                            )}
                            onChange={(val) => onChange({ ...condition, level: val })}
                        />
                        <div className="flex items-center gap-1.5 ml-2 border-l border-border/30 pl-2">
                            <span className="text-[10px] text-muted-foreground uppercase font-bold">Pos:</span>
                            <select
                                value={condition.position || 'any'}
                                onChange={(e) => onChange({ ...condition, position: e.target.value as 'above' | 'below' | 'any' })}
                                className="bg-muted/20 border border-border/50 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-ec-copper)] font-bold"
                            >
                                <option value="any">Any</option>
                                <option value="above">Above Level</option>
                                <option value="below">Below Level</option>
                            </select>
                        </div>
                    </>
                );
            default:
                return null;
        }
    };

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 12px',
            backgroundColor: 'var(--color-ec-bg-elevated)',
            border: '0.5px solid var(--color-ec-border)',
            borderRadius: 5,
            transition: 'border-color 150ms ease',
        }} className="group"
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-ec-copper)')}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-ec-border)')}
        >
            {/* Timeframe Selector */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                padding: '3px 8px',
                backgroundColor: 'var(--color-ec-bg-sidebar)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 4,
            }}>
                <Clock className="w-3 h-3 text-[var(--color-ec-copper)]" />
                <select
                    value={currentTimeframe}
                    onChange={(e) => onChange({ ...condition, timeframe: e.target.value as Timeframe })}
                    style={{
                        background: 'transparent',
                        border: 'none',
                        outline: 'none',
                        fontSize: 11,
                        fontWeight: 700,
                        color: 'var(--color-ec-copper)',
                        fontFamily: 'var(--color-ec-sans)',
                        cursor: 'pointer',
                    }}
                >
                    {Object.values(Timeframe).filter(tf => tf !== Timeframe.D1).map(tf => (
                        <option key={tf} value={tf}>{tf}</option>
                    ))}
                </select>
            </div>

            <div style={{
                width: 1,
                height: 16,
                backgroundColor: 'var(--color-ec-border)',
                flexShrink: 0,
            }}></div>

            <select
                value={condition.type}
                onChange={(e) => {
                    const type = e.target.value;
                    if (type === 'indicator_comparison') {
                        onChange({
                            type: 'indicator_comparison',
                            source: { name: IndicatorType.SMA, period: 20 },
                            comparator: Comparator.GT,
                            target: { name: IndicatorType.VWAP },
                            timeframe: currentTimeframe
                        });
                    } else if (type === 'price_level_distance') {
                        onChange({
                            type: 'price_level_distance',
                            source: { name: IndicatorType.BAR_CLOSE, offset: 0 },
                            level: { name: IndicatorType.PM_HIGH, offset: 0 },
                            comparator: 'DISTANCE_LT',
                            value_pct: 2.0,
                            timeframe: currentTimeframe
                        });
                    }
                }}
                style={{
                    background: 'transparent',
                    border: 'none',
                    outline: 'none',
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    letterSpacing: '0.08em',
                    color: 'var(--color-ec-text-secondary)',
                    fontFamily: 'var(--color-ec-sans)',
                    cursor: 'pointer',
                }}
            >
                <option value="indicator_comparison">Indicator</option>
                <option value="price_level_distance">Distance</option>
            </select>

            <div style={{
                width: 1,
                height: 16,
                backgroundColor: 'var(--color-ec-border)',
                flexShrink: 0,
            }}></div>

            <div className="flex items-center gap-2 flex-1 flex-wrap">
                {renderInputs()}
            </div>

            <button onClick={onDelete} className="text-muted-foreground hover:text-ec-loss opacity-0 group-hover:opacity-100 transition-opacity">
                <Trash2 className="w-3.5 h-3.5" />
            </button>
        </div>
    );
};

// ----------------------------------------------------------------------
// Recursive Group Component
// ----------------------------------------------------------------------
export const formatConditionText = (c: AnyCondition): { source: string; target: string } => {
    const tfStr = c.timeframe ? `[${c.timeframe}] ` : '';
    if (c.type === 'indicator_comparison') {
        if (c.source.name === IndicatorType.ELAPSED_TIME_LAST_HIGH) {
            const mins = typeof c.target === 'number' ? c.target : 20;
            const opSymbol = c.comparator === Comparator.EQ ? '=' : c.comparator === Comparator.GT ? '>' : c.comparator === Comparator.LT ? '<' : c.comparator === Comparator.LTE ? '≤' : '≥';
            const refLabel = c.source.session_ref === 'pm' ? ' (PMH del día)' : c.source.session_ref === 'rth' ? ' (Máx RTH)' : '';
            return { source: `${tfStr}Elapsed Time Last High${refLabel}:`, target: `${opSymbol} ${mins} mins` };
        }
        if (c.source.name === IndicatorType.ELAPSED_TIME) {
            const mins = typeof c.target === 'number' ? c.target : 60;
            const opSymbol = c.comparator === Comparator.EQ ? '=' : c.comparator === Comparator.GT ? '>' : c.comparator === Comparator.LT ? '<' : c.comparator === Comparator.LTE ? '≤' : '≥';
            return { source: `${tfStr}Elapsed Time:`, target: `${opSymbol} ${mins} mins` };
        }
        // Squeeze lleva la ventana y la direccion EN el resumen a proposito:
        // dos condiciones de Squeeze con distinta direccion son estrategias
        // opuestas, y sin esto se leerian identicas.
        // Los fades llevan su modo EN el resumen por el mismo motivo que el
        // Squeeze: «% Session Fade» de premercado y del dia completo son cosas
        // distintas, y sin esto las dos condiciones se leerian identicas.
        const sourceStr = c.source.name === IndicatorType.SQUEEZE
            ? `Squeeze ${c.source.squeeze_direction === 'down' ? '↓' : '↑'} ${c.source.range_minutes ?? 5} min`
            : c.source.name === IndicatorType.SESSION_FADE
            ? `% Session Fade (${c.source.session_ref === 'rth' ? 'RTH' : c.source.session_ref === 'full' ? 'día completo' : 'PM'})`
            : c.source.name === IndicatorType.FADE
            ? `% Fade (${c.source.fade_ref === 'vwap_cross' ? 'cruce VWAP' : `máx. previo ${c.source.ap_session || 'ap.RTH'}`})`
            : `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const compStr = COMPARATOR_LABELS[c.comparator] || c.comparator;
        let targetStr = '';
        if (typeof c.target === 'number') {
            if (isVolumeIndicator(c.source.name)) {
                targetStr = `${(c.target / 1000000).toString()}M`;
            } else if (isPercentIndicator(c.source.name)) {
                targetStr = `${c.target}%`;
            } else {
                targetStr = String(c.target);
            }
        } else {
            targetStr = `${INDICATOR_LABELS[c.target.name] || c.target.name}${c.target.offset ? `[t-${c.target.offset}]` : ''}`;
        }
        return { source: `${tfStr}${sourceStr}:`, target: `${compStr} ${targetStr}` };
    } else if (c.type === 'price_level_distance') {
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const levelStr = `${INDICATOR_LABELS[c.level.name] || c.level.name}${c.level.offset ? `[t-${c.level.offset}]` : ''}`;
        const compStr = c.comparator === 'DISTANCE_GT' ? '>' : '<';
        const pctStr = `${c.value_pct}%`;
        const posStr = c.position && c.position !== 'any' ? ` (${c.position})` : '';
        return { source: `${tfStr}Dist(${sourceStr}, ${levelStr}):`, target: `${compStr} ${pctStr}${posStr}` };
    }
    return { source: '', target: '' };
};

export const GroupDisplay = ({
    group,
    onChange,
    onDelete,
    level = 0,
    accentColor = 'blue',
    parentTimeframe = Timeframe.M1
}: {
    group: ConditionGroup;
    onChange: (g: ConditionGroup) => void;
    onDelete?: () => void;
    level?: number;
    accentColor?: 'blue' | 'rose' | 'amber';
    parentTimeframe?: Timeframe;
}) => {
    const [showForm, setShowForm] = React.useState(false);
    const [editingIndex, setEditingIndex] = React.useState<number | null>(null);
    const [formCondition, setFormCondition] = React.useState<any>({
        type: 'indicator_comparison',
        source: { name: IndicatorType.BAR_CLOSE, offset: 0 },
        comparator: Comparator.GT,
        target: { name: IndicatorType.VWAP, offset: 0 },
    });
    
    const compCondition = formCondition.type === 'indicator_comparison' ? formCondition : null;
    const distCondition = formCondition.type === 'price_level_distance' ? formCondition : null;
    const activeAccentColor = accentColor === 'blue' ? 'var(--color-ec-profit)' : accentColor === 'rose' ? 'var(--color-ec-loss)' : 'var(--color-ec-copper)';

    const handleToggleType = (newType: 'indicator_comparison' | 'price_level_distance') => {
        if (newType === 'indicator_comparison') {
            const allowed = getAllowedTargets(formCondition.source.name as IndicatorType, 'indicator_comparison');
            const defaultTarget = allowed.includes(IndicatorType.VWAP)
                ? { name: IndicatorType.VWAP, offset: 0 }
                : allowed.length > 0
                    ? { name: allowed[0], offset: 0 }
                    : 0;

            setFormCondition({
                type: 'indicator_comparison',
                source: formCondition.source,
                comparator: Comparator.GT,
                target: defaultTarget,
                timeframe: formCondition.timeframe
            });
        } else {
            const allowed = getAllowedTargets(formCondition.source.name as IndicatorType, 'price_level_distance');
            const defaultLevel = allowed.includes(IndicatorType.PM_HIGH)
                ? { name: IndicatorType.PM_HIGH, offset: 0 }
                : allowed.length > 0
                    ? { name: allowed[0], offset: 0 }
                    : { name: IndicatorType.PM_HIGH, offset: 0 };

            setFormCondition({
                type: 'price_level_distance',
                source: formCondition.source,
                level: defaultLevel,
                comparator: 'DISTANCE_LT',
                value_pct: 2.0,
                timeframe: formCondition.timeframe
            });
        }
    };

    const handleSaveCondition = () => {
        const savedCondition = {
            ...formCondition
        };
        // Clean up offset on comparison target if not allowed
        if (savedCondition.type === 'indicator_comparison') {
            if (typeof savedCondition.target !== 'number') {
                if (!isOffsetAllowed(savedCondition.target.name)) {
                    savedCondition.target = {
                        ...savedCondition.target,
                        offset: 0
                    };
                }
            }
        } else if (savedCondition.type === 'price_level_distance') {
            if (!isOffsetAllowed(savedCondition.level.name)) {
                savedCondition.level = {
                    ...savedCondition.level,
                    offset: 0
                };
            }
        }

        if (editingIndex !== null) {
            const newConditions = [...group.conditions];
            newConditions[editingIndex] = savedCondition;
            onChange({ ...group, conditions: newConditions });
            setEditingIndex(null);
        } else {
            onChange({
                ...group,
                conditions: [...group.conditions, savedCondition]
            });
        }
        setShowForm(false);
    };

    const handleRemoveCondition = (indexInAll: number) => {
        const newConditions = group.conditions.filter((_, i) => i !== indexInAll);
        onChange({ ...group, conditions: newConditions });
        if (editingIndex === indexInAll) {
            setEditingIndex(null);
            setShowForm(false);
        }
    };

    const addGroup = () => {
        const newGroup: ConditionGroup = {
            type: 'group',
            operator: 'AND',
            conditions: []
        };
        onChange({
            ...group,
            conditions: [...group.conditions, newGroup]
        });
    };

    const updateCondition = (index: number, newCond: AnyCondition | ConditionGroup) => {
        const newConditions = [...group.conditions];
        newConditions[index] = newCond;
        onChange({ ...group, conditions: newConditions });
    };

    const removeCondition = (index: number) => {
        const newConditions = group.conditions.filter((_, i) => i !== index);
        onChange({ ...group, conditions: newConditions });
    };

    const labelStyle: React.CSSProperties = {
        fontFamily: 'var(--color-ec-sans)',
        fontSize: '9px',
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        color: 'var(--color-ec-text-muted)',
        marginBottom: '2px',
    };

    const inputStyle: React.CSSProperties = {
        backgroundColor: 'var(--color-ec-bg-sidebar)',
        border: '0.5px solid var(--color-ec-border)',
        borderRadius: '4px',
        padding: '5px 8px',
        fontSize: '11px',
        fontWeight: 500,
        color: 'var(--color-ec-text-primary)',
        fontFamily: 'var(--color-ec-sans)',
        outline: 'none',
        width: '100%',
    };

    const selectStyle: React.CSSProperties = {
        backgroundColor: 'var(--color-ec-bg-sidebar)',
        border: '0.5px solid var(--color-ec-border)',
        borderRadius: '4px',
        padding: '5px 8px',
        fontSize: '11px',
        fontWeight: 500,
        color: 'var(--color-ec-text-primary)',
        fontFamily: 'var(--color-ec-sans)',
        outline: 'none',
        width: '100%',
        cursor: 'pointer',
    };

    const subGroups = group.conditions.filter(c => c.type === 'group') as ConditionGroup[];

    return (
        <div 
            style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
                position: 'relative',
                marginLeft: level > 0 ? 16 : 0,
                paddingLeft: level > 0 ? 16 : 0,
                paddingRight: level > 0 ? 12 : 0,
                paddingTop: level > 0 ? 12 : 0,
                paddingBottom: level > 0 ? 12 : 0,
                borderLeft: level > 0 ? `2.5px solid ${activeAccentColor}` : 'none',
                backgroundColor: level > 0 ? 'color-mix(in srgb, var(--color-ec-bg-surface) 40%, transparent)' : 'transparent',
                borderRadius: level > 0 ? '0 6px 6px 0' : 0,
                borderTop: level > 0 ? '0.5px solid var(--color-ec-border)' : 'none',
                borderBottom: level > 0 ? '0.5px solid var(--color-ec-border)' : 'none',
                borderRight: level > 0 ? '0.5px solid var(--color-ec-border)' : 'none',
            }}
        >
            {/* Group Header */}
            <div className="flex items-center gap-3">
                <div
                    style={group.operator === 'AND' ? {
                        backgroundColor: `color-mix(in srgb, ${activeAccentColor} 15%, transparent)`,
                        color: activeAccentColor,
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.1em',
                        padding: '3px 10px',
                        borderRadius: 4,
                        cursor: 'pointer',
                        border: 'none',
                    } : {
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.1em',
                        padding: '3px 10px',
                        borderRadius: 4,
                        cursor: 'pointer',
                        border: 'none',
                        color: 'var(--color-ec-text-secondary)',
                        fontFamily: 'var(--color-ec-sans)',
                        backgroundColor: 'transparent',
                    }}
                    onClick={() => onChange({ ...group, operator: group.operator === 'AND' ? 'OR' : 'AND' })}
                >
                    {group.operator}
                </div>

                {level > 0 && (
                    <span style={{
                        fontSize: 9,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        color: activeAccentColor,
                        letterSpacing: '0.08em',
                        fontFamily: 'var(--color-ec-sans)',
                        backgroundColor: `color-mix(in srgb, ${activeAccentColor} 10%, transparent)`,
                        padding: '2px 6px',
                        borderRadius: 3,
                    }}>
                        Grupo Lógico
                    </span>
                )}

                {onDelete && (
                    <button onClick={onDelete} className="ml-auto text-muted-foreground/30 hover:text-ec-loss transition-colors">
                        <Trash2 className="w-3.5 h-3.5" />
                    </button>
                )}
            </div>

            {/* Config & Tags Row */}
            <div style={{
                display: 'flex',
                flexDirection: 'row',
                gap: 16,
                alignItems: 'flex-start',
                width: '100%',
            }}>
                {/* Left side: Buttons or Vertical Form */}
                <div style={{
                    width: 250,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                    flexShrink: 0,
                }}>
                    {showForm ? (
                        <div style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 10,
                            padding: 12,
                            border: `0.5px solid ${activeAccentColor}`,
                            backgroundColor: 'var(--color-ec-bg-surface)',
                            borderRadius: 6,
                        }}>
                            {/* Form Header */}
                            <div style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                borderBottom: '0.5px solid var(--color-ec-border)',
                                paddingBottom: 6,
                                marginBottom: 4
                            }}>
                                <span style={{
                                    fontSize: 10,
                                    fontWeight: 700,
                                    textTransform: 'uppercase',
                                    color: activeAccentColor,
                                    letterSpacing: '0.08em',
                                    fontFamily: 'var(--color-ec-sans)',
                                }}>
                                    {editingIndex !== null ? 'Editar Condición' : 'Nueva Condición'}
                                </span>
                            </div>

                            {/* Timeframe selector (Tiempo) */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                <span style={labelStyle}>Tiempo</span>
                                <select
                                    value={formCondition.timeframe || parentTimeframe}
                                    onChange={(e) => setFormCondition({ ...formCondition, timeframe: e.target.value as Timeframe })}
                                    style={selectStyle}
                                >
                                    {Object.values(Timeframe).filter(tf => tf !== Timeframe.D1).map(tf => (
                                        <option key={tf} value={tf}>{tf}</option>
                                    ))}
                                </select>
                            </div>

                            {/* Variable de entrada */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                <span style={labelStyle}>Variable de entrada</span>
                                <IndicatorSelector
                                    value={formCondition.source.name}
                                    exclude={[
                                        ...Object.values(IndicatorType).filter(isOnlyTarget),
                                        ...(accentColor !== 'rose' ? [IndicatorType.ELAPSED_TIME] : [])
                                    ]}
                                    onChange={(nameStr) => {
                                        const name = nameStr as IndicatorType;
                                        const defaultParams = getDefaultParamsForIndicator(name);
                                        const timeframe = formCondition.timeframe;

                                        if (name === IndicatorType.ELAPSED_TIME_LAST_HIGH) {
                                            setFormCondition({
                                                type: 'indicator_comparison',
                                                source: { name, offset: 0, session_ref: 'full' },
                                                comparator: Comparator.GTE,
                                                target: 20,
                                                timeframe
                                            });
                                            return;
                                        }
                                        if (name === IndicatorType.ELAPSED_TIME) {
                                            setFormCondition({
                                                type: 'indicator_comparison',
                                                source: { name, offset: 0 },
                                                comparator: Comparator.GTE,
                                                target: 60,
                                                timeframe
                                            });
                                            return;
                                        }
                                        if (name?.toLowerCase() === 'range of time') {
                                            setFormCondition({
                                                type: 'indicator_comparison',
                                                source: { name, offset: 0 },
                                                comparator: Comparator.LT,
                                                target: 30,
                                                timeframe
                                            });
                                            return;
                                        }

                                        // Check if distance is supported
                                        const hasDistance = getAllowedTargets(name, 'price_level_distance').length > 0;
                                        
                                        // If we are in distance mode but the new indicator doesn't support it, switch to comparison mode
                                        if (formCondition.type === 'price_level_distance' && !hasDistance) {
                                            const allowed = getAllowedTargets(name, 'indicator_comparison');
                                            const defaultTarget = allowed.includes(IndicatorType.VWAP)
                                                ? { name: IndicatorType.VWAP, offset: 0 }
                                                : allowed.length > 0
                                                    ? { name: allowed[0], offset: 0 }
                                                    : 0;
                                            
                                            setFormCondition({
                                                type: 'indicator_comparison',
                                                source: { name, offset: 0, ...defaultParams },
                                                comparator: Comparator.GT,
                                                target: defaultTarget,
                                                timeframe
                                            });
                                        } else if (formCondition.type === 'indicator_comparison') {
                                            const allowed = getAllowedTargets(name, 'indicator_comparison');
                                            const currentTargetKey = typeof formCondition.target === 'number' ? FIXED_VALUE_KEY : (formCondition.target as IndicatorConfig).name;
                                            const isTargetAllowed = currentTargetKey === FIXED_VALUE_KEY || allowed.includes(currentTargetKey as IndicatorType);
                                            
                                            const isCrossAllowed = ALLOWED_CROSSES_INDICATORS.includes(name);
                                            let newComparator = formCondition.comparator;
                                            if (!isCrossAllowed && (newComparator === Comparator.CROSSES_ABOVE || newComparator === Comparator.CROSSES_BELOW)) {
                                                newComparator = Comparator.GT;
                                            }

                                            setFormCondition({
                                                type: 'indicator_comparison',
                                                source: { name, offset: 0, ...defaultParams },
                                                comparator: newComparator as Comparator,
                                                target: isTargetAllowed ? formCondition.target : getInitialTargetForSource(name),
                                                timeframe
                                            });
                                        } else {
                                            // We are in price_level_distance and the new indicator does support distance
                                            const allowed = getAllowedTargets(name, 'price_level_distance');
                                            const currentLevelKey = (formCondition.level as IndicatorConfig).name;
                                            const isLevelAllowed = allowed.includes(currentLevelKey);
                                            const defaultLevel = allowed.includes(IndicatorType.PM_HIGH)
                                                ? { name: IndicatorType.PM_HIGH, offset: 0 }
                                                : allowed.length > 0
                                                    ? { name: allowed[0], offset: 0 }
                                                    : { name: IndicatorType.PM_HIGH, offset: 0 };

                                            setFormCondition({
                                                type: 'price_level_distance',
                                                source: { name, offset: 0, ...defaultParams },
                                                level: isLevelAllowed ? formCondition.level : defaultLevel,
                                                comparator: formCondition.comparator as 'DISTANCE_GT' | 'DISTANCE_LT',
                                                value_pct: formCondition.value_pct,
                                                timeframe
                                            });
                                        }
                                    }}
                                />
                                <IndicatorParams
                                    value={formCondition.source}
                                    onChange={(newSource) => setFormCondition({ ...formCondition, source: newSource })}
                                    hideOffset={true}
                                />

                                {/* Checkbox for Offset to Variable de entrada */}
                                {formCondition.source.name !== IndicatorType.ELAPSED_TIME_LAST_HIGH && formCondition.source.name !== IndicatorType.ELAPSED_TIME && !isTriangle(formCondition.source.name) && (() => {
                                    const allowed = isOffsetAllowed(formCondition.source.name);
                                    return (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, opacity: allowed ? 1 : 0.35 }}>
                                                <input
                                                    type="checkbox"
                                                    id="source-offset-checkbox"
                                                    disabled={!allowed}
                                                    checked={allowed && !!formCondition.source.offset}
                                                    onChange={(e) => {
                                                        const checked = e.target.checked;
                                                        setFormCondition({
                                                            ...formCondition,
                                                            source: {
                                                                ...formCondition.source,
                                                                offset: checked ? (formCondition.source.offset || 1) : 0
                                                            }
                                                        });
                                                    }}
                                                    style={{
                                                        width: 14,
                                                        height: 14,
                                                        accentColor: 'var(--color-ec-copper)',
                                                        cursor: allowed ? 'pointer' : 'not-allowed'
                                                    }}
                                                />
                                                <label
                                                    htmlFor={allowed ? "source-offset-checkbox" : undefined}
                                                    style={{
                                                        fontSize: 11,
                                                        fontWeight: 600,
                                                        color: 'var(--color-ec-text-primary)',
                                                        cursor: allowed ? 'pointer' : 'not-allowed',
                                                        userSelect: 'none'
                                                    }}
                                                >
                                                    ¿Offset a Variable de entrada?
                                                </label>
                                                <TooltipIcon
                                                    customText="El offset simplemente indica la cantidad de velas hacia atrás en las que debe fijarse esta variable. Por ejemplo, en temporalidad de 1 minuto, si queremos una condición fija en la que el precio Close haya estado por encima del Premarket High hace 5 minutos, deberemos poner un offset de 5, para que el backtester entienda que la condición se activa si hace 5 minutos el close estaba por encima del PMH. Esta opción permite <u>crear patrones de acción del precio</u>."
                                                />
                                            </div>

                                            {/* Mostrar select de velas de retraso si el checkbox está activo */}
                                            {allowed && !!formCondition.source.offset && (
                                                <div style={{ 
                                                    display: 'flex', 
                                                    alignItems: 'center', 
                                                    gap: 8, 
                                                    paddingLeft: 20,
                                                    marginTop: 2
                                                }}>
                                                    <span style={{
                                                        fontSize: 11,
                                                        fontWeight: 600,
                                                        color: 'var(--color-ec-text-secondary)',
                                                        fontFamily: 'var(--color-ec-sans)',
                                                    }}>Velas atrás:</span>
                                                    <select
                                                        value={formCondition.source.offset || 1}
                                                        onChange={(e) => {
                                                            const val = Number(e.target.value);
                                                            setFormCondition({
                                                                ...formCondition,
                                                                source: { ...formCondition.source, offset: val }
                                                            });
                                                        }}
                                                        style={{
                                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                            border: '0.5px solid var(--color-ec-border)',
                                                            borderRadius: 4,
                                                            padding: '2px 8px 2px 6px',
                                                            fontSize: 11,
                                                            fontWeight: 700,
                                                            color: 'var(--color-ec-copper)',
                                                            fontFamily: 'var(--color-ec-sans)',
                                                            outline: 'none',
                                                            cursor: 'pointer',
                                                            width: 55,
                                                            textAlign: 'center'
                                                        }}
                                                    >
                                                        {Array.from({ length: 20 }, (_, i) => i + 1).map((val) => (
                                                            <option key={val} value={val} style={{ backgroundColor: 'var(--color-ec-bg-surface)', color: 'var(--color-ec-text-primary)' }}>
                                                                {val}
                                                            </option>
                                                        ))}
                                                    </select>
                                                </div>
                                            )}
                                        </div>
                                    );
                                })()}
                            </div>

                            {/* Mode toggle (Comparación vs Distancia %) if supported */}
                            {(() => {
                                const hasDistance = getAllowedTargets(formCondition.source.name as IndicatorType, 'price_level_distance').length > 0;
                                if (!hasDistance) return null;
                                return (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                        <span style={labelStyle}>Modo de Condición</span>
                                        <div style={{
                                            display: 'flex',
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 6,
                                            padding: 2,
                                            position: 'relative'
                                        }}>
                                            <button
                                                type="button"
                                                onClick={() => handleToggleType('indicator_comparison')}
                                                style={{
                                                    flex: 1,
                                                    padding: '6px 10px',
                                                    fontSize: 11,
                                                    fontWeight: 700,
                                                    borderRadius: 4,
                                                    border: 'none',
                                                    backgroundColor: formCondition.type === 'indicator_comparison' ? 'var(--color-ec-copper)' : 'transparent',
                                                    color: formCondition.type === 'indicator_comparison' ? '#ffffff' : 'var(--color-ec-text-muted)',
                                                    cursor: 'pointer',
                                                    transition: 'all 150ms ease',
                                                    textAlign: 'center'
                                                }}
                                            >
                                                Comparación
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => handleToggleType('price_level_distance')}
                                                style={{
                                                    flex: 1,
                                                    padding: '6px 10px',
                                                    fontSize: 11,
                                                    fontWeight: 700,
                                                    borderRadius: 4,
                                                    border: 'none',
                                                    backgroundColor: formCondition.type === 'price_level_distance' ? 'var(--color-ec-copper)' : 'transparent',
                                                    color: formCondition.type === 'price_level_distance' ? '#ffffff' : 'var(--color-ec-text-muted)',
                                                    cursor: 'pointer',
                                                    transition: 'all 150ms ease',
                                                    textAlign: 'center'
                                                }}
                                            >
                                                Distancia %
                                            </button>
                                        </div>
                                    </div>
                                );
                            })()}



                            {/* relación */}
                            {!isTriangle(formCondition.source.name) && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <span style={labelStyle}>Relación</span>
                                    {formCondition.source.name?.toLowerCase() === 'range of time' ? (
                                        <select
                                            value={compCondition ? compCondition.comparator : Comparator.LT}
                                            onChange={(e) => {
                                                if (compCondition) {
                                                    setFormCondition({
                                                        ...compCondition,
                                                        comparator: e.target.value as Comparator
                                                    });
                                                }
                                            }}
                                            style={selectStyle}
                                        >
                                            <option value={Comparator.LT}>&lt;</option>
                                            <option value={Comparator.GT}>&gt;</option>
                                            <option value={Comparator.LTE}>&le;</option>
                                            <option value={Comparator.GTE}>&ge;</option>
                                        </select>
                                    ) : formCondition.type === 'indicator_comparison' ? (
                                        <select
                                            value={compCondition ? compCondition.comparator : Comparator.GT}
                                            onChange={(e) => {
                                                if (compCondition) {
                                                    setFormCondition({
                                                        ...compCondition,
                                                        comparator: e.target.value as Comparator
                                                    });
                                                }
                                            }}
                                            style={selectStyle}
                                        >
                                            {Object.values(Comparator)
                                                .filter(c => {
                                                    if (c.includes('DISTANCE')) return false;
                                                    if (c === Comparator.CROSSES_ABOVE || c === Comparator.CROSSES_BELOW) {
                                                        const sourceName = compCondition ? compCondition.source.name : formCondition.source.name;
                                                        return ALLOWED_CROSSES_INDICATORS.includes(sourceName as IndicatorType);
                                                    }
                                                    return true;
                                                })
                                                .map(c => (
                                                    <option key={c} value={c}>{COMPARATOR_LABELS[c] || c}</option>
                                                ))
                                            }
                                        </select>
                                    ) : (
                                        <select
                                            value={formCondition.type === 'price_level_distance' ? formCondition.comparator : 'DISTANCE_GT'}
                                            onChange={(e) => {
                                                if (formCondition.type === 'price_level_distance') {
                                                    setFormCondition({
                                                        ...formCondition,
                                                        comparator: e.target.value as 'DISTANCE_GT' | 'DISTANCE_LT'
                                                    });
                                                }
                                            }}
                                            style={selectStyle}
                                        >
                                            <option value="DISTANCE_GT">&gt; que</option>
                                            <option value="DISTANCE_LT">&lt; que</option>
                                        </select>
                                    )}
                                </div>
                            )}

                            {/* Variables de cruce */}
                            {formCondition.source.name === IndicatorType.ELAPSED_TIME_LAST_HIGH || formCondition.source.name === IndicatorType.ELAPSED_TIME ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <span style={labelStyle}>Tiempo Transcurrido</span>
                                    <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                                        <input
                                            type="number"
                                            value={compCondition && typeof compCondition.target === 'number' ? compCondition.target : ''}
                                            onChange={(e) => {
                                                if (compCondition) {
                                                    setFormCondition({
                                                        ...compCondition,
                                                        type: 'indicator_comparison',
                                                        target: e.target.value === '' ? '' : Number(e.target.value)
                                                    });
                                                }
                                            }}
                                            onBlur={() => {
                                                if (compCondition) {
                                                    const val = Number(compCondition.target);
                                                    setFormCondition({
                                                        ...compCondition,
                                                        type: 'indicator_comparison',
                                                        target: isNaN(val) || val < 1 ? (formCondition.source.name === IndicatorType.ELAPSED_TIME ? 60 : 20) : Math.max(1, val)
                                                    });
                                                }
                                            }}
                                            onFocus={(e) => e.target.select()}
                                            style={{ ...inputStyle, width: '100%', paddingRight: 40 }}
                                        />
                                        <span style={{
                                            position: 'absolute',
                                            right: 8,
                                            fontSize: 10,
                                            fontWeight: 600,
                                            color: 'var(--color-ec-text-muted)',
                                            pointerEvents: 'none'
                                        }}>mins</span>
                                    </div>
                                    {formCondition.source.name === IndicatorType.ELAPSED_TIME_LAST_HIGH && (
                                        <>
                                            <span style={{ ...labelStyle, marginTop: 8 }}>Máximo de referencia</span>
                                            <select
                                                value={(compCondition?.source as { session_ref?: 'full' | 'pm' | 'rth' })?.session_ref ?? 'full'}
                                                onChange={(e) => {
                                                    if (compCondition) {
                                                        setFormCondition({
                                                            ...compCondition,
                                                            type: 'indicator_comparison',
                                                            source: { ...compCondition.source as object, session_ref: e.target.value as 'full' | 'pm' | 'rth' }
                                                        });
                                                    }
                                                }}
                                                style={selectStyle}
                                            >
                                                <option value="full">Máximo del día completo (PM + RTH)</option>
                                                <option value="pm">PMH del día (premercado)</option>
                                                <option value="rth">Máximo de RTH</option>
                                            </select>
                                            <span style={{ fontSize: 10, color: 'var(--color-ec-text-muted)', lineHeight: 1.4 }}>
                                                {(compCondition?.source as { session_ref?: string })?.session_ref === 'pm'
                                                    ? 'El reloj se resetea con cada nuevo máximo del premercado; desde las 09:30 el PMH queda congelado y el reloj sigue corriendo.'
                                                    : (compCondition?.source as { session_ref?: string })?.session_ref === 'rth'
                                                        ? 'Solo existe desde las 09:30: el reloj se resetea con cada nuevo máximo de RTH. En premercado la condición no dispara.'
                                                        : 'El reloj se resetea cada vez que el precio hace un nuevo máximo acumulado del día (premercado y RTH mezclados).'}
                                            </span>
                                        </>
                                    )}
                                </div>
                            ) : formCondition.source.name?.toLowerCase() === 'range of time' ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <span style={labelStyle}>Minutos del rango</span>
                                    <input
                                        type="number"
                                        value={compCondition && typeof compCondition.target === 'number' ? compCondition.target : ''}
                                        onChange={(e) => {
                                            if (compCondition) {
                                                setFormCondition({
                                                    ...compCondition,
                                                    type: 'indicator_comparison',
                                                    target: e.target.value === '' ? '' : Number(e.target.value)
                                                });
                                            }
                                        }}
                                        onBlur={() => {
                                            if (compCondition) {
                                                const val = Number(compCondition.target);
                                                setFormCondition({
                                                    ...compCondition,
                                                    type: 'indicator_comparison',
                                                    target: isNaN(val) || val < 0 ? 30 : Math.max(0, val)
                                                });
                                            }
                                        }}
                                        onFocus={(e) => e.target.select()}
                                        style={inputStyle}
                                    />
                                </div>
                            ) : compCondition && !isTriangle(formCondition.source.name) ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <span style={labelStyle}>Variables de cruce</span>
                                    <TargetInput
                                        value={compCondition.target}
                                        onChange={(newTarget) => setFormCondition({
                                            ...compCondition,
                                            type: 'indicator_comparison',
                                            target: newTarget
                                        })}
                                        allowedTargets={getAllowedTargets(formCondition.source.name as IndicatorType, 'indicator_comparison')}
                                        hideOffset={true}
                                        sourceIndicatorName={formCondition.source.name}
                                    />
                                    {/* Checkbox for Offset to Variable de cruce */}
                                    {typeof compCondition.target !== 'number' && (() => {
                                        const allowed = isOffsetAllowed((compCondition.target as IndicatorConfig).name);
                                        return (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, opacity: allowed ? 1 : 0.35 }}>
                                                    <input
                                                        type="checkbox"
                                                        id="offset-checkbox"
                                                        disabled={!allowed}
                                                        checked={allowed && !!compCondition.target.offset}
                                                        onChange={(e) => {
                                                            const checked = e.target.checked;
                                                            setFormCondition({
                                                                ...compCondition,
                                                                target: {
                                                                    ...compCondition.target as IndicatorConfig,
                                                                    offset: checked ? ((compCondition.target as IndicatorConfig).offset || 1) : 0
                                                                }
                                                            });
                                                        }}
                                                        style={{
                                                            width: 14,
                                                            height: 14,
                                                            accentColor: 'var(--color-ec-copper)',
                                                            cursor: allowed ? 'pointer' : 'not-allowed'
                                                        }}
                                                    />
                                                    <label
                                                        htmlFor={allowed ? "offset-checkbox" : undefined}
                                                        style={{
                                                            fontSize: 11,
                                                            fontWeight: 600,
                                                            color: 'var(--color-ec-text-primary)',
                                                            cursor: allowed ? 'pointer' : 'not-allowed',
                                                            userSelect: 'none'
                                                        }}
                                                    >
                                                        ¿Offset a Variable de cruce?
                                                    </label>
                                                    <TooltipIcon
                                                        customText="Compara la variable de entrada con el valor de la variable de cruce de X velas hacia atrás. Ejemplo: Si Bar Close > SMA_30 y le indicamos un offset de 3 velas, el Bar Close Actual comparará si es mayor que el valor del SMA_30 de hace 3 velas y no del actual. Esta opción permite <u>crear patrones de acción del precio</u>."
                                                    />
                                                </div>

                                                {/* Mostrar select de velas de retraso si el checkbox está activo */}
                                                {allowed && !!(compCondition.target as IndicatorConfig).offset && (
                                                    <div style={{ 
                                                        display: 'flex', 
                                                        alignItems: 'center', 
                                                        gap: 8, 
                                                        paddingLeft: 20,
                                                        marginTop: 2
                                                    }}>
                                                        <span style={{
                                                            fontSize: 11,
                                                            fontWeight: 600,
                                                            color: 'var(--color-ec-text-secondary)',
                                                            fontFamily: 'var(--color-ec-sans)',
                                                        }}>Velas atrás:</span>
                                                        <select
                                                            value={(compCondition.target as IndicatorConfig).offset || 1}
                                                            onChange={(e) => {
                                                                const val = Number(e.target.value);
                                                                setFormCondition({
                                                                    ...compCondition,
                                                                    target: { ...compCondition.target as IndicatorConfig, offset: val }
                                                                });
                                                            }}
                                                            style={{
                                                                backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                                border: '0.5px solid var(--color-ec-border)',
                                                                borderRadius: 4,
                                                                padding: '2px 8px 2px 6px',
                                                                fontSize: 11,
                                                                fontWeight: 700,
                                                                color: 'var(--color-ec-copper)',
                                                                fontFamily: 'var(--color-ec-sans)',
                                                                outline: 'none',
                                                                cursor: 'pointer',
                                                                width: 55,
                                                                textAlign: 'center'
                                                            }}
                                                        >
                                                            {Array.from({ length: 20 }, (_, i) => i + 1).map((val) => (
                                                                <option key={val} value={val} style={{ backgroundColor: 'var(--color-ec-bg-surface)', color: 'var(--color-ec-text-primary)' }}>
                                                                    {val}
                                                                </option>
                                                            ))}
                                                        </select>
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })()}
                                </div>
                            ) : distCondition ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                        <span style={labelStyle}>Distancia %</span>
                                        <input
                                            type="number"
                                            step="0.1"
                                            value={distCondition.value_pct ?? ''}
                                            onChange={(e) => setFormCondition({
                                                ...distCondition,
                                                type: 'price_level_distance',
                                                value_pct: e.target.value === '' ? '' : Number(e.target.value)
                                            })}
                                            onBlur={() => {
                                                const val = parseFloat(String(distCondition.value_pct));
                                                setFormCondition({
                                                    ...distCondition,
                                                    type: 'price_level_distance',
                                                    value_pct: isNaN(val) ? 0.5 : val
                                                });
                                            }}
                                            onFocus={(e) => e.target.select()}
                                            style={inputStyle}
                                        />
                                    </div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                        <span style={labelStyle}>Variables de cruce (Nivel)</span>
                                        <IndicatorSelector
                                            value={distCondition.level.name}
                                            exclude={[
                                                IndicatorType.TRIANGLE_ASCENDING,
                                                IndicatorType.TRIANGLE_DESCENDING,
                                                IndicatorType.TRIANGLE_SYMMETRIC
                                            ]}
                                            allowedTargets={getAllowedTargets(distCondition.source.name as IndicatorType, 'price_level_distance')}
                                            onChange={(nameStr) => {
                                                const name = nameStr as IndicatorType;
                                                const defaultParams = getDefaultParamsForIndicator(name);
                                                setFormCondition({
                                                    ...distCondition,
                                                    type: 'price_level_distance',
                                                    level: { 
                                                        name, 
                                                        offset: isOffsetAllowed(name) ? distCondition.level.offset : 0, 
                                                        ...defaultParams 
                                                    }
                                                });
                                            }}
                                        />
                                        <IndicatorParams
                                            value={distCondition.level}
                                            onChange={(newLevel) => setFormCondition({
                                                ...distCondition,
                                                type: 'price_level_distance',
                                                level: newLevel
                                            })}
                                            hideOffset={true}
                                        />

                                        {/* Checkbox for Offset to Variable de cruce */}
                                        {(() => {
                                            const allowed = isOffsetAllowed(distCondition.level.name);
                                            return (
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, opacity: allowed ? 1 : 0.35 }}>
                                                        <input
                                                            type="checkbox"
                                                            id="dist-offset-checkbox"
                                                            disabled={!allowed}
                                                            checked={allowed && !!distCondition.level.offset}
                                                            onChange={(e) => {
                                                                const checked = e.target.checked;
                                                                setFormCondition({
                                                                    ...distCondition,
                                                                    level: {
                                                                        ...distCondition.level,
                                                                        offset: checked ? (distCondition.level.offset || 1) : 0
                                                                    }
                                                                });
                                                            }}
                                                            style={{
                                                                width: 14,
                                                                height: 14,
                                                                accentColor: 'var(--color-ec-copper)',
                                                                cursor: allowed ? 'pointer' : 'not-allowed'
                                                            }}
                                                        />
                                                        <label
                                                            htmlFor={allowed ? "dist-offset-checkbox" : undefined}
                                                            style={{
                                                                fontSize: 11,
                                                                fontWeight: 600,
                                                                color: 'var(--color-ec-text-primary)',
                                                                cursor: allowed ? 'pointer' : 'not-allowed',
                                                                userSelect: 'none'
                                                            }}
                                                        >
                                                            ¿Offset a Variable de cruce?
                                                        </label>
                                                        <TooltipIcon
                                                            customText="Compara la variable de entrada con el valor de la variable de cruce de X velas hacia atrás. Ejemplo: Si Bar Close > SMA_30 y le indicamos un offset de 3 velas, el Bar Close Actual comparará si es mayor que el valor del SMA_30 de hace 3 velas y no del actual. Esta opción permite <u>crear patrones de acción del precio</u>."
                                                        />
                                                    </div>

                                                    {/* Mostrar select de velas de retraso si el checkbox está activo */}
                                                    {allowed && !!distCondition.level.offset && (
                                                        <div style={{ 
                                                            display: 'flex', 
                                                            alignItems: 'center', 
                                                            gap: 8, 
                                                            paddingLeft: 20,
                                                            marginTop: 2
                                                        }}>
                                                            <span style={{
                                                                fontSize: 11,
                                                                fontWeight: 600,
                                                                color: 'var(--color-ec-text-secondary)',
                                                                fontFamily: 'var(--color-ec-sans)',
                                                            }}>Velas atrás:</span>
                                                            <select
                                                                value={distCondition.level.offset || 1}
                                                                onChange={(e) => {
                                                                    const val = Number(e.target.value);
                                                                    setFormCondition({
                                                                        ...distCondition,
                                                                        level: { ...distCondition.level, offset: val }
                                                                    });
                                                                }}
                                                                style={{
                                                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                                                    border: '0.5px solid var(--color-ec-border)',
                                                                    borderRadius: 4,
                                                                    padding: '2px 8px 2px 6px',
                                                                    fontSize: 11,
                                                                    fontWeight: 700,
                                                                    color: 'var(--color-ec-copper)',
                                                                    fontFamily: 'var(--color-ec-sans)',
                                                                    outline: 'none',
                                                                    cursor: 'pointer',
                                                                    width: 55,
                                                                    textAlign: 'center'
                                                                }}
                                                            >
                                                                {Array.from({ length: 20 }, (_, i) => i + 1).map((val) => (
                                                                    <option key={val} value={val} style={{ backgroundColor: 'var(--color-ec-bg-surface)', color: 'var(--color-ec-text-primary)' }}>
                                                                        {val}
                                                                    </option>
                                                                ))}
                                                            </select>
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })()}
                                    </div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                        <span style={labelStyle}>Posición</span>
                                        <select
                                            value={distCondition.position || 'any'}
                                            onChange={(e) => setFormCondition({
                                                ...distCondition,
                                                type: 'price_level_distance',
                                                position: e.target.value as 'above' | 'below' | 'any'
                                            })}
                                            style={selectStyle}
                                        >
                                            <option value="any">Cualquiera (Any)</option>
                                            <option value="above">Por encima del nivel</option>
                                            <option value="below">Por debajo del nivel</option>
                                        </select>
                                    </div>
                                </div>
                            ) : null}



                            {/* Save/Cancel buttons */}
                            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                                <button
                                    onClick={handleSaveCondition}
                                    style={{
                                        flex: 1,
                                        padding: '6px 12px',
                                        backgroundColor: activeAccentColor,
                                        border: 'none',
                                        borderRadius: 4,
                                        fontSize: 11,
                                        fontWeight: 700,
                                        color: '#ffffff',
                                        cursor: 'pointer',
                                    }}
                                >
                                    {editingIndex !== null ? 'Guardar' : 'Añadir'}
                                </button>
                                <button
                                    onClick={() => {
                                        setShowForm(false);
                                        setEditingIndex(null);
                                    }}
                                    style={{
                                        flex: 1,
                                        padding: '6px 12px',
                                        backgroundColor: 'transparent',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 4,
                                        fontSize: 11,
                                        fontWeight: 600,
                                        color: 'var(--color-ec-text-muted)',
                                        cursor: 'pointer',
                                    }}
                                >
                                    Cancelar
                                </button>
                            </div>
                        </div>
                    ) : (
                        <div className="flex gap-2">
                            <button
                                onClick={() => {
                                    setEditingIndex(null);
                                    setFormCondition({
                                        type: 'indicator_comparison',
                                        source: { name: IndicatorType.BAR_CLOSE, offset: 0 },
                                        comparator: Comparator.GT,
                                        target: { name: IndicatorType.VWAP, offset: 0 },
                                        timeframe: parentTimeframe
                                    });
                                    setShowForm(true);
                                }}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 5,
                                    padding: '6px 12px',
                                    backgroundColor: 'transparent',
                                    border: '0.5px dashed var(--color-ec-border)',
                                    borderRadius: 5,
                                    fontSize: 11,
                                    fontWeight: 600,
                                    color: 'var(--color-ec-text-muted)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    cursor: 'pointer',
                                    transition: 'border-color 150ms ease, color 150ms ease',
                                    flex: 1,
                                    justifyContent: 'center',
                                }}
                                onMouseEnter={(e) => { e.currentTarget.style.borderColor = activeAccentColor; e.currentTarget.style.color = activeAccentColor; }}
                                onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-border)'; e.currentTarget.style.color = 'var(--color-ec-text-muted)'; }}
                            >
                                <Plus className="w-3 h-3" />
                                Condición
                            </button>
                            <button
                                onClick={addGroup}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 5,
                                    padding: '6px 12px',
                                    backgroundColor: 'transparent',
                                    border: '0.5px dashed var(--color-ec-border)',
                                    borderRadius: 5,
                                    fontSize: 11,
                                    fontWeight: 600,
                                    color: 'var(--color-ec-text-muted)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    cursor: 'pointer',
                                    transition: 'border-color 150ms ease, color 150ms ease',
                                    flex: 1,
                                    justifyContent: 'center',
                                }}
                                onMouseEnter={(e) => { e.currentTarget.style.borderColor = activeAccentColor; e.currentTarget.style.color = activeAccentColor; }}
                                onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-border)'; e.currentTarget.style.color = 'var(--color-ec-text-muted)'; }}
                            >
                                <GitBranch className="w-3 h-3" />
                                Grupo Lógico
                            </button>
                        </div>
                    )}
                </div>

                {/* Right side: Line of Tags */}
                <div style={{
                    flex: 1,
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: 6,
                    paddingTop: showForm ? 0 : 4,
                }}>
                    {group.conditions.map((cond, idx) => {
                        if (cond.type === 'group') return null;
                        return (
                            <div 
                                key={idx} 
                                onClick={() => {
                                    setEditingIndex(idx);
                                    setFormCondition(cond);
                                    setShowForm(true);
                                }}
                                style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    padding: '4px 8px',
                                    backgroundColor: 'rgba(216, 122, 61, 0.08)',
                                    border: '0.5px solid transparent',
                                    borderRadius: 4,
                                    fontSize: 10,
                                    fontWeight: 600,
                                    color: 'var(--color-ec-text-secondary)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    cursor: 'pointer',
                                    transition: 'border-color 150ms ease',
                                }}
                                onMouseEnter={(e) => e.currentTarget.style.borderColor = activeAccentColor}
                                  onMouseLeave={(e) => e.currentTarget.style.borderColor = 'transparent'}
                              >
                                {(() => {
                                    const lbl = formatConditionText(cond);
                                    return (
                                        <>
                                            <span>{lbl.source}</span>
                                            {lbl.target && <strong style={{ color: 'var(--color-ec-text-high)', marginLeft: 3 }}>{lbl.target}</strong>}
                                        </>
                                    );
                                })()}
                                <button 
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        handleRemoveCondition(idx);
                                    }} 
                                    style={{
                                        background: 'none',
                                        border: 'none',
                                        color: 'var(--color-ec-text-muted)',
                                        cursor: 'pointer',
                                        fontSize: 12,
                                        padding: '0 2px',
                                        lineHeight: 1,
                                    }}
                                    onMouseEnter={(e) => e.currentTarget.style.color = 'var(--color-ec-loss)'}
                                    onMouseLeave={(e) => e.currentTarget.style.color = 'var(--color-ec-text-muted)'}
                                >
                                    ×
                                </button>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Nested subgroups */}
            <div className="flex flex-col gap-3">
                {subGroups.map((sub, idx) => {
                    const mainIdx = group.conditions.indexOf(sub);
                    return (
                        <GroupDisplay
                            key={idx}
                            group={sub}
                            onChange={(newG) => updateCondition(mainIdx, newG)}
                            onDelete={() => removeCondition(mainIdx)}
                            level={level + 1}
                            accentColor={accentColor}
                            parentTimeframe={parentTimeframe}
                        />
                    );
                })}
            </div>
        </div>
    );
};

// ----------------------------------------------------------------------
// Main Entry Point for Logic Builder Component
// ----------------------------------------------------------------------
export const LogicBuilder = ({
    title,
    timeframe,
    onTimeframeChange,
    rootCondition,
    onConditionChange,
    accentColor = 'blue',
    candleDelay,
    onCandleDelayChange,
    children
}: {
    title: string;
    timeframe: Timeframe;
    onTimeframeChange: (tf: Timeframe) => void;
    rootCondition: ConditionGroup;
    onConditionChange: (g: ConditionGroup) => void;
    accentColor?: 'blue' | 'rose' | 'amber';
    candleDelay?: number;
    onCandleDelayChange?: (delay: number | undefined) => void;
    children?: React.ReactNode;
}) => {
    const headerAccentColor = accentColor === 'blue' ? 'var(--color-ec-profit)' : accentColor === 'rose' ? 'var(--color-ec-loss)' : 'var(--color-ec-copper)';
    const isEntry = title.toLowerCase().includes('entry');
    const tooltipText = `Esta opción (también llamada "slippage sintético") permite ejecutar la entrada o salida N velas después de que se cumpla la señal (por defecto es 1 vela para evitar look-ahead bias). Es una función especial orientada al trading sistemático de ejecución manual para dar tiempo a preparar y enviar la orden manualmente tras recibir o ver la alerta de ${isEntry ? 'entrada' : 'salida'}.

Con esta función podrás asegurarte de que tu sistema sigue siendo rentable incluso con retardo en la ejecución, puesto que la volatilidad instantanea puede "falsear" los resultados de un backtest si no se aplica de manera algorítmica (bot).`;

    const [activeTooltip, setActiveTooltip] = React.useState<{
        text: string;
        x: number;
        y: number;
        width?: number;
        title?: string;
    } | null>(null);

    const containerRef = React.useRef<HTMLDivElement>(null);

    return (
        <TooltipContext.Provider value={{ setActiveTooltip, containerRef }}>
            <div 
                ref={containerRef}
                style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 16,
                    padding: '20px 0',
                    backgroundColor: 'transparent',
                    borderBottom: '0.5px solid var(--color-ec-border)',
                    position: 'relative',
                }}
            >
                {/* Header with Title and Global Timeframe */}
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    paddingBottom: 4,
                    marginBottom: 4,
                }}>
                    <div className="flex flex-col gap-1">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{
                                width: 3,
                                height: 14,
                                borderRadius: 1,
                                backgroundColor: headerAccentColor,
                            }} />
                            <h2 style={{
                                fontFamily: 'var(--color-ec-sans)',
                                fontSize: 13,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                color: 'var(--color-ec-text-high)',
                                margin: 0,
                            }}>{title}</h2>
                        </div>
                        <span style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 10,
                            fontWeight: 400,
                            color: 'var(--color-ec-text-muted)',
                            marginTop: 2,
                        }}>Define las condiciones lógicas y el timeframe de ejecución</span>
                    </div>
                </div>

                {/* Root Condition Group */}
                <GroupDisplay
                    group={rootCondition}
                    onChange={onConditionChange}
                    accentColor={accentColor}
                    parentTimeframe={timeframe}
                />

                {/* Delayed Execution (Candle Delay) */}
                {onCandleDelayChange && (
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 12,
                        marginTop: 0,
                        paddingTop: 0,
                        borderTop: 'none',
                        paddingLeft: 4,
                        paddingRight: 4,
                        width: '100%',
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <label style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 8,
                                cursor: 'pointer',
                                userSelect: 'none',
                                fontSize: 11,
                                fontWeight: 600,
                                color: 'var(--color-ec-text-primary)',
                                fontFamily: 'var(--color-ec-sans)',
                            }}>
                                <input
                                    type="checkbox"
                                    checked={candleDelay !== undefined && candleDelay > 1}
                                    onChange={(e) => {
                                        if (e.target.checked) {
                                            onCandleDelayChange(3); // Default to 3 candles when checked
                                        } else {
                                            onCandleDelayChange(undefined); // Reset/Disable delay
                                        }
                                    }}
                                    style={{
                                        accentColor: headerAccentColor,
                                        cursor: 'pointer',
                                    }}
                                />
                                Retardar ejecución (velas futuras)
                            </label>
                            <TooltipIcon customText={tooltipText} />
                        </div>

                        {candleDelay !== undefined && candleDelay > 1 && (
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 8,
                                paddingLeft: 12,
                                borderLeft: '0.5px solid var(--color-ec-border)',
                            }}>
                                <span style={{
                                    fontSize: 11,
                                    color: 'var(--color-ec-text-muted)',
                                    fontFamily: 'var(--color-ec-sans)',
                                }}>
                                    Ejecutar en la vela futura número:
                                </span>
                                <select
                                    value={candleDelay}
                                    onChange={(e) => onCandleDelayChange(Number(e.target.value))}
                                    style={{
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: '4px',
                                        padding: '3px 8px',
                                        fontSize: '11px',
                                        fontWeight: 600,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                        cursor: 'pointer',
                                    }}
                                >
                                    {[2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 30, 45, 60].map((num) => (
                                        <option key={num} value={num}>
                                            {num}
                                        </option>
                                    ))}
                                </select>
                            </div>
                        )}
                    </div>
                )}

                {children}

                {activeTooltip && typeof document !== "undefined" && createPortal(
                    <div
                        style={{
                            position: "fixed",
                            top: activeTooltip.y,
                            left: activeTooltip.x,
                            transform: "translate(0, -100%)",
                            backgroundColor: "var(--color-ec-bg-elevated)",
                            color: "var(--color-ec-text-primary)",
                            border: "0.5px solid var(--color-ec-border)",
                            borderRadius: 4,
                            padding: "6px 8px",
                            lineHeight: 1.3,
                            width: 185,
                            zIndex: 100005,
                            pointerEvents: "none",
                            boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
                            fontFamily: "var(--color-ec-sans)",
                            whiteSpace: "normal",
                            display: "flex",
                            flexDirection: "column",
                            gap: 2,
                            textAlign: 'left',
                        }}
                    >
                        {activeTooltip.title && (
                            <strong style={{ display: 'block', color: 'var(--color-ec-copper)', fontSize: 9.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.03em', marginBottom: 2 }}>
                                {activeTooltip.title}
                            </strong>
                        )}
                        <span 
                            style={{ fontSize: 9.5, color: "var(--color-ec-text-high)", lineHeight: 1.3 }}
                            dangerouslySetInnerHTML={{ __html: activeTooltip.text }}
                        />
                    </div>,
                    document.body
                )}
            </div>
        </TooltipContext.Provider>
    );
};
