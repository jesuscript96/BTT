import React from 'react';
import {
    ConditionGroup,
    AnyCondition,
    IndicatorType,
    Comparator,
    CandlePattern,
    IndicatorConfig,
    Timeframe
} from '@/types/strategy';
import { Plus, Trash2, GitBranch, Clock } from 'lucide-react';

// ----------------------------------------------------------------------
// Constants & Helpers
// ----------------------------------------------------------------------

// Indicators that should NOT be in the distance condition dropdowns (oscillators, volume, etc)
const DISTANCE_CONDITION_EXCLUDES = [
    IndicatorType.RSI, IndicatorType.STOCHASTIC, IndicatorType.MOMENTUM,
    IndicatorType.CCI, IndicatorType.ROC, IndicatorType.DMI,
    IndicatorType.WILLIAMS_R, IndicatorType.ATR, IndicatorType.ADX,
    IndicatorType.OBV, IndicatorType.VAD, IndicatorType.ACC_DIST,
    IndicatorType.VOLUME, IndicatorType.RVOL, IndicatorType.AVOLUME,
    IndicatorType.HEIKIN_ASHI, IndicatorType.HA_OPEN, IndicatorType.HA_HIGH,
    IndicatorType.HA_LOW, IndicatorType.HA_CLOSE
];

// Indicators that often need a generic "period" as default fallback 
const getDefaultParamsForIndicator = (name: IndicatorType): Partial<IndicatorConfig> => {
    switch (name) {
        case IndicatorType.SMA:
        case IndicatorType.EMA:
        case IndicatorType.WMA:
        case IndicatorType.RSI:
        case IndicatorType.ATR:
        case IndicatorType.ADX:
        case IndicatorType.WILLIAMS_R:
        case IndicatorType.MOMENTUM:
        case IndicatorType.ROC:
        case IndicatorType.MAX_N_BARS:
            return { period: 14 };
        case IndicatorType.BOLLINGER_BANDS:
            return { period: 20, stdDev: 2 };
        case IndicatorType.MACD:
            return { period: 12, period2: 26, period3: 9 };
        case IndicatorType.STOCHASTIC:
            return { period: 14, period2: 3, period3: 3 };
        case IndicatorType.ICHIMOKU:
            return { period: 9, period2: 26, period3: 52 };
        case IndicatorType.MIN_X_DAYS:
        case IndicatorType.MAX_X_DAYS:
            return { days_lookback: 5 };
        case IndicatorType.TIME_OF_DAY:
            return { time_condition: "AFTER", time_hour: 9, time_minute: 30 };
        default:
            return {};
    }
};

