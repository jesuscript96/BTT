"use client";

import React, { useState } from 'react';
import { Strategy, initialFilterSettings, initialExitLogic, ConditionGroup } from '@/types/strategy';
import { FilterSection } from './FilterSection';
import { ConditionBuilder } from './ConditionBuilder';
import { RiskSection } from './RiskSection';
import { Save, Loader2 } from 'lucide-react';

interface Props {
    onStrategySaved?: () => void;
}

export const StrategyForm = ({ onStrategySaved }: Props) => {
    const [isSubmitting, setIsSubmitting] = useState(false);

    // Strategy State
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [filters, setFilters] = useState(initialFilterSettings);
    const [exitLogic, setExitLogic] = useState(initialExitLogic);
    const [groups, setGroups] = useState<ConditionGroup[]>([
        { id: 'default-group', conditions: [], logic: 'AND' }
    ]);

    const handleSave = async () => {
        if (!name) {
            alert("Please enter a strategy name");
            return;
        }

        setIsSubmitting(true);
        try {
            const strategyData = {
                name,
                description,
                filters,
                entry_logic: groups,
                exit_logic: exitLogic
            };

            const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
            const response = await fetch(`${apiUrl}/strategies/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(strategyData)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Failed to parse error response' }));
                const detail = errorData.detail;

                if (Array.isArray(detail)) {
                    // Handle Pydantic validation errors
                    const messages = detail.map((err: any) => {
                        const field = err.loc ? err.loc[err.loc.length - 1] : 'Field';
                        return `${field}: ${err.msg}`;
                    });
                    throw new Error(messages.join('\n'));
                } else if (typeof detail === 'object') {
                    throw new Error(JSON.stringify(detail));
                }
                throw new Error(detail || 'Failed to save');
            }

            const savedStrategy = await response.json();
            alert(`Strategy "${savedStrategy.name}" saved successfully!`);

            // Reset form
            setName("");
            setDescription("");
            setGroups([{ id: 'default-group', conditions: [], logic: 'AND' }]);

            // Trigger refresh of strategies table
            if (onStrategySaved) {
                onStrategySaved();
            }
        } catch (error) {
            console.error(error);
            let errorMessage = 'Unknown error';
            if (error instanceof Error) {
                errorMessage = error.message;
            } else if (typeof error === 'object' && error !== null) {
                errorMessage = JSON.stringify(error);
            }
            alert(`Error saving strategy: ${errorMessage}`);
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="w-full px-2 py-4 font-sans text-zinc-900">
            {/* Header */}
            <div className="flex items-center justify-between mb-8">
                <div>
                    <h1 className="text-2xl font-black text-zinc-900 tracking-tight mb-2">NEW STRATEGY</h1>
                    <p className="text-sm text-zinc-500 font-medium">Define algorithmic rules for the Short-Bias engine.</p>
                </div>
                <div className="flex gap-3">
                    <button
                        onClick={() => {/* verify logic */ }}
                        className="px-4 py-2 text-xs font-bold uppercase tracking-wider text-zinc-500 bg-white border border-zinc-200 rounded-lg hover:bg-zinc-50 transition-all hover:shadow-sm"
                    >
                        Validate Logic
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={isSubmitting}
                        className="flex items-center gap-2 px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded font-medium shadow-lg shadow-blue-900/20 transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {isSubmitting ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                            <Save className="w-4 h-4" />
                        )}
                        <span>Save Strategy</span>
                    </button>
                </div>
            </div>

            {/* Main Content Grid - 3 Columns */}
            <div className="grid grid-cols-12 gap-6">

                {/* 1. SETUP & FILTERS (Left - 3/12) */}
                <div className="col-span-12 lg:col-span-3 space-y-6">
                    {/* Metadata Card */}
                    <div className="bg-white border border-zinc-200 rounded-xl p-5 shadow-sm">
                        <div className="flex items-center gap-2 mb-4">
                            <div className="h-5 w-1 bg-blue-600 rounded-full" />
                            <h2 className="text-xs font-black text-zinc-900 uppercase tracking-widest">Identity</h2>
                        </div>

                        <div className="space-y-4">
                            <div>
                                <label className="block text-[10px] font-bold text-zinc-500 uppercase tracking-widest mb-1.5 lead">Strategy Name</label>
                                <input
                                    type="text"
                                    value={name}
                                    onChange={(e) => setName(e.target.value)}
                                    className="w-full bg-zinc-50 border border-zinc-200 rounded-lg px-3 py-2 text-sm font-bold text-zinc-900 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all placeholder:text-zinc-400"
                                    placeholder="e.g. Parabolic Short v1"
                                />
                            </div>

                            <div>
                                <label className="block text-[10px] font-bold text-zinc-500 uppercase tracking-widest mb-1.5">Description</label>
                                <textarea
                                    value={description}
                                    onChange={(e) => setDescription(e.target.value)}
                                    rows={3}
                                    className="w-full bg-zinc-50 border border-zinc-200 rounded-lg px-3 py-2 text-sm font-medium text-zinc-900 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all placeholder:text-zinc-400 resize-none"
                                    placeholder="Describe the mechanic..."
                                />
                            </div>
                        </div>
                    </div>

                    {/* Filters Card */}
                    <div className="bg-white border border-zinc-200 rounded-xl p-5 shadow-sm">
                        <div className="flex items-center gap-2 mb-4">
                            <div className="h-5 w-1 bg-zinc-900 rounded-full" />
                            <h2 className="text-xs font-black text-zinc-900 uppercase tracking-widest">Universe Filters</h2>
                        </div>
                        <FilterSection filters={filters} onChange={setFilters} />
                    </div>
                </div>

                {/* 2. ENTRY LOGIC (Center - 5/12) */}
                <div className="col-span-12 lg:col-span-5 space-y-6">
                    <div className="bg-white border border-zinc-200 rounded-xl p-5 shadow-sm h-full">
                        <div className="flex items-center gap-2 mb-2">
                            <div className="h-5 w-1 bg-green-500 rounded-full" />
                            <h2 className="text-xs font-black text-zinc-900 uppercase tracking-widest">Entry Logic</h2>
                        </div>
                        <p className="text-[10px] text-zinc-400 font-bold uppercase tracking-wide mb-6 ml-3">Trigger Conditions (AND/OR Logic)</p>

                        <ConditionBuilder groups={groups} onChange={setGroups} />
                    </div>
                </div>

                {/* 3. RISK MANAGEMENT (Right - 4/12) */}
                <div className="col-span-12 lg:col-span-4 space-y-6">
                    <div className="bg-white border border-zinc-200 rounded-xl p-5 shadow-sm h-full">
                        <div className="flex items-center gap-2 mb-2">
                            <div className="h-5 w-1 bg-red-500 rounded-full" />
                            <h2 className="text-xs font-black text-zinc-900 uppercase tracking-widest">Risk Management</h2>
                        </div>
                        <p className="text-[10px] text-zinc-400 font-bold uppercase tracking-wide mb-6 ml-3">Stops, Targets & Dilution</p>

                        <RiskSection exitLogic={exitLogic} onChange={setExitLogic} />
                    </div>
                </div>
            </div>
        </div>
    );
};
