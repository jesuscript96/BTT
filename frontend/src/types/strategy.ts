
// Enums
export enum IndicatorType {
    // Price Variables
    BAR_CLOSE = "Bar Close",
    BAR_OPEN = "Bar Open",
    HIGH_BAR = "High Bar",
    LOW_BAR = "Low Bar",
    PM_OPEN = "PM Open",
    PM_HIGH = "PM High",
    PM_LOW = "PM Low",
    RTH_OPEN = "RTH Open",
    RTH_HIGH = "RTH High",
    RTH_LOW = "RTH Low",
    AM_OPEN = "AM Open",
    PREVIOUS_MAX = "Previous max",
    PREVIOUS_MIN = "Previous min",
    YESTERDAY_OPEN = "Yesterday Open",
    YESTERDAY_CLOSE = "Yesterday Close",
    YESTERDAY_HIGH = "Yesterday High",
    YESTERDAY_LOW = "Yesterday Low",
    HIGH_X_DAYS = "High of last X days",
    LOW_X_DAYS = "Low of last X days",
    // El de verdad. Los dos de arriba se quedan SOLO por compatibilidad con
    // estrategias antiguas: comparten motor y solo fijan otros defectos.
    OVERHEAD_X_DAYS = "Overhead last X days",
    PREV_BAR_CLOSE = "Prev. Bar Close",
    PREV_BAR_OPEN = "Prev. Bar Open",
    PREV_BAR_HIGH = "Prev. Bar High",
    PREV_BAR_LOW = "Prev. Bar Low",

    // Behaviour & Patterns
    CONSEC_HIGHER_HIGHS = "Consecutive higher highs",
    CONSEC_LOWER_LOWS = "Consecutive lower lows",
    CONSEC_LOWER_HIGHS = "Consecutive lower highs",
    CONSEC_HIGHER_LOWS = "Consecutive higher lows",
    CONSEC_GREEN_CANDLES = "Consecutive green candles",
    CONSEC_RED_CANDLES = "Consecutive red candles",
    CANDLE_RANGE_PCT = "Candle Range %",
    // Recorrido de la vela CON SIGNO. Es CANDLE_RANGE_PCT sin el abs():
    // positivo = la vela subió, negativo = bajó. Sin selector de dirección a
    // propósito — el signo ya la lleva.
    RECORRIDO_PCT = "Recorrido (%)",
    RANGE_OF_TIME = "Range of Time",
    OPENING_RANGE_PLUS = "Opening range +",
    OPENING_RANGE_MINUS = "Opening range -",
    OPENING_RANGE_AM_PLUS = "Opening range AM +",
    OPENING_RANGE_AM_MINUS = "Opening range AM -",
    ELAPSED_TIME_LAST_HIGH = "Elapsed time from last High",
    ELAPSED_TIME = "Elapsed Time",
    TRIANGLE_ASCENDING = "Triangle Ascending",
    TRIANGLE_DESCENDING = "Triangle Descending",
    TRIANGLE_SYMMETRIC = "Triangle Symmetric",
    PM_HIGH_GAP = "PM High Gap (%)",
    CURRENT_GAP = "Current Gap (%)",
    OPEN_GAP = "Open Gap (%)",
    // Caida de una sesion entera, congelada: del maximo de la sesion a la
    // apertura de la siguiente (PM -> open de mercado, RTH -> open del after).
    SESSION_FADE = "% Session Fade",
    // Caida viva desde una referencia que se reancla sola: el maximo previo o
    // el VWAP en la vela en que el precio lo cruzo.
    FADE = "% Fade",

