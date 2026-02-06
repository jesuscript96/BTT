// Enum definitions matching Backend
export enum IndicatorType {
    RVOL = "RVOL",
    EXTENSION = "Parabolic Extension",
    FFT = "Failed Follow Through",
    SPREAD = "Spread Expansion",
    IMBALANCE = "Large Order Imbalance",
    RED_BARS = "Consecutive Red Bars",
    TIME_OF_DAY = "Time of Day",
    RELATIVE_STRENGTH = "Relative Strength",
    PRICE = "Price",
    VWAP = "VWAP",
    CUSTOM = "Custom"
}

export enum Operator {
    GT = ">",
    LT = "<",
    EQ = "==",
    GTE = ">=",
    LTE = "<="
}

export enum RiskType {
    FIXED = "Fixed Price",
    PERCENT = "Percent",
    ATR = "ATR Multiplier",
    STRUCTURE = "Market Structure"
}

// Interfaces
export interface FilterSettings {
    min_market_cap?: number;
    max_market_cap?: number;
    max_shares_float?: number;
    require_shortable: boolean;
    exclude_dilution: boolean;
}

export interface Condition {
    id: string;
    indicator: IndicatorType;
    operator: Operator;
    value: number | string;
    compare_to?: string;
}

export interface ConditionGroup {
    id: string;
    conditions: Condition[];
    logic: "AND" | "OR";
}

export interface ExitLogic {
    stop_loss_type: RiskType;
    stop_loss_value: number;
    take_profit_type: RiskType;
    take_profit_value: number;
    trailing_stop_active: boolean;
    trailing_stop_type?: string;
    dilution_profit_boost: boolean;
}

export interface Strategy {
    id?: string;
    name: string;
    description?: string;
    filters: FilterSettings;
    entry_logic: ConditionGroup[];
    exit_logic: ExitLogic;
    created_at?: string;
}

// Default Initial State
export const initialFilterSettings: FilterSettings = {
    require_shortable: true,
    exclude_dilution: true
};

export const initialExitLogic: ExitLogic = {
    stop_loss_type: RiskType.PERCENT,
    stop_loss_value: 5,
    take_profit_type: RiskType.PERCENT,
    take_profit_value: 15,
    trailing_stop_active: false,
    dilution_profit_boost: false
};
