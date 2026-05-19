"use client";

import React, { useState } from 'react';
import { BacktestResult } from '@/types/backtest';
import { EquityCurveChart } from './charts/EquityCurveChart';
import { DrawdownChart } from './charts/DrawdownChart';
import { RMultipleHistogram } from './charts/RMultipleHistogram';
import { EVCharts } from './charts/EVCharts';
import { PerformanceTable } from './tables/PerformanceTable';
import { TradesTable } from './tables/TradesTable';
import { CalendarHeatmap } from './tables/CalendarHeatmap';
import { CorrelationMatrix } from './portfolio/CorrelationMatrix';
import { MonteCarloResults } from './portfolio/MonteCarloResults';

interface BacktestDashboardProps {
    result: BacktestResult;
}

type TabType = 'equity' | 'drawdown' | 'performance' | 'calendar' | 'trades' | 'charts' | 'portfolio';

export function BacktestDashboard({ result }: BacktestDashboardProps) {
    const [activeTab, setActiveTab] = useState<TabType>('equity');
    const [isReady, setIsReady] = useState(false);

    console.log("BacktestDashboard Render. Result keys:", result ? Object.keys(result) : 'null');

    // Defer rendering of heavy chart components to prevent UI freeze on mount
    React.useEffect(() => {
        setIsReady(false);
        const timer = setTimeout(() => {
            setIsReady(true);
        }, 100); // Short delay to allow initial paint
        return () => clearTimeout(timer);
    }, [result.run_id]); // Re-run when a new backtest result arrives

    const tabs = [
        { id: 'equity' as TabType, label: 'Equity Curve' },
        { id: 'drawdown' as TabType, label: 'Drawdown' },
        { id: 'performance' as TabType, label: 'Performance' },
        { id: 'calendar' as TabType, label: 'Calendar' },
        { id: 'trades' as TabType, label: 'Trades' },
        { id: 'charts' as TabType, label: 'Charts' },
        { id: 'portfolio' as TabType, label: 'Portfolio' },
    ];

    if (!result) return null;

    return (
        <div className="h-full flex flex-col">
            {/* Header with Metrics (Always Render Immediately) */}
            <div className="bg-card/50 border-b border-border p-6 backdrop-blur-sm">
                <div className="flex items-center justify-between mb-4">
                    <h1 className="text-2xl font-bold text-foreground">Backtest Results</h1>
                    <span className="text-sm text-muted-foreground">
                        {new Date(result.executed_at).toLocaleString()}
                    </span>
                </div>

                {/* Key Metrics */}
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4">
                    <MetricCard
                        label="Total Trades"
                        value={result.total_trades.toString()}
                        color="text-blue-500"
                    />
                    <MetricCard
                        label="Win Rate"
                        value={`${result.win_rate.toFixed(1)}%`}
                        color={result.win_rate >= 50 ? 'text-green-500' : 'text-red-500'}
                    />
                    <MetricCard
                        label="Avg R-Multiple"
                        value={result.avg_r_multiple.toFixed(2) + 'R'}
                        color={result.avg_r_multiple > 0 ? 'text-green-500' : 'text-red-500'}
                    />
                    <MetricCard
                        label="Total Return"
                        value={`${result.total_return_r.toFixed(1)}R`}
                        color={result.total_return_r > 0 ? 'text-green-500' : 'text-red-500'}
                    />
                    <MetricCard
                        label="Return %"
                        value={`${result.total_return_pct.toFixed(1)}%`}
                        color={result.total_return_pct > 0 ? 'text-green-500' : 'text-red-500'}
                    />
                    <MetricCard
                        label="Max Drawdown"
                        value={`-${result.max_drawdown_pct.toFixed(1)}%`}
                        color="text-red-500"
                    />
                    <MetricCard
                        label="Sharpe Ratio"
                        value={result.sharpe_ratio.toFixed(2)}
                        color={result.sharpe_ratio > 1 ? 'text-green-500' : 'text-yellow-500'}
                    />
                    <MetricCard
                        label="Final Balance"
                        value={`$${result.final_balance.toLocaleString()}`}
                        color="text-teal-500"
                    />
                </div>
            </div>

            {/* Tabs */}
            <div className="bg-card border-b border-border transition-colors">
                <div className="flex gap-1 px-6">
                    {tabs.map(tab => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 ${activeTab === tab.id
                                ? 'text-blue-500 border-blue-500'
                                : 'text-muted-foreground border-transparent hover:text-foreground'
                                }`}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Content Area - Lazy Loaded */}
            <div className="flex-1 overflow-auto p-6 bg-background relative transition-colors">
                {!isReady ? (
                    <div className="absolute inset-0 flex items-center justify-center bg-background/80 z-10 backdrop-blur-sm">
                        <div className="flex flex-col items-center gap-3">
                            <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                            <span className="text-sm font-medium text-muted-foreground">Rendering Charts...</span>
                        </div>
                    </div>
                ) : (
                    <>
                        {activeTab === 'equity' && <EquityCurveChart result={result} />}
                        {activeTab === 'drawdown' && <DrawdownChart result={result} />}
                        {activeTab === 'performance' && <PerformanceTable result={result} />}
                        {activeTab === 'calendar' && <CalendarHeatmap result={result} />}
                        {activeTab === 'trades' && <TradesTable trades={result.trades} />}
                        {activeTab === 'charts' && (
                            <div className="space-y-6">
                                <RMultipleHistogram distribution={result.r_distribution} />
                                <EVCharts evByTime={result.ev_by_time} evByDay={result.ev_by_day} />
                            </div>
                        )}
                        {activeTab === 'portfolio' && (
                            <div className="space-y-6">
                                {result.correlation_matrix && (
                                    <CorrelationMatrix
                                        matrix={result.correlation_matrix}
                                        strategyNames={result.strategy_names}
                                    />
                                )}
                                {result.monte_carlo && (
                                    <MonteCarloResults
                                        monteCarlo={result.monte_carlo}
                                        initialCapital={result.initial_capital}
                                    />
                                )}
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}

interface MetricCardProps {
    label: string;
    value: string;
    color: string;
}

function MetricCard({ label, value, color }: MetricCardProps) {
    return (
        <div className="bg-card rounded-xl p-3 border border-border transition-colors shadow-sm">
            <div className="text-[10px] uppercase font-bold tracking-wider text-muted-foreground mb-1">{label}</div>
            <div className={`text-lg font-black tabular-nums ${color}`}>{value}</div>
        </div>
    );
}
