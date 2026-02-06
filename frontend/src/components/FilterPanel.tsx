"use client";

import React, { useState } from "react";
import { Search, Filter, RefreshCw, Download } from "lucide-react";

interface FilterPanelProps {
    onFilter: (filters: any) => void;
    onExport: () => void;
    isLoading: boolean;
}

export const FilterPanel: React.FC<FilterPanelProps> = ({ onFilter, onExport, isLoading }) => {
    const [minGap, setMinGap] = useState("");
    const [maxGap, setMaxGap] = useState("");
    const [minVolume, setMinVolume] = useState("");
    const [ticker, setTicker] = useState("");

    const handleApply = () => {
        onFilter({
            min_gap_percent: minGap ? parseFloat(minGap) : undefined,
            max_gap_percent: maxGap ? parseFloat(maxGap) : undefined,
            min_volume: minVolume ? parseFloat(minVolume) : undefined,
            ticker: ticker || undefined,
        });
    };

    return (
        <div className="bg-zinc-900 border-b border-zinc-800 p-4 sticky top-0 z-10">
            <div className="flex flex-col md:flex-row gap-4 items-end">
                {/* Ticker Search */}
                <div className="flex flex-col gap-1 w-full md:w-48">
                    <label className="text-xs text-zinc-400 uppercase font-semibold tracking-wider">Ticker</label>
                    <div className="relative">
                        <Search className="absolute left-2 top-2.5 h-4 w-4 text-zinc-500" />
                        <input
                            type="text"
                            placeholder="Search..."
                            value={ticker}
                            onChange={(e) => setTicker(e.target.value)}
                            className="w-full bg-zinc-800 border border-zinc-700 text-zinc-100 pl-8 pr-3 py-2 rounded text-sm focus:outline-none focus:border-blue-500 transition-colors"
                        />
                    </div>
                </div>

                {/* Gap % Filter */}
                <div className="flex flex-col gap-1 w-full md:w-64">
                    <label className="text-xs text-zinc-400 uppercase font-semibold tracking-wider">Gap % Range</label>
                    <div className="flex items-center gap-2">
                        <input
                            type="number"
                            placeholder="Min %"
                            value={minGap}
                            onChange={(e) => setMinGap(e.target.value)}
                            className="w-full bg-zinc-800 border border-zinc-700 text-zinc-100 px-3 py-2 rounded text-sm focus:outline-none focus:border-blue-500"
                        />
                        <span className="text-zinc-600">-</span>
                        <input
                            type="number"
                            placeholder="Max %"
                            value={maxGap}
                            onChange={(e) => setMaxGap(e.target.value)}
                            className="w-full bg-zinc-800 border border-zinc-700 text-zinc-100 px-3 py-2 rounded text-sm focus:outline-none focus:border-blue-500"
                        />
                    </div>
                </div>

                {/* Volume Filter */}
                <div className="flex flex-col gap-1 w-full md:w-48">
                    <label className="text-xs text-zinc-400 uppercase font-semibold tracking-wider">Min Volume</label>
                    <input
                        type="number"
                        placeholder="100000"
                        value={minVolume}
                        onChange={(e) => setMinVolume(e.target.value)}
                        className="w-full bg-zinc-800 border border-zinc-700 text-zinc-100 px-3 py-2 rounded text-sm focus:outline-none focus:border-blue-500"
                    />
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 ml-auto">
                    <button
                        onClick={handleApply}
                        disabled={isLoading}
                        className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded text-sm font-medium transition-colors disabled:opacity-50"
                    >
                        {isLoading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Filter className="h-4 w-4" />}
                        Filter
                    </button>
                    <button
                        onClick={onExport}
                        disabled={isLoading}
                        className="flex items-center gap-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 px-4 py-2 rounded text-sm font-medium border border-zinc-700 transition-colors disabled:opacity-50"
                    >
                        <Download className="h-4 w-4" />
                        Export CSV
                    </button>
                </div>
            </div>
        </div>
    );
};
