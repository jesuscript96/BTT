
import React from 'react';
import { RiskManagement, RiskType, RiskSettings, TakeProfitMode, PartialTakeProfit } from '@/types/strategy';
import { PlusCircle, Trash2, Info } from 'lucide-react';

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

    const addPartial = () => {
        const currentPartials = risk.partial_take_profits || [];
        // Default to a reasonable new partial: next 2% distance, remaining capital or 25%
        const lastDist = currentPartials.length > 0 ? currentPartials[currentPartials.length - 1].distance_pct : 3.0;
        const currentTotal = currentPartials.reduce((sum, p) => sum + p.capital_pct, 0);
        const remaining = Math.max(0, 100 - currentTotal);
        
        onChange({
            ...risk,
            partial_take_profits: [
                ...currentPartials,
                { distance_pct: Number((lastDist + 2).toFixed(1)), capital_pct: remaining > 0 ? remaining : 25 }
            ]
        });
    };

    const removePartial = (index: number) => {
        onChange({
            ...risk,
            partial_take_profits: risk.partial_take_profits.filter((_, i) => i !== index)
        });
    };

    const updatePartial = (index: number, field: keyof PartialTakeProfit, value: number) => {
        onChange({
            ...risk,
            partial_take_profits: risk.partial_take_profits.map((p, i) =>
                i === index ? { ...p, [field]: value } : p
            )
        });
    };

    const totalPartialCapital = (risk.partial_take_profits || []).reduce((sum, p) => sum + p.capital_pct, 0);



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
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] font-bold text-muted-foreground/60">{risk.use_hard_stop !== false ? 'ON' : 'OFF'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.use_hard_stop !== false ? 'bg-red-500/70' : 'bg-muted'}`}
                            onClick={() => onChange({ ...risk, use_hard_stop: risk.use_hard_stop === false })}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.use_hard_stop !== false ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
                </div>
                {(risk.use_hard_stop !== false) && (
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
                )}
            </div>

            {/* Take Profit */}
            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <label className="text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-70">Take Profit</label>
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] font-bold text-muted-foreground/60">{risk.use_take_profit !== false ? 'ON' : 'OFF'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.use_take_profit !== false ? 'bg-green-500/70' : 'bg-muted'}`}
                            onClick={() => onChange({ ...risk, use_take_profit: risk.use_take_profit === false })}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.use_take_profit !== false ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
                </div>
                {(risk.use_take_profit !== false) && (
                    <div className="space-y-4 animate-in fade-in slide-in-from-top-1">
                        {/* Mode Toggle */}
                        <div className="flex bg-muted/20 p-1 rounded-lg w-full">
                            <button
                                onClick={() => onChange({ ...risk, take_profit_mode: TakeProfitMode.FULL })}
                                className={`flex-1 py-1.5 text-[9px] font-black uppercase tracking-widest rounded-md transition-all ${risk.take_profit_mode === TakeProfitMode.FULL ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                            >
                                Completo (Full)
                            </button>
                            <button
                                onClick={() => onChange({ ...risk, take_profit_mode: TakeProfitMode.PARTIAL })}
                                className={`flex-1 py-1.5 text-[9px] font-black uppercase tracking-widest rounded-md transition-all ${risk.take_profit_mode === TakeProfitMode.PARTIAL ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                            >
                                Parciales (Partial)
                            </button>
                        </div>

                        {risk.take_profit_mode === TakeProfitMode.FULL ? (
                            <div className="flex gap-2 animate-in fade-in zoom-in-95 duration-200">
                                <select
                                    value={risk.take_profit.type}
                                    onChange={(e) => updateRiskSetting('take_profit', 'type', e.target.value)}
                                    className="bg-muted/20 border border-border/50 rounded-lg px-2 py-2 text-xs font-bold text-foreground focus:outline-none focus:ring-1 focus:ring-green-500/30 w-1/3"
                                >
                                    {Object.values(RiskType).map(type => (
                                        <option key={type} value={type}>{type}</option>
                                    ))}
                                </select>
                                <div className="relative flex-1">
                                    <input
                                        type="number"
                                        value={risk.take_profit.value}
                                        onChange={(e) => updateRiskSetting('take_profit', 'value', Number(e.target.value))}
                                        className="w-full bg-muted/20 border border-border/50 rounded-lg px-3 py-2 text-sm font-bold text-foreground focus:outline-none focus:ring-1 focus:ring-green-500/30"
                                    />
                                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-muted-foreground/40">%</span>
                                </div>
                            </div>
                        ) : (
                            <div className="space-y-4 animate-in fade-in zoom-in-95 duration-200">
                                <div className="space-y-2">
                                    {risk.partial_take_profits.map((partial, idx) => (
                                        <div key={idx} className="group relative bg-muted/10 border border-border/30 rounded-xl p-3 space-y-3 transition-all hover:border-green-500/30 hover:bg-muted/15">
                                            <div className="flex items-center justify-between">
                                                <span className="text-[10px] font-black text-green-500/70 tracking-tighter">PARTIAL #{idx + 1}</span>
                                                {risk.partial_take_profits.length > 1 && (
                                                    <button
                                                        onClick={() => removePartial(idx)}
                                                        className="p-1 text-muted-foreground hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
                                                    >
                                                        <Trash2 className="w-3.5 h-3.5" />
                                                    </button>
                                                )}
                                            </div>
                                            
                                            <div className="grid grid-cols-2 gap-4">
                                                <div className="space-y-1.5">
                                                    <label className="text-[9px] font-bold text-muted-foreground uppercase opacity-50">Distancia %</label>
                                                    <div className="relative">
                                                        <input
                                                            type="number"
                                                            step="0.1"
                                                            value={partial.distance_pct}
                                                            onChange={(e) => updatePartial(idx, 'distance_pct', Number(e.target.value))}
                                                            className="w-full bg-background/50 border border-border/50 rounded-lg px-2 py-1.5 text-xs font-bold focus:ring-1 focus:ring-green-500/30"
                                                        />
                                                        <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-bold text-muted-foreground/30">%</span>
                                                    </div>
                                                </div>
                                                <div className="space-y-1.5">
                                                    <div className="flex justify-between items-center">
                                                        <label className="text-[9px] font-bold text-muted-foreground uppercase opacity-50">Capital %</label>
                                                        <span className="text-[10px] font-black text-foreground">{partial.capital_pct}%</span>
                                                    </div>
                                                    <input
                                                        type="range"
                                                        min="1"
                                                        max="100"
                                                        value={partial.capital_pct}
                                                        onChange={(e) => updatePartial(idx, 'capital_pct', Number(e.target.value))}
                                                        className="w-full h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-green-500"
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>

                                <button
                                    onClick={addPartial}
                                    className="w-full py-2 border border-dashed border-border/60 rounded-xl flex items-center justify-center gap-2 text-[10px] font-bold text-muted-foreground hover:border-green-500/40 hover:text-green-500 hover:bg-green-500/5 transition-all"
                                >
                                    <PlusCircle className="w-3.5 h-3.5" />
                                    <span>Add Partial Take Profit</span>
                                </button>

                                <div className={`flex items-center gap-2 p-2 rounded-lg border transition-all ${Math.abs(totalPartialCapital - 100) < 0.01 ? 'bg-green-500/5 border-green-500/20 text-green-500/80' : 'bg-amber-500/5 border-amber-500/20 text-amber-500'}`}>
                                    <Info className="w-3.5 h-3.5 shrink-0" />
                                    <div className="flex-1 text-[9px] font-bold leading-tight">
                                        Total Capital: <span className="font-black underline">{totalPartialCapital}%</span>
                                        {Math.abs(totalPartialCapital - 100) > 0.01 && (
                                            <span className="block opacity-70">Sum must be exactly 100% to save/test.</span>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Re-entries Option */}
            <div className="pt-4 border-t border-dashed border-border/40">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <label className="text-[10px] font-black text-muted-foreground uppercase tracking-widest opacity-70">Accept Re-entries</label>
                        <p className="text-[9px] text-muted-foreground/50 mt-0.5">Allow entering again if a trade for this ticker was closed.</p>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] font-bold text-muted-foreground/60">{risk.accept_reentries !== false ? 'YES' : 'NO'}</span>
                        <div
                            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${risk.accept_reentries !== false ? 'bg-indigo-500' : 'bg-muted'}`}
                            onClick={() => onChange({ ...risk, accept_reentries: risk.accept_reentries === false })}
                        >
                            <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all shadow-sm ${risk.accept_reentries !== false ? 'left-4.5' : 'left-0.5'}`}></div>
                        </div>
                    </div>
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
                                <option value="Percentage">Percentage</option>
                                <option value="EMA13">EMA 13</option>
                                <option value="HWM">High Water Mark</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-[9px] font-bold text-muted-foreground uppercase mb-1.5 opacity-50">Distance %</label>
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
