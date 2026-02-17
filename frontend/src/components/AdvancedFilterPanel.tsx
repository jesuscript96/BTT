"use client";

import React, { useState } from "react";
import { Search, Filter, RefreshCw, Download, ChevronDown, ChevronUp } from "lucide-react";

interface AdvancedFilterPanelProps {
    filters: any;
    onFilterStateChange: (filters: any) => void;
    onFilter: (filters: any) => void;
    onExport: () => void;
    onSaveDataset: () => void;
    onLoadDataset: () => void;
    isLoading: boolean;
}

export const AdvancedFilterPanel: React.FC<AdvancedFilterPanelProps> = ({
    filters,
    onFilterStateChange,
    onFilter,
    onExport,
    onSaveDataset,
    onLoadDataset,
    isLoading
}) => {
    // Local state for UI responsiveness, synced with parent
    const [ticker, setTicker] = React.useState(filters.ticker || "");
    const [minGap, setMinGap] = React.useState(filters.min_gap_pct?.toString() || "");
    const [maxGap, setMaxGap] = React.useState(filters.max_gap_pct?.toString() || "");
    const [minVol, setMinVol] = React.useState(filters.min_rth_volume?.toString() || "");
    const [minPmVol, setMinPmVol] = React.useState(filters.min_pm_volume?.toString() || "5000000");
    const [startDate, setStartDate] = React.useState(filters.start_date || "");
    const [endDate, setEndDate] = React.useState(filters.end_date || "");
    const [m15Ret, setM15Ret] = React.useState(filters.min_m15_ret_pct?.toString() || "");
    const [dayRet, setDayRet] = React.useState(filters.min_rth_run_pct?.toString() || "");
    const [highSpike, setHighSpike] = React.useState(filters.min_high_spike_pct?.toString() || "");
    const [lowSpike, setLowSpike] = React.useState(filters.min_low_spike_pct?.toString() || "");
    const [hodAfter, setHodAfter] = React.useState(filters.hod_after || "");
    const [lodBefore, setLodBefore] = React.useState(filters.lod_before || "");
    const [isExpanded, setIsExpanded] = React.useState(true);

    // Sync from props (when loading datasets)
    React.useEffect(() => {
        setTicker(filters.ticker || "");
        setMinGap(filters.min_gap_pct?.toString() || "");
        setMaxGap(filters.max_gap_pct?.toString() || "");
        setMinVol(filters.min_rth_volume?.toString() || "");
        setMinPmVol(filters.min_pm_volume?.toString() || "");
        setStartDate(filters.start_date || "");
        setEndDate(filters.end_date || "");
        setM15Ret(filters.min_m15_ret_pct?.toString() || "");
        setDayRet(filters.min_rth_run_pct?.toString() || "");
        setHighSpike(filters.min_high_spike_pct?.toString() || "");
        setLowSpike(filters.min_low_spike_pct?.toString() || "");
        setHodAfter(filters.hod_after || "");
        setLodBefore(filters.lod_before || "");
    }, [filters]);

    // Report changes back to parent
    const updateParent = (key: string, value: any) => {
        onFilterStateChange({ ...filters, [key]: value });
    };

    const handleApply = () => {
        onFilter(filters);
    };

    return (
        <div className="bg-background/80 backdrop-blur-md border-b border-border sticky top-0 z-10 transition-all shadow-sm">
            <div className="p-4 flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <div className="relative">
                        <Search className="absolute left-2 top-2.5 h-4 w-4 text-zinc-400" />
                        <input
                            type="text"
                            placeholder="Ticker..."
                            value={ticker}
                            onChange={(e) => {
                                const val = e.target.value.toUpperCase();
                                setTicker(val);
                                updateParent('ticker', val);
                            }}
                            className="bg-muted/50 border border-border text-foreground pl-8 pr-3 py-2 rounded-lg text-sm w-32 focus:border-blue-500 outline-none shadow-sm transition-all placeholder:text-muted-foreground/50"
                        />
                    </div>

                    <div className="flex items-center gap-1">
                        <input
                            type="date"
                            value={startDate}
                            onChange={(e) => {
                                setStartDate(e.target.value);
                                updateParent('start_date', e.target.value);
                            }}
                            title="Start Date"
                            className="bg-muted/50 border border-border text-foreground px-2 py-2 rounded-lg text-sm focus:border-blue-500 outline-none shadow-sm transition-all w-32 [color-scheme:dark]"
                        />
                        <span className="text-muted-foreground/30">-</span>
                        <input
                            type="date"
                            value={endDate}
                            onChange={(e) => {
                                setEndDate(e.target.value);
                                updateParent('end_date', e.target.value);
                            }}
                            title="End Date"
                            className="bg-muted/50 border border-border text-foreground px-2 py-2 rounded-lg text-sm focus:border-blue-500 outline-none shadow-sm transition-all w-32 [color-scheme:dark]"
                        />
                    </div>

                    <div className="h-6 w-px bg-border" />

                    <div className="flex gap-2">
                        <FilterInput label="Min Gap" value={minGap} onChange={(v: string) => {
                            setMinGap(v);
                            updateParent('min_gap_pct', v ? parseFloat(v) : undefined);
                        }} />
                        <FilterInput label="Max Gap" value={maxGap} onChange={(v: string) => {
                            setMaxGap(v);
                            updateParent('max_gap_pct', v ? parseFloat(v) : undefined);
                        }} />
                        <FilterInput label="RTH Vol" value={minVol} onChange={(v: string) => {
                            setMinVol(v);
                            updateParent('min_rth_volume', v ? parseFloat(v) : undefined);
                        }} />
                        <FilterInput label="PM Vol" value={minPmVol} onChange={(v: string) => {
                            setMinPmVol(v);
                            updateParent('min_pm_volume', v ? parseFloat(v) : undefined);
                        }} />
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setIsExpanded(!isExpanded)}
                        className="p-2 text-zinc-400 hover:text-zinc-600 transition-colors"
                    >
                        {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    </button>
                    <button
                        onClick={handleApply}
                        disabled={isLoading}
                        className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-black tracking-tight transition-all flex items-center gap-2 shadow-md active:scale-95 disabled:opacity-50"
                    >
                        {isLoading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Filter className="h-4 w-4" />}
                        Run Scan
                    </button>
                    <button
                        onClick={onLoadDataset}
                        className="bg-card hover:bg-muted text-muted-foreground px-4 py-2 rounded-lg text-sm font-bold border border-border shadow-sm transition-all"
                        title="Load dataset"
                    >
                        <RefreshCw className="h-4 w-4" />
                    </button>
                    <button
                        onClick={onSaveDataset}
                        className="bg-card hover:bg-muted text-muted-foreground px-4 py-2 rounded-lg text-sm font-bold border border-border shadow-sm transition-all flex items-center gap-2"
                        title="Save dataset"
                    >
                        <Download className="h-4 w-4 rotate-180" />
                        Save Dataset
                    </button>
                    <button
                        onClick={onExport}
                        className="bg-card hover:bg-muted text-muted-foreground px-4 py-2 rounded-lg text-sm font-bold border border-border shadow-sm transition-all"
                        title="Export CSV"
                    >
                        <Download className="h-4 w-4" />
                    </button>
                </div>
            </div>

            {/* {isExpanded && (
                <div className="px-4 pb-4 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 border-t border-border pt-4">
                    <CategoryGroup title="Returns">
                        <FilterInput label="M15 Ret %" value={m15Ret} onChange={(v: string) => {
                            setM15Ret(v);
                            updateParent('min_m15_ret_pct', v ? parseFloat(v) : undefined);
                        }} />
                        <FilterInput label="Day Ret %" value={dayRet} onChange={(v: string) => {
                            setDayRet(v);
                            updateParent('min_rth_run_pct', v ? parseFloat(v) : undefined);
                        }} />
                    </CategoryGroup>
                    <CategoryGroup title="Volatility">
                        <FilterInput label="High Spike %" value={highSpike} onChange={(v: string) => {
                            setHighSpike(v);
                            updateParent('min_high_spike_pct', v ? parseFloat(v) : undefined);
                        }} />
                        <FilterInput label="Low Spike %" value={lowSpike} onChange={(v: string) => {
                            setLowSpike(v);
                            updateParent('min_low_spike_pct', v ? parseFloat(v) : undefined);
                        }} />
                    </CategoryGroup>
                    <CategoryGroup title="Time">
                        <FilterInput label="HOD After" value={hodAfter} onChange={(v: string) => {
                            setHodAfter(v);
                            updateParent('hod_after', v || undefined);
                        }} />
                        <FilterInput label="LOD Before" value={lodBefore} onChange={(v: string) => {
                            setLodBefore(v);
                            updateParent('lod_before', v || undefined);
                        }} />
                    </CategoryGroup>
                </div>
            )} */}
        </div>
    );
};

const FilterInput = ({ label, value, checked, onChange, isCheck = false }: any) => (
    <div className="flex flex-col gap-1">
        <span className="text-[10px] text-zinc-400 uppercase font-black tracking-widest">{label}</span>
        {isCheck ? (
            <input
                type="checkbox"
                checked={checked}
                onChange={(e) => onChange(e.target.checked)}
                className="h-4 w-4 rounded border-border bg-muted text-blue-600 focus:ring-blue-500 cursor-pointer accent-blue-600"
            />
        ) : (
            <input
                type="text"
                placeholder="-"
                value={value}
                onChange={(e) => onChange(e.target.value)}
                className="bg-muted/50 border border-border text-foreground px-2 py-1 rounded text-xs w-20 focus:border-blue-500 outline-none shadow-inner placeholder:text-muted-foreground/30 font-bold tabular-nums"
            />
        )}
    </div>
);

const CategoryGroup = ({ title, children }: any) => (
    <div className="space-y-2">
        <h4 className="text-[10px] font-black text-blue-500/80 uppercase tracking-widest border-l-2 border-blue-500 pl-2">{title}</h4>
        <div className="flex flex-wrap gap-2 text-foreground">
            {children}
        </div>
    </div>
)
