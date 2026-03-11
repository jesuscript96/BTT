
import React from 'react';
import {
    ConditionGroup,
    AnyCondition,
    IndicatorType,
    Comparator,
    CandlePattern,
    IndicatorConfig
} from '@/types/strategy';
import { Plus, Trash2, GitBranch } from 'lucide-react';

// ----------------------------------------------------------------------
// Constants & Helpers
// ----------------------------------------------------------------------

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
        IndicatorType.VWAP, IndicatorType.LINEAR_REGRESSION,
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
        IndicatorType.MAX_X_DAYS, IndicatorType.MIN_X_DAYS
    ],
    "Behavior & Patterns": [
        IndicatorType.CONSECUTIVE_HIGHER_HIGHS, IndicatorType.CONSECUTIVE_LOWER_LOWS,
        IndicatorType.CONSECUTIVE_GREEN_CANDLES, IndicatorType.CONSECUTIVE_RED_CANDLES,
        IndicatorType.OPENING_RANGE, IndicatorType.HEIKIN_ASHI
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
    // Behavior
    [IndicatorType.CONSECUTIVE_HIGHER_HIGHS]: "Consecutive Higher Highs",
    [IndicatorType.CONSECUTIVE_LOWER_LOWS]: "Consecutive Lower Lows",
    [IndicatorType.CONSECUTIVE_GREEN_CANDLES]: "Consecutive Green Candles",
    [IndicatorType.CONSECUTIVE_RED_CANDLES]: "Consecutive Red Candles",
    [IndicatorType.OPENING_RANGE]: "Opening Range",
    [IndicatorType.HEIKIN_ASHI]: "Heikin-Ashi",
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
export const IndicatorSelector = ({ value, onChange, isTarget }: { value: string, onChange: (val: string) => void, isTarget?: boolean }) => {
    return (
        <select
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs max-w-[150px] truncate"
        >
            {Object.entries(INDICATOR_CATEGORIES).map(([category, indicators]) => (
                <optgroup key={category} label={category}>
                    {indicators.map(t => (
                        <option key={t} value={t}>{INDICATOR_LABELS[t] || t}</option>
                    ))}
                </optgroup>
            ))}
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
    switch (value.name) {
        case IndicatorType.SMA:
        case IndicatorType.EMA:
        case IndicatorType.WMA:
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
                    placeholder="Period"
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
                        onChange={(e) => onChange({ ...value, time_condition: e.target.value as any })}
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
            return null; // Variable like Close, Open... doesn't need params
    }
};

// ----------------------------------------------------------------------
// Source Indicator Input (left side)
// ----------------------------------------------------------------------

export const SourceIndicatorInput = ({
    value,
    onChange
}: {
    value: IndicatorConfig;
    onChange: (val: IndicatorConfig) => void;
}) => {
    return (
        <div className="flex gap-1.5 items-center flex-wrap">
            <IndicatorSelector
                value={value.name}
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
    onDelete
}: {
    condition: AnyCondition;
    onChange: (c: AnyCondition) => void;
    onDelete: () => void;
}) => {

    const renderInputs = () => {
        switch (condition.type) {
            case 'indicator_comparison':
                return (
                    <>
                        {/* SOURCE: indicator + params */}
                        <SourceIndicatorInput
                            value={condition.source}
                            onChange={(val) => onChange({ ...condition, source: val })}
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
                            onChange={(val) => onChange({ ...condition, target: val })}
                        />
                    </>
                );
            case 'price_level_distance':
                return (
                    <>
                        <select
                            value={condition.source}
                            onChange={(e) => onChange({ ...condition, source: e.target.value as any })}
                            className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                        >
                            <option value="Close">Close</option>
                            <option value="High">High</option>
                            <option value="Low">Low</option>
                        </select>
                        <div className="text-xs text-muted-foreground">is</div>
                        <select
                            value={condition.comparator}
                            onChange={(e) => onChange({ ...condition, comparator: e.target.value as any })}
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
                                className="w-16 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                            />
                            <span className="text-xs text-muted-foreground">% from</span>
                        </div>
                        <IndicatorSelector
                            value={condition.level}
                            onChange={(val) => onChange({ ...condition, level: val as IndicatorType })}
                        />
                    </>
                );
            case 'candle_pattern':
                return (
                    <>
                        <select
                            value={condition.pattern}
                            onChange={(e) => onChange({ ...condition, pattern: e.target.value as any })}
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
                    </>
                );
        }
    };

    return (
        <div className="flex items-center gap-3 p-2 bg-card border border-border/40 rounded hover:border-border/80 transition-all group">
            <select
                value={condition.type}
                onChange={(e) => {
                    if (e.target.value === 'indicator_comparison') {
                        onChange({
                            type: 'indicator_comparison',
                            source: { name: IndicatorType.SMA, period: 20 },
                            comparator: Comparator.GT,
                            target: { name: IndicatorType.VWAP }
                        });
                    } else if (e.target.value === 'price_level_distance') {
                        onChange({
                            type: 'price_level_distance',
                            source: 'Close',
                            level: IndicatorType.PMH,
                            comparator: 'DISTANCE_LT',
                            value_pct: 2.0
                        });
                    } else {
                        onChange({
                            type: 'candle_pattern',
                            pattern: CandlePattern.RV,
                            lookback: 1,
                            consecutive_count: 3
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
    accentColor = 'blue'
}: {
    group: ConditionGroup;
    onChange: (g: ConditionGroup) => void;
    onDelete?: () => void;
    level?: number;
    accentColor?: 'blue' | 'rose' | 'amber';
}) => {

    const addCondition = () => {
        const newCondition: AnyCondition = {
            type: 'indicator_comparison',
            source: { name: IndicatorType.CLOSE },
            comparator: Comparator.GT,
            target: { name: IndicatorType.VWAP }
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
                            />
                        ) : (
                            <ConditionRow
                                condition={cond}
                                onChange={(newC) => updateCondition(idx, newC)}
                                onDelete={() => removeCondition(idx)}
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
