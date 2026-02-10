"use client";

import React, { useState, useEffect } from 'react';
import { Play, Loader2, Plus, Trash2 } from 'lucide-react';
import { Strategy } from '@/types/strategy';
import { StrategySelection, BacktestRequest, BacktestResponse } from '@/types/backtest';
import { API_URL } from '@/config/constants';

interface ExecutionPanelProps {
    onBacktestStart: () => void;
    onBacktestComplete: (result: any) => void;
    isLoading: boolean;
}

export function ExecutionPanel({ onBacktestStart, onBacktestComplete, isLoading }: ExecutionPanelProps) {
    const [strategies, setStrategies] = useState<Strategy[]>([]);
    const [selectedStrategies, setSelectedStrategies] = useState<StrategySelection[]>([]);
    const [commission, setCommission] = useState(1.0);
    const [initialCapital, setInitialCapital] = useState(100000);
    const [maxHoldingMinutes, setMaxHoldingMinutes] = useState(390);
    const [datasetSummary, setDatasetSummary] = useState<string>("");
    const [savedDatasets, setSavedDatasets] = useState<any[]>([]);
    const [selectedDatasetId, setSelectedDatasetId] = useState<string>("");
    const [loadingPhase, setLoadingPhase] = useState(0);

    // Reset loading phase when isLoading becomes false
    useEffect(() => {
        if (!isLoading) {
            setLoadingPhase(0);
        } else {
            // Start simulation
            setLoadingPhase(1);
            const interval = setInterval(() => {
                setLoadingPhase(prev => {
                    if (prev >= 4) return 4;
                    return prev + 1;
                });
            }, 1200); // Change phase every 1.2s
            return () => clearInterval(interval);
        }
    }, [isLoading]);

    // Fetch available strategies and datasets
    useEffect(() => {
        fetchStrategies();
        fetchSavedDatasets();
    }, []);

    const fetchStrategies = async () => {
        const apiUrl = API_URL;
        try {
            const response = await fetch(`${apiUrl}/strategies/`); // Added trailing slash
            const data = await response.json();
            if (Array.isArray(data)) {
                setStrategies(data);
            } else {
                console.error('Strategies API returned non-array:', data);
                setStrategies([]);
            }
        } catch (error) {
            console.error('Error fetching strategies:', error);
        }
    };

    const fetchSavedDatasets = async () => {
        const apiUrl = API_URL;
        try {
            const response = await fetch(`${apiUrl}/queries/`);
            const data = await response.json();
            if (Array.isArray(data)) {
                setSavedDatasets(data);
            } else {
                console.error('Datasets API returned non-array:', data);
                setSavedDatasets([]);
            }
        } catch (error) {
            console.error('Error fetching datasets:', error);
        }
    };

    const addStrategy = (strategyId: string) => {
        const strategy = strategies.find(s => s.id === strategyId);
        if (!strategy || selectedStrategies.find(s => s.strategy_id === strategyId)) {
            return;
        }

        const newSelection: StrategySelection = {
            strategy_id: strategyId,
            name: strategy.name,
            weight: 100 / (selectedStrategies.length + 1)
        };

        // Rebalance weights
        const rebalanced = selectedStrategies.map(s => ({
            ...s,
            weight: 100 / (selectedStrategies.length + 1)
        }));

        setSelectedStrategies([...rebalanced, newSelection]);
    };

    const removeStrategy = (strategyId: string) => {
        const filtered = selectedStrategies.filter(s => s.strategy_id !== strategyId);

        // Rebalance remaining
        const rebalanced = filtered.map(s => ({
            ...s,
            weight: filtered.length > 0 ? 100 / filtered.length : 0
        }));

        setSelectedStrategies(rebalanced);
    };

    const updateWeight = (strategyId: string, weight: number) => {
        setSelectedStrategies(prev =>
            prev.map(s =>
                s.strategy_id === strategyId ? { ...s, weight } : s
            )
        );
    };

    const normalizeWeights = () => {
        const total = selectedStrategies.reduce((sum, s) => sum + s.weight, 0);
        if (total === 0) return;

        setSelectedStrategies(prev =>
            prev.map(s => ({
                ...s,
                weight: (s.weight / total) * 100
            }))
        );
    };

    const runBacktest = async () => {
        if (selectedStrategies.length === 0) {
            alert('Please select at least one strategy');
            return;
        }

        // Normalize weights before running
        normalizeWeights();

        onBacktestStart();

        const apiUrl = API_URL;

        try {
            const weights: Record<string, number> = {};
            selectedStrategies.forEach(s => {
                weights[s.strategy_id] = s.weight;
            });

            const request: BacktestRequest = {
                strategy_ids: selectedStrategies.map(s => s.strategy_id),
                weights,
                dataset_filters: {
                    date_from: "2024-01-01",
                    date_to: "2025-12-31"
                },
                query_id: selectedDatasetId || undefined,
                commission_per_trade: commission,
                initial_capital: initialCapital,
                max_holding_minutes: maxHoldingMinutes
            };

            const response = await fetch(`${apiUrl}/backtest/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(request)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
            }

            const data: BacktestResponse = await response.json();

            if (data.status === 'success' && data.results) {
                onBacktestComplete(data.results);
            } else {
                throw new Error(data.message || 'Backtest failed');
            }
        } catch (error) {
            console.error('Backtest error:', error);
            const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
            alert(`Error running backtest: ${errorMessage}`);
            onBacktestComplete(null);
        }
    };

    const totalWeight = selectedStrategies.reduce((sum, s) => sum + s.weight, 0);

    return (
        <aside className="w-80 bg-sidebar border-r border-border flex flex-col transition-colors duration-300">
            {/* Header */}
            <div className="p-4 border-b border-border bg-sidebar/50">
                <h2 className="text-lg font-black uppercase tracking-tight text-foreground">Execution Panel</h2>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4 space-y-6">
                {/* Strategies Section */}
                <div>
                    <h3 className="text-[10px] font-black uppercase tracking-widest text-muted-foreground mb-3">Strategies</h3>

                    {/* Selected Strategies */}
                    <div className="space-y-3 mb-4">
                        {selectedStrategies.map(selection => (
                            <div
                                key={selection.strategy_id}
                                className="bg-card rounded-xl p-3 border border-border shadow-sm transition-all hover:border-blue-500/30"
                            >
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-sm text-foreground font-semibold truncate flex-1">
                                        {selection.name}
                                    </span>
                                    <button
                                        onClick={() => removeStrategy(selection.strategy_id)}
                                        className="text-muted-foreground hover:text-red-500 transition-colors ml-2"
                                    >
                                        <Trash2 className="w-4 h-4" />
                                    </button>
                                </div>
                                <div className="flex items-center gap-3">
                                    <input
                                        type="range"
                                        min="0"
                                        max="100"
                                        value={selection.weight}
                                        onChange={(e) => updateWeight(selection.strategy_id, Number(e.target.value))}
                                        className="flex-1 h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-blue-500"
                                    />
                                    <span className="text-[10px] font-bold text-muted-foreground w-10 text-right tabular-nums">
                                        {selection.weight.toFixed(0)}%
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* Add Strategy Dropdown */}
                    <select
                        onChange={(e) => {
                            if (e.target.value) {
                                addStrategy(e.target.value);
                                e.target.value = '';
                            }
                        }}
                        className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                        disabled={isLoading}
                    >
                        <option value="">+ Add Strategy</option>
                        {strategies
                            .filter(s => !selectedStrategies.find(sel => sel.strategy_id === s.id))
                            .map(strategy => (
                                <option key={strategy.id} value={strategy.id}>
                                    {strategy.name}
                                </option>
                            ))}
                    </select>

                    {/* Weight Total */}
                    {selectedStrategies.length > 0 && (
                        <div className="mt-3 flex items-center justify-between text-[10px] uppercase font-bold tracking-tighter">
                            <span className="text-muted-foreground">Total Weight:</span>
                            <span className={totalWeight === 100 ? 'text-green-500' : 'text-yellow-500'}>
                                {totalWeight.toFixed(0)}%
                            </span>
                        </div>
                    )}
                </div>

                {/* Dataset Section */}
                <div>
                    <h3 className="text-[10px] font-black uppercase tracking-widest text-muted-foreground mb-3">Dataset</h3>
                    <div className="space-y-3">
                        <select
                            value={selectedDatasetId}
                            onChange={(e) => setSelectedDatasetId(e.target.value)}
                            className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                            disabled={isLoading}
                        >
                            <option value="">Default (Global Data)</option>
                            {savedDatasets.map(ds => (
                                <option key={ds.id} value={ds.id}>
                                    {ds.name}
                                </option>
                            ))}
                        </select>

                        <div className="bg-muted border border-border rounded-lg p-3">
                            <p className="text-[9px] text-muted-foreground mb-1 uppercase font-black tracking-widest">Base Filters</p>
                            <p className="text-[11px] text-blue-500 font-bold leading-tight">
                                {selectedDatasetId
                                    ? `Using filters from "${savedDatasets.find(d => d.id === selectedDatasetId)?.name}"`
                                    : "Using historical data (Full Universe)"}
                            </p>
                        </div>
                    </div>
                </div>

                {/* Execution Settings */}
                <div className="pb-4">
                    <h3 className="text-[10px] font-black uppercase tracking-widest text-muted-foreground mb-3">Settings</h3>

                    <div className="space-y-4">
                        {/* Commission */}
                        <div>
                            <label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground block mb-1">
                                Commission / Trade ($)
                            </label>
                            <input
                                type="number"
                                value={commission}
                                onChange={(e) => setCommission(Number(e.target.value))}
                                step="0.1"
                                className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                                disabled={isLoading}
                            />
                        </div>

                        {/* Initial Capital */}
                        <div>
                            <label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground block mb-1">
                                Initial Capital ($)
                            </label>
                            <input
                                type="number"
                                value={initialCapital}
                                onChange={(e) => setInitialCapital(Number(e.target.value))}
                                step="1000"
                                className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                                disabled={isLoading}
                            />
                        </div>

                        {/* Max Holding Period */}
                        <div>
                            <label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground block mb-1">
                                Max Holding Period
                            </label>
                            <select
                                value={maxHoldingMinutes}
                                onChange={(e) => setMaxHoldingMinutes(Number(e.target.value))}
                                className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                                disabled={isLoading}
                            >
                                <option value={30}>30 minutes</option>
                                <option value={60}>1 hour</option>
                                <option value={120}>2 hours</option>
                                <option value={390}>Full RTH</option>
                            </select>
                        </div>
                    </div>
                </div>
            </div>

            {/* Run Button */}
            <div className="p-4 border-t border-border bg-sidebar/50">
                <button
                    onClick={runBacktest}
                    disabled={isLoading || selectedStrategies.length === 0}
                    className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-muted disabled:text-muted-foreground text-white font-bold py-3.5 px-4 rounded-xl flex items-center justify-center gap-2 transition-all shadow-lg shadow-blue-500/10 active:scale-[0.98]"
                >
                    {isLoading ? (
                        <div className="flex flex-col items-center w-full">
                            <div className="flex items-center gap-2 mb-2">
                                <Loader2 className="w-4 h-4 animate-spin" />
                                <span className="text-xs font-bold uppercase tracking-widest">
                                    {loadingPhase === 1 && "Connecting..."}
                                    {loadingPhase === 2 && "Fetching Data..."}
                                    {loadingPhase === 3 && "Processing..."}
                                    {loadingPhase === 4 && "Finalizing..."}
                                    {loadingPhase === 0 && "Wait..."}
                                </span>
                            </div>
                            {loadingPhase > 0 && (
                                <div className="w-full h-1 bg-white/10 rounded-full overflow-hidden">
                                    <div
                                        className="h-full bg-white transition-all duration-700 ease-out"
                                        style={{ width: `${(loadingPhase / 4) * 100}%` }}
                                    />
                                </div>
                            )}
                        </div>
                    ) : (
                        <>
                            <Play className="w-5 h-5 fill-current" />
                            <span className="uppercase tracking-widest text-xs font-black">Run Backtest</span>
                        </>
                    )}
                </button>
            </div>
        </aside>
    );
}
