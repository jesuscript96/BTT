import React from 'react';
import { ExitLogic, RiskType } from '@/types/strategy';
import { AlertOctagon, Target, TrendingUp } from 'lucide-react';

interface Props {
    exitLogic: ExitLogic;
    onChange: (logic: ExitLogic) => void;
}

export const RiskSection: React.FC<Props> = ({ exitLogic, onChange }) => {
    const handleChange = (field: keyof ExitLogic, value: string | number | boolean) => {
        onChange({ ...exitLogic, [field]: value });
    };

    return (
        <div className="space-y-4">
            {/* Stop Loss & Take Profit Container */}
            <div className="space-y-8">
                {/* 1. HARD STOP (Structure) */}
                <div className="space-y-3">
                    <div className="flex items-center gap-2">
                        <div className="p-1 px-1.5 bg-red-500/10 rounded border border-red-500/20 text-red-500 font-black text-[10px]"><AlertOctagon className="w-3 h-3" /></div>
                        <h3 className="text-[10px] font-black text-foreground uppercase tracking-widest opacity-80">I. Hard Stop Logic</h3>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="bg-muted/30 border border-border rounded-xl p-4 transition-all">
                            <label className="block text-[10px] font-black text-muted-foreground uppercase tracking-widest mb-3 opacity-60">Stop Loss Type</label>
                            <select
                                className="w-full bg-background border border-border rounded-lg px-3 py-2 text-foreground text-sm font-bold focus:outline-none focus:border-red-500/50 transition-all"
                                value={exitLogic.stop_loss_type}
                                onChange={(e) => handleChange('stop_loss_type', e.target.value)}
                            >
                                <option value={RiskType.FIXED}>Fixed Price Level</option>
                                <option value={RiskType.PERCENT}>Percentage from Entry</option>
                                <option value={RiskType.STRUCTURE}>High of Day + Buffer</option>
                            </select>
                        </div>
                        <div className="bg-muted/30 border border-border rounded-xl p-4 relative transition-all">
                            <label className="block text-[10px] font-black text-muted-foreground uppercase tracking-widest mb-3 opacity-60">Value / Buffer</label>
                            <input
                                type="number"
                                className="w-full bg-background border border-border rounded-lg px-3 py-2 text-foreground text-sm font-black tabular-nums focus:outline-none focus:border-red-500/50 transition-all"
                                placeholder="0.00"
                                value={exitLogic.stop_loss_value}
                                onChange={(e) => handleChange('stop_loss_value', Number(e.target.value))}
                            />
                            <span className="absolute right-6 top-[3.2rem] text-muted-foreground/30 text-xs font-black">
                                {exitLogic.stop_loss_type === RiskType.PERCENT ? '%' : '$'}
                            </span>
                        </div>
                    </div>
                </div>

                <div className="h-px bg-border/50" />

                {/* 2. TAKE PROFIT & DILUTION (Catalyst) */}
                <div className="space-y-3">
                    <div className="flex items-center gap-2">
                        <div className="p-1 px-1.5 bg-green-500/10 rounded border border-green-500/20 text-green-500 font-black text-[10px]"><Target className="w-3 h-3" /></div>
                        <h3 className="text-[10px] font-black text-foreground uppercase tracking-widest opacity-80">II. Profit & Catalyst</h3>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="bg-muted/30 border border-border rounded-xl p-4 transition-all">
                            <label className="block text-[10px] font-black text-muted-foreground uppercase tracking-widest mb-3 opacity-60">Base Target</label>
                            <div className="relative">
                                <input
                                    type="number"
                                    className="w-full bg-background border border-border rounded-lg px-3 py-2 text-foreground text-sm font-black tabular-nums focus:outline-none focus:border-green-500/50 transition-all"
                                    placeholder="20"
                                    value={exitLogic.take_profit_value}
                                    onChange={(e) => handleChange('take_profit_value', Number(e.target.value))}
                                />
                                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground/30 text-xs font-black">%</span>
                            </div>
                        </div>

                        <div className="bg-blue-500/5 border border-blue-500/20 rounded-xl p-4 flex items-center justify-between transition-all">
                            <div className="space-y-1">
                                <span className="block text-[10px] font-black text-blue-400 uppercase tracking-widest opacity-90">Active Dilution Boost</span>
                                <span className="block text-[10px] text-blue-500/60 font-bold leading-tight">If S-3 Active, target +15%</span>
                            </div>
                            <button
                                onClick={() => handleChange('dilution_profit_boost', !exitLogic.dilution_profit_boost)}
                                className={`w-10 h-5 rounded-full relative transition-all shadow-inner ${exitLogic.dilution_profit_boost ? 'bg-blue-600' : 'bg-muted'}`}
                            >
                                <div className={`absolute top-1 w-3 h-3 bg-white rounded-full transition-transform shadow-sm ${exitLogic.dilution_profit_boost ? 'left-6' : 'left-1'}`} />
                            </button>
                        </div>
                    </div>
                </div>

                <div className="h-px bg-border/50" />

                {/* 3. TRAILING STOP (EMA13) */}
                <div className="space-y-3">
                    <div className="flex items-center gap-2">
                        <div className="p-1 px-1.5 bg-purple-500/10 rounded border border-purple-500/20 text-purple-500 font-black text-[10px]"><TrendingUp className="w-3 h-3" /></div>
                        <h3 className="text-[10px] font-black text-foreground uppercase tracking-widest opacity-80">III. Dynamic Trailing</h3>
                    </div>

                    <div className="bg-muted/30 border border-border rounded-xl p-4 flex items-center justify-between transition-all">
                        <div className="space-y-1">
                            <span className="block text-[10px] font-black text-foreground uppercase tracking-widest opacity-80">EMA 13 Trend Following</span>
                            <span className="block text-[10px] text-muted-foreground/50 font-bold">Close position if Price matches EMA 13</span>
                        </div>
                        <button
                            onClick={() => handleChange('trailing_stop_active', !exitLogic.trailing_stop_active)}
                            className={`w-10 h-5 rounded-full relative transition-all shadow-inner ${exitLogic.trailing_stop_active ? 'bg-purple-600' : 'bg-muted'}`}
                        >
                            <div className={`absolute top-1 w-3 h-3 bg-white rounded-full transition-transform shadow-sm ${exitLogic.trailing_stop_active ? 'left-6' : 'left-1'}`} />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
