"use client";

import React, { useState, useEffect } from 'react';
import { Play, Loader2, Plus, Trash2 } from 'lucide-react';
import { Strategy } from '@/types/strategy';
import { StrategySelection, BacktestRequest, BacktestResponse } from '@/types/backtest';

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
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
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
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
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

        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

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

            if (data.status === 'success') {
                // Fetch full results
                const resultsResponse = await fetch(
                    `${apiUrl}/backtest/results/${data.run_id}`
                );

                if (!resultsResponse.ok) {
                    throw new Error(`Failed to fetch results: ${resultsResponse.statusText}`);
                }

                const results = await resultsResponse.json();
                onBacktestComplete(results);
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
        <aside className="w-80 bg-white border-r border-gray-200 flex flex-col">
            {/* Header */}
            <div className="p-4 border-b border-gray-200">
                <h2 className="text-lg font-semibold text-gray-900">Execution Panel</h2>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4 space-y-6">
                {/* Strategies Section */}
                <div>
                    <h3 className="text-sm font-medium text-gray-500 mb-3">Strategies</h3>

                    {/* Selected Strategies */}
                    <div className="space-y-2 mb-3">
                        {selectedStrategies.map(selection => (
                            <div
                                key={selection.strategy_id}
                                className="bg-white rounded-lg p-3 border border-gray-200 shadow-sm"
                            >
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-sm text-gray-900 font-medium truncate flex-1">
                                        {selection.name}
                                    </span>
                                    <button
                                        onClick={() => removeStrategy(selection.strategy_id)}
                                        className="text-red-500 hover:text-red-700 ml-2"
                                    >
                                        <Trash2 className="w-4 h-4" />
                                    </button>
                                </div>
                                <div className="flex items-center gap-2">
                                    <input
                                        type="range"
                                        min="0"
                                        max="100"
                                        value={selection.weight}
                                        onChange={(e) => updateWeight(selection.strategy_id, Number(e.target.value))}
                                        className="flex-1"
                                    />
                                    <span className="text-xs text-gray-500 w-12 text-right">
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
                        className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
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
                        <div className="mt-2 flex items-center justify-between text-xs">
                            <span className="text-gray-500">Total Weight:</span>
                            <span className={totalWeight === 100 ? 'text-green-600 font-medium' : 'text-yellow-600 font-medium'}>
                                {totalWeight.toFixed(0)}%
                            </span>
                        </div>
                    )}
                </div>

                {/* Dataset Section */}
                <div>
                    <h3 className="text-sm font-medium text-gray-500 mb-3">Dataset</h3>
                    <div className="space-y-3">
                        <select
                            value={selectedDatasetId}
                            onChange={(e) => setSelectedDatasetId(e.target.value)}
                            className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                            disabled={isLoading}
                        >
                            <option value="">Default (Global Data)</option>
                            {savedDatasets.map(ds => (
                                <option key={ds.id} value={ds.id}>
                                    {ds.name}
                                </option>
                            ))}
                        </select>

                        <div className="bg-gray-50 rounded-lg p-3 border border-gray-200">
                            <p className="text-[10px] text-gray-500 mb-1 uppercase font-bold">Base Filters</p>
                            <p className="text-xs text-blue-600 font-medium">
                                {selectedDatasetId
                                    ? `Using filters from "${savedDatasets.find(d => d.id === selectedDatasetId)?.name}"`
                                    : "Using historical data (Full Universe)"}
                            </p>
                        </div>
                    </div>
                </div>

                {/* Execution Settings */}
                <div>
                    <h3 className="text-sm font-medium text-gray-500 mb-3">Settings</h3>

                    <div className="space-y-3">
                        {/* Commission */}
                        <div>
                            <label className="text-xs text-gray-500 block mb-1">
                                Commission per Trade ($)
                            </label>
                            <input
                                type="number"
                                value={commission}
                                onChange={(e) => setCommission(Number(e.target.value))}
                                step="0.1"
                                className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                                disabled={isLoading}
                            />
                        </div>

                        {/* Initial Capital */}
                        <div>
                            <label className="text-xs text-gray-500 block mb-1">
                                Initial Capital ($)
                            </label>
                            <input
                                type="number"
                                value={initialCapital}
                                onChange={(e) => setInitialCapital(Number(e.target.value))}
                                step="1000"
                                className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                                disabled={isLoading}
                            />
                        </div>

                        {/* Max Holding Period */}
                        <div>
                            <label className="text-xs text-gray-500 block mb-1">
                                Max Holding Period
                            </label>
                            <select
                                value={maxHoldingMinutes}
                                onChange={(e) => setMaxHoldingMinutes(Number(e.target.value))}
                                className="w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
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
            <div className="p-4 border-t border-gray-200">
                <button
                    onClick={runBacktest}
                    disabled={isLoading || selectedStrategies.length === 0}
                    className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:text-gray-500 disabled:cursor-not-allowed text-white font-medium py-3 px-4 rounded-lg flex items-center justify-center gap-2 transition-colors shadow-sm"
                >
                    {isLoading ? (
                        <div className="flex flex-col items-center">
                            <div className="flex items-center gap-2 mb-1">
                                <Loader2 className="w-5 h-5 animate-spin" />
                                <span>
                                    {loadingPhase === 1 && "Connecting to MotherDuck..."}
                                    {loadingPhase === 2 && "Fetching Market Data..."}
                                    {loadingPhase === 3 && "Running Engine..."}
                                    {loadingPhase === 4 && "Finalizing Results..."}
                                    {loadingPhase === 0 && "Initializing..."}
                                </span>
                            </div>
                            {loadingPhase > 0 && (
                                <div className="w-full h-1 bg-blue-800 rounded-full overflow-hidden">
                                    <div
                                        className="h-full bg-white/50 transition-all duration-500"
                                        style={{ width: `${(loadingPhase / 4) * 100}%` }}
                                    />
                                </div>
                            )}
                        </div>
                    ) : (
                        <>
                            <Play className="w-5 h-5" />
                            Run Backtest
                        </>
                    )}
                </button>
            </div>
        </aside>
    );
}
