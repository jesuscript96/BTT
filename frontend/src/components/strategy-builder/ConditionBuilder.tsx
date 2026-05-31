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
export const COMPARATOR_LABELS: Record<string, string> = {
    [Comparator.GT]: ">",
    [Comparator.LT]: "<",
    [Comparator.GTE]: "≥",
    [Comparator.LTE]: "≤",
    [Comparator.EQ]: "=",
    [Comparator.CROSSES_ABOVE]: "↗ Crosses Above",
    [Comparator.CROSSES_BELOW]: "↘ Crosses Below",
};

export const INDICATOR_LABELS: Record<string, string> = {
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
    [IndicatorType.YESTERDAY_AM_HIGH]: "Yesterday AM High",
    [IndicatorType.YESTERDAY_AM_LOW]: "Yesterday AM Low",
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
    exclude = [],
    width = '100%'
}: { 
    value: string, 
    onChange: (val: string) => void, 
    isTarget?: boolean,
    allowedTargets?: IndicatorType[],
    exclude?: IndicatorType[],
    width?: string | number
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
                width: width,
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
    onChange,
    hideOffset = false
}: {
    value: IndicatorConfig;
    onChange: (val: IndicatorConfig) => void;
    hideOffset?: boolean;
}) => {
    return (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', width: '100%' }}>
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
                                placeholder="Period"
                                style={{
                                    width: '100%',
                                    backgroundColor: 'var(--color-ec-bg-sidebar)',
                                    border: '0.5px solid var(--color-ec-border)',
                                    borderRadius: 5,
                                    padding: '5px 10px',
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
                            <div style={{ display: 'flex', gap: 6, width: '100%' }}>
                                <input
                                    type="number"
                                    value={value.period || ''}
                                    onChange={(e) => onChange({ ...value, period: Number(e.target.value) })}
                                    placeholder="Period"
                                    style={{
                                        flex: 1,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 12,
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                    }}
                                    title="Period"
                                />
                                {value.name === IndicatorType.BOLLINGER_BANDS && (
                                    <input
                                        type="number"
                                        value={value.stdDev || ''}
                                        onChange={(e) => onChange({ ...value, stdDev: Number(e.target.value) })}
                                        placeholder="Std Dev"
                                        style={{
                                            flex: 1,
                                            backgroundColor: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: '5px 10px',
                                            fontSize: 12,
                                            fontWeight: 500,
                                            color: 'var(--color-ec-text-primary)',
                                            fontFamily: 'var(--color-ec-sans)',
                                            outline: 'none',
                                        }}
                                        title="Standard Deviation"
                                    />
                                )}
                                <select
                                    value={value.band_line || 'Upper'}
                                    onChange={(e) => onChange({ ...value, band_line: e.target.value as "Upper" | "Lower" | "Basis" })}
                                    style={{
                                        flex: 1.2,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 12,
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                        cursor: 'pointer',
                                    }}
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
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%' }}>
                                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>Mins:</span>
                                <input
                                    type="number"
                                    value={value.orb_minutes || ''}
                                    onChange={(e) => onChange({ ...value, orb_minutes: Number(e.target.value) })}
                                    placeholder="Minutes"
                                    style={{
                                        flex: 1,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 12,
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                    }}
                                    title="Reference minutes (ex. 30 for 30min ORB)"
                                />
                            </div>
                        );
                    case IndicatorType.HIGH_X_DAYS:
                    case IndicatorType.LOW_X_DAYS:
                        return (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%' }}>
                                <input
                                    type="number"
                                    value={value.days_lookback || ''}
                                    onChange={(e) => onChange({ ...value, days_lookback: Number(e.target.value) })}
                                    placeholder="Days"
                                    style={{
                                        flex: 1,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 12,
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                    }}
                                    title="Number of Days Back"
                                />
                                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-ec-text-muted)' }}>días</span>
                            </div>
                        );
                    case IndicatorType.PREVIOUS_MAX:
                    case IndicatorType.PREVIOUS_MIN:
                        return (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%' }}>
                                <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                                    Session:
                                </span>
                                <select
                                    value={value.ap_session || "ap.RTH"}
                                    onChange={(e) => onChange({ ...value, ap_session: e.target.value as "ap.PM" | "ap.RTH" | "ap.AM" })}
                                    style={{
                                        flex: 1,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 12,
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
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
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%' }}>
                                <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                                    Mins:
                                </span>
                                <input
                                    type="number"
                                    min={1}
                                    value={value.elapsed_minutes || 20}
                                    onChange={(e) => onChange({ ...value, elapsed_minutes: Number(e.target.value) })}
                                    style={{
                                        flex: 1,
                                        backgroundColor: 'var(--color-ec-bg-sidebar)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        padding: '5px 10px',
                                        fontSize: 12,
                                        fontWeight: 500,
                                        color: 'var(--color-ec-text-primary)',
                                        fontFamily: 'var(--color-ec-sans)',
                                        outline: 'none',
                                    }}
                                />
                            </div>
                        );
                    default:
                        return null;
                }
            })()}
            
            {/* Global Offset Param */}
            {!hideOffset && (
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
            )}
        </div>
    );
};

