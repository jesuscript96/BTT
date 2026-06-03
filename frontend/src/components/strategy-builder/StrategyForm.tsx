
"use client";

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import {
    Strategy,
    initialEntryLogic,
    initialExitLogic,
    initialRiskManagement,
    EntryLogic,
    ExitLogic,
    RiskManagement,
    TakeProfitMode,
    PostGapPrecondition,
    IndicatorType,
    Comparator,
    Timeframe
} from '@/types/strategy';
import { EntryLogicBuilder } from './EntryLogic';
import { ExitLogicBuilder } from './ExitLogic';
import { RiskManagementComponent } from './RiskManagement';
import { Save, Loader2, Code, FlaskConical, Database, X } from 'lucide-react';
import { getQueries, createStrategy } from '@/lib/api';

interface SavedQuery {
    id: string;
    name: string;
    filters: Record<string, any>;
    created_at?: string;
}

interface Props {
    onStrategySaved?: () => void;
}

const formatFilterValue = (key: string, value: any): string | null => {
    if (value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) return null;
    const labels: Record<string, string> = {
        min_market_cap: 'Min MCap',
        max_market_cap: 'Max MCap',
        min_price: 'Min Price',
        max_price: 'Max Price',
        min_volume: 'Min Vol',
        max_shares_float: 'Max Float',
        require_shortable: 'Shortable',
        exclude_dilution: 'No Dilution',
        date_from: 'From',
        date_to: 'To',
        min_change_pct: 'Min Chg%',
        max_change_pct: 'Max Chg%',
    };
    const label = labels[key] || key;
    if (typeof value === 'boolean') return value ? label : null;
    if (typeof value === 'number') {
        if (value >= 1_000_000) return `${label}: $${(value / 1_000_000).toFixed(1)}M`;
        if (value >= 1_000) return `${label}: ${(value / 1_000).toFixed(0)}K`;
        return `${label}: ${value}`;
    }
    return `${label}: ${value}`;
};

