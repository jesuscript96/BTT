import { IndicatorType } from '@/types/strategy';

// ─── GRUPOS DE TARGETS ───────────────────────────────

const ALL_PRICE_VARIABLES = [
    IndicatorType.BAR_CLOSE, IndicatorType.BAR_OPEN,
    IndicatorType.HIGH_BAR, IndicatorType.LOW_BAR,
    IndicatorType.PM_OPEN, IndicatorType.PM_HIGH, IndicatorType.PM_LOW,
    IndicatorType.RTH_OPEN, IndicatorType.RTH_HIGH, IndicatorType.RTH_LOW,
    IndicatorType.AM_OPEN,
    IndicatorType.PREVIOUS_MAX, IndicatorType.PREVIOUS_MIN,
    IndicatorType.YESTERDAY_OPEN, IndicatorType.YESTERDAY_CLOSE,
    IndicatorType.YESTERDAY_HIGH, IndicatorType.YESTERDAY_LOW,

    IndicatorType.HIGH_X_DAYS, IndicatorType.LOW_X_DAYS,
];

const ALL_BEHAVIOUR = [
    IndicatorType.OPENING_RANGE_PLUS, IndicatorType.OPENING_RANGE_MINUS,
    IndicatorType.OPENING_RANGE_AM_PLUS, IndicatorType.OPENING_RANGE_AM_MINUS,
];

const ALL_INDICATORS = [
    IndicatorType.SMA, IndicatorType.EMA, IndicatorType.VWAP,
    IndicatorType.DONCHIAN, IndicatorType.BOLLINGER_BANDS,
];

const YESTERDAY_VARS = [
    IndicatorType.YESTERDAY_OPEN, IndicatorType.YESTERDAY_CLOSE,
    IndicatorType.YESTERDAY_HIGH, IndicatorType.YESTERDAY_LOW,
    IndicatorType.HIGH_X_DAYS, IndicatorType.LOW_X_DAYS,
];

const PM_RTH_YESTERDAY = [
    IndicatorType.RTH_OPEN, IndicatorType.RTH_HIGH,
    IndicatorType.AM_OPEN,
    IndicatorType.YESTERDAY_OPEN, IndicatorType.YESTERDAY_CLOSE,
    IndicatorType.YESTERDAY_HIGH, IndicatorType.YESTERDAY_LOW,

    IndicatorType.HIGH_X_DAYS, IndicatorType.LOW_X_DAYS,
];

const RTH_YESTERDAY_INDICATORS = [
    IndicatorType.PM_OPEN, IndicatorType.PM_HIGH, IndicatorType.PM_LOW,
    IndicatorType.YESTERDAY_OPEN, IndicatorType.YESTERDAY_CLOSE,
    IndicatorType.YESTERDAY_HIGH, IndicatorType.YESTERDAY_LOW,

    IndicatorType.HIGH_X_DAYS, IndicatorType.LOW_X_DAYS,
    ...ALL_INDICATORS,
];

// ─── INDICADOR DE CRUCE — TARGETS POR SOURCE ─────────

export const INDICATOR_TARGETS: Record<IndicatorType, IndicatorType[]> = {
    // Price Variables — Full
    [IndicatorType.BAR_CLOSE]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.BAR_OPEN]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.HIGH_BAR]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.LOW_BAR]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],

    // PM variables
    [IndicatorType.PM_OPEN]: [...YESTERDAY_VARS],
    [IndicatorType.PM_HIGH]: [...PM_RTH_YESTERDAY, ...ALL_BEHAVIOUR],
    [IndicatorType.PM_LOW]: [...PM_RTH_YESTERDAY, ...ALL_BEHAVIOUR],

    // RTH variables
    [IndicatorType.RTH_OPEN]: [...RTH_YESTERDAY_INDICATORS],
    [IndicatorType.RTH_HIGH]: [...RTH_YESTERDAY_INDICATORS],
    [IndicatorType.RTH_LOW]: [...RTH_YESTERDAY_INDICATORS],

    // AM Open
    [IndicatorType.AM_OPEN]: [
        IndicatorType.PM_OPEN, IndicatorType.PM_HIGH, IndicatorType.PM_LOW,
        IndicatorType.RTH_OPEN, IndicatorType.RTH_HIGH, IndicatorType.RTH_LOW,
        IndicatorType.YESTERDAY_OPEN, IndicatorType.YESTERDAY_CLOSE,
        IndicatorType.YESTERDAY_HIGH, IndicatorType.YESTERDAY_LOW,
    
        IndicatorType.HIGH_X_DAYS, IndicatorType.LOW_X_DAYS,
        ...ALL_INDICATORS,
    ],

    // Solo aparecen como targets, no como source con cruces
    [IndicatorType.PREVIOUS_MAX]: [],
    [IndicatorType.PREVIOUS_MIN]: [],
    [IndicatorType.YESTERDAY_OPEN]: [],
    [IndicatorType.YESTERDAY_CLOSE]: [],
    [IndicatorType.YESTERDAY_HIGH]: [],
    [IndicatorType.YESTERDAY_LOW]: [],
    [IndicatorType.HIGH_X_DAYS]: [],
    [IndicatorType.LOW_X_DAYS]: [],

    // Behaviour & Patterns — standalone (sin cruces)
    [IndicatorType.CONSEC_HIGHER_HIGHS]: [],
    [IndicatorType.CONSEC_LOWER_LOWS]: [],
    [IndicatorType.CONSEC_LOWER_HIGHS]: [],
    [IndicatorType.CONSEC_HIGHER_LOWS]: [],
    [IndicatorType.CONSEC_GREEN_CANDLES]: [],
    [IndicatorType.CONSEC_RED_CANDLES]: [],
    [IndicatorType.CANDLE_RANGE_PCT]: [],
    [IndicatorType.RANGE_OF_TIME]: [],
    [IndicatorType.OPENING_RANGE_PLUS]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.OPENING_RANGE_MINUS]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.OPENING_RANGE_AM_PLUS]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.OPENING_RANGE_AM_MINUS]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.ELAPSED_TIME_LAST_HIGH]: [],

    // Indicators — Full
    [IndicatorType.SMA]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.EMA]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.VWAP]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.DONCHIAN]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.BOLLINGER_BANDS]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],

    // Volume — standalone o valor fijo
    [IndicatorType.ACCUMULATED_VOLUME]: [],
    [IndicatorType.YESTERDAY_VOLUME]: [],
    [IndicatorType.RVOL]: [],
    [IndicatorType.VOLUME]: [IndicatorType.VOLUME],
    [IndicatorType.ATR]: [IndicatorType.ATR],
};

