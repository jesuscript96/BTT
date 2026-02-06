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
                        <div className="p-1 bg-red-100 rounded text-red-600"><AlertOctagon className="w-3 h-3" /></div>
                        <h3 className="text-xs font-black text-zinc-900 uppercase tracking-widest">I. Hard Stop Logic</h3>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="bg-zinc-50 border border-zinc-200 rounded-lg p-4">
                            <label className="block text-[10px] font-bold text-zinc-500 uppercase tracking-widest mb-3">Stop Loss Type</label>
                            <select
                                className="w-full bg-white border border-zinc-200 rounded-md px-3 py-2 text-zinc-900 text-sm font-semibold focus:outline-none focus:border-red-500"
                                value={exitLogic.stop_loss_type}
                                onChange={(e) => handleChange('stop_loss_type', e.target.value)}
                            >
                                <option value="Fixed Price">Fixed Price Level</option>
                                <option value="Percentage">Percentage from Entry</option>
                                <option value="Structure">High of Day + Buffer</option>
                            </select>
                        </div>
                        <div className="bg-zinc-50 border border-zinc-200 rounded-lg p-4 relative">
                            <label className="block text-[10px] font-bold text-zinc-500 uppercase tracking-widest mb-3">Value / Buffer</label>
                            <input
                                type="number"
                                className="w-full bg-white border border-zinc-200 rounded-md px-3 py-2 text-zinc-900 text-sm font-bold focus:outline-none focus:border-red-500"
                                placeholder="0.00"
                                value={exitLogic.stop_loss_value}
                                onChange={(e) => handleChange('stop_loss_value', Number(e.target.value))}
                            />
                            <span className="absolute right-6 top-[3.2rem] text-zinc-400 text-xs font-bold">
                                {exitLogic.stop_loss_type === RiskType.PERCENT ? '%' : '$'}
                            </span>
                        </div>
                    </div>
                </div>

                <div className="h-px bg-zinc-100" />

                {/* 2. TAKE PROFIT & DILUTION (Catalyst) */}
                <div className="space-y-3">
                    <div className="flex items-center gap-2">
                        <div className="p-1 bg-green-100 rounded text-green-600"><Target className="w-3 h-3" /></div>
                        <h3 className="text-xs font-black text-zinc-900 uppercase tracking-widest">II. Profit & Catalyst</h3>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="bg-zinc-50 border border-zinc-200 rounded-lg p-4">
                            <label className="block text-[10px] font-bold text-zinc-500 uppercase tracking-widest mb-3">Base Target</label>
                            <div className="relative">
                                <input
                                    type="number"
                                    className="w-full bg-white border border-zinc-200 rounded-md px-3 py-2 text-zinc-900 text-sm font-bold focus:outline-none focus:border-green-500"
                                    placeholder="20"
                                    value={exitLogic.take_profit_value}
                                    onChange={(e) => handleChange('take_profit_value', Number(e.target.value))}
                                />
                                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 text-xs font-bold">%</span>
                            </div>
                        </div>

                        <div className="bg-blue-50/50 border border-blue-100 rounded-lg p-4 flex items-center justify-between">
                            <div className="space-y-1">
                                <span className="block text-xs font-black text-blue-900">Active Dilution Boost</span>
                                <span className="block text-[10px] text-blue-700 leading-tight">If S-3 Active, target +15%</span>
                            </div>
                            <button
                                onClick={() => handleChange('dilution_profit_boost', !exitLogic.dilution_profit_boost)}
                                className={`w-10 h-5 rounded-full relative transition-colors ${exitLogic.dilution_profit_boost ? 'bg-blue-600' : 'bg-zinc-300'}`}
                            >
                                <div className={`absolute top-1 w-3 h-3 bg-white rounded-full transition-transform ${exitLogic.dilution_profit_boost ? 'left-6' : 'left-1'}`} />
                            </button>
                        </div>
                    </div>
                </div>

                <div className="h-px bg-zinc-100" />

                {/* 3. TRAILING STOP (EMA13) */}
                <div className="space-y-3">
                    <div className="flex items-center gap-2">
                        <div className="p-1 bg-purple-100 rounded text-purple-600"><TrendingUp className="w-3 h-3" /></div>
                        <h3 className="text-xs font-black text-zinc-900 uppercase tracking-widest">III. Dynamic Trailing</h3>
                    </div>

                    <div className="bg-zinc-50 border border-zinc-200 rounded-lg p-4 flex items-center justify-between">
                        <div className="space-y-1">
                            <span className="block text-xs font-black text-zinc-900">EMA 13 Trend Following</span>
                            <span className="block text-[10px] text-zinc-500">Close position if Price matches EMA 13</span>
                        </div>
                        <button
                            onClick={() => handleChange('trailing_stop_active', !exitLogic.trailing_stop_active)}
                            className={`w-10 h-5 rounded-full relative transition-colors ${exitLogic.trailing_stop_active ? 'bg-purple-600' : 'bg-zinc-300'}`}
                        >
                            <div className={`absolute top-1 w-3 h-3 bg-white rounded-full transition-transform ${exitLogic.trailing_stop_active ? 'left-6' : 'left-1'}`} />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
