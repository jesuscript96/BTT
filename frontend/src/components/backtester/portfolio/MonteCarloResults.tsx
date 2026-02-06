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
        <div className="bg-[#0f1419] rounded-lg border border-gray-800 p-6">
            <div className="mb-6">
                <h2 className="text-xl font-semibold text-white mb-2">Monte Carlo Simulation</h2>
                <p className="text-sm text-gray-400">
                    1,000 simulations with randomized trade order
                </p>
            </div>

            {/* Key Metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <div className="bg-[#1a1f2e]/50 rounded-lg p-4 border border-gray-800">
                    <div className="text-xs text-gray-500 mb-1">Worst Case</div>
                    <div className="text-lg font-semibold text-red-400">
                        ${monteCarlo.worst_final_balance.toLocaleString()}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                        {((monteCarlo.worst_final_balance - initialCapital) / initialCapital * 100).toFixed(1)}%
                    </div>
                </div>

                <div className="bg-[#1a1f2e]/50 rounded-lg p-4 border border-gray-800">
                    <div className="text-xs text-gray-500 mb-1">Best Case</div>
                    <div className="text-lg font-semibold text-green-400">
                        ${monteCarlo.best_final_balance.toLocaleString()}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                        {((monteCarlo.best_final_balance - initialCapital) / initialCapital * 100).toFixed(1)}%
                    </div>
                </div>

                <div className="bg-[#1a1f2e]/50 rounded-lg p-4 border border-gray-800">
                    <div className="text-xs text-gray-500 mb-1">Worst Drawdown</div>
                    <div className="text-lg font-semibold text-red-400">
                        -{monteCarlo.worst_drawdown_pct.toFixed(2)}%
                    </div>
                </div>

                <div className="bg-[#1a1f2e]/50 rounded-lg p-4 border border-gray-800">
                    <div className="text-xs text-gray-500 mb-1">Probability of Ruin</div>
                    <div className="text-lg font-semibold text-yellow-400">
                        {monteCarlo.probability_of_ruin.toFixed(2)}%
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                        (Balance &lt; 50% initial)
                    </div>
                </div>
            </div>

            {/* Distribution Chart */}
            <div className="mb-6">
                <h3 className="text-sm font-medium text-gray-400 mb-3">Final Balance Distribution</h3>
                <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={distributionData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                        <XAxis
                            dataKey="label"
                            stroke="#6b7280"
                            tick={{ fill: '#9ca3af', fontSize: 12 }}
                        />
                        <YAxis
                            stroke="#6b7280"
                            tick={{ fill: '#9ca3af', fontSize: 12 }}
                            tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: '#1f2937',
                                border: '1px solid #374151',
                                borderRadius: '8px',
                                color: '#fff'
                            }}
                            formatter={(value: number) => [`$${value.toLocaleString()}`, 'Final Balance']}
                        />
                        <ReferenceLine
                            y={initialCapital}
                            stroke="#6b7280"
                            strokeDasharray="3 3"
                            label={{ value: 'Initial Capital', fill: '#9ca3af', fontSize: 12 }}
                        />
                        <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                    </BarChart>
                </ResponsiveContainer>
            </div>

            {/* Percentile Table */}
            <div>
                <h3 className="text-sm font-medium text-gray-400 mb-3">Percentile Breakdown</h3>
                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead className="bg-[#1a1f2e] border-b border-gray-800">
                            <tr>
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase">
                                    Percentile
                                </th>
                                <th className="px-4 py-3 text-right text-xs font-medium text-gray-400 uppercase">
                                    Final Balance
                                </th>
                                <th className="px-4 py-3 text-right text-xs font-medium text-gray-400 uppercase">
                                    Return %
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-800">
                            {[
                                { label: '5th Percentile', value: monteCarlo.percentile_5 },
                                { label: '25th Percentile', value: monteCarlo.percentile_25 },
                                { label: '50th Percentile (Median)', value: monteCarlo.median_final_balance },
                                { label: '75th Percentile', value: monteCarlo.percentile_75 },
                                { label: '95th Percentile', value: monteCarlo.percentile_95 },
                            ].map((row, index) => (
                                <tr key={index} className="hover:bg-[#1a1f2e]/50">
                                    <td className="px-4 py-3 text-white">{row.label}</td>
                                    <td className="px-4 py-3 text-right font-medium text-white">
                                        ${row.value.toLocaleString()}
                                    </td>
                                    <td className={`px-4 py-3 text-right font-medium ${row.value > initialCapital ? 'text-green-400' : 'text-red-400'
                                        }`}>
                                        {((row.value - initialCapital) / initialCapital * 100).toFixed(2)}%
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Interpretation */}
            <div className="mt-6 p-4 bg-blue-900/20 border border-blue-800 rounded-lg">
                <h4 className="text-sm font-medium text-blue-400 mb-2">Interpretation</h4>
                <p className="text-xs text-gray-300">
                    The Monte Carlo simulation randomizes the order of your trades 1,000 times to understand the range of possible outcomes.
                    The <strong>5th percentile</strong> represents the worst-case scenario (only 5% of simulations did worse),
                    while the <strong>95th percentile</strong> represents the best-case scenario (only 5% did better).
                </p>
            </div>
        </div>
    );
}
