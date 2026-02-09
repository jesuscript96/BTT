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
            <h3 className="text-foreground font-black mb-4 text-[10px] uppercase tracking-widest opacity-70">Universe Filters</h3>

            <div className="space-y-5">
                {/* Market Cap */}
                <div>
                    <label className="block text-[10px] font-black text-muted-foreground mb-2 uppercase tracking-widest opacity-60">Market Cap Range</label>
                    <div className="flex items-center gap-2">
                        <div className="relative w-full">
                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/50 text-xs font-bold">$</span>
                            <input
                                type="number"
                                value={filters.min_market_cap}
                                onChange={(e) => handleChange('min_market_cap', Number(e.target.value))}
                                className="w-full bg-muted/30 border border-border rounded-lg pl-6 pr-3 py-2 text-sm font-bold text-foreground focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 transition-all placeholder:text-muted-foreground/30 tabular-nums"
                                placeholder="Min"
                            />
                        </div>
                        <span className="text-muted-foreground/30 font-bold">-</span>
                        <div className="relative w-full">
                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/50 text-xs font-bold">$</span>
                            <input
                                type="number"
                                value={filters.max_market_cap}
                                onChange={(e) => handleChange('max_market_cap', Number(e.target.value))}
                                className="w-full bg-muted/30 border border-border rounded-lg pl-6 pr-3 py-2 text-sm font-bold text-foreground focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 transition-all placeholder:text-muted-foreground/30 tabular-nums"
                                placeholder="Max"
                            />
                        </div>
                    </div>
                </div>

                {/* Float - Placeholder */}
                <div>
                    <label className="block text-[10px] font-black text-muted-foreground mb-2 uppercase tracking-widest opacity-60">Max Float</label>
                    <input
                        type="number"
                        value={filters.max_shares_float || ''}
                        onChange={(e) => handleChange('max_shares_float', Number(e.target.value))}
                        className="w-full bg-muted/30 border border-border rounded-lg px-3 py-2 text-sm font-bold text-foreground focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 transition-all placeholder:text-muted-foreground/30 tabular-nums"
                        placeholder="Max Shares"
                    />
                </div>

                {/* Toggles */}
                <div className="space-y-3 pt-2">
                    <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-muted-foreground opacity-80">Require Shortable</span>
                        <input
                            type="checkbox"
                            checked={filters.require_shortable}
                            onChange={(e) => handleChange('require_shortable', e.target.checked)}
                            className="accent-blue-600 w-4 h-4 cursor-pointer"
                        />
                    </div>
                    <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-muted-foreground opacity-80">Exclude Dilution Risk</span>
                        <input
                            type="checkbox"
                            checked={filters.exclude_dilution}
                            onChange={(e) => handleChange('exclude_dilution', e.target.checked)}
                            className="accent-blue-600 w-4 h-4 cursor-pointer"
                        />
                    </div>
                </div>
            </div>
        </div>
    );
};