// ----------------------------------------------------------------------
// Source Indicator Input (left side)
// ----------------------------------------------------------------------

export const SourceIndicatorInput = ({
    value,
    onChange,
    exclude = [],
    hideOffset = false
}: {
    value: IndicatorConfig;
    onChange: (val: IndicatorConfig) => void;
    exclude?: IndicatorType[];
    hideOffset?: boolean;
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
            <IndicatorParams value={value} onChange={onChange} hideOffset={hideOffset} />
        </div>
    );
};

// ----------------------------------------------------------------------
// Target Input (right side, after comparator)
// ----------------------------------------------------------------------

export const TargetInput = ({
    value,
    onChange,
    allowedTargets,
    hideOffset = false
}: {
    value: IndicatorConfig | number;
    onChange: (val: IndicatorConfig | number) => void;
    allowedTargets?: IndicatorType[];
    hideOffset?: boolean;
}) => {
    const isFixed = typeof value === 'number';
    const selectedKey = isFixed ? FIXED_VALUE_KEY : (value as IndicatorConfig).name;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
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
                    hideOffset={hideOffset}
                />
            )}

            {isFixed && (
                <input
                    type="number"
                    value={value as number}
                    onChange={(e) => onChange(Number(e.target.value))}
                    placeholder="Value"
                    style={{
                        width: '100%',
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
export const formatConditionText = (c: AnyCondition): string => {
    const tfStr = c.timeframe ? `[${c.timeframe}]` : '';
    if (c.type === 'indicator_comparison') {
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const compStr = COMPARATOR_LABELS[c.comparator] || c.comparator;
        let targetStr = '';
        if (typeof c.target === 'number') {
            targetStr = String(c.target);
        } else {
            targetStr = `${INDICATOR_LABELS[c.target.name] || c.target.name}${c.target.offset ? `[t-${c.target.offset}]` : ''}`;
        }
        return `${tfStr} ${sourceStr} ${compStr} ${targetStr}`;
    } else if (c.type === 'price_level_distance') {
        const sourceStr = `${INDICATOR_LABELS[c.source.name] || c.source.name}${c.source.offset ? `[t-${c.source.offset}]` : ''}`;
        const levelStr = `${INDICATOR_LABELS[c.level.name] || c.level.name}${c.level.offset ? `[t-${c.level.offset}]` : ''}`;
        const compStr = c.comparator === 'DISTANCE_GT' ? '>' : '<';
        const pctStr = `${c.value_pct}%`;
        const posStr = c.position && c.position !== 'any' ? ` (${c.position})` : '';
        return `${tfStr} Dist(${sourceStr}, ${levelStr}) ${compStr} ${pctStr}${posStr}`;
    }
    return '';
};

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
    const [showForm, setShowForm] = React.useState(false);
    const [editingIndex, setEditingIndex] = React.useState<number | null>(null);
    const [formCondition, setFormCondition] = React.useState<AnyCondition>({
        type: 'indicator_comparison',
        source: { name: IndicatorType.BAR_CLOSE, offset: 0 },
        comparator: Comparator.GT,
        target: { name: IndicatorType.VWAP, offset: 0 },
        timeframe: parentTimeframe
    });

    const activeAccentColor = accentColor === 'blue' ? 'var(--color-ec-profit)' : accentColor === 'rose' ? 'var(--color-ec-loss)' : 'var(--color-ec-copper)';

    const handleSaveCondition = () => {
        if (editingIndex !== null) {
            const newConditions = [...group.conditions];
            newConditions[editingIndex] = formCondition;
            onChange({ ...group, conditions: newConditions });
            setEditingIndex(null);
        } else {
            onChange({
                ...group,
                conditions: [...group.conditions, formCondition]
            });
        }
        setShowForm(false);
    };

    const handleRemoveCondition = (indexInAll: number) => {
        const newConditions = group.conditions.filter((_, i) => i !== indexInAll);
        onChange({ ...group, conditions: newConditions });
        if (editingIndex === indexInAll) {
            setEditingIndex(null);
            setShowForm(false);
        }
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

    const labelStyle: React.CSSProperties = {
        fontFamily: 'var(--color-ec-sans)',
        fontSize: '9px',
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        color: 'var(--color-ec-text-muted)',
        marginBottom: '2px',
    };

    const inputStyle: React.CSSProperties = {
        backgroundColor: 'var(--color-ec-bg-sidebar)',
        border: '0.5px solid var(--color-ec-border)',
        borderRadius: '4px',
        padding: '5px 8px',
        fontSize: '11px',
        fontWeight: 500,
        color: 'var(--color-ec-text-primary)',
        fontFamily: 'var(--color-ec-sans)',
        outline: 'none',
        width: '100%',
    };

    const selectStyle: React.CSSProperties = {
        backgroundColor: 'var(--color-ec-bg-sidebar)',
        border: '0.5px solid var(--color-ec-border)',
        borderRadius: '4px',
        padding: '5px 8px',
        fontSize: '11px',
        fontWeight: 500,
        color: 'var(--color-ec-text-primary)',
        fontFamily: 'var(--color-ec-sans)',
        outline: 'none',
        width: '100%',
        cursor: 'pointer',
    };

    const subGroups = group.conditions.filter(c => c.type === 'group') as ConditionGroup[];

    return (
        <div 
            style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
                position: 'relative',
                marginLeft: level > 0 ? 16 : 0,
                paddingLeft: level > 0 ? 16 : 0,
                paddingRight: level > 0 ? 12 : 0,
                paddingTop: level > 0 ? 12 : 0,
                paddingBottom: level > 0 ? 12 : 0,
                borderLeft: level > 0 ? `2.5px solid ${activeAccentColor}` : 'none',
                backgroundColor: level > 0 ? 'color-mix(in srgb, var(--color-ec-bg-surface) 40%, transparent)' : 'transparent',
                borderRadius: level > 0 ? '0 6px 6px 0' : 0,
                borderTop: level > 0 ? '0.5px solid var(--color-ec-border)' : 'none',
                borderBottom: level > 0 ? '0.5px solid var(--color-ec-border)' : 'none',
                borderRight: level > 0 ? '0.5px solid var(--color-ec-border)' : 'none',
            }}
        >
            {/* Group Header */}
            <div className="flex items-center gap-3">
                <div
                    style={group.operator === 'AND' ? {
                        backgroundColor: `color-mix(in srgb, ${activeAccentColor} 15%, transparent)`,
                        color: activeAccentColor,
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
                    <span style={{
                        fontSize: 9,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        color: activeAccentColor,
                        letterSpacing: '0.08em',
                        fontFamily: 'var(--color-ec-sans)',
                        backgroundColor: `color-mix(in srgb, ${activeAccentColor} 10%, transparent)`,
                        padding: '2px 6px',
                        borderRadius: 3,
                    }}>
                        Grupo Lógico
                    </span>
                )}

                {onDelete && (
                    <button onClick={onDelete} className="ml-auto text-muted-foreground/30 hover:text-ec-loss transition-colors">
                        <Trash2 className="w-3.5 h-3.5" />
                    </button>
                )}
            </div>

            {/* Config & Tags Row */}
            <div style={{
                display: 'flex',
                flexDirection: 'row',
                gap: 16,
                alignItems: 'flex-start',
                width: '100%',
            }}>
                {/* Left side: Buttons or Vertical Form */}
                <div style={{
                    width: 250,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                    flexShrink: 0,
                }}>
                    {showForm ? (
                        <div style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 10,
                            padding: 12,
                            border: `0.5px solid ${activeAccentColor}`,
                            backgroundColor: 'var(--color-ec-bg-surface)',
                            borderRadius: 6,
                        }}>
                            {/* Form Header */}
                            <div style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                borderBottom: '0.5px solid var(--color-ec-border)',
                                paddingBottom: 6,
                                marginBottom: 4
                            }}>
                                <span style={{
                                    fontSize: 10,
                                    fontWeight: 700,
                                    textTransform: 'uppercase',
                                    color: activeAccentColor,
                                    letterSpacing: '0.08em',
                                    fontFamily: 'var(--color-ec-sans)',
                                }}>
                                    {editingIndex !== null ? 'Editar Condición' : 'Nueva Condición'}
                                </span>
                            </div>

                            {/* Timeframe & Type dropdowns (Tiempo y Tipo de indicador) */}
                            <div style={{ display: 'flex', gap: 8 }}>
                                <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                                    <span style={labelStyle}>Tiempo</span>
                                    <select
                                        value={formCondition.timeframe || parentTimeframe}
                                        onChange={(e) => setFormCondition({ ...formCondition, timeframe: e.target.value as Timeframe })}
                                        style={selectStyle}
                                    >
                                        {Object.values(Timeframe).map(tf => (
                                            <option key={tf} value={tf}>{tf}</option>
                                        ))}
                                    </select>
                                </div>
                                <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                                    <span style={labelStyle}>Indicador</span>
                                    <select
                                        value={formCondition.type}
                                        style={{ ...selectStyle, opacity: 0.7, cursor: 'not-allowed' }}
                                        disabled
                                    >
                                        <option value="indicator_comparison">Comparación</option>
                                    </select>
                                </div>
                            </div>

                            {/* Variable de entrada */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                <span style={labelStyle}>Variable de entrada</span>
                                <IndicatorSelector
                                    value={formCondition.source.name}
                                    onChange={(nameStr) => {
                                        const name = nameStr as IndicatorType;
                                        const defaultParams = getDefaultParamsForIndicator(name);
                                        setFormCondition({
                                            ...formCondition,
                                            source: { name, offset: formCondition.source.offset, ...defaultParams }
                                        });
                                    }}
                                />
                                <IndicatorParams
                                    value={formCondition.source}
                                    onChange={(newSource) => setFormCondition({ ...formCondition, source: newSource })}
                                    hideOffset={true}
                                />
                            </div>

                            {/* bars back */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                <span style={labelStyle}>Bars back</span>
                                <input
                                    type="number"
                                    min="0"
                                    value={formCondition.source.offset || 0}
                                    onChange={(e) => setFormCondition({
                                        ...formCondition,
                                        source: { ...formCondition.source, offset: Math.max(0, Number(e.target.value)) }
                                    })}
                                    style={inputStyle}
                                />
                            </div>

                            {/* relación */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                <span style={labelStyle}>Relación</span>
                                {formCondition.type === 'indicator_comparison' ? (
                                    <select
                                        value={formCondition.comparator}
                                        onChange={(e) => setFormCondition({ ...formCondition, comparator: e.target.value as Comparator })}
                                        style={selectStyle}
                                    >
                                        {Object.values(Comparator).filter(c => !c.includes('DISTANCE')).map(c => (
                                            <option key={c} value={c}>{COMPARATOR_LABELS[c] || c}</option>
                                        ))}
                                    </select>
                                ) : (
                                    <select
                                        value={formCondition.comparator}
                                        onChange={(e) => setFormCondition({ ...formCondition, comparator: e.target.value as 'DISTANCE_GT' | 'DISTANCE_LT' })}
                                        style={selectStyle}
                                    >
                                        <option value="DISTANCE_GT">&gt; que</option>
                                        <option value="DISTANCE_LT">&lt; que</option>
                                    </select>
                                )}
                            </div>

                            {/* Variables de cruce */}
                            {formCondition.type === 'indicator_comparison' ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <span style={labelStyle}>Variables de cruce</span>
                                    <TargetInput
                                        value={formCondition.target}
                                        onChange={(newTarget) => setFormCondition({ ...formCondition, target: newTarget })}
                                        allowedTargets={getAllowedTargets(formCondition.source.name as IndicatorType, 'indicator_comparison')}
                                        hideOffset={true}
                                    />
                                </div>
                            ) : (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                        <span style={labelStyle}>Distancia %</span>
                                        <input
                                            type="number"
                                            step="0.1"
                                            value={formCondition.value_pct}
                                            onChange={(e) => setFormCondition({ ...formCondition, value_pct: Number(e.target.value) })}
                                            style={inputStyle}
                                        />
                                    </div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                        <span style={labelStyle}>Variables de cruce (Nivel)</span>
                                        <IndicatorSelector
                                            value={formCondition.level.name}
                                            onChange={(nameStr) => {
                                                const name = nameStr as IndicatorType;
                                                const defaultParams = getDefaultParamsForIndicator(name);
                                                setFormCondition({
                                                    ...formCondition,
                                                    level: { name, offset: formCondition.level.offset, ...defaultParams }
                                                });
                                            }}
                                        />
                                        <IndicatorParams
                                            value={formCondition.level}
                                            onChange={(newLevel) => setFormCondition({ ...formCondition, level: newLevel })}
                                            hideOffset={true}
                                        />
                                    </div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                        <span style={labelStyle}>Posición</span>
                                        <select
                                            value={formCondition.position || 'any'}
                                            onChange={(e) => setFormCondition({ ...formCondition, position: e.target.value as 'above' | 'below' | 'any' })}
                                            style={selectStyle}
                                        >
                                            <option value="any">Cualquiera (Any)</option>
                                            <option value="above">Por encima del nivel</option>
                                            <option value="below">Por debajo del nivel</option>
                                        </select>
                                    </div>
                                </div>
                            )}

                            {/* segundo barsback */}
                            {formCondition.type === 'indicator_comparison' && typeof formCondition.target !== 'number' && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <span style={labelStyle}>Segundo bars back</span>
                                    <input
                                        type="number"
                                        min="0"
                                        value={formCondition.target.offset || 0}
                                        onChange={(e) => setFormCondition({
                                            ...formCondition,
                                            target: { ...(formCondition.target as IndicatorConfig), offset: Math.max(0, Number(e.target.value)) }
                                        })}
                                        style={inputStyle}
                                    />
                                </div>
                            )}
                            {formCondition.type === 'price_level_distance' && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <span style={labelStyle}>Segundo bars back</span>
                                    <input
                                        type="number"
                                        min="0"
                                        value={formCondition.level.offset || 0}
                                        onChange={(e) => setFormCondition({
                                            ...formCondition,
                                            level: { ...formCondition.level, offset: Math.max(0, Number(e.target.value)) }
                                        })}
                                        style={inputStyle}
                                    />
                                </div>
                            )}

                            {/* Save/Cancel buttons */}
                            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                                <button
                                    onClick={handleSaveCondition}
                                    style={{
                                        flex: 1,
                                        padding: '6px 12px',
                                        backgroundColor: activeAccentColor,
                                        border: 'none',
                                        borderRadius: 4,
                                        fontSize: 11,
                                        fontWeight: 700,
                                        color: '#ffffff',
                                        cursor: 'pointer',
                                    }}
                                >
                                    {editingIndex !== null ? 'Guardar' : 'Añadir'}
                                </button>
                                <button
                                    onClick={() => {
                                        setShowForm(false);
                                        setEditingIndex(null);
                                    }}
                                    style={{
                                        flex: 1,
                                        padding: '6px 12px',
                                        backgroundColor: 'transparent',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 4,
                                        fontSize: 11,
                                        fontWeight: 600,
                                        color: 'var(--color-ec-text-muted)',
                                        cursor: 'pointer',
                                    }}
                                >
                                    Cancelar
                                </button>
                            </div>
                        </div>
                    ) : (
                        <div className="flex gap-2">
                            <button
                                onClick={() => {
                                    setEditingIndex(null);
                                    setFormCondition({
                                        type: 'indicator_comparison',
                                        source: { name: IndicatorType.BAR_CLOSE, offset: 0 },
                                        comparator: Comparator.GT,
                                        target: { name: IndicatorType.VWAP, offset: 0 },
                                        timeframe: parentTimeframe
                                    });
                                    setShowForm(true);
                                }}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 5,
                                    padding: '6px 12px',
                                    backgroundColor: 'transparent',
                                    border: '0.5px dashed var(--color-ec-border)',
                                    borderRadius: 5,
                                    fontSize: 11,
                                    fontWeight: 600,
                                    color: 'var(--color-ec-text-muted)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    cursor: 'pointer',
                                    transition: 'border-color 150ms ease, color 150ms ease',
                                    flex: 1,
                                    justifyContent: 'center',
                                }}
                                onMouseEnter={(e) => { e.currentTarget.style.borderColor = activeAccentColor; e.currentTarget.style.color = activeAccentColor; }}
                                onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-border)'; e.currentTarget.style.color = 'var(--color-ec-text-muted)'; }}
                            >
                                <Plus className="w-3 h-3" />
                                Condición
                            </button>
                            <button
                                onClick={addGroup}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 5,
                                    padding: '6px 12px',
                                    backgroundColor: 'transparent',
                                    border: '0.5px dashed var(--color-ec-border)',
                                    borderRadius: 5,
                                    fontSize: 11,
                                    fontWeight: 600,
                                    color: 'var(--color-ec-text-muted)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    cursor: 'pointer',
                                    transition: 'border-color 150ms ease, color 150ms ease',
                                    flex: 1,
                                    justifyContent: 'center',
                                }}
                                onMouseEnter={(e) => { e.currentTarget.style.borderColor = activeAccentColor; e.currentTarget.style.color = activeAccentColor; }}
                                onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-ec-border)'; e.currentTarget.style.color = 'var(--color-ec-text-muted)'; }}
                            >
                                <GitBranch className="w-3 h-3" />
                                Grupo Lógico
                            </button>
                        </div>
                    )}
                </div>

                {/* Right side: Line of Tags */}
                <div style={{
                    flex: 1,
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: 6,
                    paddingTop: showForm ? 0 : 4,
                }}>
                    {group.conditions.map((cond, idx) => {
                        if (cond.type === 'group') return null;
                        return (
                            <div 
                                key={idx} 
                                onClick={() => {
                                    setEditingIndex(idx);
                                    setFormCondition(cond);
                                    setShowForm(true);
                                }}
                                style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: 6,
                                    padding: '4px 8px',
                                    backgroundColor: 'var(--color-ec-bg-elevated)',
                                    border: '0.5px solid var(--color-ec-border)',
                                    borderRadius: 4,
                                    fontSize: 10,
                                    fontWeight: 600,
                                    color: 'var(--color-ec-text-primary)',
                                    fontFamily: 'var(--color-ec-sans)',
                                    cursor: 'pointer',
                                    transition: 'border-color 150ms ease',
                                }}
                                onMouseEnter={(e) => e.currentTarget.style.borderColor = activeAccentColor}
                                onMouseLeave={(e) => e.currentTarget.style.borderColor = 'var(--color-ec-border)'}
                            >
                                <span>{formatConditionText(cond)}</span>
                                <button 
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        handleRemoveCondition(idx);
                                    }} 
                                    style={{
                                        background: 'none',
                                        border: 'none',
                                        color: 'var(--color-ec-text-muted)',
                                        cursor: 'pointer',
                                        fontSize: 12,
                                        padding: '0 2px',
                                        lineHeight: 1,
                                    }}
                                    onMouseEnter={(e) => e.currentTarget.style.color = 'var(--color-ec-loss)'}
                                    onMouseLeave={(e) => e.currentTarget.style.color = 'var(--color-ec-text-muted)'}
                                >
                                    ×
                                </button>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Nested subgroups */}
            <div className="flex flex-col gap-3">
                {subGroups.map((sub, idx) => {
                    const mainIdx = group.conditions.indexOf(sub);
                    return (
                        <GroupDisplay
                            key={idx}
                            group={sub}
                            onChange={(newG) => updateCondition(mainIdx, newG)}
                            onDelete={() => removeCondition(mainIdx)}
                            level={level + 1}
                            accentColor={accentColor}
                            parentTimeframe={parentTimeframe}
                        />
                    );
                })}
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
    const headerAccentColor = accentColor === 'blue' ? 'var(--color-ec-profit)' : accentColor === 'rose' ? 'var(--color-ec-loss)' : 'var(--color-ec-copper)';

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
            padding: '20px 0',
            backgroundColor: 'transparent',
            borderBottom: '0.5px solid var(--color-ec-border)',
        }}>
            {/* Header with Title and Global Timeframe */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                paddingBottom: 4,
                marginBottom: 4,
            }}>
                <div className="flex flex-col gap-1">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{
                            width: 3,
                            height: 14,
                            borderRadius: 1,
                            backgroundColor: headerAccentColor,
                        }} />
                        <h2 style={{
                            fontFamily: 'var(--color-ec-sans)',
                            fontSize: 13,
                            fontWeight: 700,
                            textTransform: 'uppercase',
                            letterSpacing: '0.08em',
                            color: 'var(--color-ec-text-high)',
                            margin: 0,
                        }}>{title}</h2>
                    </div>
                    <span style={{
                        fontFamily: 'var(--color-ec-sans)',
                        fontSize: 10,
                        fontWeight: 400,
                        color: 'var(--color-ec-text-muted)',
                        marginTop: 2,
                    }}>Define logic conditions and timeframe execution</span>
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
