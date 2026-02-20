
import React from 'react';
import { ExitLogic, Timeframe } from '@/types/strategy';
import { GroupDisplay } from './ConditionBuilder';

interface Props {
    logic: ExitLogic;
    onChange: (logic: ExitLogic) => void;
}

export const ExitLogicBuilder = ({ logic, onChange }: Props) => {
    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <label className="text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-70">Exit Timeframe</label>
                <select
                    value={logic.timeframe}
                    onChange={(e) => onChange({ ...logic, timeframe: e.target.value as Timeframe })}
                    className="bg-muted/20 border border-border/50 rounded px-2 py-1 text-xs font-bold"
                >
                    {Object.values(Timeframe).map(t => (
                        <option key={t} value={t}>{t}</option>
                    ))}
                </select>
            </div>

            <div className="bg-background/30 rounded-lg p-4 border border-border/30">
                <GroupDisplay
                    group={logic.root_condition}
                    onChange={(g) => onChange({ ...logic, root_condition: g })}
                    accentColor="rose"
                />
            </div>
        </div>
    );
};
