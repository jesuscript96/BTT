"use client";

import React, { useState } from "react";
import { Search, Filter, RefreshCw, Download, ChevronDown, ChevronUp } from "lucide-react";

interface AdvancedFilterPanelProps {
    onFilter: (filters: any) => void;
    onExport: () => void;
    onSaveDataset: () => void;
    onLoadDataset: () => void;
    isLoading: boolean;
}

export const AdvancedFilterPanel: React.FC<AdvancedFilterPanelProps> = ({
    onFilter,
    onExport,
    onSaveDataset,
    onLoadDataset,
    isLoading
}) => {
    const [ticker, setTicker] = useState("");
    const [minGap, setMinGap] = useState("");
    const [maxGap, setMaxGap] = useState("");
    const [minVol, setMinVol] = useState("");
    const [startDate, setStartDate] = useState("");
    const [endDate, setEndDate] = useState("");
    const [m15Ret, setM15Ret] = useState("");
    const [dayRet, setDayRet] = useState("");
    const [highSpike, setHighSpike] = useState("");
    const [lowSpike, setLowSpike] = useState("");
    const [hodAfter, setHodAfter] = useState("");
    const [lodBefore, setLodBefore] = useState("");
    const [openLtVwap, setOpenLtVwap] = useState(false);
    const [isExpanded, setIsExpanded] = useState(true);

    const handleApply = () => {
        onFilter({
            ticker: ticker || undefined,
            min_gap_pct: minGap ? parseFloat(minGap) : undefined,
            max_gap_pct: maxGap ? parseFloat(maxGap) : undefined,
            min_rth_volume: minVol ? parseFloat(minVol) : undefined,
            min_m15_ret_pct: m15Ret ? parseFloat(m15Ret) : undefined,
            min_rth_run_pct: dayRet ? parseFloat(dayRet) : undefined,
            min_high_spike_pct: highSpike ? parseFloat(highSpike) : undefined,
            min_low_spike_pct: lowSpike ? parseFloat(lowSpike) : undefined,
            hod_after: hodAfter || undefined,
            lod_before: lodBefore || undefined,
            open_lt_vwap: openLtVwap || undefined,
            start_date: startDate || undefined,
            end_date: endDate || undefined
        });
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
                            onChange={(e) => setTicker(e.target.value)}
                            className="bg-muted/50 border border-border text-foreground pl-8 pr-3 py-2 rounded-lg text-sm w-32 focus:border-blue-500 outline-none shadow-sm transition-all placeholder:text-muted-foreground/50"
                        />
                    </div>

                    <div className="flex items-center gap-1">
                        <input
                            type="date"
                            value={startDate}
                            onChange={(e) => setStartDate(e.target.value)}
                            title="Start Date"
                            className="bg-muted/50 border border-border text-foreground px-2 py-2 rounded-lg text-sm focus:border-blue-500 outline-none shadow-sm transition-all w-32 [color-scheme:dark]"
                        />
                        <span className="text-muted-foreground/30">-</span>
                        <input
                            type="date"
                            value={endDate}
                            onChange={(e) => setEndDate(e.target.value)}
                            title="End Date"
                            className="bg-muted/50 border border-border text-foreground px-2 py-2 rounded-lg text-sm focus:border-blue-500 outline-none shadow-sm transition-all w-32 [color-scheme:dark]"
                        />
                    </div>

                    <div className="h-6 w-px bg-border" />

                    <div className="flex gap-2">
                        <FilterInput label="Min Gap" value={minGap} onChange={setMinGap} />
                        <FilterInput label="Max Gap" value={maxGap} onChange={setMaxGap} />
                        <FilterInput label="Min Vol" value={minVol} onChange={setMinVol} />
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

            {isExpanded && (
                <div className="px-4 pb-4 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 border-t border-border pt-4">
                    <CategoryGroup title="Returns">
                        <FilterInput label="M15 Ret %" value={m15Ret} onChange={setM15Ret} />
                        <FilterInput label="Day Ret %" value={dayRet} onChange={setDayRet} />
                    </CategoryGroup>
                    <CategoryGroup title="Volatility">
                        <FilterInput label="High Spike %" value={highSpike} onChange={setHighSpike} />
                        <FilterInput label="Low Spike %" value={lowSpike} onChange={setLowSpike} />
                    </CategoryGroup>
                    <CategoryGroup title="Time">
                        <FilterInput label="HOD After" value={hodAfter} onChange={setHodAfter} />
                        <FilterInput label="LOD Before" value={lodBefore} onChange={setLodBefore} />
                    </CategoryGroup>
                    <CategoryGroup title="VWAP">
                        <FilterInput label="Close > VWAP" value="" isCheck />
                        <FilterInput label="Open < VWAP" checked={openLtVwap} onChange={(v: any) => setOpenLtVwap(v)} isCheck />
                    </CategoryGroup>
                </div>
            )}
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
