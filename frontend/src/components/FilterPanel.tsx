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
                        style={{
                            background: 'var(--color-ec-copper)',
                            color: 'var(--color-ec-copper-text)',
                            border: 'none',
                            borderRadius: 5,
                            padding: '9px 16px',
                            fontFamily: "'General Sans', sans-serif",
                            fontSize: 11,
                            fontWeight: 700,
                            letterSpacing: '1.2px',
                            textTransform: 'uppercase',
                            cursor: isLoading ? 'default' : 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 8,
                            opacity: isLoading ? 0.5 : 1,
                        }}
                    >
                        {isLoading ? <RefreshCw size={14} strokeWidth={1.5} className="animate-spin" /> : <Filter size={14} strokeWidth={1.5} />}
                        Filter
                    </button>
                    <button
                        onClick={onExport}
                        disabled={isLoading}
                        style={{
                            background: 'var(--color-ec-bg-surface)',
                            border: '0.5px solid var(--color-ec-border)',
                            borderRadius: 5,
                            padding: '9px 13px',
                            fontFamily: "'General Sans', sans-serif",
                            fontSize: 11,
                            fontWeight: 600,
                            textTransform: 'uppercase',
                            letterSpacing: '1.2px',
                            color: 'var(--color-ec-text-secondary)',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 8,
                        }}
                    >
                        <Download size={14} strokeWidth={1.5} />
                        Export
                    </button>
                </div>
            </div>
        </div>
    );
};