    // Indicators
    SMA = "SMA",
    EMA = "EMA",
    VWAP = "VWAP",
    DONCHIAN = "Donchian",
    // Caja de Darvas: soporte y resistencia HORIZONTALES que nacen de la
    // maquina de 3 estados del indicador (techo -> suelo -> caja). Se usa como
    // NIVEL contra el que cruzar cualquier otra variable, igual que Donchian.
    // El valor que llega al backend es el nombre canonico de indicators.py.
    DARVAS_BOX = "Darvas Box",
    BOLLINGER_BANDS = "Bollinger Bands",
    ACCUMULATED_VOLUME = "Accumulated Volume",
    ACCUM_DOLLAR_VOLUME = "Accumulated Dollar Volume",
    DOLLAR_VOLUME = "Dollar Volume",
    // Halts (12-sep-2026): cuantos halts lleva HOY el ticker cuya vela de
    // entrada al halt fue bajista (Down) o alcista (Up). Contador que se queda:
    // «Halt Down >= 1» se hace verdad en la vela del primer halt bajista. Sale
    // de la tabla de halts del lago; el bot en vivo NO lo ve.
    HALT_DOWN = "Halt Down",
    HALT_UP = "Halt Up",
    YESTERDAY_VOLUME = "Yesterday Volume",
    RVOL = "RVOL by bar",
    VOLUME = "Volume",
    ATR = "ATR",
    // Squeeze: % que ha movido el precio en una ventana de RELOJ (minutos).
    // No es un nivel: es una cifra, asi que solo se compara contra un numero.
    SQUEEZE = "Squeeze",

    // Recta de minimos cuadrados sobre el PRECIO de una ventana de RELOJ.
    // Las dos salen del MISMO ajuste: la pendiente dice cuanto se mueve, el R2
    // si es una escalera o una sierra. Ninguna es un nivel de precio.
    REG_SLOPE = "Reg. Slope",
    REG_R2 = "Reg. R2",
    // Distancia del precio a una referencia, medida en ATR (comparable entre
    // tickers, que es lo que un umbral en % no consigue).
    ATR_EXTENSION = "ATR Extension",
    // Microestructura: cuanto dinero cuesta mover el precio, y cuanto de lo
    // recorrido se devolvio. Ninguno es un nivel de precio.
    // Que fraccion del impulso se ha devuelto ya. Causal: el impulso se define
    // solo con pasado (maximo corrido + minimo anterior a ese maximo).
    // Ultimo techo (o suelo) que dejo el mercado. Es un NIVEL DE PRECIO, al
    // contrario que el resto de los nuevos: se compara con otros indicadores y
    // sirve de stop estructural.
    // Perfil de volumen intradia. El primero es una MEDIDA (percentil 0-100);
    // los otros tres son NIVELES DE PRECIO y sirven de stop estructural.
    VOL_BIN_PCT = "Vol. de la franja",
    VOL_POC = "Punto de control",
    VOL_NODE_UP = "Nodo de arriba",
    VOL_NODE_DOWN = "Nodo de abajo",
    // La ZONA DE VALOR: los dos bordes de la banda donde se ha negociado casi
    // todo. NO se mueve con el precio, al contrario que los nodos.
    VOL_ZONE_HIGH = "Zona alta",
    VOL_ZONE_LOW = "Zona baja",
    LAST_PIVOT = "Ultimo pivote",
    RETRACEMENT = "Retroceso (%)",
    ABSORPTION = "Absorption",
    WICK_RATIO = "Wick Ratio",
    ABSORPTION_WICK = "Absorption + Wick",
    // Minutos SEGUIDOS por encima (o por debajo) de un nivel: la "aceptacion".
    TIME_VS_LEVEL = "Time vs Level",

    // Momentum clasico. El backend ya los calculaba (y por la via rapida), pero
    // no estaban en ESTE enum, asi que no se podian usar en las condiciones.
    // Las tres lineas del MACD son nombres distintos, no un parametro: es como
    // las tiene el motor. `macd_line` de IndicatorConfig no lo lee nadie.
    RSI = "RSI",
    MACD = "MACD",
    MACD_SIGNAL = "MACD Signal",
    MACD_HISTOGRAM = "MACD Histogram",
}

export enum Comparator {
    GT = "GREATER_THAN",
    LT = "LESS_THAN",
    GTE = "GREATER_THAN_OR_EQUAL",
    LTE = "LESS_THAN_OR_EQUAL",
    EQ = "EQUAL",
    CROSSES_ABOVE = "CROSSES_ABOVE",
    CROSSES_BELOW = "CROSSES_BELOW",
    DISTANCE_GT = "DISTANCE_GREATER_THAN",
    DISTANCE_LT = "DISTANCE_LESS_THAN"
}

