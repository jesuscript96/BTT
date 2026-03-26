import { IndicatorType, Comparator } from '@/types/strategy';

// Helpers identifying groups
const TREND_MA = [
    IndicatorType.SMA, IndicatorType.EMA, IndicatorType.WMA,
    IndicatorType.VWAP, IndicatorType.AVWAP, IndicatorType.LINEAR_REGRESSION,
    IndicatorType.ZIG_ZAG, IndicatorType.ICHIMOKU
];

const MOMENTUM = [
    IndicatorType.RSI, IndicatorType.MACD, IndicatorType.STOCHASTIC,
    IndicatorType.MOMENTUM, IndicatorType.CCI, IndicatorType.ROC,
    IndicatorType.DMI_PLUS, IndicatorType.DMI_MINUS, IndicatorType.WILLIAMS_R
];

const VOLATILITY = [
    IndicatorType.ATR, IndicatorType.ADX, IndicatorType.BOLLINGER_BANDS,
    IndicatorType.DONCHIAN, IndicatorType.PARABOLIC_SAR
];

const VOLUME = [
    IndicatorType.OBV, IndicatorType.CMF, IndicatorType.ACC_DIST,
    IndicatorType.VOLUME, IndicatorType.RVOL, IndicatorType.AVOLUME
];

const BEHAVIOUR_AND_PRICE = [
    IndicatorType.BAR_CLOSE, IndicatorType.BAR_OPEN, IndicatorType.HIGH_BAR, IndicatorType.LOW_BAR,
    IndicatorType.PMH, IndicatorType.PML, IndicatorType.RTH_HIGH, IndicatorType.RTH_LOW,
    IndicatorType.RTH_OPEN, IndicatorType.Y_HIGH, IndicatorType.Y_LOW, IndicatorType.Y_OPEN,
    IndicatorType.Y_CLOSE, IndicatorType.MAX_X_DAYS, IndicatorType.MIN_X_DAYS,
    IndicatorType.OPENING_RANGE_PLUS, IndicatorType.OPENING_RANGE_MINUS,
    IndicatorType.OPENING_RANGE_AM_PLUS, IndicatorType.OPENING_RANGE_AM_MINUS,
    IndicatorType.HEIKIN_ASHI
];

const TIME_AND_OTHERS = [
    IndicatorType.TIME_OF_DAY, IndicatorType.RANGE_OF_TIME,
    IndicatorType.HIGH_LOW_FROM_TIME, IndicatorType.HIGH_LOW_FROM_HOUR_TIME,
    IndicatorType.RET_PCT_PM, IndicatorType.RET_PCT_RTH
];

export const ALL_INDICATORS = [
    ...TREND_MA,
    ...MOMENTUM,
    ...VOLATILITY,
    ...VOLUME,
    ...BEHAVIOUR_AND_PRICE,
    ...TIME_AND_OTHERS,
    ...[
        IndicatorType.CONSECUTIVE_HIGHER_HIGHS, IndicatorType.CONSECUTIVE_LOWER_LOWS,
        IndicatorType.CONSECUTIVE_GREEN_CANDLES, IndicatorType.CONSECUTIVE_RED_CANDLES,
        IndicatorType.CONSECUTIVE_HIGHER_LOWS, IndicatorType.CONSECUTIVE_LOWER_HIGHS
    ]
];

export function getAllowedTargets(source: IndicatorType, isDistance: boolean = false): IndicatorType[] {
    let allowed: IndicatorType[] = [];

    // Base Group A: Overlays (Trend MA)
    if (TREND_MA.includes(source)) {
        // Only themselves + Parabolic SAR and Bollinger Bands
        allowed = [...TREND_MA, IndicatorType.PARABOLIC_SAR, IndicatorType.BOLLINGER_BANDS, IndicatorType.DONCHIAN /* Donchian acts like BB */];
    }
    // Momentum & Oscillators
    else if (source === IndicatorType.DMI_PLUS || source === IndicatorType.DMI_MINUS) {
        allowed = [...MOMENTUM];
    } else if (MOMENTUM.includes(source)) {
        // All others only against themselves
        allowed = [source];
    }
    // Volatility
    else if (source === IndicatorType.ATR || source === IndicatorType.ADX) {
        allowed = [source];
    } else if (source === IndicatorType.BOLLINGER_BANDS || source === IndicatorType.DONCHIAN) {
        allowed = [IndicatorType.BOLLINGER_BANDS, IndicatorType.DONCHIAN, IndicatorType.PARABOLIC_SAR, ...TREND_MA];
    } else if (source === IndicatorType.PARABOLIC_SAR) {
        allowed = [...TREND_MA, IndicatorType.PARABOLIC_SAR, IndicatorType.BOLLINGER_BANDS, IndicatorType.DONCHIAN];
    }
    // Volume
    else if (VOLUME.includes(source)) {
        allowed = [source];
    }
    // Consecutives (Only Fixed Value supported, so return empty)
    else if ([
        IndicatorType.CONSECUTIVE_HIGHER_HIGHS, IndicatorType.CONSECUTIVE_LOWER_LOWS,
        IndicatorType.CONSECUTIVE_GREEN_CANDLES, IndicatorType.CONSECUTIVE_RED_CANDLES,
        IndicatorType.CONSECUTIVE_HIGHER_LOWS, IndicatorType.CONSECUTIVE_LOWER_HIGHS
    ].includes(source)) {
        allowed = [];
    }
    // Time & Returns
    else if (source === IndicatorType.TIME_OF_DAY || source === IndicatorType.RANGE_OF_TIME) {
        allowed = [];
    } else if (source === IndicatorType.RET_PCT_PM) {
        allowed = [source];
    } else if (source === IndicatorType.RET_PCT_RTH) {
        allowed = [source, IndicatorType.RET_PCT_PM];
    }
    // Remaining Behaviour & Price Variables
    else {
        // "No contra Momentum, Volume o Time"
        allowed = ALL_INDICATORS.filter(ind => 
            !MOMENTUM.includes(ind) && 
            !VOLUME.includes(ind) && 
            !TIME_AND_OTHERS.includes(ind)
        );
        
        // Handle distance specifics for Yesterday/MaxMin
        if (isDistance && [
            IndicatorType.Y_HIGH, IndicatorType.Y_LOW, IndicatorType.Y_OPEN, IndicatorType.Y_CLOSE,
            IndicatorType.MAX_X_DAYS, IndicatorType.MIN_X_DAYS
        ].includes(source)) {
            allowed = allowed.filter(ind => !BEHAVIOUR_AND_PRICE.includes(ind));
        }
    }

    // Distance Condition Exclusion
    if (isDistance) {
        // Many oscillators/volume are excluded from being either source or target in Distance.
        const DISTANCE_EXCLUDE = [
            ...MOMENTUM, ...VOLUME, ...TIME_AND_OTHERS,
            IndicatorType.ATR, IndicatorType.ADX,
            IndicatorType.HEIKIN_ASHI
        ];
        allowed = allowed.filter(a => !DISTANCE_EXCLUDE.includes(a));
    }

    return allowed;
}

export const DISTANCE_SOURCE_EXCLUDES = [
    ...MOMENTUM, ...VOLUME, ...TIME_AND_OTHERS,
    IndicatorType.ATR, IndicatorType.ADX,
    IndicatorType.HEIKIN_ASHI
];
