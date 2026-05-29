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

export const AdvancedFilterPanel: React.FC<AdvancedFilterPanelProps> = React.memo(({
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
    const [minGap, setMinGap] = React.useState(filters.min_gap_pct?.toString() || "20");
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
        setMinGap(filters.min_gap_pct?.toString() || "20");
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
        <div style={{
            display: 'flex',
            alignItems: 'center',
            background: 'var(--color-ec-bg-sidebar)',
            borderBottom: '0.5px solid var(--color-ec-border)',
            padding: '0 16px',
            minHeight: 44,
        }}>
            <div style={{ display: 'flex', width: '100%', alignItems: 'center', justifyContent: 'space-between', gap: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    {/* Ticker Input */}
                    <div style={{
                        display: 'flex', alignItems: 'center', gap: 6,
                        background: 'var(--color-ec-bg-sidebar)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 5, padding: '0 10px', height: 30, width: 160,
                    }}>
                        <Search size={13} style={{ color: 'var(--color-ec-text-muted)', flexShrink: 0 }} />
                        <input
                            type="text"
                            placeholder="Ticker..."
                            value={ticker}
                            onChange={(e) => {
                                const val = e.target.value.toUpperCase();
                                setTicker(val);
                                updateParent('ticker', val);
                            }}
                            style={{
                                background: 'transparent', border: 'none', outline: 'none',
                                fontFamily: "'General Sans', sans-serif", fontSize: 12, fontWeight: 400,
                                color: 'var(--color-ec-text-primary)', width: '100%',
                            }}
                        />
                    </div>

                    {/* Date Pickers */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <input
                            type="date" value={startDate}
                            onChange={(e) => { setStartDate(e.target.value); updateParent('start_date', e.target.value); }}
                            title="Start Date"
                            style={{ background: 'var(--color-ec-bg-sidebar)', border: '0.5px solid var(--color-ec-border)', borderRadius: 5, padding: '0 8px', height: 30, fontFamily: "'General Sans', sans-serif", fontSize: 12, color: 'var(--color-ec-text-primary)', outline: 'none', width: 110, colorScheme: 'dark' }}
                        />
                        <span style={{ color: 'var(--color-ec-text-muted)', fontSize: 12, padding: '0 2px' }}>—</span>
                        <input
                            type="date" value={endDate}
                            onChange={(e) => { setEndDate(e.target.value); updateParent('end_date', e.target.value); }}
                            title="End Date"
                            style={{ background: 'var(--color-ec-bg-sidebar)', border: '0.5px solid var(--color-ec-border)', borderRadius: 5, padding: '0 8px', height: 30, fontFamily: "'General Sans', sans-serif", fontSize: 12, color: 'var(--color-ec-text-primary)', outline: 'none', width: 110, colorScheme: 'dark' }}
                        />
                    </div>

                    {/* Divider */}
                    <div style={{ width: '0.5px', height: 20, background: 'var(--color-ec-border)', margin: '0 4px', flexShrink: 0 }} />

                    {/* Filter Boxes */}
                    <div style={{ display: 'flex', gap: 4 }}>
                        <FilterInput label="Min Gap" value={minGap} onChange={(v: string) => { const n = parseFloat(v); const val = v && !isNaN(n) && n < 20 ? "20" : v; setMinGap(val); updateParent('min_gap_pct', val ? parseFloat(val) : undefined); }} />
                        <FilterInput label="Max Gap" value={maxGap} onChange={(v: string) => { setMaxGap(v); updateParent('max_gap_pct', v ? parseFloat(v) : undefined); }} />
                        <FilterInput label="RTH Vol" value={minVol} onChange={(v: string) => { setMinVol(v); updateParent('min_rth_volume', v ? parseFloat(v) : undefined); }} />
                        <FilterInput label="PM Vol" value={minPmVol} onChange={(v: string) => { setMinPmVol(v); updateParent('min_pm_volume', v ? parseFloat(v) : undefined); }} />
                    </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {/* Chevron Icon Button */}
                    <button
                        onClick={() => setIsExpanded(!isExpanded)}
                        style={{
                            height: 30, width: 30, padding: 0,
                            background: 'var(--color-ec-bg-surface)',
                            border: '0.5px solid var(--color-ec-border)', borderRadius: 5,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            color: 'var(--color-ec-text-secondary)', cursor: 'pointer',
                        }}
                    >
                        {isExpanded ? <ChevronUp size={14} strokeWidth={1.5} /> : <ChevronDown size={14} strokeWidth={1.5} />}
                    </button>
                    {/* Primary Button */}
                    <button
                        onClick={handleApply} disabled={isLoading}
                        style={{
                            height: 30, padding: '0 14px',
                            background: 'var(--color-ec-copper)',
                            color: 'var(--color-ec-copper-text)', border: 'none', borderRadius: 5,
                            fontFamily: "'General Sans', sans-serif", fontSize: 11, fontWeight: 700,
                            letterSpacing: '1.2px', textTransform: 'uppercase', cursor: 'pointer',
                            display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap',
                        }}
                    >
                        {isLoading ? <RefreshCw size={14} strokeWidth={1.5} className="animate-spin" /> : <Filter size={14} strokeWidth={1.5} />}
                        Run Scan
                    </button>
                    {/* Secondary Buttons */}
                    <SecondaryButton onClick={onLoadDataset} title="Load dataset">
                        <RefreshCw size={14} strokeWidth={1.5} />
                    </SecondaryButton>
                    <SecondaryButton onClick={onSaveDataset} title="Save dataset">
                        <Download size={14} strokeWidth={1.5} style={{ transform: 'rotate(180deg)' }} />
                        <span>Save</span>
                    </SecondaryButton>
                    <SecondaryButton onClick={onExport} title="Export CSV">
                        <Download size={14} strokeWidth={1.5} />
                    </SecondaryButton>
                </div>
            </div>
        </div>
    );
});

const SecondaryButton = ({ onClick, title, children }: any) => (
    <button
        onClick={onClick}
        title={title || ''}
        style={{
            height: 30,
            padding: '0 10px',
            background: 'var(--color-ec-bg-surface)',
            border: '0.5px solid var(--color-ec-border)',
            borderRadius: 5,
            fontFamily: "'General Sans', sans-serif",
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: '1.2px',
            textTransform: 'uppercase',
            color: 'var(--color-ec-text-secondary)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 5,
        }}
    >
        {children}
    </button>
);

const FilterInput = ({ label, value, checked, onChange, isCheck = false }: any) => (
    <div style={{
        display: 'flex', flexDirection: 'column', justifyContent: 'center',
        gap: 1, paddingLeft: 10,
        borderLeft: '0.5px solid var(--color-ec-border)',
        height: 30,
    }}>
        <span style={{
            fontFamily: "'General Sans', sans-serif", fontSize: 9, fontWeight: 700,
            textTransform: 'uppercase', letterSpacing: 2,
            color: 'var(--color-ec-text-muted)', lineHeight: 1,
        }}>
            {label}
        </span>
        {isCheck ? (
            <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 rounded cursor-pointer" />
        ) : (
            <input
                type="text"
                placeholder={value ? undefined : '—'}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                style={{
                    background: 'transparent', border: 'none', outline: 'none',
                    fontFamily: "'General Sans', sans-serif", fontSize: 13, fontWeight: 600,
                    letterSpacing: '-0.3px', color: 'var(--color-ec-text-primary)',
                    width: 80, padding: 0, lineHeight: 1,
                }}
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