export enum Timeframe {
    M1 = "1m",
    M5 = "5m",
    M15 = "15m",
    M30 = "30m",
    H1 = "1h",
    D1 = "1d"
}

export enum RiskType {
    FIXED = "Fixed Amount",
    PERCENTAGE = "Percentage",
    ATR = "ATR Multiplier",
    MARKET_STRUCTURE = "Market Structure (HOD/LOD)",
    TIME = "Time",
    HOUR = "Hour"
}

export enum TakeProfitMode {
    FULL = "Full",
    PARTIAL = "Partial"
}

// Component Interfaces
export interface UniverseFilters {
    min_market_cap?: number;
    max_market_cap?: number;
    min_price?: number;
    max_price?: number;
    min_volume?: number;
    max_shares_float?: number;
    require_shortable: boolean;
    exclude_dilution: boolean;
    whitelist_sectors: string[];
    date_from?: string;
    date_to?: string;
    rules?: any[];
}

export interface IndicatorConfig {
    name: IndicatorType;
    period?: number;
    period2?: number;          // Fast period, signal period, etc.
    period3?: number;          // Slow period, etc.
    stdDev?: number;           // Standard Deviation for BB
    multiplier?: number;
    offset?: number;
    overbought?: number;
    oversold?: number;
    consecutive_count?: number;
    time_hour?: number;
    time_minute?: number;
    time_condition?: "BEFORE" | "AFTER"; // To support 'before X hour' or 'after X hour'
    days_lookback?: number;    // "Max/Min of last X days" y "Overhead last X days"
    // "Overhead last X days"
    overhead_extreme?: "max" | "min";                  // que dia se busca
    overhead_ref?: "high" | "low" | "open" | "close";  // que precio de ESE dia es el nivel
    overhead_vol_rule?: "none" | "gt" | "lt";          // su volumen frente al acumulado de hoy
    calc_on_heikin?: boolean;
    ap_session?: "ap.PM" | "ap.RTH" | "ap.AM";
    elapsed_minutes?: number;

    // Added specific parameters for new indicator rules
    macd_line?: "Signal" | "MACD Line" | "Histogram";
    band_line?: "Upper" | "Lower" | "Basis";
    orb_minutes?: number;
    ha_option?: "Close Bar" | "Open Bar" | "High Bar" | "Low Bar" | "Consecutive Green" | "Consecutive Red";
    time_from_hour?: number;
    time_from_minute?: number;
    range_minutes?: number;
    return_pct?: number;

    // New indicator-specific parameters
    deviationLevel?: number;       // Linear Regression deviation (1, 2, 3)
    reversionPercentage?: number;  // Zig Zag reversion %
    ichimoku_line?: "Tenkan" | "Kijun" | "Senkou A" | "Senkou B" | "Chikou";
    min_af?: number;               // Parabolic SAR min acceleration factor
    max_af?: number;               // Parabolic SAR max acceleration factor

    // Triangle pattern parameters
    pivot_window?: number;         // Candles for swing high/low confirmation
    tri_lookback?: number;         // Bars to search for pivots
    slope_tolerance?: number;      // Max slope considered "flat"
    min_r_squared?: number;        // Min R² for trend line quality
    min_pivots?: number;           // Min swing highs required to fit lines

    // "Elapsed time from last High": ancla del reloj.
    // "% Session Fade" lo reutiliza para elegir la sesion que se desinfla:
    // "pm" (PM High -> apertura de mercado) o "rth" (max. RTH -> open del after).
    session_ref?: "full" | "pm" | "rth";

    // "% Fade": desde donde se mide la caida. "previous_max" usa el maximo previo
    // (con la sesion de `ap_session`); "vwap_cross", el precio del VWAP en la
    // vela en que el precio lo cruzo por ultima vez.
    fade_ref?: "previous_max" | "vwap_cross";

