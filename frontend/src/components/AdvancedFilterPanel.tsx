"use client";

import React, { useState } from "react";
import { Filter, RefreshCw, Download, ChevronDown, ChevronUp, X } from "lucide-react";

interface AdvancedFilterPanelProps {
    filters: any;
    onFilterStateChange: (filters: any) => void;
    onFilter: (filters: any) => void;
    onExport: () => void;
    onSaveDataset: () => void;
    onLoadDataset: () => void;
    isLoading: boolean;
    isFilterBuilderOpen?: boolean;
    onToggleFilterBuilder?: () => void;
    activeRules?: any[];
    onRemoveRule?: (id: string) => void;
    showScanResults: boolean;
    onToggleScanResults: () => void;
}

const parseVolume = (value: string): number | undefined => {
    if (!value) return undefined;
    const clean = value.trim().toLowerCase();
    
    // Support either clean numbers or numbers ending with 'm' (e.g. "1.5" or "1.5m" -> 1,500,000)
    const numericStr = clean.endsWith('m') ? clean.slice(0, -1) : clean;
    const num = parseFloat(numericStr);
    return isNaN(num) ? undefined : num * 1000000;
};

const formatVolume = (val: any): string => {
    if (val === undefined || val === null || val === '') return '';
    const num = parseFloat(val);
    if (isNaN(num)) return '';
    // Format to millions (e.g. 1500000 -> "1.5", 500000 -> "0.5")
    return (num / 1000000).toString();
};