// ─── INDICADOR DE DISTANCIA — TARGETS POR SOURCE ─────

export const DISTANCE_TARGETS: Record<string, IndicatorType[]> = {
    [IndicatorType.BAR_CLOSE]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.BAR_OPEN]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.HIGH_BAR]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.LOW_BAR]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.PM_HIGH]: [...PM_RTH_YESTERDAY, ...ALL_BEHAVIOUR],
    [IndicatorType.PM_LOW]: [...PM_RTH_YESTERDAY, ...ALL_BEHAVIOUR],
    [IndicatorType.RTH_OPEN]: [...RTH_YESTERDAY_INDICATORS],
    [IndicatorType.RTH_HIGH]: [...RTH_YESTERDAY_INDICATORS],
    [IndicatorType.RTH_LOW]: [...RTH_YESTERDAY_INDICATORS],
    [IndicatorType.AM_OPEN]: [
        IndicatorType.PM_OPEN, IndicatorType.PM_HIGH, IndicatorType.PM_LOW,
        IndicatorType.RTH_OPEN, IndicatorType.RTH_HIGH, IndicatorType.RTH_LOW,
        IndicatorType.YESTERDAY_OPEN, IndicatorType.YESTERDAY_CLOSE,
        IndicatorType.YESTERDAY_HIGH, IndicatorType.YESTERDAY_LOW,
    
        IndicatorType.HIGH_X_DAYS, IndicatorType.LOW_X_DAYS,
        ...ALL_INDICATORS,
    ],
    [IndicatorType.PREVIOUS_MAX]: [
        IndicatorType.BAR_CLOSE, IndicatorType.BAR_OPEN,
        IndicatorType.HIGH_BAR, IndicatorType.LOW_BAR,
        IndicatorType.PM_OPEN, IndicatorType.PREVIOUS_MIN,
        IndicatorType.YESTERDAY_OPEN, IndicatorType.YESTERDAY_CLOSE,
        IndicatorType.YESTERDAY_HIGH, IndicatorType.YESTERDAY_LOW,
    
        IndicatorType.HIGH_X_DAYS, IndicatorType.LOW_X_DAYS,
        IndicatorType.VWAP,
    ],
    [IndicatorType.PREVIOUS_MIN]: [
        IndicatorType.BAR_CLOSE, IndicatorType.BAR_OPEN,
        IndicatorType.HIGH_BAR, IndicatorType.LOW_BAR,
        IndicatorType.PM_OPEN, IndicatorType.PREVIOUS_MIN,
        IndicatorType.YESTERDAY_OPEN, IndicatorType.YESTERDAY_CLOSE,
        IndicatorType.YESTERDAY_HIGH, IndicatorType.YESTERDAY_LOW,
    
        IndicatorType.HIGH_X_DAYS, IndicatorType.LOW_X_DAYS,
        IndicatorType.VWAP,
    ],
    [IndicatorType.SMA]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.EMA]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.VWAP]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.DONCHIAN]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.BOLLINGER_BANDS]: [...ALL_PRICE_VARIABLES, ...ALL_BEHAVIOUR, ...ALL_INDICATORS],
    [IndicatorType.ATR]: [IndicatorType.ATR],
};

// ─── HELPERS ─────────────────────────────────────────

export function getAllowedTargets(
    sourceIndicator: IndicatorType,
    conditionType: "indicator_comparison" | "price_level_distance"
): IndicatorType[] {
    if (conditionType === "price_level_distance") {
        return DISTANCE_TARGETS[sourceIndicator] ?? [];
    }
    return INDICATOR_TARGETS[sourceIndicator] ?? [];
}

export function isStandalone(indicator: IndicatorType): boolean {
    return (INDICATOR_TARGETS[indicator] ?? []).length === 0;
}

const ONLY_TARGET_INDICATORS = new Set([
    IndicatorType.YESTERDAY_OPEN, IndicatorType.YESTERDAY_CLOSE,
    IndicatorType.YESTERDAY_HIGH, IndicatorType.YESTERDAY_LOW,

    IndicatorType.HIGH_X_DAYS, IndicatorType.LOW_X_DAYS,
]);

export function isOnlyTarget(indicator: IndicatorType): boolean {
    return ONLY_TARGET_INDICATORS.has(indicator);
}

export function getSourceIndicators(): IndicatorType[] {
    return Object.values(IndicatorType).filter(
        ind => !isOnlyTarget(ind)
    );
}
