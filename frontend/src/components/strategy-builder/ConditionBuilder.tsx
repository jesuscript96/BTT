import React from 'react';
import {
    ConditionGroup,
    AnyCondition,
    IndicatorType,
    Comparator,
    IndicatorConfig,
    Timeframe
} from '@/types/strategy';
import { Plus, Trash2, GitBranch, Clock } from 'lucide-react';
import { getAllowedTargets } from '@/lib/indicatorValidation';

// ----------------------------------------------------------------------
// Constants & Helpers
// ----------------------------------------------------------------------

const getDefaultParamsForIndicator = (name: IndicatorType): Partial<IndicatorConfig> => {
    switch (name) {
        case IndicatorType.SMA:
        case IndicatorType.EMA:
        case IndicatorType.ATR:
            return { period: 14 };
        case IndicatorType.BOLLINGER_BANDS:
            return { period: 20, stdDev: 2, band_line: "Upper" };
        case IndicatorType.DONCHIAN:
            return { period: 20, band_line: "Upper" };
        case IndicatorType.HIGH_X_DAYS:
        case IndicatorType.LOW_X_DAYS:
            return { days_lookback: 5 };
        case IndicatorType.PREVIOUS_MAX:
        case IndicatorType.PREVIOUS_MIN:
            return { ap_session: "ap.RTH" };
        case IndicatorType.ELAPSED_TIME_LAST_HIGH:
            return { elapsed_minutes: 20 };
        case IndicatorType.OPENING_RANGE_PLUS:
        case IndicatorType.OPENING_RANGE_MINUS:
        case IndicatorType.OPENING_RANGE_AM_PLUS:
        case IndicatorType.OPENING_RANGE_AM_MINUS:
            return { orb_minutes: 30 };
        default:
            return {};
    }
};

