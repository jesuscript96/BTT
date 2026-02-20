
import React from 'react';
import { UniverseFilters } from '@/types/strategy';

interface Props {
    filters: UniverseFilters;
    onChange: (filters: UniverseFilters) => void;
}

export const UniverseFiltersComponent: React.FC<Props> = ({ filters, onChange }) => {
    const handleChange = (key: keyof UniverseFilters, value: any) => {
        onChange({ ...filters, [key]: value });
    };

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
                <div>
                    <label className="block text-[10px] font-black text-muted-foreground uppercase tracking-widest mb-2 opacity-50">Min Market Cap</label>
                    <input
                        type="number"
                        value={filters.min_market_cap || ''}
                        onChange={(e) => handleChange('min_market_cap', e.target.value ? Number(e.target.value) : undefined)}
                        className="w-full bg-muted/20 border border-border/50 rounded-lg px-3 py-2 text-sm font-medium text-foreground focus:outline-none focus:ring-1 focus:ring-green-500/30 focus:border-green-500/50 transition-all placeholder:text-muted-foreground/20"
                        placeholder="No limit"
                    />
                </div>
                <div>
                    <label className="block text-[10px] font-black text-muted-foreground uppercase tracking-widest mb-2 opacity-50">Max Market Cap</label>
                    <input
                        type="number"
                        value={filters.max_market_cap || ''}
                        onChange={(e) => handleChange('max_market_cap', e.target.value ? Number(e.target.value) : undefined)}
                        className="w-full bg-muted/20 border border-border/50 rounded-lg px-3 py-2 text-sm font-medium text-foreground focus:outline-none focus:ring-1 focus:ring-green-500/30 focus:border-green-500/50 transition-all placeholder:text-muted-foreground/20"
                        placeholder="No limit"
                    />
                </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
                <div>
                    <label className="block text-[10px] font-black text-muted-foreground uppercase tracking-widest mb-2 opacity-50">Min Price</label>
                    <input
                        type="number"
                        value={filters.min_price || ''}
                        onChange={(e) => handleChange('min_price', e.target.value ? Number(e.target.value) : undefined)}
                        className="w-full bg-muted/20 border border-border/50 rounded-lg px-3 py-2 text-sm font-medium text-foreground focus:outline-none focus:ring-1 focus:ring-green-500/30 focus:border-green-500/50 transition-all placeholder:text-muted-foreground/20"
                        placeholder="No limit"
                    />
                </div>
                <div>
                    <label className="block text-[10px] font-black text-muted-foreground uppercase tracking-widest mb-2 opacity-50">Max Price</label>
                    <input
                        type="number"
                        value={filters.max_price || ''}
                        onChange={(e) => handleChange('max_price', e.target.value ? Number(e.target.value) : undefined)}
                        className="w-full bg-muted/20 border border-border/50 rounded-lg px-3 py-2 text-sm font-medium text-foreground focus:outline-none focus:ring-1 focus:ring-green-500/30 focus:border-green-500/50 transition-all placeholder:text-muted-foreground/20"
                        placeholder="No limit"
                    />
                </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
                <div>
                    <label className="block text-[10px] font-black text-muted-foreground uppercase tracking-widest mb-2 opacity-50">Min Volume</label>
                    <input
                        type="number"
                        value={filters.min_volume || ''}
                        onChange={(e) => handleChange('min_volume', e.target.value ? Number(e.target.value) : undefined)}
                        className="w-full bg-muted/20 border border-border/50 rounded-lg px-3 py-2 text-sm font-medium text-foreground focus:outline-none focus:ring-1 focus:ring-green-500/30 focus:border-green-500/50 transition-all placeholder:text-muted-foreground/20"
                        placeholder="No limit"
                    />
                </div>
                <div>
                    <label className="block text-[10px] font-black text-muted-foreground uppercase tracking-widest mb-2 opacity-50">Max Float</label>
                    <input
                        type="number"
                        value={filters.max_shares_float || ''}
                        onChange={(e) => handleChange('max_shares_float', e.target.value ? Number(e.target.value) : undefined)}
                        className="w-full bg-muted/20 border border-border/50 rounded-lg px-3 py-2 text-sm font-medium text-foreground focus:outline-none focus:ring-1 focus:ring-green-500/30 focus:border-green-500/50 transition-all placeholder:text-muted-foreground/20"
                        placeholder="No limit"
                    />
                </div>
            </div>

            <div className="pt-2 space-y-3">
                <label className="flex items-center gap-3 cursor-pointer group">
                    <div className={`w-4 h-4 rounded border flex items-center justify-center transition-all ${filters.require_shortable ? 'bg-green-500 border-green-500' : 'border-muted-foreground/50 group-hover:border-green-500/50'}`}>
                        {filters.require_shortable && <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>}
                    </div>
                    <input
                        type="checkbox"
                        className="hidden"
                        checked={filters.require_shortable}
                        onChange={(e) => handleChange('require_shortable', e.target.checked)}
                    />
                    <span className="text-xs font-bold text-muted-foreground group-hover:text-foreground transition-colors">Require Shortable (HTB/ETB)</span>
                </label>

                <label className="flex items-center gap-3 cursor-pointer group">
                    <div className={`w-4 h-4 rounded border flex items-center justify-center transition-all ${filters.exclude_dilution ? 'bg-green-500 border-green-500' : 'border-muted-foreground/50 group-hover:border-green-500/50'}`}>
                        {filters.exclude_dilution && <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>}
                    </div>
                    <input
                        type="checkbox"
                        className="hidden"
                        checked={filters.exclude_dilution}
                        onChange={(e) => handleChange('exclude_dilution', e.target.checked)}
                    />
                    <span className="text-xs font-bold text-muted-foreground group-hover:text-foreground transition-colors">Exclude Dilution (S-3/F-3)</span>
                </label>
            </div>
        </div>
    );
};