    // Squeeze: direccion del spike. El indicador devuelve SIEMPRE positivo el
    // movimiento en la direccion elegida, para que la condicion se lea igual
    // arriba que abajo ("Squeeze > 10"). La ventana va en `range_minutes`.
    squeeze_direction?: "up" | "down";

    // "ATR Extension" y "Time vs Level": contra que nivel se mide.
    //   ref_level  cual es el nivel. Si es "sma"/"ema", su periodo sale de
    //              `period2` — en "ATR Extension" `period` es el del ATR.
    //   level_dir  solo para "Time vs Level": si el reloj corre mientras el
    //              precio esta POR ENCIMA ("above") o POR DEBAJO ("below").
    ref_level?: "vwap" | "sma" | "ema" | "day_open" | "rth_open" | "pmh" | "pml"
        | "prev_close" | "previous_max" | "previous_min" | "hod" | "lod";
    level_dir?: "above" | "below";

    // "Wick Ratio": que mecha se mide, la de arriba o la de abajo.
    wick_side?: "upper" | "lower";
    // "Absorption + Wick": los dos umbrales van DENTRO del indicador, porque la
    // condicion solo tiene un `target`. El indicador devuelve 1 o 0.
    abs_op?: "gt" | "lt";
    abs_level?: number;
    wick_op?: "gt" | "lt";
    wick_level?: number;
    // "Retroceso (%)": impulso al alza ("up") o a la baja ("down").
    swing_dir?: "up" | "down";
    // Perfil de volumen: anchura de franja (% del primer precio del dia) y
    // liston para que una franja cuente como nodo (% del volumen del POC).
    bin_pct?: number;
    liston_pct?: number;
    // "Zona alta"/"Zona baja": que % del volumen del dia abarca la banda (70 es
    // lo clasico). Distinto de `liston_pct`, que es lo que necesita UNA franja
    // para contar como nodo.
    zona_pct?: number;
}

export interface ComparisonCondition {
    type: "indicator_comparison";
    source: IndicatorConfig;
    comparator: Comparator;
    target: IndicatorConfig | number;
    timeframe?: Timeframe;
}

export interface PriceLevelDistanceCondition {
    type: "price_level_distance";
    source: IndicatorConfig;
    level: IndicatorConfig;
    comparator: "DISTANCE_GT" | "DISTANCE_LT";
    value_pct: number;
    position?: 'above' | 'below' | 'any';
    timeframe?: Timeframe;
}

export type AnyCondition = ComparisonCondition | PriceLevelDistanceCondition;

// Recursive Logical Group
export interface ConditionGroup {
    type: "group";
    operator: "AND" | "OR";
    conditions: (ConditionGroup | AnyCondition)[];
}

export interface EntryTimeWindow {
    from_time: string; // Formato "HH:MM"
    to_time: string;   // Formato "HH:MM"
}

export interface EntryLogic {
    timeframe: Timeframe;
    root_condition: ConditionGroup;
    entry_time_windows?: EntryTimeWindow[];
    candle_delay?: number;
}

export interface ExitLogic {
    timeframe: Timeframe;
    root_condition: ConditionGroup;
    candle_delay?: number;
}

export interface RiskSettings {
    type: RiskType;
    value: number | string;
    operator?: string;
    offset_pct?: number;
    // Solo hard_stop: nivel de respaldo en REENTRADAS cuando el principal
    // queda invalidado al entrar (ej. corto con el PMH ya roto). El motor lo
    // lee del JSON; undefined = sin respaldo (nivel invalidado = no se entra).
    fallback_value?: string;
    // Con true, el respaldo rescata TAMBIEN la primera entrada con el nivel
    // invalidado (no solo reentradas).
    fallback_first_entry?: boolean;
    // SOLO con type = "ATR Multiplier". Respaldo en % del precio de entrada
    // para las primeras velas del dia, cuando el ATR(14) todavia no existe
    // (le faltan velas). Ausente o 0 = en ese tramo NO se entra.
    //
    // El respaldo produce un precio de stop normal, asi que pasa por los
    // MISMOS topes que el ATR: Cangrejo A y B, hibrido y `size_by_sl`.
    atr_fallback_pct?: number;
    // SOLO con value = "Ultimo pivote alto"/"bajo". Velas de confirmacion a
    // cada lado. Por defecto 3.
    pivot_window?: number;
    // Respaldo en % cuando el nivel ESTRUCTURAL no se resuelve en esa vela (el
    // pivote sin confirmar, un PMH inexistente...). Ausente = 5 %, que es lo
    // que el motor usaba clavado en el codigo.
    struct_fallback_pct?: number;
}

