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

    const tabs = [
        { id: 'equity' as TabType, label: 'Equity Curve' },
        { id: 'drawdown' as TabType, label: 'Drawdown' },
        { id: 'performance' as TabType, label: 'Performance' },
        { id: 'calendar' as TabType, label: 'Calendar' },
        { id: 'trades' as TabType, label: 'Trades' },
        { id: 'charts' as TabType, label: 'Charts' },
        { id: 'portfolio' as TabType, label: 'Portfolio' },
    ];

    return (
        <div className="h-full flex flex-col">
            {/* Header with Metrics */}
            <div className="bg-[#0f1419] border-b border-gray-800 p-6">
                <div className="flex items-center justify-between mb-4">
                    <h1 className="text-2xl font-bold text-white">Backtest Results</h1>
                    <span className="text-sm text-gray-400">
                        {new Date(result.executed_at).toLocaleString()}
                    </span>
                </div>

                {/* Key Metrics */}
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4">
                    <MetricCard
                        label="Total Trades"
                        value={result.total_trades.toString()}
                        color="text-blue-400"
                    />
                    <MetricCard
                        label="Win Rate"
                        value={`${result.win_rate.toFixed(1)}%`}
                        color={result.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}
                    />
                    <MetricCard
                        label="Avg R-Multiple"
                        value={result.avg_r_multiple.toFixed(2) + 'R'}
                        color={result.avg_r_multiple > 0 ? 'text-green-400' : 'text-red-400'}
                    />
                    <MetricCard
                        label="Total Return"
                        value={`${result.total_return_r.toFixed(1)}R`}
                        color={result.total_return_r > 0 ? 'text-green-400' : 'text-red-400'}
                    />
                    <MetricCard
                        label="Return %"
                        value={`${result.total_return_pct.toFixed(1)}%`}
                        color={result.total_return_pct > 0 ? 'text-green-400' : 'text-red-400'}
                    />
                    <MetricCard
                        label="Max Drawdown"
                        value={`-${result.max_drawdown_pct.toFixed(1)}%`}
                        color="text-red-400"
                    />
                    <MetricCard
                        label="Sharpe Ratio"
                        value={result.sharpe_ratio.toFixed(2)}
                        color={result.sharpe_ratio > 1 ? 'text-green-400' : 'text-yellow-400'}
                    />
                    <MetricCard
                        label="Final Balance"
                        value={`$${result.final_balance.toLocaleString()}`}
                        color="text-teal-400"
                    />
                </div>
            </div>

            {/* Tabs */}
            <div className="bg-[#0f1419] border-b border-gray-800">
                <div className="flex gap-1 px-6">
                    {tabs.map(tab => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`px-4 py-3 text-sm font-medium transition-colors border-b-2 ${activeTab === tab.id
                                    ? 'text-blue-400 border-blue-400'
                                    : 'text-gray-400 border-transparent hover:text-gray-300'
                                }`}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-auto p-6 bg-[#0a0e1a]">
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
        <div className="bg-[#1a1f2e]/50 rounded-lg p-3 border border-gray-800">
            <div className="text-xs text-gray-500 mb-1">{label}</div>
            <div className={`text-lg font-semibold ${color}`}>{value}</div>
        </div>
    );
}