// Indicator Categories
const INDICATOR_CATEGORIES = {
    "Trend & Moving Averages": [
        IndicatorType.SMA, IndicatorType.EMA, IndicatorType.WMA,
        IndicatorType.VWAP, IndicatorType.AVWAP, IndicatorType.LINEAR_REGRESSION,
        IndicatorType.ZIG_ZAG, IndicatorType.ICHIMOKU
    ],
    "Momentum & Oscillators": [
        IndicatorType.RSI, IndicatorType.MACD, IndicatorType.STOCHASTIC,
        IndicatorType.MOMENTUM, IndicatorType.CCI, IndicatorType.ROC,
        IndicatorType.DMI, IndicatorType.WILLIAMS_R
    ],
    "Volatility": [
        IndicatorType.ATR, IndicatorType.ADX, IndicatorType.BOLLINGER_BANDS,
        IndicatorType.PARABOLIC_SAR, IndicatorType.MEDAUGH_SHADING
    ],
    "Volume": [
        IndicatorType.OBV, IndicatorType.VAD, IndicatorType.CMF,
        IndicatorType.ACC_DIST, IndicatorType.VOLUME, IndicatorType.RVOL,
        IndicatorType.AVOLUME
    ],
    "Price Variables": [
        IndicatorType.CLOSE, IndicatorType.OPEN, IndicatorType.HIGH,
        IndicatorType.LOW, IndicatorType.PMH, IndicatorType.PML,
        IndicatorType.HOD, IndicatorType.LOD, IndicatorType.Y_HIGH,
        IndicatorType.Y_LOW, IndicatorType.Y_OPEN, IndicatorType.Y_CLOSE,
        IndicatorType.MAX_X_DAYS, IndicatorType.MIN_X_DAYS,
        IndicatorType.CURRENT_OPEN, IndicatorType.BAR_OPEN, IndicatorType.DAY_OPEN, IndicatorType.PREV_CLOSE
    ],
    "Behavior & Patterns": [
        IndicatorType.CONSECUTIVE_HIGHER_HIGHS, IndicatorType.CONSECUTIVE_LOWER_LOWS,
        IndicatorType.CONSECUTIVE_GREEN_CANDLES, IndicatorType.CONSECUTIVE_RED_CANDLES,
        IndicatorType.OPENING_RANGE, IndicatorType.HEIKIN_ASHI,
        IndicatorType.HA_CLOSE, IndicatorType.HA_HIGH, IndicatorType.HA_LOW, IndicatorType.HA_OPEN
    ],
    "Time & Others": [
        IndicatorType.TIME_OF_DAY, IndicatorType.PIVOT_POINTS,
        IndicatorType.RET_PCT_PM, IndicatorType.RET_PCT_RTH, IndicatorType.RET_PCT_AM,
        IndicatorType.MAX_N_BARS, IndicatorType.CUSTOM
    ]
};

// Human-readable labels for comparators using symbols
const COMPARATOR_LABELS: Record<string, string> = {
    [Comparator.GT]: ">",
    [Comparator.LT]: "<",
    [Comparator.GTE]: "≥",
    [Comparator.LTE]: "≤",
    [Comparator.EQ]: "=",
    [Comparator.CROSSES_ABOVE]: "↗ Crosses Above",
    [Comparator.CROSSES_BELOW]: "↘ Crosses Below",
};

