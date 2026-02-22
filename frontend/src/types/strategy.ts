
// Enums
export enum IndicatorType {
    SMA = "SMA",
    EMA = "EMA",
    WMA = "WMA",
    RVOL = "RVOL",
    VWAP = "VWAP",
    AVWAP = "AVWAP",
    RSI = "RSI",
    MACD = "MACD",
    ATR = "ATR",
    ADX = "ADX",
    WILLIAMS_R = "Williams %R",
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
    Y_CLOSE = "Yesterday Close",
    VOLUME = "Volume",
    AVOLUME = "Accumulated Volume",
    CONSECUTIVE_RED_CANDLES = "Consecutive Red Candles",
    CONSECUTIVE_HIGHER_HIGHS = "Consecutive Higher Highs",
    CONSECUTIVE_LOWER_LOWS = "Consecutive Lower Lows",
    RET_PCT_PM = "Ret % PM",
    RET_PCT_RTH = "Ret % RTH",
    RET_PCT_AM = "Ret % AM",
    TIME_OF_DAY = "Time of Day",
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
    multiplier?: number;
    offset?: number;
    overbought?: number;
    oversold?: number;
    consecutive_count?: number;
    time_hour?: number;
    time_minute?: number;
}

export interface ComparisonCondition {
    type: "indicator_comparison";
    source: IndicatorConfig;
    comparator: Comparator;
    target: IndicatorConfig | number;
}

export interface PriceLevelCondition {
    type: "price_level_distance";
    source: "Close" | "High" | "Low";
    level: IndicatorType;
    comparator: "DISTANCE_GT" | "DISTANCE_LT";
    value_pct: number;
}

export interface CandleCondition {
    type: "candle_pattern";
    pattern: CandlePattern;
    lookback: number;
    consecutive_count: number;
}

export type AnyCondition = ComparisonCondition | PriceLevelCondition | CandleCondition;

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

export interface TrailingStopSettings {
    active: boolean;
    type: string;
    buffer_pct: number;
}

export interface RiskManagement {
    use_hard_stop?: boolean;
    use_take_profit?: boolean;
    hard_stop: RiskSettings;
    take_profit: RiskSettings;
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
    hard_stop: { type: RiskType.PERCENTAGE, value: 2.0 },
    take_profit: { type: RiskType.PERCENTAGE, value: 6.0 },
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