export const AdvancedFilterPanel: React.FC<AdvancedFilterPanelProps> = React.memo(({
    filters,
    onFilterStateChange,
    onFilter,
    onExport,
    onSaveDataset,
    onLoadDataset,
    isLoading,
    isFilterBuilderOpen,
    onToggleFilterBuilder,
    activeRules,
    onRemoveRule,
    showScanResults,
    onToggleScanResults
}) => {
    // Local state for UI responsiveness, synced with parent
    const [ticker, setTicker] = React.useState(filters.ticker || "");
    const [minGap, setMinGap] = React.useState(filters.min_gap_pct?.toString() || "20");
    const [maxGap, setMaxGap] = React.useState(filters.max_gap_pct?.toString() || "");
    const [minPmGap, setMinPmGap] = React.useState(filters.min_pmh_gap_pct?.toString() || "");
    const [maxPmGap, setMaxPmGap] = React.useState(filters.max_pmh_gap_pct?.toString() || "");
    const [minVol, setMinVol] = React.useState(formatVolume(filters.min_rth_volume));
    const [minPmVol, setMinPmVol] = React.useState(formatVolume(filters.min_pm_volume));
    const [startDate, setStartDate] = React.useState(filters.start_date || "");
    const [endDate, setEndDate] = React.useState(filters.end_date || "");
    const [m15Ret, setM15Ret] = React.useState(filters.min_m15_ret_pct?.toString() || "");
    const [dayRet, setDayRet] = React.useState(filters.min_rth_run_pct?.toString() || "");
    const [highSpike, setHighSpike] = React.useState(filters.min_high_spike_pct?.toString() || "");
    const [lowSpike, setLowSpike] = React.useState(filters.min_low_spike_pct?.toString() || "");
    const [hodAfter, setHodAfter] = React.useState(filters.hod_after || "");
    const [lodBefore, setLodBefore] = React.useState(filters.lod_before || "");
    const [showRulesDropdown, setShowRulesDropdown] = React.useState(false);

    // Sync from props (when loading datasets)
    React.useEffect(() => {
        setTicker(filters.ticker || "");
        setMinGap(filters.min_gap_pct?.toString() || "20");
        setMaxGap(filters.max_gap_pct?.toString() || "");
        setMinPmGap(filters.min_pmh_gap_pct?.toString() || "");
        setMaxPmGap(filters.max_pmh_gap_pct?.toString() || "");
        setMinVol(formatVolume(filters.min_rth_volume));
        setMinPmVol(formatVolume(filters.min_pm_volume));
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
            border: '0.5px solid var(--color-ec-border)',
            borderRadius: 7,
            padding: '0 16px',
            minHeight: 44,
        }}>
            <div style={{ display: 'flex', width: '100%', alignItems: 'center', justifyContent: 'space-between', gap: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
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
                    </div>                    {/* Divider */}
                    <div style={{ width: '0.5px', height: 20, background: 'var(--color-ec-border)', margin: '0 4px', flexShrink: 0 }} />

                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{
                            fontFamily: "'General Sans', sans-serif",
                            fontSize: 10,
                            fontWeight: 800,
                            textTransform: 'uppercase',
                            letterSpacing: '1px',
                            color: 'var(--color-ec-text-muted)',
                            marginRight: 6,
                            whiteSpace: 'nowrap'
                        }}>Filtros básicos</span>

                        <FilterInput label="Min RTH Gap" value={minGap} onChange={(v: string) => { const n = parseFloat(v); const val = v && !isNaN(n) && n < 20 ? "20" : v; setMinGap(val); updateParent('min_gap_pct', val ? parseFloat(val) : undefined); }} />
                        <FilterInput label="Max RTH Gap" value={maxGap} onChange={(v: string) => { setMaxGap(v); updateParent('max_gap_pct', v ? parseFloat(v) : undefined); }} />
                        <FilterInput label="Min PM Gap" value={minPmGap} onChange={(v: string) => { setMinPmGap(v); updateParent('min_pmh_gap_pct', v ? parseFloat(v) : undefined); }} />
                        <FilterInput label="Max PM Gap" value={maxPmGap} onChange={(v: string) => { setMaxPmGap(v); updateParent('max_pmh_gap_pct', v ? parseFloat(v) : undefined); }} />
                        <FilterInput label="RTH Vol (M)" placeholder="0.0M" value={minVol} onChange={(v: string) => { setMinVol(v); updateParent('min_rth_volume', parseVolume(v)); }} />
                        <FilterInput label="PM Vol (M)" placeholder="0.0M" value={minPmVol} onChange={(v: string) => { setMinPmVol(v); updateParent('min_pm_volume', parseVolume(v)); }} />

                        {onToggleFilterBuilder && (
                            <button
                                onClick={onToggleFilterBuilder}
                                style={{
                                    height: 30,
                                    padding: '0 14px',
                                    background: 'var(--color-ec-copper)',
                                    color: 'var(--color-ec-copper-text)',
                                    border: 'none',
                                    borderRadius: 5,
                                    fontFamily: "'General Sans', sans-serif",
                                    fontSize: 11,
                                    fontWeight: 700,
                                    letterSpacing: '1.2px',
                                    textTransform: 'uppercase',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 6,
                                    marginLeft: 8,
                                    whiteSpace: 'nowrap'
                                }}
                            >
                                más filtros
                            </button>
                        )}

                        {activeRules && activeRules.length > 0 && (
                            <div style={{ position: 'relative', marginLeft: 8 }}>
                                <button
                                    onClick={() => setShowRulesDropdown(!showRulesDropdown)}
                                    style={{
                                        height: 30,
                                        padding: '0 12px',
                                        background: showRulesDropdown ? 'var(--color-ec-bg-surface-hover)' : 'var(--color-ec-bg-surface)',
                                        border: '0.5px solid var(--color-ec-border)',
                                        borderRadius: 5,
                                        fontFamily: "'General Sans', sans-serif",
                                        fontSize: 11,
                                        fontWeight: 600,
                                        color: 'var(--color-ec-text-secondary)',
                                        cursor: 'pointer',
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: 6,
                                        whiteSpace: 'nowrap'
                                    }}
                                >
                                    <span>{activeRules.length} {activeRules.length === 1 ? 'filtro' : 'filtros'}</span>
                                    {showRulesDropdown ? <ChevronUp size={12} strokeWidth={2} /> : <ChevronDown size={12} strokeWidth={2} />}
                                </button>

                                {showRulesDropdown && (
                                    <>
                                        {/* Click outside backdrop overlay */}
                                        <div 
                                            onClick={() => setShowRulesDropdown(false)}
                                            style={{
                                                position: 'fixed',
                                                top: 0,
                                                left: 0,
                                                right: 0,
                                                bottom: 0,
                                                zIndex: 99,
                                            }}
                                        />
                                        <div style={{
                                            position: 'absolute',
                                            top: 'calc(100% + 6px)',
                                            left: 0,
                                            background: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 6,
                                            padding: '8px',
                                            minWidth: 220,
                                            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                                            zIndex: 100,
                                            display: 'flex',
                                            flexDirection: 'column',
                                            gap: 4,
                                        }}>
                                            <div style={{
                                                padding: '4px 6px',
                                                fontSize: 9,
                                                fontWeight: 800,
                                                textTransform: 'uppercase',
                                                letterSpacing: '1px',
                                                color: 'var(--color-ec-text-muted)',
                                                borderBottom: '0.5px solid var(--color-ec-border)',
                                                paddingBottom: 6,
                                                marginBottom: 4,
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                alignItems: 'center',
                                            }}>
                                                <span>Filtros avanzados</span>
                                                <button
                                                    onClick={() => {
                                                        activeRules.forEach(rule => onRemoveRule && onRemoveRule(rule.id));
                                                        setShowRulesDropdown(false);
                                                    }}
                                                    style={{
                                                        background: 'none',
                                                        border: 'none',
                                                        color: 'var(--color-ec-copper)',
                                                        fontSize: 9,
                                                        fontWeight: 700,
                                                        textTransform: 'uppercase',
                                                        cursor: 'pointer',
                                                        padding: 0
                                                    }}
                                                >
                                                    Limpiar todo
                                                </button>
                                            </div>
                                            <div style={{ maxHeight: 180, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
                                                {activeRules.map(rule => (
                                                    <div key={rule.id} style={{
                                                        background: 'var(--color-ec-bg-surface)',
                                                        border: '0.5px solid var(--color-ec-border)',
                                                        padding: '4px 8px',
                                                        borderRadius: 4,
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        justifyContent: 'space-between',
                                                        gap: 8,
                                                        whiteSpace: 'nowrap',
                                                    }}>
                                                        <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--color-ec-text-primary)' }}>
                                                            {rule.metric} {rule.operator} {rule.value}
                                                        </span>
                                                        <button
                                                            onClick={() => onRemoveRule && onRemoveRule(rule.id)}
                                                            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-ec-text-muted)', padding: 2, display: 'flex', borderRadius: 3 }}
                                                        >
                                                            <X size={12} strokeWidth={2} />
                                                        </button>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    </>
                                )}
                            </div>
                        )}
                    </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {/* Chevron Icon Button */}
                    <button
                        onClick={onToggleScanResults}
                        title={showScanResults ? "Colapsar resultados de escaneo" : "Expandir resultados de escaneo"}
                        style={{
                            height: 30, width: 30, padding: 0,
                            background: 'var(--color-ec-bg-surface)',
                            border: '0.5px solid var(--color-ec-border)', borderRadius: 5,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            color: 'var(--color-ec-text-secondary)', cursor: 'pointer',
                        }}
                    >
                        {showScanResults ? <ChevronUp size={14} strokeWidth={1.5} /> : <ChevronDown size={14} strokeWidth={1.5} />}
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
                        <Download size={14} strokeWidth={1.5} />
                        <span>LOAD</span>
                    </SecondaryButton>
                    <SecondaryButton onClick={onSaveDataset} title="Save dataset">
                        <Download size={14} strokeWidth={1.5} style={{ transform: 'rotate(180deg)' }} />
                        <span>Save</span>
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

const FilterInput = ({ label, value, checked, onChange, isCheck = false, placeholder = '—' }: any) => (
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
                placeholder={value ? undefined : placeholder}
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
