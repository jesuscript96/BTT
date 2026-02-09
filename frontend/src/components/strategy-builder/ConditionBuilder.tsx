
import React from 'react';
import { ConditionGroup, Condition, IndicatorType, Operator } from '@/types/strategy';
import { Trash2, Plus, Clock } from 'lucide-react';

interface Props {
    groups: ConditionGroup[];
    onChange: (groups: ConditionGroup[]) => void;
}

const generateId = () => Math.random().toString(36).substr(2, 9); // Simple ID generator

export const ConditionBuilder: React.FC<Props> = ({ groups, onChange }) => {

    const addGroup = () => {
        onChange([
            ...groups,
            { id: generateId(), conditions: [], logic: "AND" }
        ]);
    };

    const removeGroup = (groupId: string) => {
        onChange(groups.filter(g => g.id !== groupId));
    };

    const addCondition = (groupId: string) => {
        const newCondition: Condition = {
            id: generateId(),
            indicator: IndicatorType.PRICE,
            operator: Operator.GT,
            value: 0
        };

        const newGroups = groups.map(g => {
            if (g.id === groupId) {
                return { ...g, conditions: [...g.conditions, newCondition] };
            }
            return g;
        });

        onChange(newGroups);
    };

    const removeCondition = (groupId: string, conditionId: string) => {
        const newGroups = groups.map(g => {
            if (g.id === groupId) {
                return { ...g, conditions: g.conditions.filter(c => c.id !== conditionId) };
            }
            return g;
        });
        onChange(newGroups);
    };

    const updateCondition = (groupId: string, conditionId: string, field: keyof Condition, value: string | number) => {

        const newGroups = groups.map(g => {
            if (g.id === groupId) {
                const newConditions = g.conditions.map(c => {
                    if (c.id === conditionId) {
                        return { ...c, [field]: value };
                    }
                    return c;
                });
                return { ...g, conditions: newConditions };
            }
            return g;
        });
        onChange(newGroups);
    };

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    {/* Header handled by parent */}
                </div>

                <button
                    onClick={addGroup}
                    className="flex items-center gap-2 px-3 py-1.5 bg-green-500/10 text-green-500 border border-green-500/20 hover:bg-green-500/20 hover:border-green-500/30 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all shadow-sm shadow-green-900/10"
                >
                    <Plus className="w-3 h-3" />
                    Add Logic Block
                </button>
            </div>

            {groups.map((group, index) => (
                <div key={group.id} className="bg-muted/30 border border-border rounded-xl p-5 relative group/card transition-all hover:bg-muted/40 hover:shadow-sm">
                    <div className="flex items-center justify-between mb-4 border-b border-border/50 pb-3">
                        <div className="flex items-center gap-3">
                            <span className="bg-muted text-muted-foreground text-[10px] font-black uppercase tracking-widest px-2 py-0.5 rounded border border-border/50">Group {index + 1}</span>
                            <span className="text-muted-foreground/40 text-[10px] font-black tracking-widest">ALL CONDITIONS (AND)</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => addCondition(group.id)}
                                className="flex items-center gap-1 text-[10px] font-black uppercase tracking-widest text-blue-500 hover:text-blue-400 bg-blue-500/10 hover:bg-blue-500/20 px-2.5 py-1.5 rounded-lg border border-blue-500/20 transition-all"
                            >
                                <Plus className="w-3 h-3" />
                                Add Condition
                            </button>
                            <button
                                onClick={() => removeGroup(group.id)}
                                className="text-muted-foreground/30 hover:text-red-500 transition-colors p-1"
                            >
                                <Trash2 className="w-4 h-4" />
                            </button>
                        </div>
                    </div>

                    <div className="space-y-3">
                        {group.conditions.length === 0 && (
                            <div className="text-center py-8 text-muted-foreground/40 text-[10px] font-black uppercase tracking-widest border-2 border-dashed border-border rounded-lg bg-background/50">
                                No conditions defined. Add a market trigger.
                            </div>
                        )}

                        {group.conditions.map((condition) => (
                            <div key={condition.id} className="flex flex-col md:flex-row items-center gap-3 bg-background/50 border border-border rounded-xl p-3 shadow-sm hover:border-blue-500/50 transition-all">
                                {/* Indicator Select */}
                                <div className="w-full md:w-1/3">
                                    <select
                                        className="w-full bg-muted/50 border border-border rounded-lg px-3 py-2 text-foreground text-sm font-bold focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 focus:outline-none transition-all"
                                        value={condition.indicator}
                                        onChange={(e) => updateCondition(group.id, condition.id, 'indicator', e.target.value)}
                                    >
                                        {Object.values(IndicatorType).map(t => (
                                            <option key={t} value={t}>{t}</option>
                                        ))}
                                    </select>
                                </div>

                                {/* Operator Select */}
                                <div className="w-full md:w-auto">
                                    <select
                                        className="w-full md:w-20 bg-muted/50 border border-border rounded-lg px-2 py-2 text-foreground text-sm font-black tabular-nums text-center focus:outline-none transition-all"
                                        value={condition.operator}
                                        onChange={(e) => updateCondition(group.id, condition.id, 'operator', e.target.value)}
                                    >
                                        {Object.values(Operator).map(t => (
                                            <option key={t} value={t}>{t}</option>
                                        ))}
                                    </select>
                                </div>

                                {/* Dynamic Input Fields based on Indicator */}
                                <div className="w-full md:flex-1 relative flex gap-2">
                                    {/* Main Value Input */}
                                    <div className="relative flex-1">
                                        <input
                                            type={condition.indicator === IndicatorType.TIME_OF_DAY ? "time" : "text"}
                                            className="w-full bg-muted/50 border border-border rounded-lg px-3 py-2 text-foreground text-sm font-bold tabular-nums focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 focus:outline-none placeholder:text-muted-foreground/30 transition-all [color-scheme:dark]"
                                            placeholder={
                                                condition.indicator === IndicatorType.EXTENSION ? "Threshold % (e.g. 15)" :
                                                    condition.indicator === IndicatorType.RVOL ? "Multiplier (e.g. 3)" :
                                                        "Value..."
                                            }
                                            value={condition.value}
                                            onChange={(e) => updateCondition(group.id, condition.id, 'value', e.target.value)}
                                        />
                                        {condition.indicator === IndicatorType.TIME_OF_DAY && (
                                            <Clock className="w-4 h-4 text-muted-foreground/50 absolute right-3 top-1/2 -translate-y-1/2" />
                                        )}
                                    </div>

                                    {/* Compare To / Extra Params */}
                                    {(condition.indicator === IndicatorType.EXTENSION) && (
                                        <div className="w-1/2">
                                            <select
                                                className="w-full bg-muted/50 border border-border rounded-lg px-3 py-2 text-muted-foreground text-xs font-black uppercase tracking-widest focus:outline-none"
                                                value={condition.compare_to || "EMA9"}
                                                onChange={(e) => updateCondition(group.id, condition.id, 'compare_to', e.target.value)}
                                            >
                                                <option value="EMA9">vs EMA 9</option>
                                                <option value="EMA20">vs EMA 20</option>
                                                <option value="VWAP">vs VWAP</option>
                                                <option value="HOD">vs HOD</option>
                                            </select>
                                        </div>
                                    )}
                                </div>

                                <button
                                    onClick={() => removeCondition(group.id, condition.id)}
                                    className="p-2 text-muted-foreground/30 hover:text-red-500 hover:bg-red-500/10 rounded-lg transition-colors"
                                >
                                    <Trash2 className="w-4 h-4" />
                                </button>
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    );
};
