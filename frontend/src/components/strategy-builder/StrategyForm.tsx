
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
    RiskManagement
} from '@/types/strategy';
import { EntryLogicBuilder } from './EntryLogic';
import { ExitLogicBuilder } from './ExitLogic';
import { RiskManagementComponent } from './RiskManagement';
import { Save, Loader2, Code, FlaskConical, Database, X } from 'lucide-react';
import { API_URL } from '@/config/constants';

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
    const [entryLogic, setEntryLogic] = useState<EntryLogic>(initialEntryLogic);
    const [exitLogic, setExitLogic] = useState<ExitLogic>(initialExitLogic);
    const [riskManagement, setRiskManagement] = useState<RiskManagement>(initialRiskManagement);

    // Dataset State
    const [savedDatasets, setSavedDatasets] = useState<SavedQuery[]>([]);
    const [selectedDatasetId, setSelectedDatasetId] = useState<string>("");
    const [loadingDatasets, setLoadingDatasets] = useState(true);

    // View State
    const [showJson, setShowJson] = useState(false);

    useEffect(() => {
        fetchSavedDatasets();
    }, []);

    const fetchSavedDatasets = async () => {
        setLoadingDatasets(true);
        try {
            const response = await fetch(`${API_URL}/queries/`);
            const data = await response.json();
            if (Array.isArray(data)) setSavedDatasets(data);
        } catch (error) {
            console.error('Error fetching datasets:', error);
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

        setIsSubmitting(true);
        try {
            const strategyData = constructStrategyPayload();
            const response = await fetch(`${API_URL}/strategies/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(strategyData)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Failed to parse error response' }));
                const detail = errorData.detail;
                let errorMessage = 'Failed to save';
                if (Array.isArray(detail)) {
                    errorMessage = detail.map((err: any) => `${err.loc.join('.')}: ${err.msg}`).join('\n');
                } else if (typeof detail === 'object') {
                    errorMessage = JSON.stringify(detail);
                } else {
                    errorMessage = detail || 'Failed to save';
                }
                throw new Error(errorMessage);
            }

            const savedStrategy = await response.json();
            alert(`Strategy "${savedStrategy.name}" saved successfully!`);

            setName("");
            setDescription("");
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
            const response = await fetch(`${API_URL}/strategies/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(strategyData)
            });

            if (!response.ok) throw new Error('Failed to save strategy draft');
            const savedStrategy = await response.json();

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
        <div className="flex h-[calc(100vh-80px)] overflow-hidden">
            {/* LEFT: Builder Form */}
            <div className={`flex-1 overflow-y-auto px-5 py-3 font-sans text-foreground transition-all duration-300`}>

                {/* Header */}
                <div className="flex items-center justify-between mb-3 sticky top-0 z-10 bg-background/95 backdrop-blur py-2 border-b border-border/40">
                    <div>
                        <h1 className="text-lg font-black text-foreground tracking-tight uppercase">New Strategy</h1>
                        <p className="text-[10px] text-muted-foreground font-medium">Algorithmic Strategy Designer</p>
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={() => setShowJson(!showJson)}
                            className={`px-2.5 py-1.5 rounded-lg border transition-all text-xs ${showJson ? 'bg-blue-500/10 border-blue-500 text-blue-500' : 'bg-card border-border text-muted-foreground hover:bg-muted'}`}
                            title="Toggle JSON Preview"
                        >
                            <Code className="w-3.5 h-3.5" />
                        </button>
                        <button
                            onClick={handleTestInBacktester}
                            disabled={isTesting || isSubmitting}
                            className="flex items-center gap-1.5 px-4 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg font-black uppercase tracking-widest text-[10px] shadow-lg shadow-amber-900/30 transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
                            title="Save as draft & preload in Backtester"
                        >
                            {isTesting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FlaskConical className="w-3.5 h-3.5" />}
                            <span>Test</span>
                        </button>
                        <button
                            onClick={handleSave}
                            disabled={isSubmitting}
                            className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-black uppercase tracking-widest text-[10px] shadow-lg shadow-blue-900/40 transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {isSubmitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                            <span>Save</span>
                        </button>
                    </div>
                </div>

                <div className="space-y-4 pb-4">

                    {/* ROW 1: Metadata + Dataset + Bias */}
                    <section className="grid grid-cols-12 gap-4">
                        {/* Metadata */}
                        <div className="col-span-12 lg:col-span-5 space-y-3">
                            <div className="flex items-center gap-2 mb-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-indigo-500"></div>
                                <h2 className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">Metadata</h2>
                            </div>
                            <div className="space-y-2">
                                <div>
                                    <label className="block text-[9px] font-bold text-muted-foreground uppercase mb-1">Name</label>
                                    <input
                                        type="text"
                                        value={name}
                                        onChange={(e) => setName(e.target.value)}
                                        className="w-full bg-muted/10 border border-border/50 rounded-lg px-3 py-1.5 text-sm font-bold focus:ring-1 focus:ring-indigo-500/50"
                                        placeholder="My Strategy Name"
                                    />
                                </div>
                                <div>
                                    <label className="block text-[9px] font-bold text-muted-foreground uppercase mb-1">Description</label>
                                    <textarea
                                        value={description}
                                        onChange={(e) => setDescription(e.target.value)}
                                        rows={2}
                                        className="w-full bg-muted/10 border border-border/50 rounded-lg px-3 py-1.5 text-sm font-medium resize-none focus:ring-1 focus:ring-indigo-500/50"
                                        placeholder="Description..."
                                    />
                                </div>
                            </div>
                        </div>

                        {/* Dataset Selector */}
                        <div className="col-span-12 lg:col-span-7">
                            <div className="flex items-center gap-2 mb-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-cyan-500"></div>
                                <h2 className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">Dataset (Saved Query)</h2>
                            </div>
                            <div className="bg-card/30 border border-border/40 rounded-xl p-4 space-y-3">
                                <div className="flex items-center gap-2">
                                    <Database className="w-3.5 h-3.5 text-cyan-500 shrink-0" />
                                    <select
                                        value={selectedDatasetId}
                                        onChange={(e) => setSelectedDatasetId(e.target.value)}
                                        className="flex-1 bg-background border border-border rounded-lg px-3 py-1.5 text-sm text-foreground focus:ring-1 focus:ring-cyan-500/50 outline-none"
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
                                            className="p-1 rounded hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
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
                                                    className="inline-flex items-center px-2 py-0.5 rounded-md bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 text-[10px] font-bold"
                                                >
                                                    {formatted}
                                                </span>
                                            );
                                        })}
                                        {Object.entries(selectedDataset.filters).every(([k, v]) => !formatFilterValue(k, v)) && (
                                            <span className="text-[10px] text-muted-foreground/50 italic">No active filters</span>
                                        )}
                                    </div>
                                )}

                                {!selectedDatasetId && (
                                    <p className="text-[10px] text-muted-foreground/40 font-medium">
                                        Select a saved query to use as the backtest dataset
                                    </p>
                                )}
                            </div>

                            {/* Long / Short Bias Toggle */}
                            <div className="mt-3">
                                <div className="flex items-center gap-2 mb-2">
                                    <div className="w-1.5 h-1.5 rounded-full bg-amber-500"></div>
                                    <h2 className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">Direction Bias</h2>
                                </div>
                                <div className="flex gap-2">
                                    <button
                                        onClick={() => setBias('long')}
                                        className={`flex-1 py-2 rounded-lg text-xs font-black uppercase tracking-widest transition-all border ${bias === 'long'
                                            ? 'bg-emerald-500/15 border-emerald-500 text-emerald-500 shadow-md shadow-emerald-500/10'
                                            : 'bg-card/30 border-border/40 text-muted-foreground hover:border-emerald-500/30 hover:text-emerald-400'
                                            }`}
                                    >
                                        ↑ Long Bias
                                    </button>
                                    <button
                                        onClick={() => setBias('short')}
                                        className={`flex-1 py-2 rounded-lg text-xs font-black uppercase tracking-widest transition-all border ${bias === 'short'
                                            ? 'bg-red-500/15 border-red-500 text-red-500 shadow-md shadow-red-500/10'
                                            : 'bg-card/30 border-border/40 text-muted-foreground hover:border-red-500/30 hover:text-red-400'
                                            }`}
                                    >
                                        ↓ Short Bias
                                    </button>
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* FULL-WIDTH: Entry Logic */}
                    <section>
                        <div className="flex items-center gap-2 mb-2">
                            <div className="w-1.5 h-1.5 rounded-full bg-blue-500"></div>
                            <h2 className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">Entry Logic</h2>
                        </div>
                        <div className="bg-card/30 border border-border/40 rounded-xl p-4">
                            <EntryLogicBuilder logic={entryLogic} onChange={setEntryLogic} />
                        </div>
                    </section>

                    {/* FULL-WIDTH: Exit Logic */}
                    <section>
                        <div className="flex items-center gap-2 mb-2">
                            <div className="w-1.5 h-1.5 rounded-full bg-rose-500"></div>
                            <h2 className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">Exit Logic</h2>
                        </div>
                        <div className="bg-card/30 border border-border/40 rounded-xl p-4">
                            <ExitLogicBuilder logic={exitLogic} onChange={setExitLogic} />
                        </div>
                    </section>

                    {/* FULL-WIDTH: Risk Management */}
                    <section>
                        <div className="flex items-center gap-2 mb-2">
                            <div className="w-1.5 h-1.5 rounded-full bg-red-500"></div>
                            <h2 className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">Risk Management</h2>
                        </div>
                        <div className="bg-card/30 border border-border/40 rounded-xl p-4">
                            <RiskManagementComponent risk={riskManagement} onChange={setRiskManagement} />
                        </div>
                    </section>

                </div>
            </div>

            {/* RIGHT: JSON Preview Panel */}
            {showJson && (
                <div className="w-[360px] border-l border-border/40 bg-zinc-950 overflow-y-auto font-mono text-xs p-4 transition-all animate-in slide-in-from-right-10">
                    <div className="flex items-center justify-between mb-3 sticky top-0 bg-zinc-950 pb-2 border-b border-border/20">
                        <h3 className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Live JSON Preview</h3>
                        <span className="px-2 py-0.5 rounded bg-blue-900/20 text-blue-400 text-[9px] font-bold">READ ONLY</span>
                    </div>
                    <pre className="text-zinc-400 whitespace-pre-wrap break-all text-[11px]">
                        {JSON.stringify(constructStrategyPayload(), null, 2)}
                    </pre>
                </div>
            )}
        </div>
    );
};