// Human-readable labels for indicators
const INDICATOR_LABELS: Record<string, string> = {
    // Trend
    [IndicatorType.SMA]: "SMA",
    [IndicatorType.EMA]: "EMA",
    [IndicatorType.WMA]: "WMA",
    [IndicatorType.VWAP]: "VWAP",
    [IndicatorType.AVWAP]: "AVWAP (Anchored)",
    [IndicatorType.LINEAR_REGRESSION]: "Linear Regression",
    [IndicatorType.ZIG_ZAG]: "Zig Zag",
    [IndicatorType.ICHIMOKU]: "Ichimoku Clouds",
    // Momentum
    [IndicatorType.RSI]: "RSI",
    [IndicatorType.MACD]: "MACD",
    [IndicatorType.STOCHASTIC]: "Stochastic",
    [IndicatorType.MOMENTUM]: "Momentum",
    [IndicatorType.CCI]: "CCI",
    [IndicatorType.ROC]: "ROC",
    [IndicatorType.DMI]: "DMI",
    [IndicatorType.WILLIAMS_R]: "Williams %R",
    // Volatility
    [IndicatorType.ATR]: "ATR",
    [IndicatorType.ADX]: "ADX",
    [IndicatorType.BOLLINGER_BANDS]: "Bollinger Bands",
    [IndicatorType.PARABOLIC_SAR]: "Parabolic SAR",
    [IndicatorType.MEDAUGH_SHADING]: "Medaugh Shading",
    // Volume
    [IndicatorType.OBV]: "On-Balance Volume (OBV)",
    [IndicatorType.VAD]: "Vol Accum/Distribution",
    [IndicatorType.CMF]: "Chaikin Money Flow",
    [IndicatorType.ACC_DIST]: "Accumulation/Distribution",
    [IndicatorType.VOLUME]: "Volume",
    [IndicatorType.RVOL]: "RVOL",
    [IndicatorType.AVOLUME]: "Accumulated Volume",
    // Variables
    [IndicatorType.CLOSE]: "Close",
    [IndicatorType.OPEN]: "Open",
    [IndicatorType.HIGH]: "High",
    [IndicatorType.LOW]: "Low",
    [IndicatorType.PMH]: "PM High",
    [IndicatorType.PML]: "PM Low",
    [IndicatorType.HOD]: "HOD",
    [IndicatorType.LOD]: "LOD",
    [IndicatorType.Y_HIGH]: "Yesterday High",
    [IndicatorType.Y_LOW]: "Yesterday Low",
    [IndicatorType.Y_OPEN]: "Yesterday Open",
    [IndicatorType.Y_CLOSE]: "Yesterday Close",
    [IndicatorType.MAX_X_DAYS]: "Max of last X days",
    [IndicatorType.MIN_X_DAYS]: "Min of last X days",
    [IndicatorType.CURRENT_OPEN]: "Current Open",
    [IndicatorType.BAR_OPEN]: "Bar Open",
    [IndicatorType.DAY_OPEN]: "Day Open",
    [IndicatorType.PREV_CLOSE]: "Previous Close",
    // Behavior
    [IndicatorType.CONSECUTIVE_HIGHER_HIGHS]: "Consecutive Higher Highs",
    [IndicatorType.CONSECUTIVE_LOWER_LOWS]: "Consecutive Lower Lows",
    [IndicatorType.CONSECUTIVE_GREEN_CANDLES]: "Consecutive Green Candles",
    [IndicatorType.CONSECUTIVE_RED_CANDLES]: "Consecutive Red Candles",
    [IndicatorType.OPENING_RANGE]: "Opening Range",
    [IndicatorType.HEIKIN_ASHI]: "Heikin-Ashi (Candle)",
    [IndicatorType.HA_CLOSE]: "HA Close",
    [IndicatorType.HA_HIGH]: "HA High",
    [IndicatorType.HA_LOW]: "HA Low",
    [IndicatorType.HA_OPEN]: "HA Open",
    // Time & Others
    [IndicatorType.TIME_OF_DAY]: "Time of Day",
    [IndicatorType.PIVOT_POINTS]: "Pivot Points",
    [IndicatorType.RET_PCT_PM]: "Ret % PM",
    [IndicatorType.RET_PCT_RTH]: "Ret % RTH",
    [IndicatorType.RET_PCT_AM]: "Ret % AM",
    [IndicatorType.MAX_N_BARS]: "Max N Bars",
    [IndicatorType.CUSTOM]: "Custom",
};

const FIXED_VALUE_KEY = "__FIXED_VALUE__";

// ----------------------------------------------------------------------
// Generic Selector
// ----------------------------------------------------------------------
export const IndicatorSelector = ({ 
    value, 
    onChange, 
    isTarget,
    exclude = []
}: { 
    value: string, 
    onChange: (val: string) => void, 
    isTarget?: boolean,
    exclude?: IndicatorType[]
}) => {
    return (
        <select
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs max-w-[150px] truncate"
        >
            {Object.entries(INDICATOR_CATEGORIES).map(([category, indicators]) => {
                const filtered = indicators.filter(t => !exclude.includes(t));
                if (filtered.length === 0) return null;
                
                return (
                    <optgroup key={category} label={category}>
                        {filtered.map(t => (
                            <option key={t} value={t}>{INDICATOR_LABELS[t] || t}</option>
                        ))}
                    </optgroup>
                );
            })}
            {isTarget && <option value={FIXED_VALUE_KEY}>── Fixed Value ──</option>}
        </select>
    );
};

