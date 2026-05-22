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
        <div className="bg-ec-bg-base border-b border-ec-bg-surface p-4 sticky top-0 z-10">
            <div className="flex flex-col md:flex-row gap-4 items-end">
                {/* Ticker Search */}
                <div className="flex flex-col gap-1 w-full md:w-48">
                    <label className="text-xs text-ec-text-secondary uppercase font-semibold tracking-wider">Ticker</label>
                    <div className="relative">
                        <Search className="absolute left-2 top-2.5 h-4 w-4 text-ec-text-muted" />
                        <input
                            type="text"
                            placeholder="Search..."
                            value={ticker}
                            onChange={(e) => setTicker(e.target.value)}
                            className="w-full bg-ec-bg-surface border border-ec-bg-elevated text-ec-text-high pl-8 pr-3 py-2 rounded text-sm focus:outline-none focus:border-blue-500 transition-colors"
                        />
                    </div>
                </div>

                {/* Gap % Filter */}
                <div className="flex flex-col gap-1 w-full md:w-64">
                    <label className="text-xs text-ec-text-secondary uppercase font-semibold tracking-wider">Gap % Range</label>
                    <div className="flex items-center gap-2">
                        <input
                            type="number"
                            placeholder="Min %"
                            value={minGap}
                            onChange={(e) => setMinGap(e.target.value)}
                            className="w-full bg-ec-bg-surface border border-ec-bg-elevated text-ec-text-high px-3 py-2 rounded text-sm focus:outline-none focus:border-blue-500"
                        />
                        <span className="text-ec-text-primary">-</span>
                        <input
                            type="number"
                            placeholder="Max %"
                            value={maxGap}
                            onChange={(e) => setMaxGap(e.target.value)}
                            className="w-full bg-ec-bg-surface border border-ec-bg-elevated text-ec-text-high px-3 py-2 rounded text-sm focus:outline-none focus:border-blue-500"
                        />
                    </div>
                </div>

                {/* Volume Filter */}
                <div className="flex flex-col gap-1 w-full md:w-48">
                    <label className="text-xs text-ec-text-secondary uppercase font-semibold tracking-wider">Min Volume</label>
                    <input
                        type="number"
                        placeholder="100000"
                        value={minVolume}
                        onChange={(e) => setMinVolume(e.target.value)}
                        className="w-full bg-ec-bg-surface border border-ec-bg-elevated text-ec-text-high px-3 py-2 rounded text-sm focus:outline-none focus:border-blue-500"
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
                        className="flex items-center gap-2 bg-ec-bg-surface hover:bg-ec-bg-elevated text-ec-text-primary px-4 py-2 rounded text-sm font-medium border border-ec-bg-elevated transition-colors disabled:opacity-50"
                    >
                        <Download className="h-4 w-4" />
                        Export CSV
                    </button>
                </div>
            </div>
        </div>
    );
};