export interface PartialTakeProfit {
    distance_pct: number | 'EOD' | string;
    capital_pct: number;
}

export interface TrailingStopSettings {
    active: boolean;
    type: string;
    buffer_pct: number;
    buffer_r?: number;
}

export interface RiskManagement {
    use_hard_stop?: boolean;
    use_take_profit?: boolean;
    take_profit_mode: TakeProfitMode;
    accept_reentries?: boolean;
    max_reentries?: number;
    hard_stop: RiskSettings;
    take_profit: RiskSettings;
    partial_take_profits: PartialTakeProfit[];
    trailing_stop: TrailingStopSettings;
    /** OJO: `max_drawdown_daily` no lo lee ningun motor; la UI lo pinta pero no
     *  hace nada. El cortacircuitos real es `daily_loss_limit`. */
    max_drawdown_daily?: number;
    /** Cortacircuitos de perdida diaria: corta la sesion al cruzar el umbral. */
    daily_loss_limit?: {
        enabled: boolean;
        /** CASH = dolares fijos; PCT = % del capital de apertura del dia. */
        unit: 'CASH' | 'PCT';
        value: number;
        on_open_positions: 'LET_RUN' | 'CLOSE_ALL';
    };
    size_by_sl?: boolean;
    /** STOP HÍBRIDO: va por distancia al stop, pero con techo de exposición.
     *  `techo $ = (hybrid_max_loss_pct% × capital) / hybrid_black_swan_pct%`
     *  Resuelve el punto ciego del modo por SL: con el stop muy ceñido el
     *  tamaño se dispara y un hueco brutal deja debiendo dinero. Recorta,
     *  no anula. Implica `size_by_sl`. */
    hybrid_stop?: boolean;
    /** El peor movimiento en contra que quieres contemplar, en %. */
    hybrid_black_swan_pct?: number | null;
    /** Cuánto de tu CUENTA ENTERA aceptas perder si eso pasa, en %. */
    hybrid_max_loss_pct?: number | null;
    /** ESTILO CANGREJO (PRD de Álvaro, 8-sep-2026). Acota cada trade «o por
     *  recorrido del SL, o por pérdida máxima». Dos modos EXCLUYENTES entre sí
     *  y con el stop híbrido; son TECHOS sobre el sizing que ya haya, así que
     *  solo recortan.
     *   · `recorrido` → `cangrejo_max_sl_dist_pct`: el stop nunca a más de ese
     *     % del entry. Aprieta el stop: cambia DÓNDE sales.
     *   · `perdida`   → `cangrejo_max_loss_at_sl_pct`: el SL nunca cuesta más
     *     de ese % de la cuenta. Encoge el tamaño: cambia CUÁNTO pones. */
    cangrejo_active?: boolean;
    cangrejo_mode?: 'recorrido' | 'perdida' | null;
    cangrejo_max_sl_dist_pct?: number | null;
    cangrejo_max_loss_at_sl_pct?: number | null;
    /** INERTES, sin UI: la primera versión de la tarjeta tenía cuatro topes y
     *  resultó poco intuitiva. Se admiten para que un borrador viejo no
     *  reviente, pero ningún motor los lee. */
    cangrejo_max_mv_entry_pct?: number | null;
    cangrejo_max_mv_pyr_pct?: number | null;
    swing_option?: {
        active: boolean;
        target_day: 'gap_1_day' | 'gap_2_day';
    };
    exclude_days?: number[];
    exclude_months?: number[];
    exclude_days_active?: boolean;
}

