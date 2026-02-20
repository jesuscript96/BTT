
"use client";

import React, { useState } from 'react';
import {
    Strategy,
    initialUniverseFilters,
    initialEntryLogic,
    initialRiskManagement,
    UniverseFilters,
    EntryLogic,
    RiskManagement
} from '@/types/strategy';
import { UniverseFiltersComponent } from './UniverseFilters';
import { EntryLogicBuilder } from './EntryLogic';
import { RiskManagementComponent } from './RiskManagement';
import { Save, Loader2, Code, LayoutTemplate } from 'lucide-react';
import { API_URL } from '@/config/constants';

interface Props {
    onStrategySaved?: () => void;
}

export const StrategyForm = ({ onStrategySaved }: Props) => {
    const [isSubmitting, setIsSubmitting] = useState(false);

    // Strategy State
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [filters, setFilters] = useState<UniverseFilters>(initialUniverseFilters);
    const [entryLogic, setEntryLogic] = useState<EntryLogic>(initialEntryLogic);
    const [riskManagement, setRiskManagement] = useState<RiskManagement>(initialRiskManagement);

    // View State
    const [showJson, setShowJson] = useState(true);

    const constructStrategyPayload = (): Strategy => {
        return {
            name,
            description,
            universe_filters: filters,
            entry_logic: entryLogic,
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
            const apiUrl = API_URL;
            // Use correct endpoint structure
            const response = await fetch(`${apiUrl}/strategies/`, {
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

            // Reset form
            setName("");
            setDescription("");
            setEntryLogic(initialEntryLogic);

            if (onStrategySaved) onStrategySaved();
        } catch (error) {
            console.error(error);
            alert(`Error saving strategy: ${error instanceof Error ? error.message : 'Unknown error'}`);
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="flex h-[calc(100vh-100px)] overflow-hidden">
            {/* LEFT: Builder Form */}
            <div className={`flex-1 overflow-y-auto px-6 py-4 font-sans text-foreground transition-all duration-300 ${showJson ? 'mr-0' : ''}`}>

                {/* Header */}
                <div className="flex items-center justify-between mb-8 sticky top-0 z-10 bg-background/95 backdrop-blur py-2 border-b border-border/40">
                    <div>
                        <h1 className="text-2xl font-black text-foreground tracking-tight mb-1 uppercase">New Strategy</h1>
                        <p className="text-xs text-muted-foreground font-medium">Algorithmic Strategy Designer</p>
                    </div>
                    <div className="flex gap-3">
                        <button
                            onClick={() => setShowJson(!showJson)}
                            className={`px-3 py-2 rounded-lg border transition-all ${showJson ? 'bg-blue-500/10 border-blue-500 text-blue-500' : 'bg-card border-border text-muted-foreground hover:bg-muted'}`}
                            title="Toggle JSON Preview"
                        >
                            <Code className="w-4 h-4" />
                        </button>
                        <button
                            onClick={handleSave}
                            disabled={isSubmitting}
                            className="flex items-center gap-2 px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-black uppercase tracking-widest text-xs shadow-lg shadow-blue-900/40 transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                            <span>Save Strategy</span>
                        </button>
                    </div>
                </div>

                <div className="space-y-12 pb-20">

                    {/* 1. IDENTITY & UNIVERSE */}
                    <section className="grid grid-cols-12 gap-8">
                        <div className="col-span-12 lg:col-span-4 space-y-6">
                            <div className="flex items-center gap-2 mb-4">
                                <div className="w-1.5 h-1.5 rounded-full bg-indigo-500"></div>
                                <h2 className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">Metadata</h2>
                            </div>
                            <div className="space-y-4">
                                <div>
                                    <label className="block text-[10px] font-bold text-muted-foreground uppercase mb-2">Name</label>
                                    <input
                                        type="text"
                                        value={name}
                                        onChange={(e) => setName(e.target.value)}
                                        className="w-full bg-muted/10 border border-border/50 rounded-lg px-3 py-2 text-sm font-bold focus:ring-1 focus:ring-indigo-500/50"
                                        placeholder="My Strategy Name"
                                    />
                                </div>
                                <div>
                                    <label className="block text-[10px] font-bold text-muted-foreground uppercase mb-2">Description</label>
                                    <textarea
                                        value={description}
                                        onChange={(e) => setDescription(e.target.value)}
                                        rows={3}
                                        className="w-full bg-muted/10 border border-border/50 rounded-lg px-3 py-2 text-sm font-medium resize-none focus:ring-1 focus:ring-indigo-500/50"
                                        placeholder="Description..."
                                    />
                                </div>
                            </div>
                        </div>

                        <div className="col-span-12 lg:col-span-8">
                            <div className="flex items-center gap-2 mb-6">
                                <div className="w-1.5 h-1.5 rounded-full bg-green-500"></div>
                                <h2 className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">Universe Filters</h2>
                            </div>
                            <div className="bg-card/30 border border-border/40 rounded-xl p-6">
                                <UniverseFiltersComponent filters={filters} onChange={setFilters} />
                            </div>
                        </div>
                    </section>

                    {/* 2. ENTRY LOGIC */}
                    <section>
                        <div className="flex items-center gap-2 mb-6">
                            <div className="w-1.5 h-1.5 rounded-full bg-blue-500"></div>
                            <h2 className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">Entry Logic</h2>
                        </div>
                        <div className="bg-card/30 border border-border/40 rounded-xl p-6 min-h-[300px]">
                            <EntryLogicBuilder logic={entryLogic} onChange={setEntryLogic} />
                        </div>
                    </section>

                    {/* 3. RISK MANAGEMENT */}
                    <section>
                        <div className="flex items-center gap-2 mb-6">
                            <div className="w-1.5 h-1.5 rounded-full bg-red-500"></div>
                            <h2 className="text-[10px] font-black text-muted-foreground uppercase tracking-widest">Risk Management</h2>
                        </div>
                        <div className="bg-card/30 border border-border/40 rounded-xl p-6 max-w-2xl">
                            <RiskManagementComponent risk={riskManagement} onChange={setRiskManagement} />
                        </div>
                    </section>

                </div>
            </div>

            {/* RIGHT: JSON Preview Panel */}
            {showJson && (
                <div className="w-[400px] border-l border-border/40 bg-zinc-950 overflow-y-auto font-mono text-xs p-4 transition-all animate-in slide-in-from-right-10">
                    <div className="flex items-center justify-between mb-4 sticky top-0 bg-zinc-950 pb-2 border-b border-border/20">
                        <h3 className="text-muted-foreground font-bold uppercase tracking-wider text-[10px]">Live JSON Preview</h3>
                        <span className="px-2 py-0.5 rounded bg-blue-900/20 text-blue-400 text-[9px] font-bold">READ ONLY</span>
                    </div>
                    <pre className="text-zinc-400 whitespace-pre-wrap break-all">
                        {JSON.stringify(constructStrategyPayload(), null, 2)}
                    </pre>
                </div>
            )}
        </div>
    );
};
