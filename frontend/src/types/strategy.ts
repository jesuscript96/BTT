
// Enums
export enum IndicatorType {
    // Trend / MA
    SMA = "SMA",
    EMA = "EMA",
    WMA = "WMA",
    VWAP = "VWAP",
    AVWAP = "AVWAP",
    LINEAR_REGRESSION = "Linear Regression",
    ZIG_ZAG = "Zig Zag",
    ICHIMOKU = "Ichimoku Clouds",

    // Momentum
    RSI = "RSI",
    MACD = "MACD",
    STOCHASTIC = "Stochastic",
    MOMENTUM = "Momentum",
    CCI = "CCI",
    ROC = "ROC",
    DMI = "DMI",
    WILLIAMS_R = "Williams %R",

    // Volatility
    ATR = "ATR",
    ADX = "ADX",
    BOLLINGER_BANDS = "Bollinger Bands",
    PARABOLIC_SAR = "Parabolic SAR",
    MEDAUGH_SHADING = "Medaugh Shading",

    // Volume
    OBV = "OBV",
    VAD = "VAD",
    CMF = "CMF",
    ACC_DIST = "Acc/Dist",
    VOLUME = "Volume",
    RVOL = "RVOL",
    AVOLUME = "Accumulated Volume",

    // Price Variables
    CLOSE = "Close",
    OPEN = "Open",
    HIGH = "High",
    LOW = "Low",
    PMH = "Pre-Market High",
    PML = "Pre-Market Low",
    HOD = "High of Day",
    LOD = "Low of Day",
    Y_HIGH = "Yesterday High",
    Y_LOW = "Yesterday Low",
    Y_OPEN = "Yesterday Open",
    Y_CLOSE = "Yesterday Close",
    MAX_X_DAYS = "Max of last X days",
    MIN_X_DAYS = "Min of last X days",
    CURRENT_OPEN = "Current Open",
    BAR_OPEN = "Bar Open",
    DAY_OPEN = "Day Open",
    PREV_CLOSE = "Previous Close",

    // Behavior Variables
    CONSECUTIVE_HIGHER_HIGHS = "Consecutive Higher Highs",
    CONSECUTIVE_LOWER_LOWS = "Consecutive Lower Lows",
    CONSECUTIVE_RED_CANDLES = "Consecutive Red Candles",
    CONSECUTIVE_GREEN_CANDLES = "Consecutive Green Candles",
    OPENING_RANGE = "Opening Range",
    HEIKIN_ASHI = "Heikin-Ashi",
    HA_OPEN = "HA Open",
    HA_HIGH = "HA High",
    HA_LOW = "HA Low",
    HA_CLOSE = "HA Close",

    // Time / Others
    TIME_OF_DAY = "Time of Day",
    PIVOT_POINTS = "Pivot Points",

    // Existing / Retained Returns
    RET_PCT_PM = "Ret % PM",
    RET_PCT_RTH = "Ret % RTH",
    RET_PCT_AM = "Ret % AM",
    MAX_N_BARS = "Max N Bars",
    CUSTOM = "Custom"
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

export enum CandlePattern {
    RV = "RED_VOLUME",
    RV_PLUS = "RED_VOLUME_PLUS",
    GV = "GREEN_VOLUME",
    GV_PLUS = "GREEN_VOLUME_PLUS",
    DOJI = "DOJI",
    HAMMER = "HAMMER",
    SHOOTING_STAR = "SHOOTING_STAR"
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

export interface CandleCondition {
    type: "candle_pattern";
    pattern: CandlePattern;
    lookback: number;
    consecutive_count: number;
    timeframe?: Timeframe;
    calc_on_heikin?: boolean;
}

export type AnyCondition = ComparisonCondition | PriceLevelDistanceCondition | CandleCondition;

// Recursive Logical Group
export interface ConditionGroup {
    type: "group";
    operator: "AND" | "OR";
    conditions: (ConditionGroup | AnyCondition)[];
}

export interface EntryLogic {
    timeframe: Timeframe;
    root_condition: ConditionGroup;
}

export interface ExitLogic {
    timeframe: Timeframe;
    root_condition: ConditionGroup;
}

export interface RiskSettings {
    type: RiskType;
    value: number;
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
}

export interface Strategy {
    id?: string;
    name: string;
    description?: string;
    bias: 'long' | 'short';
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
    trailing_stop: { active: false, type: "Percentage", buffer_pct: 0.5 }
};

export const initialExitLogic: ExitLogic = {
    timeframe: Timeframe.M1,
    root_condition: {
        type: "group",
        operator: "AND",
        conditions: []
    }
};