export interface PostGapPrecondition {
    id: string;
    day: 'gap_day' | 'gap_1_day';
    metric: 'volume' | 'close_vs_open' | 'close_vs_high_low' | 'close_vs_pm_high' | 'close_vs_pm_low' | 'close_vs_high' | 'close_vs_low' | 'close_vs_vwap' | 'close_vs_sma' | 'candle_range_pct' | 'candle_range_ratio_gap_1_vs_gap';
    operator: '>' | '<' | '> High' | '< Low';
    value?: number;
    sma_period?: number;
}

export interface Strategy {
    id?: string;
    name: string;
    description?: string;
    bias: 'long' | 'short';
    apply_day?: 'gap_day' | 'gap_1_day' | 'gap_2_day';
    postgap_preconditions?: PostGapPrecondition[];
    universe_filters?: UniverseFilters;
    entry_logic: EntryLogic;
    exit_logic?: ExitLogic;
    risk_management: RiskManagement;
    // Solo presente si la piramidación está activa y con niveles válidos.
    pyramiding?: { timeframe: Timeframe; mode?: 'individual' | 'sequential'; levels: PyramidLevel[] };
    // Modelos avanzados (XGBoost / HMM). Solo presente si el bloque esta
    // encendido; sin el, la estrategia es identica a las de siempre.
    advanced_model?: any;
    // Scalping. Solo presente si el bloque esta encendido y el gatillo tiene
    // condiciones; sin el, la estrategia es identica a las de siempre.
    scalping?: ScalpingBlock;
    is_wizard?: boolean;
    dataset_id?: string | null;
    // The API sometimes returns the strategy wrapped as `{ id, name, definition: {...} }`
    // and sometimes flat. Components read `strategy.definition?.x ?? strategy.x` to
    // support both shapes; keep this loose so those accesses type-check everywhere.
    definition?: any;
    created_at?: string;
    updated_at?: string;
}

// Default Initial State
export const initialUniverseFilters: UniverseFilters = {
    require_shortable: true,
    exclude_dilution: true,
    whitelist_sectors: []
};

export const initialEntryLogic: EntryLogic = {
    timeframe: Timeframe.M1,
    root_condition: {
        type: "group",
        operator: "AND",
        conditions: []
    }
};

export const initialRiskManagement: RiskManagement = {
    use_hard_stop: false,
    use_take_profit: false,
    take_profit_mode: TakeProfitMode.FULL,
    accept_reentries: false,
    max_reentries: -1,
    hard_stop: { type: RiskType.PERCENTAGE, value: 2.0 },
    take_profit: { type: RiskType.PERCENTAGE, value: 6.0 },
    partial_take_profits: [
        { distance_pct: 3.0, capital_pct: 50.0 },
        { distance_pct: 6.0, capital_pct: 50.0 }
    ],
    trailing_stop: { active: false, type: "Percentage", buffer_pct: 0.5 },
    size_by_sl: false,
    hybrid_stop: false,
    hybrid_black_swan_pct: null,
    hybrid_max_loss_pct: null,
    cangrejo_active: false,
    cangrejo_mode: null,
    cangrejo_max_sl_dist_pct: null,
    cangrejo_max_loss_at_sl_pct: null,
    cangrejo_max_mv_entry_pct: null,
    cangrejo_max_mv_pyr_pct: null,
    swing_option: { active: false, target_day: 'gap_1_day' },
    exclude_days: [],
    exclude_months: [],
    exclude_days_active: false
};

export const initialExitLogic: ExitLogic = {
    timeframe: Timeframe.M1,
    root_condition: {
        type: "group",
        operator: "AND",
        conditions: []
    }
};