const INDICATOR_CATEGORIES: Record<string, IndicatorType[]> = {
    "Price Variables": [
        IndicatorType.BAR_CLOSE, IndicatorType.BAR_OPEN,
        IndicatorType.HIGH_BAR, IndicatorType.LOW_BAR,
        IndicatorType.PM_OPEN, IndicatorType.PM_HIGH, IndicatorType.PM_LOW,
        IndicatorType.RTH_OPEN, IndicatorType.RTH_HIGH, IndicatorType.RTH_LOW,
        IndicatorType.AM_OPEN,
        IndicatorType.PREVIOUS_MAX, IndicatorType.PREVIOUS_MIN,
        IndicatorType.ELAPSED_TIME_LAST_HIGH,
    ],
    "Behaviour & Patterns": [
        IndicatorType.CONSEC_HIGHER_HIGHS, IndicatorType.CONSEC_LOWER_LOWS,
        IndicatorType.CONSEC_LOWER_HIGHS, IndicatorType.CONSEC_HIGHER_LOWS,
        IndicatorType.CONSEC_GREEN_CANDLES, IndicatorType.CONSEC_RED_CANDLES,
        IndicatorType.CANDLE_RANGE_PCT, IndicatorType.RANGE_OF_TIME,
        IndicatorType.OPENING_RANGE_PLUS, IndicatorType.OPENING_RANGE_MINUS,
        IndicatorType.OPENING_RANGE_AM_PLUS, IndicatorType.OPENING_RANGE_AM_MINUS,
    ],
    "Indicators": [
        IndicatorType.SMA, IndicatorType.EMA, IndicatorType.VWAP,
        IndicatorType.DONCHIAN, IndicatorType.BOLLINGER_BANDS,
        IndicatorType.ACCUMULATED_VOLUME, IndicatorType.YESTERDAY_ACCUMULATED_VOLUME,
        IndicatorType.YESTERDAY_VOLUME,
        IndicatorType.RVOL, IndicatorType.VOLUME, IndicatorType.ATR,
    ],
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

const INDICATOR_LABELS: Record<string, string> = {
    // Price Variables
    [IndicatorType.BAR_CLOSE]: "Bar Close",
    [IndicatorType.BAR_OPEN]: "Bar Open",
    [IndicatorType.HIGH_BAR]: "High Bar",
    [IndicatorType.LOW_BAR]: "Low Bar",
    [IndicatorType.PM_OPEN]: "PM Open",
    [IndicatorType.PM_HIGH]: "PM High",
    [IndicatorType.PM_LOW]: "PM Low",
    [IndicatorType.RTH_OPEN]: "RTH Open",
    [IndicatorType.RTH_HIGH]: "RTH High",
    [IndicatorType.RTH_LOW]: "RTH Low",
    [IndicatorType.AM_OPEN]: "AM Open",
    [IndicatorType.PREVIOUS_MAX]: "Previous Max",
    [IndicatorType.PREVIOUS_MIN]: "Previous Min",
    [IndicatorType.YESTERDAY_OPEN]: "Yesterday Open",
    [IndicatorType.YESTERDAY_CLOSE]: "Yesterday Close",
    [IndicatorType.YESTERDAY_HIGH]: "Yesterday High",
    [IndicatorType.YESTERDAY_LOW]: "Yesterday Low",
    [IndicatorType.HIGH_X_DAYS]: "High of last X days",
    [IndicatorType.LOW_X_DAYS]: "Low of last X days",
    [IndicatorType.ELAPSED_TIME_LAST_HIGH]: "Elapsed Time Last High",
    // Behaviour & Patterns
    [IndicatorType.CONSEC_HIGHER_HIGHS]: "Consec Higher Highs",
    [IndicatorType.CONSEC_LOWER_LOWS]: "Consec Lower Lows",
    [IndicatorType.CONSEC_LOWER_HIGHS]: "Consec Lower Highs",
    [IndicatorType.CONSEC_HIGHER_LOWS]: "Consec Higher Lows",
    [IndicatorType.CONSEC_GREEN_CANDLES]: "Consec Green Candles",
    [IndicatorType.CONSEC_RED_CANDLES]: "Consec Red Candles",
    [IndicatorType.CANDLE_RANGE_PCT]: "Candle Range %",
    [IndicatorType.RANGE_OF_TIME]: "Range of Time",
    [IndicatorType.OPENING_RANGE_PLUS]: "Opening Range +",
    [IndicatorType.OPENING_RANGE_MINUS]: "Opening Range -",
    [IndicatorType.OPENING_RANGE_AM_PLUS]: "Opening Range AM +",
    [IndicatorType.OPENING_RANGE_AM_MINUS]: "Opening Range AM -",
    // Indicators
    [IndicatorType.SMA]: "SMA",
    [IndicatorType.EMA]: "EMA",
    [IndicatorType.VWAP]: "VWAP",
    [IndicatorType.DONCHIAN]: "Donchian",
    [IndicatorType.BOLLINGER_BANDS]: "Bollinger Bands",
    [IndicatorType.ACCUMULATED_VOLUME]: "Accum. Volume",
    [IndicatorType.YESTERDAY_ACCUMULATED_VOLUME]: "Yesterday Accum. Volume",
    [IndicatorType.YESTERDAY_VOLUME]: "Yesterday Volume",
    [IndicatorType.RVOL]: "RVOL",
    [IndicatorType.VOLUME]: "Volume",
    [IndicatorType.ATR]: "ATR",
};

const FIXED_VALUE_KEY = "__FIXED_VALUE__";

// ----------------------------------------------------------------------
// Generic Selector
// ----------------------------------------------------------------------
export const IndicatorSelector = ({ 
    value, 
    onChange, 
    isTarget,
    allowedTargets,
    exclude = []
}: { 
    value: string, 
    onChange: (val: string) => void, 
    isTarget?: boolean,
    allowedTargets?: IndicatorType[],
    exclude?: IndicatorType[]
}) => {
    return (
        <select
            value={value}
            onChange={(e) => onChange(e.target.value)}
            style={{
                backgroundColor: 'var(--color-ec-bg-sidebar)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 5,
                padding: '5px 10px',
                fontSize: 12,
                fontWeight: 500,
                color: 'var(--color-ec-text-primary)',
                fontFamily: 'var(--color-ec-sans)',
                minWidth: 130,
                outline: 'none',
                cursor: 'pointer',
            }}
        >
            {Object.entries(INDICATOR_CATEGORIES).map(([category, indicators]) => {
                const filtered = indicators.filter(t => 
                    (allowedTargets ? allowedTargets.includes(t) : true) && 
                    !exclude.includes(t)
                );
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
                    case IndicatorType.ATR:
                        return (
                            <input
                                type="number"
                                value={value.period || ''}
                                onChange={(e) => onChange({ ...value, period: Number(e.target.value) })}
                                placeholder="P"
                                style={{
                                    width: 64,
                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                    border: '0.5px solid var(--color-ec-border)',
                                    borderRadius: 5,
                                    padding: '5px 8px',
                                    fontSize: 12,
                                    fontWeight: 500,
                                    color: 'var(--color-ec-text-primary)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    outline: 'none',
                                }}
                                title="Period"
                            />
                        );
                    case IndicatorType.BOLLINGER_BANDS:
                    case IndicatorType.DONCHIAN:
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
                                {value.name === IndicatorType.BOLLINGER_BANDS && (
                                    <input
                                        type="number"
                                        value={value.stdDev || ''}
                                        onChange={(e) => onChange({ ...value, stdDev: Number(e.target.value) })}
                                        placeholder="SD"
                                        className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                        title="Standard Deviation"
                                    />
                                )}
                                <select
                                    value={value.band_line || 'Upper'}
                                    onChange={(e) => onChange({ ...value, band_line: e.target.value as "Upper" | "Lower" | "Basis" })}
                                    className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs w-20"
                                >
                                    <option value="Upper">Upper</option>
                                    <option value="Lower">Lower</option>
                                    <option value="Basis">Basis</option>
                                </select>
                            </div>
                        );
                    case IndicatorType.OPENING_RANGE_PLUS:
                    case IndicatorType.OPENING_RANGE_MINUS:
                    case IndicatorType.OPENING_RANGE_AM_PLUS:
                    case IndicatorType.OPENING_RANGE_AM_MINUS:
                        return (
                            <div className="flex gap-1.5 items-center">
                                <span className="text-xs text-muted-foreground whitespace-nowrap">Mins:</span>
                                <input
                                    type="number"
                                    value={value.orb_minutes || ''}
                                    onChange={(e) => onChange({ ...value, orb_minutes: Number(e.target.value) })}
                                    placeholder="M"
                                    className="w-14 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                                    title="Reference minutes (ex. 30 for 30min ORB)"
                                />
                            </div>
                        );
                    case IndicatorType.HIGH_X_DAYS:
                    case IndicatorType.LOW_X_DAYS:
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
                    case IndicatorType.PREVIOUS_MAX:
                    case IndicatorType.PREVIOUS_MIN:
                        return (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <span style={{ fontSize: 9, fontWeight: 700,
                                    color: 'var(--color-ec-text-muted)',
                                    textTransform: 'uppercase', letterSpacing: 1 }}>
                                    Desde:
                                </span>
                                <select
                                    value={value.ap_session || "ap.RTH"}
                                    onChange={(e) => onChange({ ...value, ap_session: e.target.value as "ap.PM" | "ap.RTH" | "ap.AM" })}
                                    style={{
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 4,
                                        padding: '3px 6px',
                                        fontSize: 11,
                                        color: 'var(--color-ec-copper)',
                                        cursor: 'pointer',
                                    }}
                                >
                                    <option value="ap.PM">ap.PM</option>
                                    <option value="ap.RTH">ap.RTH</option>
                                    <option value="ap.AM">ap.AM</option>
                                </select>
                            </div>
                        );
                    case IndicatorType.ELAPSED_TIME_LAST_HIGH:
                        return (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <span style={{ fontSize: 9, fontWeight: 700,
                                    color: 'var(--color-ec-text-muted)',
                                    textTransform: 'uppercase', letterSpacing: 1 }}>
                                    Mins:
                                </span>
                                <input
                                    type="number"
                                    min={1}
                                    value={value.elapsed_minutes || 20}
                                    onChange={(e) => onChange({ ...value, elapsed_minutes: Number(e.target.value) })}
                                    style={{
                                        width: 50,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 4,
                                        padding: '3px 6px',
                                        fontSize: 11,
                                        color: 'var(--color-ec-text-primary)',
                                        textAlign: 'center',
                                        outline: 'none',
                                    }}
                                />
                            </div>
                        );
                    default:
                        return null;
                }
            })()}
            {/* Global Offset Param for all indicators (Close-X, etc) */}
            <div className="flex items-center gap-1.5 ml-1 border-l border-border/30 pl-2">
                <span style={{
                    fontSize: 9,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    letterSpacing: '0.1em',
                    color: 'var(--color-ec-copper)',
                    fontFamily: 'var(--color-ec-sans)',
                }}>Bars Back (X):</span>
                <input
                    type="number"
                    min="0"
                    value={value.offset || 0}
                    onChange={(e) => onChange({ ...value, offset: Math.max(0, Number(e.target.value)) })}
                    placeholder="0"
                    style={{
                        width: 52,
                        backgroundColor: 'color-mix(in srgb, var(--color-ec-copper) 10%, transparent)',
                        border: '0.5px solid color-mix(in srgb, var(--color-ec-copper) 30%, transparent)',
                        borderRadius: 4,
                        padding: '4px 8px',
                        fontSize: 11,
                        fontWeight: 700,
                        color: 'var(--color-ec-copper)',
                        fontFamily: 'var(--color-ec-sans)',
                        outline: 'none',
                    }}
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
    onChange,
    allowedTargets
}: {
    value: IndicatorConfig | number;
    onChange: (val: IndicatorConfig | number) => void;
    allowedTargets?: IndicatorType[];
}) => {
    const isFixed = typeof value === 'number';
    const selectedKey = isFixed ? FIXED_VALUE_KEY : (value as IndicatorConfig).name;

    return (
        <div className="flex gap-1.5 items-center flex-wrap">
            <IndicatorSelector
                isTarget
                value={selectedKey}
                allowedTargets={allowedTargets}
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
                    style={{
                        width: 72,
                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5,
                        padding: '5px 8px',
                        fontSize: 12,
                        fontWeight: 500,
                        color: 'var(--color-ec-text-primary)',
                        fontFamily: 'var(--color-ec-sans)',
                        outline: 'none',
                    }}
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

    const handleSourceChange = (newSource: IndicatorConfig) => {
        onChange({ ...condition, source: newSource });
    };

    const handleTargetChange = (newTarget: IndicatorConfig | number) => {
        if (condition.type === 'indicator_comparison') {
            onChange({ ...condition, target: newTarget });
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
                            className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs font-mono text-[var(--color-ec-copper)]"
                        >
                            {Object.values(Comparator).filter(c => !c.includes('DISTANCE')).map(c => (
                                <option key={c} value={c}>{COMPARATOR_LABELS[c] || c}</option>
                            ))}
                        </select>

                        {/* TARGET: indicator OR fixed value */}
                        <TargetInput
                            value={condition.target}
                            onChange={handleTargetChange}
                            allowedTargets={getAllowedTargets(condition.source.name as IndicatorType, 'indicator_comparison')}
                        />
                    </>
                );
            case 'price_level_distance':
                return (
                    <>
                        <SourceIndicatorInput
                            value={condition.source}
                            exclude={[]}
                            onChange={(val) => onChange({ ...condition, source: val })}
                        />
                        <div className="text-xs text-muted-foreground">is</div>
                        <select
                            value={condition.comparator}
                            onChange={(e) => onChange({ ...condition, comparator: e.target.value as 'DISTANCE_GT' | 'DISTANCE_LT' })}
                            className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs font-mono text-[var(--color-ec-copper)]"
                        >
                            <option value="DISTANCE_GT">&gt; than</option>
                            <option value="DISTANCE_LT">&lt; than</option>
                        </select>
                        <div className="flex items-center gap-1">
                            <input
                                type="number"
                                value={condition.value_pct}
                                onChange={(e) => onChange({ ...condition, value_pct: Number(e.target.value) })}
                                className="w-12 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs text-[var(--color-ec-copper)] font-mono"
                            />
                            <span className="text-[10px] text-muted-foreground">%</span>
                        </div>
                        <div className="text-xs text-muted-foreground">from</div>
                        <SourceIndicatorInput
                            value={condition.level}
                            exclude={[]}
                            onChange={(val) => onChange({ ...condition, level: val })}
                        />
                        <div className="flex items-center gap-1.5 ml-2 border-l border-border/30 pl-2">
                            <span className="text-[10px] text-muted-foreground uppercase font-bold">Pos:</span>
                            <select
                                value={condition.position || 'any'}
                                onChange={(e) => onChange({ ...condition, position: e.target.value as 'above' | 'below' | 'any' })}
                                className="bg-muted/20 border border-border/50 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-ec-copper)] font-bold"
                            >
                                <option value="any">Any</option>
                                <option value="above">Above Level</option>
                                <option value="below">Below Level</option>
                            </select>
                        </div>
                    </>
                );
            default:
                return null;
        }
    };

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 12px',
            backgroundColor: 'var(--color-ec-bg-elevated)',
            border: '0.5px solid var(--color-ec-border)',
            borderRadius: 5,
            transition: 'border-color 150ms ease',
        }} className="group"
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-ec-copper)')}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-ec-border)')}
        >
            {/* Timeframe Selector */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                padding: '3px 8px',
                backgroundColor: 'var(--color-ec-bg-sidebar)',
                border: '0.5px solid var(--color-ec-border)',
                borderRadius: 4,
            }}>
                <Clock className="w-3 h-3 text-[var(--color-ec-copper)]" />
                <select
                    value={currentTimeframe}
                    onChange={(e) => onChange({ ...condition, timeframe: e.target.value as Timeframe })}
                    style={{
                        background: 'transparent',
                        border: 'none',
                        outline: 'none',
                        fontSize: 11,
                        fontWeight: 700,
                        color: 'var(--color-ec-copper)',
                        fontFamily: 'var(--color-ec-sans)',
                        cursor: 'pointer',
                    }}
                >
                    {Object.values(Timeframe).map(tf => (
                        <option key={tf} value={tf}>{tf}</option>
                    ))}
                </select>
            </div>

            <div style={{
                width: 1,
                height: 16,
                backgroundColor: 'var(--color-ec-border)',
                flexShrink: 0,
            }}></div>

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
                            source: { name: IndicatorType.BAR_CLOSE, offset: 0 },
                            level: { name: IndicatorType.PM_HIGH, offset: 0 },
                            comparator: 'DISTANCE_LT',
                            value_pct: 2.0,
                            timeframe: currentTimeframe
                        });
                    }
                }}
                style={{
                    background: 'transparent',
                    border: 'none',
                    outline: 'none',
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    letterSpacing: '0.08em',
                    color: 'var(--color-ec-text-secondary)',
                    fontFamily: 'var(--color-ec-sans)',
                    cursor: 'pointer',
                }}
            >
                <option value="indicator_comparison">Indicator</option>
            </select>

            <div style={{
                width: 1,
                height: 16,
                backgroundColor: 'var(--color-ec-border)',
                flexShrink: 0,
            }}></div>

            <div className="flex items-center gap-2 flex-1 flex-wrap">
                {renderInputs()}
            </div>

            <button onClick={onDelete} className="text-muted-foreground hover:text-ec-loss opacity-0 group-hover:opacity-100 transition-opacity">
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
            source: { name: IndicatorType.BAR_CLOSE },
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

    return (
        <div className={`
            flex flex-col gap-3 relative
            ${level > 0 ? 'ml-6 pl-4 border-l-2 border-dashed border-border/40' : ''}
        `}>
            {/* Group Header */}
            <div className="flex items-center gap-3">
                <div
                    style={group.operator === 'AND' ? {
                        backgroundColor: 'color-mix(in srgb, var(--color-ec-copper) 15%, transparent)',
                        color: 'var(--color-ec-copper)',
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.1em',
                        padding: '3px 10px',
                        borderRadius: 4,
                        cursor: 'pointer',
                        border: 'none',
                    } : {
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.1em',
                        padding: '3px 10px',
                        borderRadius: 4,
                        cursor: 'pointer',
                        border: 'none',
                        color: 'var(--color-ec-text-secondary)',
                        fontFamily: 'var(--color-ec-sans)',
                        backgroundColor: 'transparent',
                    }}
                    onClick={() => onChange({ ...group, operator: group.operator === 'AND' ? 'OR' : 'AND' })}
                >
                    {group.operator}
                </div>

                {level > 0 && (
                    <span className="text-xs text-muted-foreground/50 font-mono">Group</span>
                )}

                {onDelete && (
                    <button onClick={onDelete} className="ml-auto text-muted-foreground/30 hover:text-ec-loss transition-colors">
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
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 5,
                        padding: '5px 12px',
                        backgroundColor: 'transparent',
                        border: '0.5px dashed var(--color-ec-border)',
                        borderRadius: 5,
                        fontSize: 11,
                        fontWeight: 600,
                        color: 'var(--color-ec-text-muted)',
                        fontFamily: 'var(--color-ec-sans)',
                        cursor: 'pointer',
                        transition: 'border-color 150ms ease, color 150ms ease',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-copper)'; e.currentTarget.style.color = 'var(--color-ec-copper)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-border)'; e.currentTarget.style.color = 'var(--color-ec-text-muted)'; }}
                >
                    <Plus className="w-3 h-3" />
                    Condition
                </button>
                <button
                    onClick={addGroup}
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 5,
                        padding: '5px 12px',
                        backgroundColor: 'transparent',
                        border: '0.5px dashed var(--color-ec-border)',
                        borderRadius: 5,
                        fontSize: 11,
                        fontWeight: 600,
                        color: 'var(--color-ec-text-muted)',
                        fontFamily: 'var(--color-ec-sans)',
                        cursor: 'pointer',
                        transition: 'border-color 150ms ease, color 150ms ease',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-copper)'; e.currentTarget.style.color = 'var(--color-ec-copper)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-border)'; e.currentTarget.style.color = 'var(--color-ec-text-muted)'; }}
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
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
            padding: '16px 20px',
            backgroundColor: 'var(--color-ec-bg-surface)',
            border: '0.5px solid var(--color-ec-border)',
            borderRadius: 7,
        }}>
            {/* Header with Title and Global Timeframe */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                paddingBottom: 12,
                borderBottom: '0.5px solid var(--color-ec-border)',
                marginBottom: 4,
            }}>
                <div className="flex flex-col gap-1">
                    <h2 style={{
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 13,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.08em',
                        color: 'var(--color-ec-text-high)',
                    }}>{title}</h2>
                    <span style={{
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 400,
                        color: 'var(--color-ec-text-muted)',
                        marginTop: 2,
                    }}>Define logic conditions and timeframe execution</span>
                </div>
                
                <div className="flex items-center gap-3">
                    <span style={{
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 9,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.12em',
                        color: 'var(--color-ec-text-muted)',
                    }}>Global TF:</span>
                    <select
                        value={timeframe}
                        onChange={(e) => onTimeframeChange(e.target.value as Timeframe)}
                        style={{
                            backgroundColor: 'var(--color-ec-bg-elevated)',
                            border: '0.5px solid var(--color-ec-copper)',
                            borderRadius: 4,
                            padding: '3px 8px',
                            fontSize: 11,
                            fontWeight: 700,
                            color: 'var(--color-ec-copper)',
                            fontFamily: 'var(--color-ec-sans)',
                            outline: 'none',
                            cursor: 'pointer',
                        }}
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