// ----------------------------------------------------------------------
// Dynamic Inputs specific to Indicator
// ----------------------------------------------------------------------
export const IndicatorParams = ({
    value,
    onChange
}: {
    value: IndicatorConfig;
    onChange: (val: IndicatorConfig) => void;
}) => {
    return (
        <div className="flex gap-1.5 items-center flex-wrap">
            {/* Specific Params */}
            {(() => {
                switch (value.name) {
                    case IndicatorType.SMA:
                    case IndicatorType.EMA:
                    case IndicatorType.WMA:
                    case IndicatorType.VWAP:
                    case IndicatorType.RSI:
                    case IndicatorType.ATR:
                    case IndicatorType.ADX:
                    case IndicatorType.WILLIAMS_R:
                    case IndicatorType.MOMENTUM:
                    case IndicatorType.ROC:
                    case IndicatorType.CCI:
                    case IndicatorType.MAX_N_BARS:
                        return (
                            <input
                                type="number"
                                value={value.period || ''}
                                onChange={(e) => onChange({ ...value, period: Number(e.target.value) })}
                                placeholder="P"
                                className="w-14 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                title="Period"
                            />
                        );
                    case IndicatorType.BOLLINGER_BANDS:
                        return (
                            <div className="flex gap-1.5 items-center">
                                <input
                                    type="number"
                                    value={value.period || ''}
                                    onChange={(e) => onChange({ ...value, period: Number(e.target.value) })}
                                    placeholder="Per"
                                    className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                    title="Period"
                                />
                                <input
                                    type="number"
                                    value={value.stdDev || ''}
                                    onChange={(e) => onChange({ ...value, stdDev: Number(e.target.value) })}
                                    placeholder="SD"
                                    className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                    title="Standard Deviation"
                                />
                            </div>
                        );
                    case IndicatorType.MACD:
                    case IndicatorType.STOCHASTIC:
                        return (
                            <div className="flex gap-1.5 items-center flex-wrap max-w-[180px]">
                                <input
                                    type="number"
                                    value={value.period || ''}
                                    onChange={(e) => onChange({ ...value, period: Number(e.target.value) })}
                                    placeholder="F"
                                    className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                    title="Fast/K Period"
                                />
                                <input
                                    type="number"
                                    value={value.period2 || ''}
                                    onChange={(e) => onChange({ ...value, period2: Number(e.target.value) })}
                                    placeholder="S"
                                    className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                    title="Slow/D Period"
                                />
                                <input
                                    type="number"
                                    value={value.period3 || ''}
                                    onChange={(e) => onChange({ ...value, period3: Number(e.target.value) })}
                                    placeholder="Sig"
                                    className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                    title="Signal/Smoothing Period"
                                />
                            </div>
                        );
                    case IndicatorType.ICHIMOKU:
                        return (
                            <div className="flex gap-1.5 items-center flex-wrap max-w-[180px]">
                                <input
                                    type="number"
                                    value={value.period || ''}
                                    onChange={(e) => onChange({ ...value, period: Number(e.target.value) })}
                                    placeholder="Cnv"
                                    className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                    title="Conversion Line (Tenkan)"
                                />
                                <input
                                    type="number"
                                    value={value.period2 || ''}
                                    onChange={(e) => onChange({ ...value, period2: Number(e.target.value) })}
                                    placeholder="Bas"
                                    className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                    title="Base Line (Kijun)"
                                />
                                <input
                                    type="number"
                                    value={value.period3 || ''}
                                    onChange={(e) => onChange({ ...value, period3: Number(e.target.value) })}
                                    placeholder="SpB"
                                    className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                    title="Leading Span B"
                                />
                            </div>
                        );
                    case IndicatorType.MIN_X_DAYS:
                    case IndicatorType.MAX_X_DAYS:
                        return (
                            <div className="flex items-center gap-1.5">
                                <input
                                    type="number"
                                    value={value.days_lookback || ''}
                                    onChange={(e) => onChange({ ...value, days_lookback: Number(e.target.value) })}
                                    placeholder="N"
                                    className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                    title="Number of Days Back"
                                />
                                <span className="text-[10px] text-muted-foreground whitespace-nowrap">days</span>
                            </div>
                        );
                    case IndicatorType.TIME_OF_DAY:
                        return (
                            <div className="flex gap-1.5 items-center">
                                <select
                                    value={value.time_condition || 'AFTER'}
                                    onChange={(e) => onChange({ ...value, time_condition: e.target.value as 'BEFORE' | 'AFTER' })}
                                    className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                >
                                    <option value="BEFORE">Before</option>
                                    <option value="AFTER">After</option>
                                </select>
                                <input
                                    type="time"
                                    value={`${String(value.time_hour ?? 9).padStart(2, '0')}:${String(value.time_minute ?? 30).padStart(2, '0')}`}
                                    onChange={(e) => {
                                        const [h, m] = e.target.value.split(':');
                                        if (h && m) {
                                            onChange({ ...value, time_hour: Number(h), time_minute: Number(m) });
                                        }
                                    }}
                                    className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs w-24"
                                />
                            </div>
                        );
                    default:
                        return null;
                }
            })()}
            {/* Global Offset Param for all indicators (Close-X, etc) */}
            <div className="flex items-center gap-1.5 ml-1 border-l border-border/30 pl-2">
                <span className="text-[10px] text-blue-400 uppercase font-black tracking-tighter">Bars Back (X):</span>
                <input
                    type="number"
                    min="0"
                    value={value.offset || 0}
                    onChange={(e) => onChange({ ...value, offset: Math.max(0, Number(e.target.value)) })}
                    placeholder="0"
                    className="w-12 bg-blue-500/10 border border-blue-500/30 rounded px-1.5 py-0.5 text-[11px] text-blue-400 font-black"
                    title="Offset: 0 = current bar, 1 = previous bar, etc."
                />
            </div>
        </div>
    );
};

