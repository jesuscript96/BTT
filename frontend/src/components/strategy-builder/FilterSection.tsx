import React from 'react';
import { FilterSettings } from '@/types/strategy';

interface Props {
    filters: FilterSettings;
    onChange: (filters: FilterSettings) => void;
}

export const FilterSection: React.FC<Props> = ({ filters, onChange }) => {
    const handleChange = (field: keyof FilterSettings, value: string | number | boolean) => {
        onChange({ ...filters, [field]: value });
    };

    return (
        <div>
            <h3 className="text-zinc-100 font-semibold mb-4 text-sm uppercase tracking-wider">Universe Filters</h3>

            <div className="space-y-5">
                {/* Market Cap */}
                <div>
                    <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wide">Market Cap Range</label>
                    <div className="flex items-center gap-2">
                        <div className="relative w-full">
                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400 text-xs font-bold">$</span>
                            <input
                                type="number"
                                value={filters.min_market_cap}
                                onChange={(e) => handleChange('min_market_cap', Number(e.target.value))}
                                className="w-full bg-zinc-50 border border-zinc-200 rounded-lg pl-6 pr-3 py-2 text-sm font-bold text-zinc-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 transition-all"
                                placeholder="Min"
                            />
                        </div>
                        <span className="text-zinc-400 font-bold">-</span>
                        <div className="relative w-full">
                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400 text-xs font-bold">$</span>
                            <input
                                type="number"
                                value={filters.max_market_cap}
                                onChange={(e) => handleChange('max_market_cap', Number(e.target.value))}
                                className="w-full bg-zinc-50 border border-zinc-200 rounded-lg pl-6 pr-3 py-2 text-sm font-bold text-zinc-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 transition-all"
                                placeholder="Max"
                            />
                        </div>
                    </div>
                </div>

                {/* Float - Placeholder */}
                <div>
                    <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wide">Max Float</label>
                    <input
                        type="number"
                        value={filters.max_shares_float || ''}
                        onChange={(e) => handleChange('max_shares_float', Number(e.target.value))}
                        className="w-full bg-zinc-50 border border-zinc-200 rounded-lg px-3 py-2 text-sm font-bold text-zinc-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 transition-all"
                        placeholder="Max Shares"
                    />
                </div>

                {/* Toggles */}
                <div className="space-y-3 pt-2">
                    <div className="flex items-center justify-between">
                        <span className="text-sm text-zinc-400">Require Shortable</span>
                        <input
                            type="checkbox"
                            checked={filters.require_shortable}
                            onChange={(e) => handleChange('require_shortable', e.target.checked)}
                            className="accent-blue-600 w-4 h-4"
                        />
                    </div>
                    <div className="flex items-center justify-between">
                        <span className="text-sm text-zinc-400">Exclude Dilution Risk</span>
                        <input
                            type="checkbox"
                            checked={filters.exclude_dilution}
                            onChange={(e) => handleChange('exclude_dilution', e.target.checked)}
                            className="accent-blue-600 w-4 h-4"
                        />
                    </div>
                </div>
            </div>
        </div>
    );
};
