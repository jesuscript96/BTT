import { IndicatorType } from '@/types/strategy';

// ─────────────────────────────────────────────────────────────
// Group definitions (internal, used by getAllowedTargets)
// ─────────────────────────────────────────────────────────────

const TREND_MA: IndicatorType[] = [
    IndicatorType.SMA, IndicatorType.EMA, IndicatorType.WMA,
    IndicatorType.VWAP, IndicatorType.VWAP_SD_PLUS, IndicatorType.VWAP_SD_MINUS,
    IndicatorType.LINEAR_REGRESSION, IndicatorType.ZIG_ZAG, IndicatorType.ICHIMOKU
];

const MOMENTUM: IndicatorType[] = [
    IndicatorType.RSI, IndicatorType.MACD, IndicatorType.STOCHASTIC,
    IndicatorType.MOMENTUM, IndicatorType.CCI, IndicatorType.ROC,
    IndicatorType.DMI_PLUS, IndicatorType.DMI_MINUS, IndicatorType.WILLIAMS_R
];

const VOLATILITY: IndicatorType[] = [
    IndicatorType.ATR, IndicatorType.ADX, IndicatorType.BOLLINGER_BANDS,
    IndicatorType.DONCHIAN, IndicatorType.PARABOLIC_SAR
];

const VOLUME: IndicatorType[] = [
    IndicatorType.OBV, IndicatorType.VOLUME, IndicatorType.RVOL,
    IndicatorType.AVOLUME, IndicatorType.SMA_VOLUME
];

const PRICE_VARIABLES: IndicatorType[] = [
    IndicatorType.BAR_CLOSE, IndicatorType.BAR_OPEN,
    IndicatorType.HIGH_BAR, IndicatorType.LOW_BAR,
    IndicatorType.PMH, IndicatorType.PML,
    IndicatorType.RTH_HIGH, IndicatorType.RTH_LOW, IndicatorType.RTH_OPEN,
    IndicatorType.Y_HIGH, IndicatorType.Y_LOW, IndicatorType.Y_OPEN, IndicatorType.Y_CLOSE,
    IndicatorType.MAX_X_DAYS, IndicatorType.MIN_X_DAYS
];

const BEHAVIOR_PATTERNS: IndicatorType[] = [
    IndicatorType.CONSECUTIVE_HIGHER_HIGHS, IndicatorType.CONSECUTIVE_LOWER_LOWS,
    IndicatorType.CONSECUTIVE_RED_CANDLES, IndicatorType.CONSECUTIVE_GREEN_CANDLES,
    IndicatorType.CONSECUTIVE_HIGHER_LOWS, IndicatorType.CONSECUTIVE_LOWER_HIGHS,
    IndicatorType.OPENING_RANGE_PLUS, IndicatorType.OPENING_RANGE_MINUS,
    IndicatorType.OPENING_RANGE_AM_PLUS, IndicatorType.OPENING_RANGE_AM_MINUS,
    IndicatorType.HEIKIN_ASHI
];

const TIME_AND_OTHERS: IndicatorType[] = [
    IndicatorType.TIME_OF_DAY, IndicatorType.RANGE_OF_TIME,
    IndicatorType.HIGH_LOW_FROM_TIME, IndicatorType.HIGH_LOW_FROM_HOUR_TIME,
    IndicatorType.RET_PCT_PM, IndicatorType.RET_PCT_RTH
];

// Consecutives-only subset (only Fixed Value as target)
const CONSECUTIVES: IndicatorType[] = [
    IndicatorType.CONSECUTIVE_HIGHER_HIGHS, IndicatorType.CONSECUTIVE_LOWER_LOWS,
    IndicatorType.CONSECUTIVE_RED_CANDLES, IndicatorType.CONSECUTIVE_GREEN_CANDLES,
    IndicatorType.CONSECUTIVE_HIGHER_LOWS, IndicatorType.CONSECUTIVE_LOWER_HIGHS
];

// Overlay-compatible: indicators that live on the price axis
const OVERLAY_TARGETS: IndicatorType[] = [
    ...TREND_MA,
    IndicatorType.BOLLINGER_BANDS, IndicatorType.DONCHIAN, IndicatorType.PARABOLIC_SAR,
    ...PRICE_VARIABLES
];

// ─────────────────────────────────────────────────────────────
// getAllowedTargets
// Returns the list of IndicatorTypes that can appear as "Target"
// when `source` is selected. An empty array means only Fixed Value.
// ─────────────────────────────────────────────────────────────

