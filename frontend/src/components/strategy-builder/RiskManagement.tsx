
import React from 'react';
import { RiskManagement, RiskType, RiskSettings } from '@/types/strategy';

interface Props {
    risk: RiskManagement;
    onChange: (risk: RiskManagement) => void;
}

export const RiskManagementComponent: React.FC<Props> = ({ risk, onChange }) => {

    const updateRiskSetting = (key: 'hard_stop' | 'take_profit', field: keyof RiskSettings, value: any) => {
        onChange({
            ...risk,
            [key]: {
                ...risk[key],
                [field]: value
            }
        });
    };



    // Helper for Trailing (fixing typing above)
    const setTrailingField = (field: keyof typeof risk.trailing_stop, value: any) => {
        onChange({
            ...risk,
            trailing_stop: {
                ...risk.trailing_stop,
                [field]: value
            }
        });
    };


    return (
        <div className="space-y-8">

            {/* Hard Stop */}
            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <label className="text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-70">Hard Stop Loss</label>
                </div>
                <div className="flex gap-2">
                    <select
                        value={risk.hard_stop.type}
                        onChange={(e) => updateRiskSetting('hard_stop', 'type', e.target.value)}
                        className="bg-muted/20 border border-border/50 rounded-lg px-2 py-2 text-xs font-bold text-foreground focus:outline-none focus:ring-1 focus:ring-red-500/30 w-1/3"
                    >
                        {Object.values(RiskType).map(type => (
                            <option key={type} value={type}>{type}</option>
                        ))}
                    </select>
                    <input
                        type="number"
                        value={risk.hard_stop.value}
                        onChange={(e) => updateRiskSetting('hard_stop', 'value', Number(e.target.value))}
                        className="bg-muted/20 border border-border/50 rounded-lg px-3 py-2 text-sm font-bold text-foreground focus:outline-none focus:ring-1 focus:ring-red-500/30 flex-1"
                    />
                </div>
            </div>

            {/* Take Profit */}
            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <label className="text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-70">Take Profit</label>
                </div>
                <div className="flex gap-2">
                    <select
                        value={risk.take_profit.type}
                        onChange={(e) => updateRiskSetting('take_profit', 'type', e.target.value)}
                        className="bg-muted/20 border border-border/50 rounded-lg px-2 py-2 text-xs font-bold text-foreground focus:outline-none focus:ring-1 focus:ring-green-500/30 w-1/3"
                    >
                        {Object.values(RiskType).map(type => (
                            <option key={type} value={type}>{type}</option>
                        ))}
                    </select>
                    <input
                        type="number"
                        value={risk.take_profit.value}
                        onChange={(e) => updateRiskSetting('take_profit', 'value', Number(e.target.value))}
                        className="bg-muted/20 border border-border/50 rounded-lg px-3 py-2 text-sm font-bold text-foreground focus:outline-none focus:ring-1 focus:ring-green-500/30 flex-1"
                    />
                </div>
            </div>

            {/* Trailing Stop */}
            <div className="pt-4 border-t border-dashed border-border/40">
                <div className="flex items-center justify-between mb-4">
                    <label className="text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-70">Trailing Stop</label>
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] font-bold text-muted-foreground/60">{risk.trailing_stop.active ? 'ACTIVE' : 'OFF'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.trailing_stop.active ? 'bg-blue-500' : 'bg-muted'}`}
                            onClick={() => setTrailingField('active', !risk.trailing_stop.active)}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.trailing_stop.active ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
                </div>

                {risk.trailing_stop.active && (
                    <div className="grid grid-cols-2 gap-3 animate-in fade-in slide-in-from-top-1">
                        <div>
                            <label className="block text-[9px] font-bold text-muted-foreground uppercase mb-1.5 opacity-50">Type</label>
                            <select
                                value={risk.trailing_stop.type}
                                onChange={(e) => setTrailingField('type', e.target.value)}
                                className="w-full bg-muted/20 border border-border/50 rounded-md px-2 py-1.5 text-xs font-medium text-foreground"
                            >
                                <option value="EMA13">EMA 13</option>
                                <option value="HWM">High Water Mark</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-[9px] font-bold text-muted-foreground uppercase mb-1.5 opacity-50">Buffer %</label>
                            <input
                                type="number"
                                step="0.1"
                                value={risk.trailing_stop.buffer_pct}
                                onChange={(e) => setTrailingField('buffer_pct', Number(e.target.value))}
                                className="w-full bg-muted/20 border border-border/50 rounded-md px-2 py-1.5 text-xs font-medium text-foreground"
                            />
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
