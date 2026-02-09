"use client";

import React from 'react';
import { MonteCarloResult } from '@/types/backtest';
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    ReferenceLine
} from 'recharts';

interface MonteCarloResultsProps {
    monteCarlo: MonteCarloResult;
    initialCapital: number;
}

export function MonteCarloResults({ monteCarlo, initialCapital }: MonteCarloResultsProps) {
    // Create distribution data for visualization
    const distributionData = [
        { label: '5th %ile', value: monteCarlo.percentile_5 },
        { label: '25th %ile', value: monteCarlo.percentile_25 },
        { label: 'Median', value: monteCarlo.median_final_balance },
        { label: '75th %ile', value: monteCarlo.percentile_75 },
        { label: '95th %ile', value: monteCarlo.percentile_95 },
    ];

    return (
        <div className="bg-card rounded-xl border border-border p-6 transition-colors shadow-sm">
            <div className="mb-6">
                <h2 className="text-xl font-semibold text-gray-900 mb-2">Monte Carlo Simulation</h2>
                <p className="text-sm text-gray-500">
                    1,000 simulations with randomized trade order
                </p>
            </div>

            {/* Key Metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                    <div className="text-xs text-gray-500 mb-1">Worst Case</div>
                    <div className="text-lg font-semibold text-red-600">
                        ${monteCarlo.worst_final_balance.toLocaleString()}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                        {((monteCarlo.worst_final_balance - initialCapital) / initialCapital * 100).toFixed(1)}%
                    </div>
                </div>

                <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                    <div className="text-xs text-gray-500 mb-1">Best Case</div>
                    <div className="text-lg font-semibold text-green-600">
                        ${monteCarlo.best_final_balance.toLocaleString()}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                        {((monteCarlo.best_final_balance - initialCapital) / initialCapital * 100).toFixed(1)}%
                    </div>
                </div>

                <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                    <div className="text-xs text-gray-500 mb-1">Worst Drawdown</div>
                    <div className="text-lg font-semibold text-red-600">
                        -{monteCarlo.worst_drawdown_pct.toFixed(2)}%
                    </div>
                </div>

                <div className="bg-orange-500/5 rounded-xl p-4 border border-border transition-colors">
                    <div className="text-[10px] font-black text-orange-500 uppercase tracking-widest mb-1">Probability of Ruin</div>
                    <div className="text-lg font-black text-orange-500 tabular-nums">
                        {monteCarlo.probability_of_ruin.toFixed(2)}%
                    </div>
                    <div className="text-xs font-medium text-orange-500/60 mt-1 italic">
                        (Balance &lt; 50% initial)
                    </div>
                </div>
            </div>

            {/* Distribution Chart */}
            <div className="mb-6">
                <h3 className="text-xs font-black text-muted-foreground uppercase tracking-widest mb-4">Final Balance Distribution</h3>
                <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={distributionData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(156, 163, 175, 0.1)" vertical={false} />
                        <XAxis
                            dataKey="label"
                            stroke="rgba(156, 163, 175, 0.5)"
                            tick={{ fill: 'rgba(156, 163, 175, 0.8)', fontSize: 10, fontWeight: 700 }}
                            axisLine={false}
                            tickLine={false}
                        />
                        <YAxis
                            stroke="rgba(156, 163, 175, 0.5)"
                            tick={{ fill: 'rgba(156, 163, 175, 0.8)', fontSize: 10, fontWeight: 700 }}
                            axisLine={false}
                            tickLine={false}
                            tickFormatter={(value: number | undefined) => value !== undefined ? `$${(value / 1000).toFixed(0)}k` : '$0'}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: 'var(--card)',
                                border: '1px solid var(--border)',
                                borderRadius: '12px',
                                color: 'var(--foreground)',
                                fontSize: '11px',
                                fontWeight: 'bold',
                                boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
                                backdropFilter: 'blur(8px)'
                            }}
                            itemStyle={{ color: 'var(--foreground)' }}
                            formatter={(value: number | undefined) => {
                                if (value === undefined) return [0, 'Simulations'];
                                return [value, 'Simulations'];
                            }}
                        />
                        <ReferenceLine
                            y={initialCapital}
                            stroke="rgba(156, 163, 175, 0.3)"
                            strokeDasharray="3 3"
                            label={{ value: 'Initial', fill: 'rgba(156, 163, 175, 0.5)', fontSize: 10, fontWeight: 900 }}
                        />
                        <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                    </BarChart>
                </ResponsiveContainer>
            </div>

            {/* Percentile Table */}
            <div>
                <h3 className="text-[10px] font-black text-muted-foreground uppercase tracking-widest mb-4">Balance Percentiles</h3>
                <div className="overflow-x-auto rounded-xl border border-border">
                    <table className="w-full text-sm">
                        <thead className="bg-muted/50">
                            <tr>
                                <th className="px-4 py-2 text-left text-[10px] font-black text-muted-foreground uppercase tracking-wider">Percentile</th>
                                <th className="px-4 py-2 text-right text-[10px] font-black text-muted-foreground uppercase tracking-wider">Final Balance</th>
                                <th className="px-4 py-2 text-right text-[10px] font-black text-muted-foreground uppercase tracking-wider">Total Return</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {[
                                { label: '5th Percentile', value: monteCarlo.percentile_5 },
                                { label: '25th Percentile', value: monteCarlo.percentile_25 },
                                { label: '50th Percentile (Median)', value: monteCarlo.median_final_balance },
                                { label: '75th Percentile', value: monteCarlo.percentile_75 },
                                { label: '95th Percentile', value: monteCarlo.percentile_95 },
                            ].map((row, index) => (
                                <tr key={index} className="hover:bg-muted/30 transition-colors">
                                    <td className="px-4 py-3 font-bold text-foreground">{row.label}</td>
                                    <td className="px-4 py-3 text-right font-black tabular-nums text-foreground">
                                        ${row.value.toLocaleString()}
                                    </td>
                                    <td className={`px-4 py-3 text-right font-black tabular-nums ${row.value > initialCapital ? 'text-green-500' : 'text-red-500'}`}>
                                        {((row.value - initialCapital) / initialCapital * 100).toFixed(2)}%
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Interpretation */}
            <div className="mt-8 p-4 bg-muted/30 border border-border rounded-xl">
                <h4 className="text-[10px] font-black text-foreground uppercase tracking-widest mb-2 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
                    Interpretation
                </h4>
                <p className="text-xs text-muted-foreground leading-relaxed">
                    The Monte Carlo simulation randomizes the order of your trades 1,000 times to understand the range of possible outcomes.
                    The <span className="font-bold text-foreground tracking-tight">5th percentile</span> represents the worst-case scenario (only 5% of simulations did worse),
                    while the <span className="font-bold text-foreground tracking-tight">95th percentile</span> represents the best-case scenario (only 5% did better).
                </p>
            </div>
        </div>
    );
}
