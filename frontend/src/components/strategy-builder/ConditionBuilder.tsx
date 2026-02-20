
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

// Indicators that need a period parameter (e.g. SMA(20), EMA(9), RSI(14))
const PERIOD_INDICATORS = new Set([
    IndicatorType.SMA, IndicatorType.EMA, IndicatorType.WMA,
    IndicatorType.RSI, IndicatorType.MACD, IndicatorType.ATR,
    IndicatorType.RVOL
]);

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
    [IndicatorType.SMA]: "SMA",
    [IndicatorType.EMA]: "EMA",
    [IndicatorType.WMA]: "WMA",
    [IndicatorType.RSI]: "RSI",
    [IndicatorType.MACD]: "MACD",
    [IndicatorType.ATR]: "ATR",
    [IndicatorType.RVOL]: "RVOL",
    [IndicatorType.VWAP]: "Cumulative VWAP (Day)",
    [IndicatorType.AVWAP]: "Anchored VWAP (Day)",
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
    [IndicatorType.Y_CLOSE]: "Yesterday Close",
    [IndicatorType.CUSTOM]: "Custom",
};

const FIXED_VALUE_KEY = "__FIXED_VALUE__";

// ----------------------------------------------------------------------
// Source Indicator Input (left side)
// Shows: dropdown + period param if applicable. Nothing else.
// ----------------------------------------------------------------------

export const SourceIndicatorInput = ({
    value,
    onChange
}: {
    value: IndicatorConfig;
    onChange: (val: IndicatorConfig) => void;
}) => {
    const needsPeriod = PERIOD_INDICATORS.has(value.name);

    return (
        <div className="flex gap-1.5 items-center">
            <select
                value={value.name}
                onChange={(e) => {
                    const name = e.target.value as IndicatorType;
                    const newVal: IndicatorConfig = { name };
                    if (PERIOD_INDICATORS.has(name)) newVal.period = 20;
                    onChange(newVal);
                }}
                className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
            >
                {Object.values(IndicatorType).map(t => (
                    <option key={t} value={t}>{INDICATOR_LABELS[t] || t}</option>
                ))}
            </select>
            {needsPeriod && (
                <input
                    type="number"
                    value={value.period || ''}
                    onChange={(e) => onChange({ ...value, period: Number(e.target.value) })}
                    placeholder="Period"
                    className="w-16 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                />
            )}
        </div>
    );
};

// ----------------------------------------------------------------------
// Target Input (right side, after comparator)
// Dropdown with all indicators + "Fixed Value" option.
// If indicator selected → show period if needed.
// If "Fixed Value" selected → show numeric input.
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
    const needsPeriod = !isFixed && PERIOD_INDICATORS.has((value as IndicatorConfig).name);

    return (
        <div className="flex gap-1.5 items-center">
            <select
                value={selectedKey}
                onChange={(e) => {
                    const key = e.target.value;
                    if (key === FIXED_VALUE_KEY) {
                        onChange(0);
                    } else {
                        const name = key as IndicatorType;
                        const newVal: IndicatorConfig = { name };
                        if (PERIOD_INDICATORS.has(name)) newVal.period = 20;
                        onChange(newVal);
                    }
                }}
                className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
            >
                {Object.values(IndicatorType).map(t => (
                    <option key={t} value={t}>{INDICATOR_LABELS[t] || t}</option>
                ))}
                <option value={FIXED_VALUE_KEY}>── Fixed Value ──</option>
            </select>

            {/* Period input for indicators that need it */}
            {!isFixed && needsPeriod && (
                <input
                    type="number"
                    value={(value as IndicatorConfig).period || ''}
                    onChange={(e) => onChange({ ...(value as IndicatorConfig), period: Number(e.target.value) })}
                    placeholder="Period"
                    className="w-16 bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                />
            )}

            {/* Numeric input for fixed value */}
            {isFixed && (
                <input
                    type="number"
                    value={value as number}
                    onChange={(e) => onChange(Number(e.target.value))}
                    placeholder="Value"
                    className="w-20 bg-muted/20 border border-amber-500/40 rounded px-2 py-1 text-xs text-amber-400 font-bold"
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
                        <select
                            value={condition.level}
                            onChange={(e) => onChange({ ...condition, level: e.target.value as any })}
                            className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs"
                        >
                            <option value="Pre-Market High">PMH</option>
                            <option value="Pre-Market Low">PML</option>
                            <option value="Yesterday High">Y-High</option>
                            <option value="Yesterday Low">Y-Low</option>
                            <option value="VWAP">VWAP</option>
                            <option value="EMA">EMA</option>
                        </select>
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