export function getAllowedTargets(source: IndicatorType, isDistance: boolean = false): IndicatorType[] {
    let allowed: IndicatorType[] = [];

    // ── Trend / MA ──────────────────────────────────────────
    if (TREND_MA.includes(source)) {
        allowed = [...OVERLAY_TARGETS];
    }

    // ── Momentum & Oscillators ──────────────────────────────
    // DMI+, DMI-, ADX can cross-compare
    else if (source === IndicatorType.DMI_PLUS) {
        allowed = [IndicatorType.DMI_MINUS, IndicatorType.ADX];
    }
    else if (source === IndicatorType.DMI_MINUS) {
        allowed = [IndicatorType.DMI_PLUS, IndicatorType.ADX];
    }
    else if (source === IndicatorType.ADX) {
        allowed = [IndicatorType.DMI_PLUS, IndicatorType.DMI_MINUS];
    }
    // All other momentum → only Fixed Value
    else if (MOMENTUM.includes(source)) {
        allowed = [];
    }

    // ── Volatility ──────────────────────────────────────────
    else if (source === IndicatorType.ATR) {
        allowed = []; // Only Fixed Value
    }
    else if (source === IndicatorType.BOLLINGER_BANDS || source === IndicatorType.DONCHIAN) {
        allowed = [...TREND_MA, IndicatorType.PARABOLIC_SAR, IndicatorType.BOLLINGER_BANDS, IndicatorType.DONCHIAN, ...PRICE_VARIABLES];
    }
    else if (source === IndicatorType.PARABOLIC_SAR) {
        allowed = [...TREND_MA, IndicatorType.BOLLINGER_BANDS, IndicatorType.DONCHIAN, IndicatorType.PARABOLIC_SAR, ...PRICE_VARIABLES];
    }

    // ── Volume ──────────────────────────────────────────────
    else if (source === IndicatorType.VOLUME) {
        allowed = [IndicatorType.SMA_VOLUME];
    }
    else if (source === IndicatorType.SMA_VOLUME) {
        allowed = [IndicatorType.VOLUME];
    }
    else if (VOLUME.includes(source)) {
        allowed = []; // OBV, RVOL, Accumulated Volume → only Fixed Value
    }

    // ── Consecutives → only Fixed Value ─────────────────────
    else if (CONSECUTIVES.includes(source)) {
        allowed = [];
    }

    // ── Time & Returns ──────────────────────────────────────
    else if (source === IndicatorType.TIME_OF_DAY || source === IndicatorType.RANGE_OF_TIME) {
        allowed = []; // Self-contained → only Fixed Value
    }
    else if (source === IndicatorType.RET_PCT_PM) {
        allowed = []; // Only Fixed Value
    }
    else if (source === IndicatorType.RET_PCT_RTH) {
        allowed = [IndicatorType.RET_PCT_PM];
    }
    else if (source === IndicatorType.HIGH_LOW_FROM_TIME || source === IndicatorType.HIGH_LOW_FROM_HOUR_TIME) {
        allowed = [...TREND_MA, ...PRICE_VARIABLES];
    }

    // ── Behavior (Opening Range, Heikin-Ashi) ───────────────
    else if (source === IndicatorType.HEIKIN_ASHI) {
        allowed = [...TREND_MA, ...PRICE_VARIABLES];
    }
    else if ([
        IndicatorType.OPENING_RANGE_PLUS, IndicatorType.OPENING_RANGE_MINUS,
        IndicatorType.OPENING_RANGE_AM_PLUS, IndicatorType.OPENING_RANGE_AM_MINUS
    ].includes(source)) {
        allowed = [...OVERLAY_TARGETS];
    }

    // ── Price Variables (Bar Close, PMH, Y_High, Max X Days, etc.) ─
    else if (PRICE_VARIABLES.includes(source)) {
        allowed = [...OVERLAY_TARGETS];
    }

    // ── Fallback ────────────────────────────────────────────
    else {
        allowed = [];
    }

    // ── Distance exclusions ─────────────────────────────────
    if (isDistance) {
        const DISTANCE_EXCLUDE: IndicatorType[] = [
            ...MOMENTUM, ...VOLUME, ...TIME_AND_OTHERS,
            IndicatorType.ATR, IndicatorType.ADX,
            IndicatorType.HEIKIN_ASHI, ...CONSECUTIVES
        ];
        allowed = allowed.filter(a => !DISTANCE_EXCLUDE.includes(a));
    }

    // Always remove the source itself (can't compare X vs X without params difference)
    // Actually some indicators CAN compare to themselves (e.g. SMA(20) vs SMA(50))
    // so we keep self-references for parameterized indicators

    return allowed;
}

// ─────────────────────────────────────────────────────────────
// DISTANCE_SOURCE_EXCLUDES
// Indicators that CANNOT be used as source in a Distance condition
// ─────────────────────────────────────────────────────────────

export const DISTANCE_SOURCE_EXCLUDES: IndicatorType[] = [
    ...MOMENTUM, ...VOLUME, ...TIME_AND_OTHERS,
    IndicatorType.ATR, IndicatorType.ADX,
    IndicatorType.HEIKIN_ASHI, ...CONSECUTIVES
];
