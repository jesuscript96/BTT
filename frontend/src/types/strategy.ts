
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
    TRIANGLE_ASCENDING = "Triangle Ascending",
    TRIANGLE_DESCENDING = "Triangle Descending",
    TRIANGLE_SYMMETRIC = "Triangle Symmetric",

    // Indicators
    SMA = "SMA",
    EMA = "EMA",
    VWAP = "VWAP",
    DONCHIAN = "Donchian",
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
    MARKET_STRUCTURE = "Market Structure (HOD/LOD)"
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
    min_pivots?: number;           // Min swing highs/lows required to fit lines
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
}

export interface ExitLogic {
    timeframe: Timeframe;
    root_condition: ConditionGroup;
}

export interface RiskSettings {
    type: RiskType;
    value: number | string;
}

export interface PartialTakeProfit {
    distance_pct: number;
    capital_pct: number;
}

export interface TrailingStopSettings {
    active: boolean;
    type: string;
    buffer_pct: number;
}

export interface RiskManagement {
    use_hard_stop?: boolean;
    use_take_profit?: boolean;
    take_profit_mode: TakeProfitMode;
    accept_reentries?: boolean;
    hard_stop: RiskSettings;
    take_profit: RiskSettings;
    partial_take_profits: PartialTakeProfit[];
    trailing_stop: TrailingStopSettings;
    max_drawdown_daily?: number;
    size_by_sl?: boolean;
}

export interface PostGapPrecondition {
    id: string;
    day: 'gap_day' | 'gap_1_day';
    metric: 'volume' | 'close_vs_open' | 'close_vs_high_low' | 'close_vs_pm_high' | 'close_vs_vwap' | 'close_vs_sma' | 'candle_range_pct';
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
    use_hard_stop: true,
    use_take_profit: true,
    take_profit_mode: TakeProfitMode.FULL,
    accept_reentries: true,
    hard_stop: { type: RiskType.PERCENTAGE, value: 2.0 },
    take_profit: { type: RiskType.PERCENTAGE, value: 6.0 },
    partial_take_profits: [
        { distance_pct: 3.0, capital_pct: 50.0 },
        { distance_pct: 6.0, capital_pct: 50.0 }
    ],
    trailing_stop: { active: false, type: "Percentage", buffer_pct: 0.5 },
    size_by_sl: false
};

export const initialExitLogic: ExitLogic = {
    timeframe: Timeframe.M1,
    root_condition: {
        type: "group",
        operator: "AND",
        conditions: []
    }
};