// ----------------------------------------------------------------------
// Source Indicator Input (left side)
// ----------------------------------------------------------------------

export const SourceIndicatorInput = ({
    value,
    onChange,
    exclude = []
}: {
    value: IndicatorConfig;
    onChange: (val: IndicatorConfig) => void;
    exclude?: IndicatorType[];
}) => {
    return (
        <div className="flex gap-1.5 items-center bg-muted/5 border border-border/20 rounded px-1.5 py-1">
            <IndicatorSelector
                value={value.name}
                exclude={exclude}
                onChange={(nameStr) => {
                    const name = nameStr as IndicatorType;
                    const defaultParams = getDefaultParamsForIndicator(name);
                    onChange({ name, ...defaultParams });
                }}
            />
            <IndicatorParams value={value} onChange={onChange} />
        </div>
    );
};

// ----------------------------------------------------------------------
// Target Input (right side, after comparator)
// ----------------------------------------------------------------------

export const TargetInput = ({
    value,
    onChange
}: {
    value: IndicatorConfig | number;
    onChange: (val: IndicatorConfig | number) => void;
}) => {
    const isFixed = typeof value === 'number';
    const selectedKey = isFixed ? FIXED_VALUE_KEY : (value as IndicatorConfig).name;

    return (
        <div className="flex gap-1.5 items-center flex-wrap">
            <IndicatorSelector
                isTarget
                value={selectedKey}
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

            {!isFixed && (
                <IndicatorParams
                    value={value as IndicatorConfig}
                    onChange={(newVal) => onChange(newVal)}
                />
            )}

            {isFixed && (
                <input
                    type="number"
                    value={value as number}
                    onChange={(e) => onChange(Number(e.target.value))}
                    placeholder="Value"
                    className="w-16 bg-muted/20 border border-amber-500/40 rounded px-2 py-1 text-xs text-amber-400 font-bold"
                />
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

    // Helper to auto-update target if source is HA
    const handleSourceChange = (newSource: IndicatorConfig) => {
        if (condition.type === 'indicator_comparison') {
            const isHA = [IndicatorType.HA_CLOSE, IndicatorType.HA_HIGH, IndicatorType.HA_LOW, IndicatorType.HA_OPEN].includes(newSource.name);
            const newTarget = typeof condition.target === 'object' 
                ? { ...condition.target, calc_on_heikin: isHA }
                : condition.target;
            
            onChange({ ...condition, source: newSource, target: newTarget });
        } else if (condition.type === 'price_level_distance') {
            onChange({ ...condition, source: newSource });
        }
    };

    const handleTargetChange = (newTarget: IndicatorConfig | number) => {
        if (condition.type === 'indicator_comparison') {
            const isHA = [IndicatorType.HA_CLOSE, IndicatorType.HA_HIGH, IndicatorType.HA_LOW, IndicatorType.HA_OPEN].includes(condition.source.name);
            const finalTarget = typeof newTarget === 'object'
                ? { ...newTarget, calc_on_heikin: isHA }
                : newTarget;
            onChange({ ...condition, target: finalTarget });
        }
    };

    const renderInputs = () => {
        switch (condition.type) {
            case 'indicator_comparison':
                return (
                    <>
                        {/* SOURCE: indicator + params */}
                        <SourceIndicatorInput
                            value={condition.source}
                            onChange={handleSourceChange}
                        />

                        {/* COMPARATOR: symbols */}
                        <select
                            value={condition.comparator}
                            onChange={(e) => onChange({ ...condition, comparator: e.target.value as Comparator })}
                            className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs font-mono text-blue-400"
                        >
                            {Object.values(Comparator).filter(c => !c.includes('DISTANCE')).map(c => (
                                <option key={c} value={c}>{COMPARATOR_LABELS[c] || c}</option>
                            ))}
                        </select>

                        {/* TARGET: indicator OR fixed value */}
                        <TargetInput
                            value={condition.target}
                            onChange={handleTargetChange}
                        />
                    </>
                );
            case 'price_level_distance':
                return (
                    <>
                        <SourceIndicatorInput
                            value={condition.source}
                            exclude={DISTANCE_CONDITION_EXCLUDES as IndicatorType[]}
                            onChange={(val) => onChange({ ...condition, source: val })}
                        />
                        <div className="text-xs text-muted-foreground">is</div>
                        <select
                            value={condition.comparator}
                            onChange={(e) => onChange({ ...condition, comparator: e.target.value as 'DISTANCE_GT' | 'DISTANCE_LT' })}
                            className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs font-mono text-blue-400"
                        >
                            <option value="DISTANCE_GT">&gt; than</option>
                            <option value="DISTANCE_LT">&lt; than</option>
                        </select>
                        <div className="flex items-center gap-1">
                            <input
                                type="number"
                                value={condition.value_pct}
                                onChange={(e) => onChange({ ...condition, value_pct: Number(e.target.value) })}
                                className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs text-blue-400 font-mono"
                            />
                            <span className="text-[10px] text-muted-foreground">%</span>
                        </div>
                        <div className="text-xs text-muted-foreground">from</div>
                        <SourceIndicatorInput
                            value={condition.level}
                            exclude={DISTANCE_CONDITION_EXCLUDES as IndicatorType[]}
                            onChange={(val) => onChange({ ...condition, level: val })}
                        />
                        <div className="flex items-center gap-1.5 ml-2 border-l border-border/30 pl-2">
                            <span className="text-[10px] text-muted-foreground uppercase font-bold">Pos:</span>
                            <select
                                value={condition.position || 'any'}
                                onChange={(e) => onChange({ ...condition, position: e.target.value as 'above' | 'below' | 'any' })}
                                className="bg-muted/20 border border-border/50 rounded px-1.5 py-0.5 text-[10px] text-blue-400 font-bold"
                            >
                                <option value="any">Any</option>
                                <option value="above">Above Level</option>
                                <option value="below">Below Level</option>
                            </select>
                        </div>
                    </>
                );
            case 'candle_pattern':
                return (
                    <>
                        <select
                            value={condition.pattern}
                            onChange={(e) => onChange({ ...condition, pattern: e.target.value as CandlePattern })}
                            className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                        >
                            {Object.values(CandlePattern).map(p => (
                                <option key={p} value={p}>{p}</option>
                            ))}
                        </select>
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-muted-foreground">Streak:</span>
                            <input
                                type="number"
                                value={condition.consecutive_count}
                                onChange={(e) => onChange({ ...condition, consecutive_count: Number(e.target.value) })}
                                className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                            />
                        </div>

                        {/* Heikin-Ashi Toggle for Patterns */}
                        <div className="flex items-center gap-2 ml-2 border-l border-border/30 pl-3">
                            <input
                                type="checkbox"
                                id={`ha-pattern-${condition.pattern}`}
                                checked={condition.calc_on_heikin || false}
                                onChange={(e) => onChange({ ...condition, calc_on_heikin: e.target.checked })}
                                className="w-3.5 h-3.5 rounded border-border/50 bg-muted/20 text-blue-500 focus:ring-blue-500"
                            />
                            <label 
                                htmlFor={`ha-pattern-${condition.pattern}`}
                                className="text-[10px] font-bold text-blue-400 uppercase tracking-wider cursor-pointer select-none"
                            >
                                Use Heikin-Ashi
                            </label>
                        </div>
                    </>
                );
        }
    };

    return (
        <div className="flex items-center gap-3 p-2 bg-card border border-border/40 rounded hover:border-border/80 transition-all group">
            {/* Timeframe Selector */}
            <div className="flex items-center gap-1.5 px-2 py-0.5 bg-muted/30 rounded border border-border/30">
                <Clock className="w-3 h-3 text-blue-400" />
                <select
                    value={currentTimeframe}
                    onChange={(e) => onChange({ ...condition, timeframe: e.target.value as Timeframe })}
                    className="bg-transparent text-[10px] font-bold text-blue-400 focus:outline-none cursor-pointer"
                >
                    {Object.values(Timeframe).map(tf => (
                        <option key={tf} value={tf}>{tf}</option>
                    ))}
                </select>
            </div>

            <div className="h-4 w-px bg-border/40"></div>

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
                            source: { name: IndicatorType.CLOSE, offset: 0 },
                            level: { name: IndicatorType.PMH, offset: 0 },
                            comparator: 'DISTANCE_LT',
                            value_pct: 2.0,
                            timeframe: currentTimeframe
                        });
                    } else {
                        onChange({
                            type: 'candle_pattern',
                            pattern: CandlePattern.RV,
                            lookback: 1,
                            consecutive_count: 3,
                            timeframe: currentTimeframe
                        });
                    }
                }}
                className="bg-transparent text-[10px] font-black uppercase tracking-wider text-muted-foreground focus:outline-none cursor-pointer"
            >
                <option value="indicator_comparison">Indicator</option>
                <option value="price_level_distance">Distance</option>
                <option value="candle_pattern">Pattern</option>
            </select>

            <div className="h-4 w-px bg-border/40"></div>

            <div className="flex items-center gap-2 flex-1 flex-wrap">
                {renderInputs()}
            </div>

            <button onClick={onDelete} className="text-muted-foreground hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity">
                <Trash2 className="w-3.5 h-3.5" />
            </button>
        </div>
    );
};