export const StrategyForm = ({ onStrategySaved }: Props) => {
    const router = useRouter();
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [isTesting, setIsTesting] = useState(false);

    // Strategy State
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [bias, setBias] = useState<'long' | 'short'>('long');
    const [applyDay, setApplyDay] = useState<'gap_day' | 'gap_1_day' | 'gap_2_day'>('gap_day');
    const [postgapPreconditions, setPostgapPreconditions] = useState<PostGapPrecondition[]>([]);
    const [entryLogic, setEntryLogic] = useState<EntryLogic>(initialEntryLogic);
    const [exitLogic, setExitLogic] = useState<ExitLogic>(initialExitLogic);
    const [riskManagement, setRiskManagement] = useState<RiskManagement>(initialRiskManagement);

    // Preconditions builder temp state
    const [tempDay, setTempDay] = useState<'gap_day' | 'gap_1_day'>('gap_day');
    const [tempSource, setTempSource] = useState<'cierre' | 'volume' | 'candle_range_pct'>('cierre');
    const [tempOperator, setTempOperator] = useState<'>' | '<'>('>');
    const [tempTarget, setTempTarget] = useState<'apertura' | 'high_low_previo' | 'pm_high' | 'vwap' | 'sma'>('apertura');
    const [tempValue, setTempValue] = useState<number>(1000000);
    const [tempSmaPeriod, setTempSmaPeriod] = useState<number>(20);

    useEffect(() => {
        if (applyDay === 'gap_day') {
            setPostgapPreconditions([]);
        } else if (applyDay === 'gap_1_day') {
            setPostgapPreconditions(prev => prev.map(p => ({ ...p, day: 'gap_day' })));
            setTempDay('gap_day');
        }
    }, [applyDay]);

    // Dataset State
    const [savedDatasets, setSavedDatasets] = useState<SavedQuery[]>([]);
    const [selectedDatasetId, setSelectedDatasetId] = useState<string>("");
    const [loadingDatasets, setLoadingDatasets] = useState(true);

    // View State
    const [showJson, setShowJson] = useState(false);

    // Validation
    const isTPValid = !riskManagement.use_take_profit || 
                     riskManagement.take_profit_mode === TakeProfitMode.FULL || 
                     Math.abs((riskManagement.partial_take_profits || []).reduce((sum, p) => sum + p.capital_pct, 0) - 100) < 0.01;

    const canSubmit = name && !isSubmitting && !isTesting && isTPValid;

    useEffect(() => {
        fetchSavedDatasets();
    }, []);

    const fetchSavedDatasets = async () => {
        setLoadingDatasets(true);
        try {
            const data = await getQueries();
            setSavedDatasets(data);
        } catch (error) {
            console.error("Error fetching datasets:", error);
            setSavedDatasets([]);
        } finally {
            setLoadingDatasets(false);
        }
    };

    const selectedDataset = savedDatasets.find(d => d.id === selectedDatasetId);

    const constructStrategyPayload = (): Strategy => {
        return {
            name: name || 'Untitled Strategy',
            description,
            bias,
            apply_day: applyDay,
            postgap_preconditions: postgapPreconditions,
            entry_logic: entryLogic,
            exit_logic: exitLogic,
            risk_management: riskManagement
        };
    };

    const handleSave = async () => {
        if (!name) {
            alert("Please enter a strategy name");
            return;
        }

        if (!isTPValid) {
            alert("The sum of Partial Take Profit capital must be exactly 100%");
            return;
        }

        setIsSubmitting(true);
        try {
            const strategyData = constructStrategyPayload();
            const savedStrategy = await createStrategy(strategyData);
            alert(`Strategy "${savedStrategy.name}" saved successfully!`);

            setName("");
            setDescription("");
            setPostgapPreconditions([]);
            setEntryLogic(initialEntryLogic);
            setExitLogic(initialExitLogic);

            if (onStrategySaved) onStrategySaved();
        } catch (error) {
            console.error(error);
            alert(`Error saving strategy: ${error instanceof Error ? error.message : 'Unknown error'}`);
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleTestInBacktester = async () => {
        setIsTesting(true);
        try {
            // Save strategy as draft first
            const strategyData = constructStrategyPayload();
            const savedStrategy = await createStrategy(strategyData);

            // Store prefill data — autoRun is FALSE, just preload
            sessionStorage.setItem('backtester_prefill', JSON.stringify({
                strategy_id: savedStrategy.id,
                strategy_name: savedStrategy.name,
                dataset_id: selectedDatasetId || null
            }));

            if (onStrategySaved) onStrategySaved();

            router.push('/backtester?prefill=true');
        } catch (error) {
            console.error(error);
            alert(`Error: ${error instanceof Error ? error.message : 'Unknown error'}`);
        } finally {
            setIsTesting(false);
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
            {/* LEFT: Builder Form */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '0' }} className="font-sans text-foreground transition-all duration-300">

                {/* Header */}
                <div style={{ position: 'sticky', top: 0, zIndex: 10, backgroundColor: 'var(--color-ec-bg-base)', borderBottom: '0.5px solid var(--color-ec-border)', padding: '20px 20px 16px 20px', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                    <div>
                        <h1 style={{ fontFamily: 'var(--color-ec-serif)', fontSize: 32, fontWeight: 600, color: 'var(--color-ec-text-high)', letterSpacing: '-0.5px', lineHeight: 1.1 }}>New Strategy</h1>
                        <p style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 2, color: 'var(--color-ec-text-muted)', marginTop: 4 }}>Algorithmic Strategy Designer</p>
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={() => setShowJson(!showJson)}
                            className={`px-2.5 py-1.5 rounded border transition-all text-xs ${showJson ? 'bg-[var(--color-ec-copper)]/10 border-[var(--color-ec-copper)] text-[var(--color-ec-copper)]' : 'bg-card border-border text-[var(--color-ec-text-muted)] hover:bg-muted'}`}
                            title="Toggle JSON Preview"
                        >
                            <Code className="w-3.5 h-3.5" />
                        </button>
                        <button
                            onClick={handleTestInBacktester}
                            disabled={!canSubmit}
                            className="flex items-center gap-1.5 rounded-[5px]"
                            style={{
                                background: 'var(--color-ec-bg-surface)',
                                border: '0.5px solid var(--color-ec-border)',
                                color: 'var(--color-ec-text-secondary)',
                                padding: '9px 13px',
                                fontFamily: "'General Sans', sans-serif",
                                fontSize: 11,
                                fontWeight: 600,
                                letterSpacing: '1.2px',
                                textTransform: 'uppercase',
                                cursor: 'pointer',
                            }}
                            title={!isTPValid ? "Partial TP sum must be 100%" : "Save as draft & preload in Backtester"}
                        >
                            {isTesting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FlaskConical className="w-3.5 h-3.5" />}
                            <span>Test</span>
                        </button>
                        <button
                            onClick={handleSave}
                            disabled={!canSubmit}
                            className="flex items-center gap-1.5 rounded-[5px]"
                            style={{
                                background: 'var(--color-ec-copper)',
                                color: 'var(--color-ec-copper-text)',
                                border: 'none',
                                padding: '9px 16px',
                                fontFamily: "'General Sans', sans-serif",
                                fontSize: 11,
                                fontWeight: 700,
                                letterSpacing: '1.2px',
                                textTransform: 'uppercase',
                                cursor: 'pointer',
                            }}
                            title={!isTPValid ? "Partial TP sum must be 100%" : "Save Strategy"}
                        >
                            {isSubmitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                            <span>Save</span>
                        </button>
                    </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 20, padding: '20px 20px 60px 20px' }}>

                    {/* ROW 1: Metadata + Dataset + Bias */}
                    <section style={{ display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: 16 }}>
                        {/* Metadata */}
                        <div className="col-span-12 lg:col-span-5 space-y-3">
                            <div className="flex items-center gap-2" style={{ marginBottom: 12 }}>
                                <div className="w-1.5 h-1.5 rounded-full bg-[var(--color-ec-copper)]"></div>
                                <h2 className="text-[10px] font-bold text-[var(--color-ec-text-muted)] uppercase tracking-widest">Metadata</h2>
                            </div>
                            <div className="space-y-2">
                                <div>
                                    <label className="block text-[9px] font-bold text-[var(--color-ec-text-muted)] uppercase mb-1">Name</label>
                                    <input
                                        type="text"
                                        value={name}
                                        onChange={(e) => setName(e.target.value)}
                                        style={{
                                            background: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: '8px 11px',
                                            fontFamily: 'var(--color-ec-sans)',
                                            fontSize: 12,
                                            fontWeight: 400,
                                            color: 'var(--color-ec-text-primary)',
                                            outline: 'none',
                                            width: '100%'
                                        }}
                                        className="focus:border-[var(--color-ec-copper)]"
                                        placeholder="My Strategy Name"
                                    />
                                </div>
                                <div>
                                    <label className="block text-[9px] font-bold text-[var(--color-ec-text-muted)] uppercase mb-1">Description</label>
                                    <textarea
                                        value={description}
                                        onChange={(e) => setDescription(e.target.value)}
                                        rows={2}
                                        style={{
                                            background: 'var(--color-ec-bg-sidebar)',
                                            border: '0.5px solid var(--color-ec-border)',
                                            borderRadius: 5,
                                            padding: '8px 11px',
                                            fontFamily: 'var(--color-ec-sans)',
                                            fontSize: 12,
                                            fontWeight: 400,
                                            color: 'var(--color-ec-text-primary)',
                                            outline: 'none',
                                            width: '100%',
                                            resize: 'none'
                                        }}
                                        className="focus:border-[var(--color-ec-copper)]"
                                        placeholder="Description..."
                                    />
                                </div>
                            </div>
                        </div>

                        {/* Dataset Selector */}
                        <div className="col-span-12 lg:col-span-7">
                            <div className="flex items-center gap-2" style={{ marginBottom: 12 }}>
                                <div className="w-1.5 h-1.5 rounded-full bg-[var(--color-ec-copper)]"></div>
                                <h2 className="text-[10px] font-bold text-[var(--color-ec-text-muted)] uppercase tracking-widest">Dataset (Saved Query)</h2>
                            </div>
                            <div className="bg-[var(--color-ec-bg-surface)] border-[0.5px] border-[var(--color-ec-border)] rounded p-4 space-y-3">
                                <div className="flex items-center gap-2">
                                    <Database className="w-3.5 h-3.5 text-cyan-500 shrink-0" />
                                    <select
                                        value={selectedDatasetId}
                                        onChange={(e) => setSelectedDatasetId(e.target.value)}
                                        className="flex-1 bg-[var(--color-ec-bg-sidebar)] border-[0.5px] border-[var(--color-ec-border)] rounded px-3 py-1.5 text-sm text-foreground focus:ring-1 focus:ring-[var(--color-ec-copper)]/50 outline-none"
                                    >
                                        <option value="">No dataset (Full Universe)</option>
                                        {loadingDatasets ? (
                                            <option disabled>Loading...</option>
                                        ) : (
                                            savedDatasets.map(ds => (
                                                <option key={ds.id} value={ds.id}>{ds.name}</option>
                                            ))
                                        )}
                                    </select>
                                    {selectedDatasetId && (
                                        <button
                                            onClick={() => setSelectedDatasetId("")}
                                            className="p-1 rounded hover:bg-muted transition-colors text-[var(--color-ec-text-muted)] hover:text-foreground"
                                        >
                                            <X className="w-3.5 h-3.5" />
                                        </button>
                                    )}
                                </div>

                                {/* Filter Tags */}
                                {selectedDataset && (
                                    <div className="flex flex-wrap gap-1.5 animate-in fade-in slide-in-from-top-1 duration-200">
                                        {Object.entries(selectedDataset.filters).map(([key, value]) => {
                                            const formatted = formatFilterValue(key, value);
                                            if (!formatted) return null;
                                            return (
                                                <span
                                                    key={key}
                                                    className="inline-flex items-center px-2 py-0.5 rounded-md bg-[var(--color-ec-copper)]/10 border border-[var(--color-ec-copper)]/20 text-[var(--color-ec-copper)] text-[10px] font-bold"
                                                >
                                                    {formatted}
                                                </span>
                                            );
                                        })}
                                        {Object.entries(selectedDataset.filters).every(([k, v]) => !formatFilterValue(k, v)) && (
                                            <span className="text-[10px] text-[var(--color-ec-text-muted)]/50 italic">No active filters</span>
                                        )}
                                    </div>
                                )}

                                {!selectedDatasetId && (
                                    <p className="text-[10px] text-[var(--color-ec-text-muted)]/40 font-medium">
                                        Select a saved query to use as the backtest dataset
                                    </p>
                                )}
                            </div>

                            {/* Long / Short Bias Toggle */}
                            <div className="mt-3">
                                <div className="flex items-center gap-2" style={{ marginBottom: 12 }}>
                                    <div className="w-1.5 h-1.5 rounded-full bg-[var(--color-ec-copper)]"></div>
                                    <h2 className="text-[10px] font-bold text-[var(--color-ec-text-muted)] uppercase tracking-widest">Direction Bias</h2>
                                </div>
                                <div className="flex gap-2">
                                    <button
                                        onClick={() => setBias('long')}
                                        className={`flex-1 py-2 rounded-lg text-xs font-bold uppercase tracking-widest transition-all border ${bias === 'long'
                                            ? 'bg-ec-profit/15 border-ec-profit text-ec-profit shadow-md shadow-ec-profit/10'
                                            : 'bg-[var(--color-ec-bg-surface)] border-[var(--color-ec-border)] text-[var(--color-ec-text-muted)] hover:border-ec-profit/30 hover:text-ec-profit'
                                            }`}
                                    >
                                        ↑ Long Bias
                                    </button>
                                    <button
                                        onClick={() => setBias('short')}
                                        className={`flex-1 py-2 rounded-lg text-xs font-bold uppercase tracking-widest transition-all border ${bias === 'short'
                                            ? 'bg-ec-loss/15 border-ec-loss text-ec-loss shadow-md shadow-ec-loss/10'
                                            : 'bg-[var(--color-ec-bg-surface)] border-[var(--color-ec-border)] text-[var(--color-ec-text-muted)] hover:border-ec-loss/30 hover:text-ec-loss'
                                            }`}
                                    >
                                        ↓ Short Bias
                                    </button>
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* DIVIDER 1 */}
                    <div style={{ height: '0.5px', backgroundColor: 'var(--color-ec-border)', width: '100%', margin: '4px 0' }} />

                    {/* SECTION: PRE-GAP CONDITIONS */}
                    {applyDay !== 'gap_day' && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '16px 0' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <div style={{
                                    width: 3,
                                    height: 14,
                                    borderRadius: 1,
                                    backgroundColor: 'var(--color-ec-copper)',
                                }} />
                                <h2 style={{
                                    fontFamily: 'var(--color-ec-sans)',
                                    fontSize: 13,
                                    fontWeight: 700,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.08em',
                                    color: 'var(--color-ec-text-high)',
                                    margin: 0,
                                }}>Condiciones previas post-gap</h2>
                            </div>

                            {/* Form to add preconditions */}
                            <div style={{
                                display: 'flex',
                                flexDirection: 'column',
                                gap: 10,
                                padding: 12,
                                backgroundColor: 'rgba(28, 30, 33, 0.2)',
                                border: '0.5px solid var(--color-ec-border)',
                                borderRadius: 6,
                            }}>
                                {/* Top: Day selector (only for gap_2_day) */}
                                {applyDay === 'gap_2_day' && (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, borderBottom: '0.5px solid var(--color-ec-border)', paddingBottom: 10, marginBottom: 2 }}>
                                        <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Evaluar en</label>
                                        <select
                                            value={tempDay}
                                            onChange={(e) => setTempDay(e.target.value as any)}
                                            style={{
                                                background: 'var(--color-ec-bg-surface)',
                                                border: '0.5px solid var(--color-ec-border)',
                                                color: 'var(--color-ec-text-primary)',
                                                fontSize: 11,
                                                padding: '4px 8px',
                                                borderRadius: 4,
                                                outline: 'none',
                                                fontFamily: 'var(--color-ec-sans)',
                                                width: 'fit-content',
                                                cursor: 'pointer',
                                            }}
                                        >
                                            <option value="gap_day">Día del Gap</option>
                                            <option value="gap_1_day">Día Gap +1</option>
                                        </select>
                                    </div>
                                )}

                                {/* Bottom: Inputs Row */}
                                <div style={{
                                    display: 'flex',
                                    flexDirection: 'row',
                                    alignItems: 'flex-end',
                                    flexWrap: 'wrap',
                                    gap: 8,
                                }}>
                                    {/* Source variable selector */}
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                                        <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Variable</label>
                                        <select
                                            value={tempSource}
                                            onChange={(e) => {
                                                const src = e.target.value as 'cierre' | 'volume' | 'candle_range_pct';
                                                setTempSource(src);
                                                
                                                // Set sensible default values/operators
                                                if (src === 'volume') {
                                                    setTempValue(1000000);
                                                } else if (src === 'candle_range_pct') {
                                                    setTempValue(2.0);
                                                }
                                            }}
                                            style={{
                                                background: 'var(--color-ec-bg-surface)',
                                                border: '0.5px solid var(--color-ec-border)',
                                                color: 'var(--color-ec-text-primary)',
                                                fontSize: 11,
                                                padding: '4px 8px',
                                                borderRadius: 4,
                                                outline: 'none',
                                                fontFamily: 'var(--color-ec-sans)',
                                                width: 'fit-content',
                                                cursor: 'pointer',
                                            }}
                                        >
                                            <option value="cierre">Cierre</option>
                                            <option value="volume">Volumen Total</option>
                                            <option value="candle_range_pct">Rango de Vela %</option>
                                        </select>
                                    </div>

                                    {/* Operator selector */}
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                                        <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Operador</label>
                                        <select
                                            value={tempOperator}
                                            onChange={(e) => setTempOperator(e.target.value as any)}
                                            style={{
                                                background: 'var(--color-ec-bg-surface)',
                                                border: '0.5px solid var(--color-ec-border)',
                                                color: 'var(--color-ec-text-primary)',
                                                fontSize: 11,
                                                padding: '4px 8px',
                                                borderRadius: 4,
                                                outline: 'none',
                                                fontFamily: 'var(--color-ec-sans)',
                                                width: 'fit-content',
                                                cursor: 'pointer',
                                            }}
                                        >
                                            <option value=">">mayor que (&gt;)</option>
                                            <option value="<">menor que (&lt;)</option>
                                        </select>
                                    </div>

                                    {/* Target variable selector (only if source is cierre) */}
                                    {tempSource === 'cierre' && (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                                            <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Comparado con</label>
                                            <select
                                                value={tempTarget}
                                                onChange={(e) => setTempTarget(e.target.value as any)}
                                                style={{
                                                    background: 'var(--color-ec-bg-surface)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontSize: 11,
                                                    padding: '4px 8px',
                                                    borderRadius: 4,
                                                    outline: 'none',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    width: 'fit-content',
                                                    cursor: 'pointer',
                                                }}
                                            >
                                                <option value="apertura">Apertura</option>
                                                <option value="high_low_previo">High/Low Previo</option>
                                                <option value="pm_high">PM High</option>
                                                <option value="vwap">VWAP</option>
                                                <option value="sma">SMA</option>
                                            </select>
                                        </div>
                                    )}

                                    {/* SMA Period input */}
                                    {tempSource === 'cierre' && tempTarget === 'sma' && (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, width: 60 }}>
                                            <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Periodo</label>
                                            <input
                                                type="number"
                                                value={tempSmaPeriod}
                                                min={2}
                                                max={500}
                                                onChange={(e) => setTempSmaPeriod(parseInt(e.target.value) || 20)}
                                                style={{
                                                    background: 'var(--color-ec-bg-surface)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontSize: 11,
                                                    padding: '4px 8px',
                                                    borderRadius: 4,
                                                    outline: 'none',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    width: '100%',
                                                }}
                                            />
                                        </div>
                                    )}

                                    {/* Value input (only for volume and candle_range_pct) */}
                                    {tempSource !== 'cierre' && (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, width: tempSource === 'volume' ? 90 : 70 }}>
                                            <label style={{ fontSize: 8, fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase' }}>Valor</label>
                                            <input
                                                type="number"
                                                value={tempValue}
                                                onChange={(e) => {
                                                    const val = parseFloat(e.target.value);
                                                    setTempValue(isNaN(val) ? 0 : val);
                                                }}
                                                style={{
                                                    background: 'var(--color-ec-bg-surface)',
                                                    border: '0.5px solid var(--color-ec-border)',
                                                    color: 'var(--color-ec-text-primary)',
                                                    fontSize: 11,
                                                    padding: '4px 8px',
                                                    borderRadius: 4,
                                                    outline: 'none',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    width: '100%',
                                                }}
                                            />
                                        </div>
                                    )}

                                    {/* Add button */}
                                    <button
                                        type="button"
                                        onClick={() => {
                                            let metric: PostGapPrecondition['metric'] = 'volume';
                                            let operator: PostGapPrecondition['operator'] = '>';
                                            let value: number | undefined = undefined;
                                            let sma_period: number | undefined = undefined;

                                            if (tempSource === 'cierre') {
                                                if (tempTarget === 'apertura') {
                                                    metric = 'close_vs_open';
                                                    operator = tempOperator;
                                                } else if (tempTarget === 'high_low_previo') {
                                                    metric = 'close_vs_high_low';
                                                    operator = tempOperator === '>' ? '> High' : '< Low';
                                                } else if (tempTarget === 'pm_high') {
                                                    metric = 'close_vs_pm_high';
                                                    operator = tempOperator;
                                                } else if (tempTarget === 'vwap') {
                                                    metric = 'close_vs_vwap';
                                                    operator = tempOperator;
                                                } else if (tempTarget === 'sma') {
                                                    metric = 'close_vs_sma';
                                                    operator = tempOperator;
                                                    sma_period = tempSmaPeriod;
                                                }
                                            } else if (tempSource === 'volume') {
                                                metric = 'volume';
                                                operator = tempOperator;
                                                value = tempValue;
                                            } else if (tempSource === 'candle_range_pct') {
                                                metric = 'candle_range_pct';
                                                operator = tempOperator;
                                                value = tempValue;
                                            }

                                            const newCond: PostGapPrecondition = {
                                                id: `precond_${Date.now()}`,
                                                day: applyDay === 'gap_1_day' ? 'gap_day' : tempDay,
                                                metric,
                                                operator,
                                                value,
                                                sma_period,
                                            };
                                            setPostgapPreconditions([...postgapPreconditions, newCond]);
                                        }}
                                        style={{
                                            backgroundColor: 'var(--color-ec-copper)',
                                            color: 'var(--color-ec-copper-text)',
                                            border: 'none',
                                            padding: '6px 12px',
                                            borderRadius: 4,
                                            fontSize: 10,
                                            fontWeight: 700,
                                            cursor: 'pointer',
                                            textTransform: 'uppercase',
                                            letterSpacing: '0.5px',
                                            height: 25,
                                        }}
                                    >
                                        + Añadir
                                    </button>
                                </div>
                            </div>

                            {/* Summary Tag List */}
                            {postgapPreconditions.length === 0 ? (
                                <p style={{
                                    fontFamily: 'var(--color-ec-sans)',
                                    fontSize: 11,
                                    color: 'var(--color-ec-text-muted)',
                                    margin: '4px 0 0 0',
                                    opacity: 0.5,
                                    fontStyle: 'italic',
                                }}>
                                    Sin condiciones previas configuradas. La estrategia se ejecutará en todas las configuraciones.
                                </p>
                            ) : (
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                                    {postgapPreconditions.map((cond) => {
                                        const dayLabel = cond.day === 'gap_day' ? 'Día del Gap' : 'Día Gap +1';
                                        let metricLabel = 'Cierre';
                                        let valLabel = '';
                                        
                                        if (cond.metric === 'volume') {
                                            metricLabel = 'Volumen Total';
                                            valLabel = `${cond.operator} ${(cond.value ?? 0).toLocaleString()}`;
                                        } else if (cond.metric === 'close_vs_open') {
                                            valLabel = `${cond.operator} Apertura`;
                                        } else if (cond.metric === 'close_vs_high_low') {
                                            valLabel = cond.operator === '> High' ? '> High Previo' : '< Low Previo';
                                        } else if (cond.metric === 'close_vs_pm_high') {
                                            valLabel = `${cond.operator} PM High`;
                                        } else if (cond.metric === 'close_vs_vwap') {
                                            valLabel = `${cond.operator} VWAP`;
                                        } else if (cond.metric === 'close_vs_sma') {
                                            valLabel = `${cond.operator} SMA ${cond.sma_period}`;
                                        } else if (cond.metric === 'candle_range_pct') {
                                            metricLabel = 'Rango de Vela %';
                                            valLabel = `${cond.operator} ${cond.value}%`;
                                        }
                                        
                                        return (
                                            <div
                                                key={cond.id}
                                                style={{
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: 6,
                                                    backgroundColor: 'rgba(216, 122, 61, 0.08)',
                                                    border: '0.5px solid var(--color-ec-copper)',
                                                    borderRadius: 4,
                                                    padding: '4px 8px',
                                                    fontFamily: 'var(--color-ec-sans)',
                                                    fontSize: 10,
                                                    fontWeight: 600,
                                                    color: 'var(--color-ec-text-secondary)',
                                                }}
                                            >
                                                <span style={{ color: 'var(--color-ec-copper)' }}>{dayLabel}</span>
                                                <span>•</span>
                                                <span>{metricLabel}:</span>
                                                <strong style={{ color: 'var(--color-ec-text-high)' }}>{valLabel}</strong>
                                                
                                                <button
                                                    type="button"
                                                    onClick={() => {
                                                        setPostgapPreconditions(postgapPreconditions.filter(p => p.id !== cond.id));
                                                    }}
                                                    style={{
                                                        background: 'none',
                                                        border: 'none',
                                                        color: 'var(--color-ec-text-muted)',
                                                        cursor: 'pointer',
                                                        fontSize: 12,
                                                        lineHeight: 1,
                                                        padding: '0 2px',
                                                        marginLeft: 4,
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                    }}
                                                >
                                                    ×
                                                </button>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    )}

                    {/* DIVIDER 2 */}
                    <div style={{ height: '0.5px', backgroundColor: 'var(--color-ec-border)', width: '100%', margin: '4px 0' }} />

                    {/* SECTION: APPLY DAY SELECTOR */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', fontSize: 11, fontFamily: 'var(--color-ec-sans)' }}>
                        <span style={{ fontWeight: 700, color: 'var(--color-ec-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Aplicar en:</span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            {(['gap_day', 'gap_1_day', 'gap_2_day'] as const).map((day, idx) => {
                                const isActive = applyDay === day;
                                const labels: Record<string, string> = {
                                    gap_day: 'Gap Day',
                                    gap_1_day: 'Gap +1 Day',
                                    gap_2_day: 'Gap +2 Day',
                                };
                                return (
                                    <React.Fragment key={day}>
                                        {idx > 0 && <span style={{ color: 'var(--color-ec-border)', fontSize: 9 }}>/</span>}
                                        <span
                                            onClick={() => setApplyDay(day)}
                                            style={{
                                                color: isActive ? 'var(--color-ec-copper)' : 'var(--color-ec-text-muted)',
                                                fontWeight: isActive ? 700 : 400,
                                                cursor: 'pointer',
                                                transition: 'color 150ms ease',
                                                fontSize: 11,
                                            }}
                                            onMouseEnter={(e) => {
                                                if (!isActive) e.currentTarget.style.color = 'var(--color-ec-text-primary)';
                                            }}
                                            onMouseLeave={(e) => {
                                                if (!isActive) e.currentTarget.style.color = 'var(--color-ec-text-muted)';
                                            }}
                                        >
                                            {labels[day]}
                                        </span>
                                    </React.Fragment>
                                );
                            })}
                        </div>
                    </div>

                    {/* FULL-WIDTH: Entry Logic */}
                    <section style={{
                        backgroundColor: 'var(--color-ec-bg-surface)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 7,
                        padding: '16px 20px'
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
                            <span style={{ color: 'var(--color-ec-copper)', fontSize: 8, lineHeight: 1 }}>●</span>
                            <h2 style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 2, color: 'var(--color-ec-text-muted)' }}>Entry Logic</h2>
                        </div>
                        <EntryLogicBuilder logic={entryLogic} onChange={setEntryLogic} />
                    </section>

                    {/* FULL-WIDTH: Exit Logic */}
                    <section style={{
                        backgroundColor: 'var(--color-ec-bg-surface)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 7,
                        padding: '16px 20px'
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
                            <span style={{ color: 'var(--color-ec-copper)', fontSize: 8, lineHeight: 1 }}>●</span>
                            <h2 style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 2, color: 'var(--color-ec-text-muted)' }}>Exit Logic</h2>
                        </div>
                        <ExitLogicBuilder logic={exitLogic} onChange={setExitLogic} />
                    </section>

                    {/* FULL-WIDTH: Risk Management */}
                    <section style={{
                        backgroundColor: 'var(--color-ec-bg-surface)',
                        border: '0.5px solid var(--color-ec-border)',
                        borderRadius: 7,
                        padding: '16px 20px'
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
                            <span style={{ color: 'var(--color-ec-copper)', fontSize: 8, lineHeight: 1 }}>●</span>
                            <h2 style={{ fontFamily: 'var(--color-ec-sans)', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 2, color: 'var(--color-ec-text-muted)' }}>Risk Management</h2>
                        </div>
                        <RiskManagementComponent risk={riskManagement} onChange={setRiskManagement} />
                    </section>

                </div>
            </div>

            {/* RIGHT: JSON Preview Panel */}
            {showJson && (
                <div className="w-[360px] border-l border-[var(--color-ec-border)] bg-ec-bg-base overflow-y-auto font-mono text-xs p-4 transition-all animate-in slide-in-from-right-10">
                    <div className="flex items-center justify-between mb-3 sticky top-0 bg-ec-bg-base pb-2 border-b border-border/20">
                        <h3 className="text-[var(--color-ec-text-muted)] font-bold uppercase tracking-wider text-[10px]">Live JSON Preview</h3>
                        <span className="px-2 py-0.5 rounded bg-[var(--color-ec-bg-elevated)] text-[var(--color-ec-text-muted)] text-[9px] font-bold">READ ONLY</span>
                    </div>
                    <pre className="text-ec-text-secondary whitespace-pre-wrap break-all text-[11px]">
                        {JSON.stringify(constructStrategyPayload(), null, 2)}
                    </pre>
                </div>
            )}
        </div>
    );
};