// ── Piramidación (2026-08-22) ────────────────────────────────────────────
// Gestión dinámica de la posición: niveles con el MISMO árbol de condiciones
// que entrada/salida, evaluados por el backend con la misma maquinaria (todos
// los indicadores y grupos AND/OR funcionan sin lista aparte). Cada nivel
// añade (% del EQUITY de la cuenta) o quita (% de la posición FLOTANTE) y
// dispara UNA sola vez por trade; la reentrada los rearma. TP/SL corren en
// paralelo y se llevan lo que las reducciones no quiten.
export interface PyramidLevel {
    root_condition: ConditionGroup;
    action: 'add' | 'reduce';
    // Que significa `capital_pct`:
    //   'pct' (por defecto) -> % del equity al añadir, % de la posicion
    //                          flotante al quitar
    //   'usd'               -> una cantidad FIJA en dolares, convertida a
    //                          acciones al precio de la barra
    unit: 'pct' | 'usd';
    capital_pct: number;   // % en unidades de UI (1 = 1%), o $ si unit='usd'
    // Cuantas veces puede disparar por trade (flancos de su señal). 1 = el
    // clasico "una vez"; con Darvas, 3 = hasta tres cajas seguidas.
    times: number;
    // MODO DE TAMAÑO DEL NIVEL, independiente del de la entrada: un añadido
    // puede ir por distancia al stop aunque la entrada vaya por valor de
    // mercado. Sin declarar = por valor de mercado, como siempre.
    //   size_by_sl        -> `capital_pct` pasa a ser RIESGO, no capital
    //   hybrid_stop       -> por SL, pero con techo de exposición propio
    // Los porcentajes del híbrido son de este nivel y NO los de la entrada:
    // se reparten entre las dos para que juntas no pasen de lo asumible.
    size_by_sl?: boolean;
    hybrid_stop?: boolean;
    hybrid_black_swan_pct?: number | null;
    hybrid_max_loss_pct?: number | null;
}

export interface PyramidingConfig {
    active: boolean;       // toggle de la UI; si está OFF, la definición NO
                           // lleva la clave `pyramiding` (regla nº1: sin
                           // piramidar, nada cambia en el backend)
    timeframe: Timeframe;
    // individual (por defecto): cada piramide vigila su condicion en paralelo,
    // sin anclaje entre ellas. sequential: cada una se ARMA solo cuando la
    // anterior ya ha disparado al menos una vez.
    mode: 'individual' | 'sequential';
    levels: PyramidLevel[];
}

export const emptyPyramidLevel = (): PyramidLevel => ({
    root_condition: { type: "group", operator: "AND", conditions: [] },
    action: 'add',
    unit: 'pct',
    capital_pct: 1.0,
    times: 1,
});

export const initialPyramiding: PyramidingConfig = {
    active: false,
    timeframe: Timeframe.M1,
    mode: 'individual',
    levels: [],
};

// ── Scalping (2026-09-12) ──
// La entrada logica ABRE una ventana y la salida logica la CIERRA. Dentro,
// cada cumplimiento nuevo del gatillo es una entrada (reentradas ilimitadas),
// con el stop y el take profit de la estrategia, una salida por tiempo propia
// y una pausa de N velas tras cada salida.
export interface ScalpingBlock {
    timeframe: Timeframe;
    // El gatillo: el MISMO arbol de condiciones que entrada/salida.
    root_condition: ConditionGroup;
    // Salida por tiempo, en minutos desde la entrada. 0 = sin salida propia.
    max_minutes: number;
    // Velas que hay que esperar tras una salida para volver a entrar. 0 = ninguna.
    cooldown_bars: number;
    // % de la cifra de capital/riesgo del panel que usa CADA scalp. 100 = la
    // cifra entera (como una entrada normal). Se aplica escalando `risk_r`.
    capital_pct: number;
}

export interface ScalpingConfig extends ScalpingBlock {
    active: boolean;       // toggle de la UI; si esta OFF, la definicion NO
                           // lleva la clave `scalping` (regla nº1)
}

export const initialScalping: ScalpingConfig = {
    active: false,
    timeframe: Timeframe.M1,
    root_condition: { type: "group", operator: "AND", conditions: [] },
    max_minutes: 5,
    cooldown_bars: 1,
    capital_pct: 100,
};