// ----------------------------------------------------------------------
// Recursive Group Component
// ----------------------------------------------------------------------

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

    const addCondition = () => {
        const newCondition: AnyCondition = {
            type: 'indicator_comparison',
            source: { name: IndicatorType.CLOSE },
            comparator: Comparator.GT,
            target: { name: IndicatorType.VWAP },
            timeframe: parentTimeframe
        };
        onChange({
            ...group,
            conditions: [...group.conditions, newCondition]
        });
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

    const colorMap = {
        blue: {
            and: 'bg-blue-500/10 text-blue-500 hover:bg-blue-500/20',
            or: 'bg-orange-500/10 text-orange-500 hover:bg-orange-500/20'
        },
        rose: {
            and: 'bg-rose-500/10 text-rose-500 hover:bg-rose-500/20',
            or: 'bg-orange-500/10 text-orange-500 hover:bg-orange-500/20'
        },
        amber: {
            and: 'bg-amber-500/10 text-amber-500 hover:bg-amber-500/20',
            or: 'bg-orange-500/10 text-orange-500 hover:bg-orange-500/20'
        }
    };

    const colors = colorMap[accentColor];

    return (
        <div className={`
            flex flex-col gap-3 relative
            ${level > 0 ? 'ml-6 pl-4 border-l-2 border-dashed border-border/40' : ''}
        `}>
            {/* Group Header */}
            <div className="flex items-center gap-3">
                <div className={`
                    px-2 py-0.5 rounded text-[10px] font-black uppercase tracking-widest cursor-pointer select-none transition-colors
                    ${group.operator === 'AND' ? colors.and : colors.or}
                 `}
                    onClick={() => onChange({ ...group, operator: group.operator === 'AND' ? 'OR' : 'AND' })}
                >
                    {group.operator}
                </div>

                {level > 0 && (
                    <span className="text-xs text-muted-foreground/50 font-mono">Group</span>
                )}

                {onDelete && (
                    <button onClick={onDelete} className="ml-auto text-muted-foreground/30 hover:text-red-500 transition-colors">
                        <Trash2 className="w-3.5 h-3.5" />
                    </button>
                )}
            </div>

            {/* Conditions List */}
            <div className="flex flex-col gap-2">
                {group.conditions.map((cond, idx) => (
                    <div key={idx}>
                        {cond.type === 'group' ? (
                            <GroupDisplay
                                group={cond}
                                onChange={(newG) => updateCondition(idx, newG)}
                                onDelete={() => removeCondition(idx)}
                                level={level + 1}
                                accentColor={accentColor}
                                parentTimeframe={parentTimeframe}
                            />
                        ) : (
                            <ConditionRow
                                condition={cond}
                                onChange={(newC) => updateCondition(idx, newC)}
                                onDelete={() => removeCondition(idx)}
                                parentTimeframe={parentTimeframe}
                            />
                        )}
                    </div>
                ))}
            </div>

            {/* Add Buttons */}
            <div className="flex gap-2 mt-1">
                <button
                    onClick={addCondition}
                    className="flex items-center gap-1 px-2 py-1 rounded border border-border/40 hover:bg-muted/50 text-[10px] font-bold text-muted-foreground transition-colors"
                >
                    <Plus className="w-3 h-3" />
                    Condition
                </button>
                <button
                    onClick={addGroup}
                    className="flex items-center gap-1 px-2 py-1 rounded border border-border/40 hover:bg-muted/50 text-[10px] font-bold text-muted-foreground transition-colors"
                >
                    <GitBranch className="w-3 h-3" />
                    Logic Group
                </button>
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
    accentColor = 'blue'
}: {
    title: string;
    timeframe: Timeframe;
    onTimeframeChange: (tf: Timeframe) => void;
    rootCondition: ConditionGroup;
    onConditionChange: (g: ConditionGroup) => void;
    accentColor?: 'blue' | 'rose' | 'amber';
}) => {
    return (
        <div className="flex flex-col gap-6 p-6 bg-card border border-border/40 rounded-sm">
            {/* Header with Title and Global Timeframe */}
            <div className="flex items-center justify-between pb-4 border-b border-border/40">
                <div className="flex flex-col gap-1">
                    <h2 className="text-sm font-black uppercase tracking-widest text-foreground">{title}</h2>
                    <span className="text-[10px] text-muted-foreground">Define logic conditions and timeframe execution</span>
                </div>
                
                <div className="flex items-center gap-3">
                    <span className="text-[10px] font-bold uppercase text-muted-foreground">Global TF:</span>
                    <select
                        value={timeframe}
                        onChange={(e) => onTimeframeChange(e.target.value as Timeframe)}
                        className="bg-muted/30 border border-blue-500/30 rounded px-2 py-1 text-xs text-blue-400 font-black cursor-pointer hover:border-blue-500/60 transition-colors"
                    >
                        {Object.values(Timeframe).map(tf => (
                            <option key={tf} value={tf}>{tf}</option>
                        ))}
                    </select>
                </div>
            </div>

            {/* Root Condition Group */}
            <GroupDisplay
                group={rootCondition}
                onChange={onConditionChange}
                accentColor={accentColor}
                parentTimeframe={timeframe}
            />
        </div>
    );
};
