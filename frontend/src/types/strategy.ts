
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
    YESTERDAY_VOLUME = "Yesterday Volume",
    RVOL = "RVOL by bar",
    VOLUME = "Volume",
    ATR = "ATR",
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
    days_lookback?: number;    // "Max/Min of last X days"
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

    // "Elapsed time from last High": ancla del reloj
    session_ref?: "full" | "pm" | "rth";
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
