"use client";

import React, { useState, useEffect } from 'react';
import { Play, Loader2, Trash2 } from 'lucide-react';
import { Strategy } from '@/types/strategy';
import { StrategySelection, BacktestRequest, BacktestResponse } from '@/types/backtest';
import { API_URL } from '@/config/constants';

interface PrefillData {
    strategy_id: string;
    strategy_name: string;
    dataset_id: string | null;
}

interface ExecutionPanelProps {
    onBacktestStart: () => void;
    onBacktestComplete: (result: any) => void;
    isLoading: boolean;
    prefillData?: PrefillData | null;
}

export function ExecutionPanel({ onBacktestStart, onBacktestComplete, isLoading, prefillData }: ExecutionPanelProps) {
    const [strategies, setStrategies] = useState<Strategy[]>([]);
    const [selectedStrategies, setSelectedStrategies] = useState<StrategySelection[]>([]);

    // Settings State
    const [commissionPerShare, setCommissionPerShare] = useState(0.005);
    const [slippagePct, setSlippagePct] = useState(0.05);
    const [lookaheadPrevention, setLookaheadPrevention] = useState(false);
    const [initialCapital, setInitialCapital] = useState(100000);
    const [riskPerTradeR, setRiskPerTradeR] = useState(1.0);
    const [marketInterval, setMarketInterval] = useState<'PM' | 'RTH' | 'AM'>('RTH');
    const [dateFrom, setDateFrom] = useState('2024-01-01');
    const [dateTo, setDateTo] = useState('2025-12-31');
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
            setLoadingPhase(1);
            const interval = setInterval(() => {
                setLoadingPhase(prev => {
                    if (prev >= 4) return 4;
                    return prev + 1;
                });
            }, 1200);
            return () => clearInterval(interval);
        }
    }, [isLoading]);

    // Fetch available strategies and datasets
    useEffect(() => {
        fetchStrategies();
        fetchSavedDatasets();
    }, []);

    // Handle prefill from strategy builder (preload only, NO auto-run)
    useEffect(() => {
        if (prefillData) {
            setSelectedStrategies([{
                strategy_id: prefillData.strategy_id,
                name: prefillData.strategy_name,
                weight: 100
            }]);
            if (prefillData.dataset_id) {
                setSelectedDatasetId(prefillData.dataset_id);
            }
        }
    }, [prefillData]);

    const fetchStrategies = async () => {
        try {
            const response = await fetch(`${API_URL}/strategies/`);
            const data = await response.json();
            if (Array.isArray(data)) {
                setStrategies(data);
            } else {
                setStrategies([]);
            }
        } catch (error) {
            console.error('Error fetching strategies:', error);
        }
    };

    const fetchSavedDatasets = async () => {
        try {
            const response = await fetch(`${API_URL}/queries/`);
            const data = await response.json();
            if (Array.isArray(data)) {
                setSavedDatasets(data);
            } else {
                setSavedDatasets([]);
            }
        } catch (error) {
            console.error('Error fetching datasets:', error);
        }
    };

    const addStrategy = (strategyId: string) => {
        const strategy = strategies.find(s => s.id === strategyId);
        if (!strategy || selectedStrategies.find(s => s.strategy_id === strategyId)) return;

        const newSelection: StrategySelection = {
            strategy_id: strategyId,
            name: strategy.name,
            weight: 100 / (selectedStrategies.length + 1)
        };

        const rebalanced = selectedStrategies.map(s => ({
            ...s,
            weight: 100 / (selectedStrategies.length + 1)
        }));

        setSelectedStrategies([...rebalanced, newSelection]);
    };

    const removeStrategy = (strategyId: string) => {
        const filtered = selectedStrategies.filter(s => s.strategy_id !== strategyId);
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

        normalizeWeights();
        onBacktestStart();

        try {
            const weights: Record<string, number> = {};
            selectedStrategies.forEach(s => {
                weights[s.strategy_id] = s.weight;
            });

            const request: BacktestRequest = {
                strategy_ids: selectedStrategies.map(s => s.strategy_id),
                weights,
                dataset_filters: {
                    date_from: dateFrom,
                    date_to: dateTo
                },
                query_id: selectedDatasetId || undefined,
                commission_per_share: commissionPerShare,
                slippage_pct: slippagePct,
                lookahead_prevention: lookaheadPrevention,
                initial_capital: initialCapital,
                risk_per_trade_r: riskPerTradeR,
                market_interval: marketInterval,
                date_from: dateFrom,
                date_to: dateTo,
                max_holding_minutes: maxHoldingMinutes
            };

            const response = await fetch(`${API_URL}/backtest/run`, {
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

    const inputCls = "w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:ring-2 focus:ring-blue-500 outline-none transition-colors";
    const labelCls = "text-[9px] uppercase font-bold tracking-widest text-muted-foreground block mb-1";

    return (
        <aside className="w-80 bg-sidebar border-r border-border flex flex-col transition-colors duration-300">
            {/* Header */}
            <div className="p-4 border-b border-border bg-sidebar/50">
                <h2 className="text-lg font-black uppercase tracking-tight text-foreground">Execution Panel</h2>
                {prefillData && (
                    <p className="text-[10px] text-amber-500 font-bold uppercase tracking-widest mt-1">⚡ Pre-loaded from Strategy Builder</p>
                )}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4 space-y-5">
                {/* Strategies Section */}
                <div>
                    <h3 className="text-[10px] font-black uppercase tracking-widest text-muted-foreground mb-3">Strategies</h3>

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

                    <select
                        onChange={(e) => {
                            if (e.target.value) {
                                addStrategy(e.target.value);
                                e.target.value = '';
                            }
                        }}
                        className={inputCls}
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
                    <select
                        value={selectedDatasetId}
                        onChange={(e) => setSelectedDatasetId(e.target.value)}
                        className={inputCls}
                        disabled={isLoading}
                    >
                        <option value="">Default (Global Data)</option>
                        {savedDatasets.map(ds => (
                            <option key={ds.id} value={ds.id}>
                                {ds.name}
                            </option>
                        ))}
                    </select>
                </div>

                {/* ═══ Execution Settings ═══ */}
                <div className="pb-2">
                    <h3 className="text-[10px] font-black uppercase tracking-widest text-muted-foreground mb-3">Settings</h3>

                    <div className="space-y-3">
                        {/* Commission */}
                        <div>
                            <label className={labelCls}>Commission ($/share)</label>
                            <input
                                type="number"
                                value={commissionPerShare}
                                onChange={(e) => setCommissionPerShare(Number(e.target.value))}
                                step="0.001"
                                className={inputCls}
                                disabled={isLoading}
                            />
                        </div>

                        {/* Slippage */}
                        <div>
                            <label className={labelCls}>Slippage (%)</label>
                            <input
                                type="number"
                                value={slippagePct}
                                onChange={(e) => setSlippagePct(Number(e.target.value))}
                                step="0.01"
                                className={inputCls}
                                disabled={isLoading}
                            />
                        </div>

                        {/* Lookahead Prevention */}
                        <div>
                            <label className={labelCls}>Lookahead Prevention</label>
                            <div className="flex items-center gap-3">
                                <button
                                    onClick={() => setLookaheadPrevention(!lookaheadPrevention)}
                                    className={`relative w-10 h-5 rounded-full transition-colors ${lookaheadPrevention ? 'bg-blue-600' : 'bg-muted'}`}
                                    disabled={isLoading}
                                >
                                    <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${lookaheadPrevention ? 'translate-x-5' : 'translate-x-0.5'}`} />
                                </button>
                                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                                    {lookaheadPrevention ? 'shift(1) ON' : 'OFF'}
                                </span>
                            </div>
                            <p className="text-[9px] text-muted-foreground/50 mt-1">Shifts entry/exit by 1 bar to avoid look-ahead bias</p>
                        </div>

                        {/* Capital */}
                        <div>
                            <label className={labelCls}>Capital ($)</label>
                            <input
                                type="number"
                                value={initialCapital}
                                onChange={(e) => setInitialCapital(Number(e.target.value))}
                                step="1000"
                                className={inputCls}
                                disabled={isLoading}
                            />
                        </div>

                        {/* Risk per Trade (R) */}
                        <div>
                            <label className={labelCls}>Risk per Trade (R)</label>
                            <input
                                type="number"
                                value={riskPerTradeR}
                                onChange={(e) => setRiskPerTradeR(Number(e.target.value))}
                                step="0.1"
                                className={inputCls}
                                disabled={isLoading}
                            />
                            <p className="text-[9px] text-muted-foreground/50 mt-1">Fixed R amount to risk per trade</p>
                        </div>

                        {/* Market Interval */}
                        <div>
                            <label className={labelCls}>Market Interval</label>
                            <div className="flex gap-1.5">
                                {(['PM', 'RTH', 'AM'] as const).map((interval) => (
                                    <button
                                        key={interval}
                                        onClick={() => setMarketInterval(interval)}
                                        disabled={isLoading}
                                        className={`flex-1 py-1.5 rounded-lg text-xs font-black uppercase tracking-widest transition-all border ${marketInterval === interval
                                                ? 'bg-blue-500/15 border-blue-500 text-blue-500'
                                                : 'bg-card border-border text-muted-foreground hover:border-blue-500/30'
                                            }`}
                                    >
                                        {interval}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Date Range */}
                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <label className={labelCls}>Date From</label>
                                <input
                                    type="date"
                                    value={dateFrom}
                                    onChange={(e) => setDateFrom(e.target.value)}
                                    className={inputCls}
                                    disabled={isLoading}
                                />
                            </div>
                            <div>
                                <label className={labelCls}>Date To</label>
                                <input
                                    type="date"
                                    value={dateTo}
                                    onChange={(e) => setDateTo(e.target.value)}
                                    className={inputCls}
                                    disabled={isLoading}
                                />
                            </div>
                        </div>

                        {/* Max Holding Period */}
                        <div>
                            <label className={labelCls}>Max Holding Period</label>
                            <select
                                value={maxHoldingMinutes}
                                onChange={(e) => setMaxHoldingMinutes(Number(e.target.value))}
                                className={inputCls}
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
